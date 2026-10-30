package olt

import (
	"context"
	"encoding/hex"
	"errors"
	"fmt"
	"net"
	"os"
	"sort"
	"strconv"
	"strings"
	"sync"
	"testing"
	"time"

	"github.com/gosnmp/gosnmp"
)

// fakeMIB is an in-memory agent. The values for PON 0/0/14 are the ones read from a real MA5608T R015 over SNMP and
// cross-checked with the CLI (serials replaced by fictitious ones of the same shape).
type fakeMIB struct {
	vals    map[string]SNMPValue
	gets    []string // every OID asked for, in order
	walkErr map[string]error
	maxSeen int
}

func newPon14() *fakeMIB {
	const ifx = 4194307584
	m := &fakeMIB{vals: map[string]SNMPValue{}, walkErr: map[string]error{}}
	m.vals[fmt.Sprintf("%s.%d", oidIfDesc, ifx)] = SNMPValue{Bytes: []byte("Huawei-MA5600-V800R015-GPON_UNI"), IsBytes: true}
	run := map[int]int64{0: 2, 1: 2, 2: 2, 3: 2, 4: 2, 5: 2, 6: 2, 7: 1, 8: 2, 9: 2, 10: 1, 11: 1}
	cause := map[int]int64{0: 13, 1: 2, 2: 1, 3: 1, 4: 2, 5: 13, 6: 13, 8: 2, 9: 1}
	rx := map[int]int64{7: -1328, 10: -1318, 11: -1492}
	for id, r := range run {
		m.vals[fmt.Sprintf("%s.46.1.15.%d.%d", hwXpon, ifx, id)] = SNMPValue{Int: r, IsInt: true}
		m.vals[fmt.Sprintf("%s.43.1.3.%d.%d", hwXpon, ifx, id)] = SNMPValue{Bytes: []byte{0x48, 0x57, 0x54, 0x43, 0x30, 0, 0, byte(id)}, IsBytes: true}
		if c, ok := cause[id]; ok {
			m.vals[fmt.Sprintf("%s.46.1.24.%d.%d", hwXpon, ifx, id)] = SNMPValue{Int: c, IsInt: true}
		}
		if v, ok := rx[id]; ok {
			m.vals[fmt.Sprintf("%s.51.1.4.%d.%d", hwXpon, ifx, id)] = SNMPValue{Int: v, IsInt: true}
		}
	}
	return m
}

func (m *fakeMIB) Get(_ context.Context, oids []string) (map[string]SNMPValue, error) {
	out := map[string]SNMPValue{}
	for _, o := range oids {
		m.gets = append(m.gets, o)
		if v, ok := m.vals[o]; ok {
			out[o] = v
		} else {
			out[o] = SNMPValue{Missing: true}
		}
	}
	return out, nil
}

func (m *fakeMIB) Walk(_ context.Context, root string, maxRows int) ([]SNMPRow, error) {
	if err := m.walkErr[root]; err != nil {
		return nil, err
	}
	var keys []string
	for k := range m.vals {
		if strings.HasPrefix(k, root+".") {
			keys = append(keys, k)
		}
	}
	sort.Slice(keys, func(i, j int) bool { return oidLess(keys[i], keys[j]) })
	if len(keys) > maxRows {
		return nil, ErrSNMPTooLarge
	}
	var rows []SNMPRow
	for _, k := range keys {
		rows = append(rows, SNMPRow{Suffix: strings.TrimPrefix(k, root+"."), Value: m.vals[k]})
	}
	return rows, nil
}

func TestSNMPRealShapedPonIsReadAndProvenComplete(t *testing.T) {
	snap, err := HuaweiSNMP{}.Snapshot(context.Background(), newPon14(), []string{"0/0/14"})
	if err != nil {
		t.Fatal(err)
	}
	if snap.Identity != (Identity{Vendor: "huawei", Model: "MA5600", Firmware: "MA5600V800R015"}) {
		t.Fatalf("identity %+v", snap.Identity)
	}
	if len(snap.PONs) != 1 || !snap.PONs[0].Verified || snap.PONs[0].Status != "up" || len(snap.ONUs) != 12 {
		t.Fatalf("pons=%+v onus=%d", snap.PONs, len(snap.ONUs))
	}
	byID := map[int]ONU{}
	for _, u := range snap.ONUs {
		if len(u.Serial) != 16 || strings.ToUpper(u.Serial) != u.Serial || u.PonPath != "0/0/14" {
			t.Errorf("bad ONU %+v", u)
		}
		id, _ := strconv.ParseInt(u.Serial[14:], 16, 32)
		byID[int(id)] = u
	}
	// ONT-id -> status, from the real device: 0/5/6 dying-gasp (code 13), 1/4/8 LOSi (code 2), 2/3/9 link-down (code 1), 7/10/11 online
	for id, st := range map[int]string{0: "dying_gasp", 5: "dying_gasp", 6: "dying_gasp", 1: "los", 4: "los", 8: "los",
		2: "offline", 3: "offline", 9: "offline", 7: "online", 10: "online", 11: "online"} {
		if byID[id].Status != st {
			t.Errorf("ONT %d: want %s, got %q", id, st, byID[id].Status)
		}
	}
	rxs := map[float64]bool{}
	for _, u := range snap.ONUs {
		if u.Status == "online" {
			if u.RxDBm == nil {
				t.Errorf("online ONU without Rx: %+v", u)
				continue
			}
			rxs[*u.RxDBm] = true
		} else if u.RxDBm != nil {
			t.Errorf("non-online ONU with a reading: %+v", u)
		}
	}
	if !rxs[-13.28] || !rxs[-13.18] || !rxs[-14.92] || len(rxs) != 3 {
		t.Errorf("Rx values: %v", rxs)
	}
}

func TestSNMPListingIsNotVerifiedWhenTheTwoWalksDisagreeOrLookWrong(t *testing.T) {
	const ifx = 4194307584
	for name, mut := range map[string]func(*fakeMIB){
		"a serial row is missing": func(m *fakeMIB) { delete(m.vals, fmt.Sprintf("%s.43.1.3.%d.4", hwXpon, ifx)) },
		"a state row is missing":  func(m *fakeMIB) { delete(m.vals, fmt.Sprintf("%s.46.1.15.%d.4", hwXpon, ifx)) },
		"an extra serial row": func(m *fakeMIB) {
			m.vals[fmt.Sprintf("%s.43.1.3.%d.50", hwXpon, ifx)] = SNMPValue{Bytes: make([]byte, 8), IsBytes: true}
		},
		"unknown run state": func(m *fakeMIB) { m.vals[fmt.Sprintf("%s.46.1.15.%d.3", hwXpon, ifx)] = SNMPValue{Int: 7, IsInt: true} },
		"short serial": func(m *fakeMIB) {
			m.vals[fmt.Sprintf("%s.43.1.3.%d.3", hwXpon, ifx)] = SNMPValue{Bytes: []byte{1, 2, 3}, IsBytes: true}
		},
		"duplicate serial": func(m *fakeMIB) {
			m.vals[fmt.Sprintf("%s.43.1.3.%d.3", hwXpon, ifx)] = m.vals[fmt.Sprintf("%s.43.1.3.%d.2", hwXpon, ifx)]
		},
		"ONT id out of range": func(m *fakeMIB) {
			m.vals[fmt.Sprintf("%s.46.1.15.%d.200", hwXpon, ifx)] = SNMPValue{Int: 1, IsInt: true}
		},
	} {
		m := newPon14()
		mut(m)
		snap, err := HuaweiSNMP{}.Snapshot(context.Background(), m, []string{"0/0/14"})
		if err != nil {
			t.Errorf("%s: %v", name, err)
			continue
		}
		if snap.PONs[0].Verified {
			t.Errorf("%s: must not be verified", name)
		}
	}
}

func TestSNMPWalkFailureOrOverflowFailsTheWholeSnapshotWithoutPartialData(t *testing.T) {
	const ifx = 4194307584
	for name, key := range map[string]string{"state walk": "46.1.15", "serial walk": "43.1.3"} {
		m := newPon14()
		m.walkErr[fmt.Sprintf("%s.%s.%d", hwXpon, key, ifx)] = errors.New("request timeout")
		if snap, err := (HuaweiSNMP{}).Snapshot(context.Background(), m, []string{"0/0/14"}); err == nil || len(snap.ONUs) != 0 {
			t.Errorf("%s: want error and no data, got %v / %d onus", name, err, len(snap.ONUs))
		}
	}
	m := newPon14()
	for i := 20; i < 20+maxONTs; i++ { // more rows than a PON can have
		m.vals[fmt.Sprintf("%s.46.1.15.%d.%d", hwXpon, ifx, 1000+i)] = SNMPValue{Int: 1, IsInt: true}
	}
	if _, err := (HuaweiSNMP{}).Snapshot(context.Background(), m, []string{"0/0/14"}); !errors.Is(err, ErrSNMPTooLarge) {
		t.Fatalf("want ErrSNMPTooLarge, got %v", err)
	}
}

func TestSNMPRefusesUnvalidatedDevicesBeforeReadingAnythingElse(t *testing.T) {
	const ifx = 4194307584
	m := newPon14()
	m.vals[fmt.Sprintf("%s.%d", oidIfDesc, ifx)] = SNMPValue{Bytes: []byte("Huawei-MA5600-V800R018-GPON_UNI"), IsBytes: true}
	if _, err := (HuaweiSNMP{}).Snapshot(context.Background(), m, []string{"0/0/14"}); err == nil || !strings.Contains(err.Error(), "not validated") {
		t.Fatalf("another release must be refused: %v", err)
	}
	if len(m.gets) != 1 {
		t.Fatalf("only the identity GET may happen, saw %v", m.gets)
	}
	m = newPon14()
	m.vals[fmt.Sprintf("%s.%d", oidIfDesc, ifx)] = SNMPValue{Bytes: []byte("some-other-vendor"), IsBytes: true}
	if _, err := (HuaweiSNMP{}).Snapshot(context.Background(), m, []string{"0/0/14"}); err == nil {
		t.Fatal("an unrecognised interface name must be refused")
	}
}

func TestSNMPPonIfIndexFormulaAndRefusals(t *testing.T) {
	for path, want := range map[string]int{"0/0/14": 4194307584, "0/0/0": 4194304000, "0/1/0": 4194312192, "0/1/4": 4194313216} {
		if got, err := ponIfIndex(path); err != nil || got != want {
			t.Errorf("%s: got %d, %v want %d", path, got, err, want)
		}
	}
	for _, bad := range []string{"1/0/0", "0/0", "0/0/16", "0/21/0", "0/-1/0", "0/0/x", "0/0/0/0", ""} {
		if _, err := ponIfIndex(bad); err == nil {
			t.Errorf("%q must be refused", bad)
		}
	}
	m := newPon14() // 0/0/13 has no ifDescr in this MIB: the formula must not be trusted blindly
	if _, err := (HuaweiSNMP{}).Snapshot(context.Background(), m, []string{"0/0/14", "0/0/13"}); err == nil {
		t.Fatal("a port whose ifIndex is not a GPON interface must fail the snapshot")
	}
}

func pdu(oid string, v any, t gosnmp.Asn1BER) gosnmp.SnmpPDU {
	return gosnmp.SnmpPDU{Name: "." + oid, Type: t, Value: v}
}

func TestWalkBulkProvesTheEndOfTheTableOnlyByLeavingTheSubtree(t *testing.T) {
	root := "1.3.6.1.4.1.2011.6.128.1.1.2.46.1.15.100"
	noTick := func(context.Context) error { return nil }
	row := func(n int, v int) gosnmp.SnmpPDU { return pdu(fmt.Sprintf("%s.%d", root, n), v, gosnmp.Integer) }
	out := pdu("1.3.6.1.4.1.2011.6.128.1.1.2.46.1.16.100.0", 1, gosnmp.Integer) // next column: outside the subtree
	pages := [][]gosnmp.SnmpPDU{{row(0, 2), row(1, 1)}, {row(7, 1), out}}
	i := 0
	rows, err := walkBulk(context.Background(), root, 100, noTick, func(string) ([]gosnmp.SnmpPDU, error) { i++; return pages[i-1], nil })
	if err != nil || len(rows) != 3 || rows[2].Suffix != "7" {
		t.Fatalf("rows=%v err=%v", rows, err)
	}
	// endOfMibView also ends it
	i = 0
	rows, err = walkBulk(context.Background(), root, 100, noTick, func(string) ([]gosnmp.SnmpPDU, error) {
		i++
		if i == 1 {
			return []gosnmp.SnmpPDU{row(0, 1)}, nil
		}
		return []gosnmp.SnmpPDU{pdu(root+".1", nil, gosnmp.EndOfMibView)}, nil
	})
	if err != nil || len(rows) != 1 {
		t.Fatalf("rows=%v err=%v", rows, err)
	}
	// anything missing/odd INSIDE the subtree is a broken answer, not an end (it would truncate the listing and fake completeness)
	for name, bad := range map[string]gosnmp.SnmpPDU{
		"null":             pdu(root+".1", nil, gosnmp.Null),
		"noSuchObject":     pdu(root+".1", nil, gosnmp.NoSuchObject),
		"noSuchInstance":   pdu(root+".1", nil, gosnmp.NoSuchInstance),
		"unsupported type": pdu(root+".1", "1.3.6.1", gosnmp.ObjectIdentifier),
	} {
		call := 0
		if _, err := walkBulk(context.Background(), root, 100, noTick, func(string) ([]gosnmp.SnmpPDU, error) {
			call++
			if call == 1 {
				return []gosnmp.SnmpPDU{row(0, 1), bad}, nil
			}
			return []gosnmp.SnmpPDU{out}, nil // a later page would end the table cleanly: only the bad value may cause the error
		}); err == nil {
			t.Errorf("%s inside the subtree must fail the walk, not end it", name)
		}
	}
	// an error mid-walk is NEVER a finished table
	i = 0
	if _, err := walkBulk(context.Background(), root, 100, noTick, func(string) ([]gosnmp.SnmpPDU, error) {
		i++
		if i == 2 {
			return nil, errors.New("request timeout")
		}
		return []gosnmp.SnmpPDU{row(0, 1)}, nil
	}); err == nil {
		t.Fatal("a timeout must not look like the end of the table")
	}
	// non-increasing OIDs (a looping agent), empty answers and the row limit all fail
	if _, err := walkBulk(context.Background(), root, 100, noTick, func(string) ([]gosnmp.SnmpPDU, error) {
		return []gosnmp.SnmpPDU{row(5, 1), row(3, 1)}, nil
	}); err == nil {
		t.Fatal("non-increasing OIDs must fail")
	}
	if _, err := walkBulk(context.Background(), root, 100, noTick, func(string) ([]gosnmp.SnmpPDU, error) { return nil, nil }); err == nil {
		t.Fatal("an empty bulk answer must fail")
	}
	n := 0
	if _, err := walkBulk(context.Background(), root, 3, noTick, func(string) ([]gosnmp.SnmpPDU, error) {
		n += 2
		return []gosnmp.SnmpPDU{row(n-1, 1), row(n, 1)}, nil
	}); !errors.Is(err, ErrSNMPTooLarge) {
		t.Fatalf("want ErrSNMPTooLarge, got %v", err)
	}
	// the request budget stops a runaway walk
	budget := errors.New("budget")
	if _, err := walkBulk(context.Background(), root, 100, func(context.Context) error { return budget },
		func(string) ([]gosnmp.SnmpPDU, error) { return []gosnmp.SnmpPDU{row(0, 1)}, nil }); !errors.Is(err, budget) {
		t.Fatalf("want the budget error, got %v", err)
	}
}

func TestOIDOrderIsNumericNotLexical(t *testing.T) {
	if !oidLess("1.3.6.9", "1.3.6.10") || oidLess("1.3.6.10", "1.3.6.9") || oidLess("1.3.6", "1.3.6") || !oidLess("1.3.6", "1.3.6.1") {
		t.Fatal("numeric OID comparison is wrong")
	}
}

func TestDialSNMPRefusesAnythingNotAnAllowlistedIPLiteral(t *testing.T) {
	ok := func(h string) bool { return h == "192.0.2.10:161" }
	for name, cfg := range map[string]SNMPConfig{
		"hostname":        {Addr: "olt.example.com:161", Community: "x", Allowed: func(string) bool { return true }},
		"not allowlisted": {Addr: "192.0.2.11:161", Community: "x", Allowed: ok},
		"no allowlist":    {Addr: "192.0.2.10:161", Community: "x"},
		"empty community": {Addr: "192.0.2.10:161", Allowed: ok},
		"multicast":       {Addr: "224.0.0.1:161", Community: "x", Allowed: func(string) bool { return true }},
		"link-local":      {Addr: "169.254.169.254:161", Community: "x", Allowed: func(string) bool { return true }},
		"unspecified":     {Addr: "0.0.0.0:161", Community: "x", Allowed: func(string) bool { return true }},
		"bad port":        {Addr: "192.0.2.10:0", Community: "x", Allowed: func(string) bool { return true }},
		"no port":         {Addr: "192.0.2.10", Community: "x", Allowed: func(string) bool { return true }},
	} {
		if _, _, err := DialSNMP(context.Background(), cfg); !errors.Is(err, ErrSNMPDenied) {
			t.Errorf("%s: want ErrSNMPDenied, got %v", name, err)
		}
	}
	if got := redact("failed with s3cret in text", "s3cret"); strings.Contains(got, "s3cret") {
		t.Fatalf("community leaked: %q", got)
	}
}

func TestSNMPCodeCanOnlyReadNeverSet(t *testing.T) {
	for _, f := range []string{"snmp.go", "huawei_snmp.go"} {
		b, err := os.ReadFile(f)
		if err != nil {
			t.Fatal(err)
		}
		for _, banned := range []string{".Set(", "SetRequest", "SetPDU", "SendTrap", "InformRequest"} {
			if strings.Contains(string(b), banned) {
				t.Errorf("%s must not contain %q: the SNMP transport is read-only", f, banned)
			}
		}
	}
}

// silentAgent is a UDP socket that receives and counts packets but never answers: the worst case for the client.
func silentAgent(t *testing.T) (addr string, packets func() int) {
	t.Helper()
	pc, err := net.ListenPacket("udp", "127.0.0.1:0")
	if err != nil {
		t.Fatal(err)
	}
	t.Cleanup(func() { pc.Close() })
	var mu sync.Mutex
	n := 0
	go func() {
		b := make([]byte, 2048)
		for {
			if _, _, err := pc.ReadFrom(b); err != nil {
				return
			}
			mu.Lock()
			n++
			mu.Unlock()
		}
	}()
	return pc.LocalAddr().String(), func() int { mu.Lock(); defer mu.Unlock(); return n }
}

func dialSilent(t *testing.T, addr string, mut func(*SNMPConfig)) SNMPReader {
	t.Helper()
	old := snmpMinPace
	snmpMinPace = time.Millisecond // the floor is enforced separately (TestSNMPPaceFloor); other tests need to run fast
	t.Cleanup(func() { snmpMinPace = old })
	cfg := SNMPConfig{Addr: addr, Community: "s3cret", Allowed: func(h string) bool { return h == addr },
		Timeout: 100 * time.Millisecond, Pace: time.Millisecond}
	mut(&cfg)
	r, closeFn, err := DialSNMP(context.Background(), cfg)
	if err != nil {
		t.Fatal(err)
	}
	t.Cleanup(closeFn)
	return r
}

func TestSNMPEveryRetransmissionIsCountedPacedAndBudgeted(t *testing.T) {
	addr, packets := silentAgent(t)
	r := dialSilent(t, addr, func(c *SNMPConfig) { c.Retries = 2 })
	_, err := r.Get(context.Background(), []string{"1.3.6.1.2.1.1.3.0"})
	if err == nil || strings.Contains(err.Error(), "s3cret") {
		t.Fatalf("want a timeout error without the community, got %v", err)
	}
	time.Sleep(50 * time.Millisecond)
	if packets() != 3 {
		t.Fatalf("1 request + 2 retransmissions = 3 packets, saw %d", packets())
	}
	addr2, packets2 := silentAgent(t)
	r2 := dialSilent(t, addr2, func(c *SNMPConfig) { c.Retries = 5; c.MaxReqs = 2 })
	if _, err := r2.Get(context.Background(), []string{"1.3.6.1.2.1.1.3.0"}); !errors.Is(err, ErrSNMPBudget) {
		t.Fatalf("want ErrSNMPBudget, got %v", err)
	}
	time.Sleep(50 * time.Millisecond)
	if packets2() != 2 {
		t.Fatalf("the request budget caps PACKETS, retransmissions included: saw %d", packets2())
	}
}

func TestSNMPAnOperationContextInterruptsABlockedCall(t *testing.T) {
	addr, _ := silentAgent(t)
	r := dialSilent(t, addr, func(c *SNMPConfig) { c.Timeout = 30 * time.Second; c.Retries = 3 })
	ctx, cancel := context.WithTimeout(context.Background(), 300*time.Millisecond)
	defer cancel()
	start := time.Now()
	_, err := r.Get(ctx, []string{"1.3.6.1.2.1.1.3.0"})
	if err == nil || time.Since(start) > 3*time.Second {
		t.Fatalf("the cycle deadline must interrupt a blocked call: err=%v after %v", err, time.Since(start))
	}
	start = time.Now()
	if _, err := r.Walk(ctx, "1.3.6.1.2.1.2.2.1.2", 10); err == nil || time.Since(start) > 3*time.Second {
		t.Fatalf("same for Walk: err=%v after %v", err, time.Since(start))
	}
}

func TestSNMPPaceFloorCannotBeLoweredByConfig(t *testing.T) {
	addr, _ := silentAgent(t)
	for _, pace := range []time.Duration{0, time.Millisecond, 200 * time.Millisecond, 999 * time.Millisecond} {
		r, closeFn, err := DialSNMP(context.Background(), SNMPConfig{Addr: addr, Community: "x", Allowed: func(string) bool { return true }, Pace: pace})
		if err != nil {
			t.Fatal(err)
		}
		if got := r.(*snmpClient).cfg.Pace; got < time.Second {
			t.Errorf("pace %v became %v: below the 1s floor", pace, got)
		}
		closeFn()
	}
}

func dateAndTime(y, mo, d, h, mi, s int, sign byte, th, tm int) SNMPValue {
	return SNMPValue{IsBytes: true, Bytes: []byte{byte(y >> 8), byte(y), byte(mo), byte(d), byte(h), byte(mi), byte(s), 0, sign, byte(th), byte(tm)}}
}

func TestSNMPReadsTheLastDownTimeOfOfflineOnusOnlyAndInBatches(t *testing.T) {
	const ifx = 4194307584
	m := newPon14()
	// the OLT says ONT 0 went down 2026-10-30 02:30:34 at UTC-04:00; ONT 1 reports the all-zero "never" value; ONT 2 an 8-byte value (no zone)
	m.vals[fmt.Sprintf("%s.46.1.23.%d.0", hwXpon, ifx)] = dateAndTime(2026, 10, 30, 2, 30, 34, '-', 4, 0)
	m.vals[fmt.Sprintf("%s.46.1.23.%d.1", hwXpon, ifx)] = SNMPValue{IsBytes: true, Bytes: []byte{0, 0, 1, 1, 0, 0, 0, 0, '+', 0, 0}}
	m.vals[fmt.Sprintf("%s.46.1.23.%d.2", hwXpon, ifx)] = SNMPValue{IsBytes: true, Bytes: []byte{0x07, 0xEA, 10, 30, 2, 30, 34, 0}}
	m.vals[fmt.Sprintf("%s.46.1.23.%d.7", hwXpon, ifx)] = dateAndTime(2026, 10, 1, 1, 1, 1, '+', 0, 0) // an ONLINE ONU: must never be asked
	snap, err := HuaweiSNMP{}.Snapshot(context.Background(), m, []string{"0/0/14"})
	if err != nil {
		t.Fatal(err)
	}
	byID := map[int]ONU{}
	for _, u := range snap.ONUs {
		id, _ := strconv.ParseInt(u.Serial[14:], 16, 32)
		byID[int(id)] = u
	}
	want := time.Date(2026, 10, 30, 6, 30, 34, 0, time.UTC)
	if g := byID[0].LastDownAt; g == nil || !g.Equal(want) {
		t.Fatalf("ONT 0: want %s got %v", want, g)
	}
	for _, id := range []int{1, 2, 3, 4, 5, 6, 8, 9, 7, 10, 11} {
		if byID[id].LastDownAt != nil {
			t.Errorf("ONT %d must have no last-down time: %v", id, byID[id].LastDownAt)
		}
	}
	asked := 0
	for _, o := range m.gets {
		if strings.Contains(o, ".46.1.23.") {
			asked++
			if strings.HasSuffix(o, ".7") || strings.HasSuffix(o, ".10") || strings.HasSuffix(o, ".11") {
				t.Errorf("an online ONU was asked for its last down time: %s", o)
			}
		}
	}
	if asked != 9 {
		t.Fatalf("one OID per OFFLINE ONU (9), got %d", asked)
	}
}

func TestParseDateAndTimeIsStrict(t *testing.T) {
	ok := dateAndTime(2026, 10, 30, 2, 30, 34, '-', 4, 0).Bytes
	if got, good := parseDateAndTime(ok); !good || !got.Equal(time.Date(2026, 10, 30, 6, 30, 34, 0, time.UTC)) {
		t.Fatalf("%v %v", got, good)
	}
	for name, b := range map[string][]byte{
		"short": ok[:8], "empty": nil, "year 0": dateAndTime(0, 1, 1, 0, 0, 0, '+', 0, 0).Bytes, "year 2009": dateAndTime(2009, 1, 1, 0, 0, 0, '+', 0, 0).Bytes,
		"month 13": dateAndTime(2026, 13, 1, 0, 0, 0, '+', 0, 0).Bytes, "feb 30": dateAndTime(2026, 2, 30, 0, 0, 0, '+', 0, 0).Bytes,
		"hour 24": dateAndTime(2026, 1, 1, 24, 0, 0, '+', 0, 0).Bytes, "bad sign": dateAndTime(2026, 1, 1, 0, 0, 0, '*', 0, 0).Bytes,
		"zone 15h": dateAndTime(2026, 1, 1, 0, 0, 0, '+', 15, 0).Bytes, "zone 14h30": dateAndTime(2026, 1, 1, 0, 0, 0, '+', 14, 30).Bytes,
		"second 60": dateAndTime(2026, 1, 1, 0, 0, 60, '+', 0, 0).Bytes, "decisecond 255": withDeci(ok, 255), "decisecond 10": withDeci(ok, 10),
	} {
		if _, good := parseDateAndTime(b); good {
			t.Errorf("%s must be refused", name)
		}
	}
}

func withDeci(b []byte, d byte) []byte {
	c := append([]byte(nil), b...)
	c[7] = d
	return c
}

func TestSNMPLastDownFailureNeverFailsTheSnapshot(t *testing.T) {
	m := &failingDown{newPon14()}
	snap, err := HuaweiSNMP{}.Snapshot(context.Background(), m, []string{"0/0/14"})
	if err != nil || len(snap.ONUs) != 12 || !snap.PONs[0].Verified {
		t.Fatalf("err=%v onus=%d", err, len(snap.ONUs))
	}
	for _, u := range snap.ONUs {
		if u.LastDownAt != nil {
			t.Fatalf("nothing was read: %+v", u)
		}
	}
}

type failingDown struct{ *fakeMIB }

func (f *failingDown) Get(ctx context.Context, oids []string) (map[string]SNMPValue, error) {
	for _, o := range oids {
		if strings.Contains(o, ".46.1.23.") {
			return nil, errors.New("snmp: timeout")
		}
	}
	return f.fakeMIB.Get(ctx, oids)
}

func fakeSerial(id int) string {
	return strings.ToUpper(hex.EncodeToString([]byte{0x48, 0x57, 0x54, 0x43, 0x30, 0, 0, byte(id)}))
}

func TestLastDownsReadsOnlyTheTargetsAndOnlyAcceptsATimeWhoseSerialMatches(t *testing.T) {
	const ifx = 4194307584
	m := newPon14()
	m.vals[fmt.Sprintf("%s.46.1.23.%d.0", hwXpon, ifx)] = dateAndTime(2026, 10, 30, 2, 30, 34, '-', 4, 0)
	m.vals[fmt.Sprintf("%s.46.1.23.%d.1", hwXpon, ifx)] = dateAndTime(2026, 10, 29, 1, 0, 0, '+', 0, 0)
	m.vals[fmt.Sprintf("%s.46.1.23.%d.2", hwXpon, ifx)] = SNMPValue{IsBytes: true, Bytes: []byte{0, 0, 1, 1, 0, 0, 0, 0, '+', 0, 0}} // "never"
	m.vals[fmt.Sprintf("%s.46.1.23.%d.7", hwXpon, ifx)] = dateAndTime(2026, 10, 1, 1, 1, 1, '+', 0, 0)                               // an online ONU: never asked
	targets := []DownTarget{
		{PonPath: "0/0/14", OntID: 0, Serial: fakeSerial(0)},
		{PonPath: "0/0/14", OntID: 1, Serial: "4857544399999999"}, // the table moved: that ONT-ID is now another ONU
		{PonPath: "0/0/14", OntID: 2, Serial: fakeSerial(2)},
	}
	got, err := HuaweiSNMP{}.LastDowns(context.Background(), m, targets)
	if err != nil || len(got) != 1 || !got[fakeSerial(0)].Equal(time.Date(2026, 10, 30, 6, 30, 34, 0, time.UTC)) {
		t.Fatalf("only the ONU whose serial still matches and whose time is real: %v err=%v", got, err)
	}
	for _, o := range m.gets {
		if strings.Contains(o, ".46.1.15.") || strings.Contains(o, ".46.1.24.") || strings.Contains(o, ".51.1.4.") || strings.HasSuffix(o, ".46.1.23."+fmt.Sprint(ifx)+".7") {
			t.Errorf("a focused read must not ask for %s", o)
		}
	}
}

func TestLastDownsCostsOneRequestPerFiveOnusAndRefusesWhatIsNotAGponPort(t *testing.T) {
	const ifx = 4194307584
	m := newPon14()
	var targets []DownTarget
	for id := 0; id < 12; id++ {
		targets = append(targets, DownTarget{PonPath: "0/0/14", OntID: id, Serial: fakeSerial(id)})
	}
	cm := &countingMIB{fakeMIB: m}
	if _, err := (HuaweiSNMP{}).LastDowns(context.Background(), cm, targets); err != nil || cm.requests != 3 || cm.maxOIDs > snmpGetOIDs {
		t.Fatalf("12 ONUs = 3 requests (4 + 5 + 3; the port check rides the first), none above %d OIDs: requests=%d max=%d err=%v",
			snmpGetOIDs, cm.requests, cm.maxOIDs, err)
	}
	m.vals[fmt.Sprintf("%s.%d", oidIfDesc, ifx)] = SNMPValue{Bytes: []byte("Ethernet0/0/1"), IsBytes: true}
	if got, err := (HuaweiSNMP{}).LastDowns(context.Background(), m, targets); err == nil || len(got) != 0 {
		t.Fatalf("an ifIndex that is not a GPON port must read nothing: %v %v", got, err)
	}
	for name, bad := range map[string][]DownTarget{
		"two ports":   {{PonPath: "0/0/14", OntID: 1, Serial: "A"}, {PonPath: "0/0/13", OntID: 1, Serial: "B"}},
		"id past end": {{PonPath: "0/0/14", OntID: 128, Serial: "A"}},
		"negative id": {{PonPath: "0/0/14", OntID: -1, Serial: "A"}},
		"bad port":    {{PonPath: "0/0/14;x", OntID: 1, Serial: "A"}},
	} {
		if _, err := (HuaweiSNMP{}).LastDowns(context.Background(), newPon14(), bad); err == nil {
			t.Errorf("%s must be refused", name)
		}
	}
}

type countingMIB struct {
	*fakeMIB
	requests, maxOIDs int
}

func (c *countingMIB) Get(ctx context.Context, oids []string) (map[string]SNMPValue, error) {
	c.requests++
	c.maxOIDs = max(c.maxOIDs, len(oids))
	return c.fakeMIB.Get(ctx, oids)
}

type deadMIB struct{ *fakeMIB }

func (deadMIB) Get(context.Context, []string) (map[string]SNMPValue, error) {
	return nil, errors.New("request timeout")
}

func TestLastDownsErrorSaysWhichPortAndOntIDsTheAgentStoppedAnsweringOn(t *testing.T) {
	_, err := HuaweiSNMP{}.LastDowns(context.Background(), deadMIB{newPon14()}, []DownTarget{
		{PonPath: "0/0/14", OntID: 3, Serial: "A"}, {PonPath: "0/0/14", OntID: 9, Serial: "B"}})
	if err == nil || !strings.Contains(err.Error(), "port 0/0/14 ont-ids 3..9") || !strings.Contains(err.Error(), "request timeout") {
		t.Fatalf("the error must carry the port and the ONT-ID range: %v", err)
	}
}
