package collector

import (
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"os"
	"path/filepath"
	"reflect"
	"regexp"
	"strings"
	"sync/atomic"
	"testing"
	"time"

	"github.com/keslleykledston/44-fibercore_ai/agents/edge/internal/olt"
)

type fileSession struct{ dir string }

func (f fileSession) Run(_ context.Context, cmd string) (string, error) {
	m := map[string]string{
		"display version": "display_version.txt", "display ont info summary 0/1/0": "ont_info_summary_0_1_0.txt",
		"display ont optical-info 0/1/0 all": "ont_optical_0_1_0.txt",
	}
	n, ok := m[cmd]
	if !ok {
		return "", errors.New("unexpected " + cmd)
	}
	b, err := os.ReadFile(filepath.Join("..", "olt", "testdata", f.dir, n))
	return string(b), err
}

func src(name, dir string, unverified bool) OLTSource {
	return OLTSource{Name: name, Driver: olt.Huawei{}, Ports: []string{"0/1/0"}, AllowUnverified: unverified,
		Open: func(context.Context) (olt.Session, func(), error) { return fileSession{dir}, func() {}, nil }}
}

func TestOLTSnapshotPayloadMatchesCloudContractAndNeverClaimsObserved(t *testing.T) {
	c := &OLT{EdgeID: "e1", Sources: []OLTSource{src("OLT-A", "huawei_ma5800/R018", false)},
		Now: func() time.Time { return time.Date(2026, 10, 28, 1, 0, 0, 0, time.UTC) }}
	items, err := c.Collect(context.Background())
	if err != nil || len(items) != 1 || items[0].Kind != "olt_snapshot" || items[0].Key != "olt:OLT-A" {
		t.Fatalf("items=%v err=%v", items, err)
	}
	golden := filepath.Join("..", "..", "..", "..", "tests", "fixtures", "edge", "olt_snapshot_huawei.golden.json")
	if os.Getenv("UPDATE_GOLDEN") == "1" {
		var pretty map[string]any
		_ = json.Unmarshal(items[0].Payload, &pretty)
		b, _ := json.MarshalIndent(pretty, "", "  ")
		_ = os.MkdirAll(filepath.Dir(golden), 0o755)
		_ = os.WriteFile(golden, append(b, '\n'), 0o644)
	}
	want, err := os.ReadFile(golden)
	if err != nil {
		t.Fatal(err)
	}
	var wantV, gotV any
	_ = json.Unmarshal(want, &wantV)
	_ = json.Unmarshal(items[0].Payload, &gotV)
	if !reflect.DeepEqual(wantV, gotV) {
		t.Fatalf("payload differs from golden consumed by the Python contract test:\n%s", items[0].Payload)
	}
	var p map[string]any
	_ = json.Unmarshal(items[0].Payload, &p)
	if p["driver_level"] != "identified" || p["name"] != "OLT-A" || p["vendor"] != "huawei" || p["firmware"] != "R018" || p["edge_id"] != "e1" {
		t.Fatalf("payload=%v", p)
	}
	if len(p["onus"].([]any)) != 3 || len(p["pons"].([]any)) != 1 {
		t.Fatalf("payload=%v", p)
	}
}

func TestUnknownFirmwareRefusedUnlessExplicitlyAllowed(t *testing.T) {
	bad := src("OLT-B", "huawei_ma5800/R018", false)
	bad.Open = func(context.Context) (olt.Session, func(), error) {
		return versionOverride{fileSession{"huawei_ma5800/R018"}}, func() {}, nil
	}
	items, err := (&OLT{EdgeID: "e", Sources: []OLTSource{bad}}).Collect(context.Background())
	if !errors.Is(err, olt.ErrUnsupportedFirmware) || len(items) != 0 {
		t.Fatalf("items=%v err=%v", items, err)
	}
	bad.AllowUnverified = true
	items, err = (&OLT{EdgeID: "e", Sources: []OLTSource{bad}}).Collect(context.Background())
	if err != nil || len(items) != 1 {
		t.Fatalf("items=%v err=%v", items, err)
	}
	var p map[string]any
	_ = json.Unmarshal(items[0].Payload, &p)
	if p["driver_level"] != "identified" {
		t.Fatalf("unverified must stay identified: %v", p["driver_level"])
	}
}

type versionOverride struct{ fileSession }

func (v versionOverride) Run(ctx context.Context, cmd string) (string, error) {
	if cmd == "display version" {
		return "  VERSION : R999\n  PRODUCT : MA5800-X7\n", nil
	}
	return v.fileSession.Run(ctx, cmd)
}

func TestOneOLTFailureKeepsOthers(t *testing.T) {
	broken := OLTSource{Name: "OLT-X", Driver: olt.Huawei{}, Ports: []string{"0/1/0"},
		Open: func(context.Context) (olt.Session, func(), error) { return nil, nil, errors.New("unreachable") }}
	items, err := (&OLT{EdgeID: "e", Sources: []OLTSource{broken, src("OLT-A", "huawei_ma5800/R018", false)}}).Collect(context.Background())
	if err == nil || len(items) != 1 {
		t.Fatalf("items=%d err=%v", len(items), err)
	}
}

type bulkSession struct{ n int }

func (b *bulkSession) Run(_ context.Context, cmd string) (string, error) {
	b.n++
	switch cmd {
	case "display version":
		return "  VERSION : R018\n  PRODUCT : MA5800-X7\n", nil
	case "show version":
		return "Model : C300\nSoftware Version : V2.1.0P3\n", nil
	}
	return "", nil
}

func TestMaxPortsFitsCommandBudgetForBothVendors(t *testing.T) {
	var ports []string
	for i := 0; i < 256; i++ {
		ports = append(ports, fmt.Sprintf("0/1/%d", i))
	}
	for name, drv := range map[string]olt.Driver{"huawei": olt.Huawei{}, "zte": olt.ZTE{}} {
		bs := &bulkSession{}
		s := OLTSource{Name: name, Driver: drv, Ports: ports,
			Open: func(context.Context) (olt.Session, func(), error) { return bs, func() {}, nil }}
		if _, err := (&OLT{EdgeID: "e", Sources: []OLTSource{s}}).Collect(context.Background()); err != nil {
			t.Fatalf("%s with 256 ports: %v (commands issued=%d, budget=%d)", name, err, bs.n, commandBudget(256))
		}
	}
}

type pagedSession struct{ fileSession }

func (p pagedSession) Run(ctx context.Context, cmd string) (string, error) {
	if cmd == "display ont info summary 0/1/0" {
		b, err := os.ReadFile(filepath.Join("..", "olt", "testdata", "huawei_ma5800/R018", "ont_info_summary_paginated_0_1_0.txt"))
		return string(b), err
	}
	return p.fileSession.Run(ctx, cmd)
}

func TestPaginatedOLTOutputYieldsNoSnapshotAndNeverACompletePON(t *testing.T) {
	s := src("OLT-P", "huawei_ma5800/R018", false)
	s.Open = func(context.Context) (olt.Session, func(), error) {
		return pagedSession{fileSession{"huawei_ma5800/R018"}}, func() {}, nil
	}
	items, err := (&OLT{EdgeID: "e", Sources: []OLTSource{s}}).Collect(context.Background())
	if !errors.Is(err, olt.ErrPaginated) || len(items) != 0 {
		t.Fatalf("truncated output must not produce a snapshot (it would be sent with complete=true): items=%v err=%v", items, err)
	}
}

func TestIdentifiedDriverNeverDeclaresAPonComplete(t *testing.T) {
	items, err := (&OLT{EdgeID: "e", Sources: []OLTSource{src("OLT-C", "huawei_ma5800/R018", false)}}).Collect(context.Background())
	if err != nil || len(items) != 1 {
		t.Fatalf("items=%v err=%v", items, err)
	}
	var p struct {
		PONs []struct {
			Complete bool `json:"complete"`
		} `json:"pons"`
	}
	_ = json.Unmarshal(items[0].Payload, &p)
	if len(p.PONs) != 1 || p.PONs[0].Complete {
		t.Fatalf("an identified (synthetic-fixture) driver cannot prove completeness: %s", items[0].Payload)
	}
}

type shellLike struct{ olt.Session }

func (shellLike) EndProven() bool { return false }

func TestPonCompleteNeedsObservedDriverAndAProvenEndOfCommand(t *testing.T) {
	exec := fileSession{t.TempDir()}
	for _, c := range []struct {
		name     string
		level    olt.Level
		sess     olt.Session
		verified bool
		want     bool
	}{
		{"observed + exec", olt.LevelObserved, exec, false, true},
		{"observed + shell, end inferred from a device-controlled prompt", olt.LevelObserved, shellLike{exec}, false, false},
		{"observed + shell, listing proven complete in band", olt.LevelObserved, shellLike{exec}, true, true},
		{"identified + exec", olt.LevelIdentified, exec, false, false},
		{"identified + shell, even if the driver says verified", olt.LevelIdentified, shellLike{exec}, true, false},
	} {
		if got := ponComplete(c.level, c.sess, olt.PON{Verified: c.verified}); got != c.want {
			t.Errorf("%s: got %v want %v", c.name, got, c.want)
		}
	}
}

// r015Session replays the REAL MA5608T R015 captures through the same command sequence the R015 profile sends.
type r015Session struct{ dropRow bool }

var (
	r015Erased = regexp.MustCompile(`-{2,}\s*More\s*\(\s*Press\s+'?Q'?\s+to\s+break\s*\)\s*-{2,}\x1b\[\d+D *\x1b\[\d+D`)
	r015Esc    = regexp.MustCompile(`\x1b\[[0-9;?]*[ -/]*[@-~]`)
)

func (r r015Session) Run(_ context.Context, cmd string) (string, error) {
	files := map[string]string{
		"display version": "display_version.txt", "display ont info 14 all": "ont_info_14_all_paged.txt",
		"display ont optical-info 14 all": "ont_optical_info_14_all.txt",
	}
	switch cmd {
	case "enable", "config", "quit", "interface gpon 0/0":
		return "", nil
	}
	n, ok := files[cmd]
	if !ok {
		return "", errors.New("unexpected " + cmd)
	}
	b, err := os.ReadFile(filepath.Join("..", "olt", "testdata", "huawei_ma5608t", "MA5600V800R015C00", n))
	out := strings.ReplaceAll(r015Esc.ReplaceAllString(r015Erased.ReplaceAllString(string(b), ""), ""), "\r", "")
	if r.dropRow && n == "ont_info_14_all_paged.txt" {
		out = regexp.MustCompile(`(?m)^ *0/ 0/14 +3 .*\n`).ReplaceAllString(out, "")
	}
	return out, err
}

func r015Payload(t *testing.T, sess olt.Session) (level string, complete bool, onus int) {
	t.Helper()
	s := OLTSource{Name: "OLT-R015", Driver: olt.HuaweiR015{}, Ports: []string{"0/0/14"},
		Open: func(context.Context) (olt.Session, func(), error) { return sess, func() {}, nil }}
	items, err := (&OLT{EdgeID: "e", Sources: []OLTSource{s}}).Collect(context.Background())
	if err != nil || len(items) != 1 {
		t.Fatalf("items=%d err=%v", len(items), err)
	}
	var p struct {
		Level string `json:"driver_level"`
		PONs  []struct {
			Complete bool `json:"complete"`
		} `json:"pons"`
		ONUs []json.RawMessage `json:"onus"`
	}
	if err := json.Unmarshal(items[0].Payload, &p); err != nil || len(p.PONs) != 1 {
		t.Fatalf("payload: %v %s", err, items[0].Payload)
	}
	return p.Level, p.PONs[0].Complete, len(p.ONUs)
}

// withObservedR015 simulates the future promotion of the R015 profile; it never touches the shipped registry permanently.
func withObservedR015(t *testing.T) {
	t.Helper()
	saved := append([]olt.Homologation(nil), olt.Registry...)
	for i := range olt.Registry {
		if strings.HasPrefix(olt.Registry[i].ModelPrefix, "MA56") {
			olt.Registry[i].Level = olt.LevelObserved
		}
	}
	t.Cleanup(func() { olt.Registry = saved })
}

func TestR015ShellListingIsCompleteOnlyWhenTheCLIsOwnTotalMatches(t *testing.T) {
	withObservedR015(t)
	lvl, complete, n := r015Payload(t, shellLike{r015Session{}})
	if lvl != "observed" || !complete || n != 12 {
		t.Fatalf("full listing over a shell: level=%s complete=%v onus=%d", lvl, complete, n)
	}
	_, complete, n = r015Payload(t, shellLike{r015Session{dropRow: true}})
	if complete || n != 11 {
		t.Fatalf("a listing cut short must not be complete: complete=%v onus=%d", complete, n)
	}
}

// The shipped registry must NOT promote the R015 family on a single-PON capture (Codex review): until the promotion
// checklist is met every PON of this firmware is reported incomplete, so it cannot open or close a mass-outage incident.
func TestShippedRegistryKeepsR015IdentifiedSoNoPonIsEverComplete(t *testing.T) {
	lvl, complete, n := r015Payload(t, shellLike{r015Session{}})
	if lvl != "identified" || complete || n != 12 {
		t.Fatalf("shipped registry: level=%s complete=%v onus=%d (want identified, incomplete, 12)", lvl, complete, n)
	}
}

// snmpFake is a tiny agent for PON 0/0/14 (ifIndex 4194307584): 6 ONTs, 2 online. Values have the shape read from a real OLT.
type snmpFake struct{ dropSerial bool }

const (
	fkBase = "1.3.6.1.4.1.2011.6.128.1.1.2"
	fkIf   = 4194307584
)

func (f snmpFake) vals() map[string]olt.SNMPValue {
	m := map[string]olt.SNMPValue{fmt.Sprintf("1.3.6.1.2.1.2.2.1.2.%d", fkIf): {Bytes: []byte("Huawei-MA5600-V800R015-GPON_UNI"), IsBytes: true}}
	for id := 0; id < 6; id++ {
		run := int64(2)
		if id >= 4 {
			run = 1
			m[fmt.Sprintf("%s.51.1.4.%d.%d", fkBase, fkIf, id)] = olt.SNMPValue{Int: -1300 - int64(id), IsInt: true}
		} else {
			m[fmt.Sprintf("%s.46.1.24.%d.%d", fkBase, fkIf, id)] = olt.SNMPValue{Int: 13, IsInt: true}
		}
		m[fmt.Sprintf("%s.46.1.15.%d.%d", fkBase, fkIf, id)] = olt.SNMPValue{Int: run, IsInt: true}
		if !(f.dropSerial && id == 3) {
			m[fmt.Sprintf("%s.43.1.3.%d.%d", fkBase, fkIf, id)] = olt.SNMPValue{Bytes: []byte{0x48, 0x57, 0x54, 0x43, 0x40, 0, 0, byte(id)}, IsBytes: true}
		}
	}
	return m
}

func (f snmpFake) Get(_ context.Context, oids []string) (map[string]olt.SNMPValue, error) {
	v, out := f.vals(), map[string]olt.SNMPValue{}
	for _, o := range oids {
		if x, ok := v[o]; ok {
			out[o] = x
		} else {
			out[o] = olt.SNMPValue{Missing: true}
		}
	}
	return out, nil
}

func (f snmpFake) Walk(_ context.Context, root string, _ int) ([]olt.SNMPRow, error) {
	var rows []olt.SNMPRow
	for id := 0; id < 6; id++ { // ids ascend, so rows come out in OID order
		if v, ok := f.vals()[fmt.Sprintf("%s.%d", root, id)]; ok {
			rows = append(rows, olt.SNMPRow{Suffix: fmt.Sprint(id), Value: v})
		}
	}
	return rows, nil
}

func snmpPayload(t *testing.T, r olt.SNMPReader) (level string, complete bool, onus int, statuses map[string]int) {
	t.Helper()
	s := OLTSource{Name: "OLT-SNMP", Ports: []string{"0/0/14"}, SNMPDriver: olt.HuaweiSNMP{},
		OpenSNMP: func(context.Context) (olt.SNMPReader, func(), error) { return r, func() {}, nil }}
	items, err := (&OLT{EdgeID: "e", Sources: []OLTSource{s}}).Collect(context.Background())
	if err != nil || len(items) != 1 {
		t.Fatalf("items=%d err=%v", len(items), err)
	}
	var p struct {
		Level string `json:"driver_level"`
		PONs  []struct {
			Complete bool `json:"complete"`
		} `json:"pons"`
		ONUs []struct {
			Status string `json:"status"`
		} `json:"onus"`
	}
	if err := json.Unmarshal(items[0].Payload, &p); err != nil || len(p.PONs) != 1 {
		t.Fatalf("payload: %v %s", err, items[0].Payload)
	}
	statuses = map[string]int{}
	for _, u := range p.ONUs {
		statuses[u.Status]++
	}
	return p.Level, p.PONs[0].Complete, len(p.ONUs), statuses
}

func TestSNMPSourceFeedsTheSamePayloadAndCompletenessNeedsAnObservedDriverAndProof(t *testing.T) {
	lvl, complete, n, st := snmpPayload(t, snmpFake{})
	if lvl != "identified" || complete || n != 6 || st["online"] != 2 || st["dying_gasp"] != 4 {
		t.Fatalf("shipped registry: level=%s complete=%v onus=%d statuses=%v", lvl, complete, n, st)
	}
	withObservedR015(t)
	if lvl, complete, _, _ := snmpPayload(t, snmpFake{}); lvl != "observed" || !complete {
		t.Fatalf("promoted + proven by the two walks: level=%s complete=%v", lvl, complete)
	}
	if _, complete, n, _ := snmpPayload(t, snmpFake{dropSerial: true}); complete || n != 5 {
		t.Fatalf("a listing whose two walks disagree must not be complete: complete=%v onus=%d", complete, n)
	}
}

type failingSNMP struct{ snmpFake }

func (failingSNMP) Get(context.Context, []string) (map[string]olt.SNMPValue, error) {
	return nil, errors.New("request timeout (after 1 retries)")
}

func TestAFailedSNMPCollectionLeavesTheDeviceAloneForTheCooldown(t *testing.T) {
	opens := 0
	clock := time.Date(2026, 10, 28, 12, 0, 0, 0, time.UTC)
	src := OLTSource{Name: "OLT-COOL", Ports: []string{"0/0/14"}, SNMPDriver: olt.HuaweiSNMP{},
		OpenSNMP: func(context.Context) (olt.SNMPReader, func(), error) { opens++; return failingSNMP{}, func() {}, nil }}
	o := &OLT{EdgeID: "e", Sources: []OLTSource{src}, Now: func() time.Time { return clock }}
	if _, err := o.Collect(context.Background()); err == nil || opens != 1 {
		t.Fatalf("first collection must fail after opening once: err=%v opens=%d", err, opens)
	}
	clock = clock.Add(time.Minute) // still cooling: nothing may be sent to the OLT
	if _, err := o.Collect(context.Background()); err == nil || !strings.Contains(err.Error(), "cooling down") || opens != 1 {
		t.Fatalf("during the cooldown the device must not be touched: err=%v opens=%d", err, opens)
	}
	clock = clock.Add(5 * time.Minute) // cooldown over: it may try again (and fail again, restarting the cooldown)
	if _, err := o.Collect(context.Background()); err == nil || opens != 2 {
		t.Fatalf("after the cooldown it tries again: err=%v opens=%d", err, opens)
	}
	// success is never cooled: a healthy OLT is collected every cycle
	ok := OLTSource{Name: "OLT-OK", Ports: []string{"0/0/14"}, SNMPDriver: olt.HuaweiSNMP{},
		OpenSNMP: func(context.Context) (olt.SNMPReader, func(), error) { return snmpFake{}, func() {}, nil }}
	o2 := &OLT{EdgeID: "e", Sources: []OLTSource{ok}, Now: func() time.Time { return clock }}
	for i := 0; i < 3; i++ {
		if _, err := o2.Collect(context.Background()); err != nil {
			t.Fatalf("cycle %d: %v", i, err)
		}
	}
}

type gatedSNMP struct {
	snmpFake
	entered chan struct{}
	release chan struct{}
}

func (g gatedSNMP) Get(ctx context.Context, oids []string) (map[string]olt.SNMPValue, error) {
	select {
	case g.entered <- struct{}{}:
	default:
	}
	<-g.release
	return g.snmpFake.Get(ctx, oids)
}

func TestOnlyOneSNMPCollectionPerOLTRunsAtATime(t *testing.T) {
	g := gatedSNMP{entered: make(chan struct{}, 1), release: make(chan struct{})}
	var opens atomic.Int32
	src := OLTSource{Name: "OLT-ONE", Ports: []string{"0/0/14"}, SNMPDriver: olt.HuaweiSNMP{},
		OpenSNMP: func(context.Context) (olt.SNMPReader, func(), error) { opens.Add(1); return g, func() {}, nil }}
	o := &OLT{EdgeID: "e", Sources: []OLTSource{src}}
	done := make(chan error, 1)
	go func() { _, err := o.Collect(context.Background()); done <- err }()
	<-g.entered // the first collection is now talking to the device
	// a second one (the periodic worker AND a job can overlap) must be refused without opening anything
	if _, err := o.Collect(context.Background()); err == nil || !strings.Contains(err.Error(), "already running") || opens.Load() != 1 {
		t.Fatalf("overlap must be refused before any I/O: err=%v opens=%d", err, opens.Load())
	}
	close(g.release)
	if err := <-done; err != nil {
		t.Fatal(err)
	}
	if _, err := o.Collect(context.Background()); err != nil { // reservation released: the next cycle runs normally
		t.Fatalf("after the first one finished: %v", err)
	}
}

func TestTwoAliasesOfOneAgentShareTheLockAndTheCooldown(t *testing.T) {
	opens := 0
	clock := time.Date(2026, 10, 28, 12, 0, 0, 0, time.UTC)
	mk := func(name string) OLTSource {
		return OLTSource{Name: name, SNMPKey: "192.0.2.10:161", Ports: []string{"0/0/14"}, SNMPDriver: olt.HuaweiSNMP{},
			OpenSNMP: func(context.Context) (olt.SNMPReader, func(), error) { opens++; return failingSNMP{}, func() {}, nil }}
	}
	o := &OLT{EdgeID: "e", Sources: []OLTSource{mk("alias-1"), mk("alias-2")}, Now: func() time.Time { return clock }}
	_, err := o.Collect(context.Background())
	if err == nil || opens != 1 || !strings.Contains(err.Error(), "cooling down") {
		t.Fatalf("the failure of one alias must cool the whole agent: err=%v opens=%d", err, opens)
	}
}

type countingSession struct {
	runs *int
	err  error
}

func (c countingSession) Run(ctx context.Context, cmd string) (string, error) {
	*c.runs++
	if c.err != nil {
		return "", c.err
	}
	return fileSession{"huawei_ma5800/R018"}.Run(ctx, cmd)
}

func cliSrc(opens *int, runs *int, fail error) OLTSource {
	return OLTSource{Name: "OLT-CLI", Driver: olt.Huawei{}, Ports: []string{"0/1/0"}, AllowUnverified: true,
		Open: func(context.Context) (olt.Session, func(), error) {
			*opens++
			return countingSession{runs, fail}, func() {}, nil
		}}
}

func TestAFailedCLICollectionLeavesTheDeviceAloneForTheCooldownAndRetriesAfterIt(t *testing.T) {
	var opens, runs int
	clock := time.Date(2026, 10, 29, 12, 0, 0, 0, time.UTC)
	o := &OLT{EdgeID: "e", Sources: []OLTSource{cliSrc(&opens, &runs, errors.New("ssh: unable to authenticate"))}, Now: func() time.Time { return clock }}
	if _, err := o.Collect(context.Background()); err == nil || opens != 1 {
		t.Fatalf("first attempt must fail after one login: err=%v opens=%d", err, opens)
	}
	clock = clock.Add(14 * time.Minute) // the sooner-retry after an incomplete round must not log in again
	if _, err := o.Collect(context.Background()); err == nil || !strings.Contains(err.Error(), "cooling down") || opens != 1 {
		t.Fatalf("inside the CLI cooldown nothing may reach the device: err=%v opens=%d", err, opens)
	}
	clock = clock.Add(2 * time.Minute)
	if _, err := o.Collect(context.Background()); err == nil || opens != 2 {
		t.Fatalf("after the cooldown it tries again: err=%v opens=%d", err, opens)
	}
}

func TestIntervalPacesAHealthyCLIOLTWithoutReportingAnIncompleteRound(t *testing.T) {
	var opens, runs int
	clock := time.Date(2026, 10, 29, 12, 0, 0, 0, time.UTC)
	s := cliSrc(&opens, &runs, nil)
	s.Interval = 15 * time.Minute
	o := &OLT{EdgeID: "e", Sources: []OLTSource{s}, Now: func() time.Time { return clock }}
	items, err := o.Collect(context.Background())
	if err != nil || len(items) != 1 || opens != 1 {
		t.Fatalf("first call collects: items=%d err=%v opens=%d", len(items), err, opens)
	}
	for _, d := range []time.Duration{30 * time.Second, 5 * time.Minute, 9 * time.Minute} { // NBI ticks and sooner retries
		clock = clock.Add(d)
		items, err = o.Collect(context.Background())
		if err != nil || len(items) != 0 || opens != 1 {
			t.Fatalf("not due at +%s: a quiet skip, not an error and not a device touch: items=%d err=%v opens=%d", d, len(items), err, opens)
		}
	}
	clock = clock.Add(time.Minute) // 15m30s after the first attempt
	if items, err = o.Collect(context.Background()); err != nil || len(items) != 1 || opens != 2 {
		t.Fatalf("due again: items=%d err=%v opens=%d", len(items), err, opens)
	}
}

func TestACustomCooldownOverridesTheDefaultAndPacingAppliesPerPhysicalDevice(t *testing.T) {
	var opens, runs int
	clock := time.Date(2026, 10, 29, 12, 0, 0, 0, time.UTC)
	mk := func(name string) OLTSource {
		s := cliSrc(&opens, &runs, errors.New("boom"))
		s.Name, s.SNMPKey, s.Cooldown = name, "192.0.2.10:22", time.Minute
		return s
	}
	o := &OLT{EdgeID: "e", Sources: []OLTSource{mk("a1"), mk("a2")}, Now: func() time.Time { return clock }}
	if _, err := o.Collect(context.Background()); err == nil || opens != 1 {
		t.Fatalf("an alias of the same device must be refused while the first is cooling: err=%v opens=%d", err, opens)
	}
	clock = clock.Add(2 * time.Minute)
	if _, err := o.Collect(context.Background()); err == nil || opens != 2 {
		t.Fatalf("custom 1 min cooldown elapsed: err=%v opens=%d", err, opens)
	}
}

func TestPacingSurvivesARestartSoACrashLoopCannotLogInRepeatedly(t *testing.T) {
	path := filepath.Join(t.TempDir(), "queue.db.olt-guard.json")
	clock := time.Date(2026, 10, 29, 12, 0, 0, 0, time.UTC)
	var opens, runs int
	boot := func(fail error, interval time.Duration) *OLT { // a brand-new process: nothing but the file is remembered
		s := cliSrc(&opens, &runs, fail)
		s.Interval = interval
		return &OLT{EdgeID: "e", Sources: []OLTSource{s}, Guard: FileGuard{Path: path}, Now: func() time.Time { return clock }}
	}
	if _, err := boot(errors.New("ssh: unable to authenticate"), 15*time.Minute).Collect(context.Background()); err == nil || opens != 1 {
		t.Fatalf("first boot fails after one login: err=%v opens=%d", err, opens)
	}
	for i := 0; i < 5; i++ { // cron relaunches the binary every minute
		clock = clock.Add(time.Minute)
		if _, err := boot(errors.New("again"), 15*time.Minute).Collect(context.Background()); err == nil || !strings.Contains(err.Error(), "cooling down") || opens != 1 {
			t.Fatalf("restart %d inside the cooldown must not dial: err=%v opens=%d", i, err, opens)
		}
	}
	clock = clock.Add(11 * time.Minute) // cooldown (15 min) over
	if items, err := boot(nil, 15*time.Minute).Collect(context.Background()); err != nil || len(items) != 1 || opens != 2 {
		t.Fatalf("after the cooldown a restart may collect: items=%d err=%v opens=%d", len(items), err, opens)
	}
	clock = clock.Add(2 * time.Minute) // a SUCCESS also paces: the interval holds across a restart
	if items, err := boot(nil, 15*time.Minute).Collect(context.Background()); err != nil || len(items) != 0 || opens != 2 {
		t.Fatalf("a restart right after a successful collection stays quiet: items=%d err=%v opens=%d", len(items), err, opens)
	}
	if fi, err := os.Stat(path); err != nil || fi.Mode().Perm() != 0o600 {
		t.Fatalf("state file must be 0600: %v %v", fi, err)
	}
}

func TestAnAttemptThatDiesMidWayStillCountsAfterTheRestart(t *testing.T) {
	path := filepath.Join(t.TempDir(), "g.json")
	clock := time.Date(2026, 10, 29, 12, 0, 0, 0, time.UTC)
	var opens, runs int
	s := cliSrc(&opens, &runs, nil)
	s.Interval = 15 * time.Minute
	s.Open = func(context.Context) (olt.Session, func(), error) {
		opens++
		panic("process killed while the session was open") // no failure bookkeeping ever runs
	}
	func() {
		defer func() { _ = recover() }()
		_, _ = (&OLT{Sources: []OLTSource{s}, Guard: FileGuard{Path: path}, Now: func() time.Time { return clock }}).Collect(context.Background())
	}()
	if opens != 1 {
		t.Fatalf("opens=%d", opens)
	}
	clock = clock.Add(time.Minute)
	if items, err := (&OLT{Sources: []OLTSource{s}, Guard: FileGuard{Path: path}, Now: func() time.Time { return clock }}).Collect(context.Background()); err == nil || len(items) != 0 || opens != 1 {
		t.Fatalf("the attempt AND its pessimistic cooldown are persisted BEFORE any I/O: items=%d err=%v opens=%d", len(items), err, opens)
	}
}

func TestACorruptStateFileMakesTheGuardAssumeTheDeviceWasJustTouched(t *testing.T) {
	path := filepath.Join(t.TempDir(), "g.json")
	if err := os.WriteFile(path, []byte("{not json"), 0o600); err != nil {
		t.Fatal(err)
	}
	clock := time.Date(2026, 10, 29, 12, 0, 0, 0, time.UTC)
	var opens, runs int
	s := cliSrc(&opens, &runs, nil)
	s.Interval = 15 * time.Minute
	o := &OLT{Sources: []OLTSource{s}, Guard: FileGuard{Path: path}, Now: func() time.Time { return clock }}
	if items, err := o.Collect(context.Background()); err != nil || len(items) != 0 || opens != 0 {
		t.Fatalf("unknown history: wait one interval, do not dial: items=%d err=%v opens=%d", len(items), err, opens)
	}
	clock = clock.Add(16 * time.Minute)
	if items, err := o.Collect(context.Background()); err != nil || len(items) != 1 || opens != 1 {
		t.Fatalf("after one interval it works again (and the file is healthy): items=%d err=%v opens=%d", len(items), err, opens)
	}
	if _, err := (FileGuard{Path: path}).Load(); err != nil {
		t.Fatalf("the corrupt file must have been replaced: %v", err)
	}
}

type brokenGuard struct{}

func (brokenGuard) Load() (map[string]GuardState, error) { return map[string]GuardState{}, nil }
func (brokenGuard) Save(map[string]GuardState) error     { return errors.New("read-only file system") }

func TestIfThePacingCannotBeRememberedTheDeviceIsNotTouched(t *testing.T) {
	var opens, runs int
	o := &OLT{Sources: []OLTSource{cliSrc(&opens, &runs, nil)}, Guard: brokenGuard{}}
	if _, err := o.Collect(context.Background()); err == nil || opens != 0 {
		t.Fatalf("fail closed: err=%v opens=%d", err, opens)
	}
}

func TestCLIAndSNMPEntriesOfOnePhysicalOLTShareOneGuard(t *testing.T) {
	var opens, runs int
	cli := cliSrc(&opens, &runs, nil)
	cli.Name, cli.SNMPKey = "olt-ssh", "192.0.2.10"
	snmpOpens := 0
	sn := OLTSource{Name: "olt-snmp", SNMPKey: "192.0.2.10", Ports: []string{"0/0/14"}, SNMPDriver: olt.HuaweiSNMP{},
		OpenSNMP: func(context.Context) (olt.SNMPReader, func(), error) { snmpOpens++; return snmpFake{}, func() {}, nil }}
	gate := make(chan struct{})
	entered := make(chan struct{}, 1)
	cli.Open = func(context.Context) (olt.Session, func(), error) {
		opens++
		entered <- struct{}{}
		<-gate
		return countingSession{&runs, nil}, func() {}, nil
	}
	o := &OLT{Sources: []OLTSource{cli}}
	done := make(chan struct{})
	go func() { _, _ = o.Collect(context.Background()); close(done) }()
	<-entered
	o.Sources = []OLTSource{sn} // the periodic worker meets a job: same host, other transport
	if _, err := o.Collect(context.Background()); err == nil || !strings.Contains(err.Error(), "already running") || snmpOpens != 0 {
		t.Fatalf("SNMP must wait for the SSH session on the same OLT: err=%v snmpOpens=%d", err, snmpOpens)
	}
	close(gate)
	<-done
}

func TestACorruptStateCoolsEveryTransportEvenWithoutAnInterval(t *testing.T) {
	path := filepath.Join(t.TempDir(), "g.json")
	if err := os.WriteFile(path, []byte("garbage"), 0o600); err != nil {
		t.Fatal(err)
	}
	clock := time.Date(2026, 10, 29, 12, 0, 0, 0, time.UTC)
	snmpOpens := 0
	sn := OLTSource{Name: "olt-snmp", SNMPKey: "192.0.2.10", Ports: []string{"0/0/14"}, SNMPDriver: olt.HuaweiSNMP{}, // Interval 0: paced per packet only
		OpenSNMP: func(context.Context) (olt.SNMPReader, func(), error) { snmpOpens++; return snmpFake{}, func() {}, nil }}
	o := &OLT{Sources: []OLTSource{sn}, Guard: FileGuard{Path: path}, Now: func() time.Time { return clock }}
	for i := 0; i < 3; i++ { // the next calls must not slip through after the first one was deferred
		_, _ = o.Collect(context.Background())
		clock = clock.Add(time.Minute)
	}
	if snmpOpens != 0 {
		t.Fatalf("a corrupt guard file must keep the agent untouched for the whole cooldown: opens=%d", snmpOpens)
	}
	clock = clock.Add(5 * time.Minute)
	if _, err := o.Collect(context.Background()); err != nil || snmpOpens != 1 {
		t.Fatalf("after the cooldown it collects: err=%v opens=%d", err, snmpOpens)
	}
}

type flakySave struct {
	inner FileGuard
	fail  *bool
}

func (f flakySave) Load() (map[string]GuardState, error) { return f.inner.Load() }
func (f flakySave) Save(m map[string]GuardState) error {
	if *f.fail {
		return errors.New("disk full")
	}
	return f.inner.Save(m)
}

func TestAFailureWhoseCooldownCannotBeSavedStillLeavesTheReservationOnDisk(t *testing.T) {
	path := filepath.Join(t.TempDir(), "g.json")
	clock := time.Date(2026, 10, 29, 12, 0, 0, 0, time.UTC)
	var opens, runs int
	failSave := false
	s := cliSrc(&opens, &runs, errors.New("boom"))
	s.Open = func(context.Context) (olt.Session, func(), error) {
		opens++
		failSave = true // the disk fills up while the session is open
		return nil, nil, errors.New("connection refused")
	}
	g := flakySave{FileGuard{Path: path}, &failSave}
	if _, err := (&OLT{Sources: []OLTSource{s}, Guard: g, Now: func() time.Time { return clock }}).Collect(context.Background()); err == nil {
		t.Fatal("expected failure")
	}
	failSave = false
	clock = clock.Add(time.Minute) // a restarted process reads the pessimistic reservation written before the I/O
	if _, err := (&OLT{Sources: []OLTSource{s}, Guard: g, Now: func() time.Time { return clock }}).Collect(context.Background()); err == nil || !strings.Contains(err.Error(), "cooling down") || opens != 1 {
		t.Fatalf("restart must still be cooling: err=%v opens=%d", err, opens)
	}
}

func TestGuardFilesThatAreValidJSONButNotAnObjectAreCorruptNotACrash(t *testing.T) {
	for _, body := range []string{"null", "[]", `"x"`, "42", ""} {
		path := filepath.Join(t.TempDir(), "g.json")
		if err := os.WriteFile(path, []byte(body), 0o600); err != nil {
			t.Fatal(err)
		}
		clock := time.Date(2026, 10, 29, 12, 0, 0, 0, time.UTC)
		var opens, runs int
		s := cliSrc(&opens, &runs, nil)
		s.Interval = 15 * time.Minute
		o := &OLT{Sources: []OLTSource{s}, Guard: FileGuard{Path: path}, Now: func() time.Time { return clock }}
		if items, err := o.Collect(context.Background()); err != nil || len(items) != 0 || opens != 0 {
			t.Fatalf("%q: corrupt => quiet wait, no panic, no dial: items=%d err=%v opens=%d", body, len(items), err, opens)
		}
	}
}

func TestATimestampFarInTheFutureCannotBlockTheDeviceForever(t *testing.T) {
	path := filepath.Join(t.TempDir(), "g.json")
	clock := time.Date(2026, 10, 29, 12, 0, 0, 0, time.UTC)
	far := clock.Add(400 * 24 * time.Hour)
	if err := (FileGuard{Path: path}).Save(map[string]GuardState{"OLT-CLI": {Last: far, CoolUntil: far}}); err != nil {
		t.Fatal(err)
	}
	var opens, runs int
	s := cliSrc(&opens, &runs, nil)
	s.Interval = 15 * time.Minute
	o := &OLT{Sources: []OLTSource{s}, Guard: FileGuard{Path: path}, Now: func() time.Time { return clock }}
	if _, err := o.Collect(context.Background()); err == nil || opens != 0 {
		t.Fatalf("pulled back to a normal cooldown, not trusted: err=%v opens=%d", err, opens)
	}
	// a process restarted every few minutes must not renew the cooldown from the original absurd value
	for i := 0; i < 3; i++ {
		clock = clock.Add(4 * time.Minute)
		o = &OLT{Sources: []OLTSource{s}, Guard: FileGuard{Path: path}, Now: func() time.Time { return clock }}
		_, _ = o.Collect(context.Background())
	}
	if opens != 0 {
		t.Fatalf("still inside the corrected cooldown: opens=%d", opens)
	}
	clock = clock.Add(16 * time.Minute)
	o = &OLT{Sources: []OLTSource{s}, Guard: FileGuard{Path: path}, Now: func() time.Time { return clock }}
	if items, err := o.Collect(context.Background()); err != nil || len(items) != 1 || opens != 1 {
		t.Fatalf("a fresh process after the corrected cooldown works: items=%d err=%v opens=%d", len(items), err, opens)
	}
}

func TestOLTTimeoutGrowsWithPortsButNeverPastTheAgentsRoundLimit(t *testing.T) {
	for ports, want := range map[int]time.Duration{1: 5 * time.Minute, 16: 5 * time.Minute, 17: 5*time.Minute + 15*time.Second, 32: 9 * time.Minute, 256: 9 * time.Minute} {
		if got := oltTimeout(ports); got != want {
			t.Errorf("oltTimeout(%d)=%s want %s", ports, got, want)
		}
	}
}

func TestOnCollectedReportsOnlyAttemptsThatReachedTheDeviceAndNeverDeviceOutput(t *testing.T) {
	var opens, runs int
	clock := time.Date(2026, 10, 29, 12, 0, 0, 0, time.UTC)
	type call struct {
		name  string
		items int
		err   string
	}
	var calls []call
	s := cliSrc(&opens, &runs, nil)
	s.Interval = 15 * time.Minute
	o := &OLT{Sources: []OLTSource{s}, Now: func() time.Time { return clock },
		OnCollected: func(n string, _ time.Duration, items int, err error) {
			c := call{n, items, ""}
			if err != nil {
				c.err = err.Error()
			}
			calls = append(calls, c)
		}}
	_, _ = o.Collect(context.Background())
	clock = clock.Add(time.Minute)
	_, _ = o.Collect(context.Background()) // not due: a silent skip, nothing reached the device
	if len(calls) != 1 || calls[0].name != "OLT-CLI" || calls[0].items != 1 || calls[0].err != "" {
		t.Fatalf("calls=%+v", calls)
	}
}

func TestTheTimeoutCoversOpeningTheSessionNotOnlyTheReads(t *testing.T) {
	var opens, runs int
	for _, snmp := range []bool{false, true} {
		s := cliSrc(&opens, &runs, nil)
		s.Timeout = 50 * time.Millisecond
		s.Open = func(ctx context.Context) (olt.Session, func(), error) { <-ctx.Done(); return nil, nil, ctx.Err() } // a login that hangs
		if snmp {
			s = OLTSource{Name: "snmp", Ports: []string{"0/0/14"}, SNMPDriver: olt.HuaweiSNMP{}, Timeout: 50 * time.Millisecond,
				OpenSNMP: func(ctx context.Context) (olt.SNMPReader, func(), error) { <-ctx.Done(); return nil, nil, ctx.Err() }}
		}
		start := time.Now()
		_, err := (&OLT{Sources: []OLTSource{s}}).Collect(context.Background())
		if err == nil || !errors.Is(err, context.DeadlineExceeded) || time.Since(start) > 2*time.Second {
			t.Fatalf("snmp=%v: a hanging login must be cut by the per-OLT budget: err=%v after %s", snmp, err, time.Since(start))
		}
	}
}

func TestExclusiveSharesTheGuardAndHonoursAShorterCooldownOnlyAfterALogin(t *testing.T) {
	var opens, runs int
	clock := time.Date(2026, 10, 30, 12, 0, 0, 0, time.UTC)
	o := &OLT{EdgeID: "e", Sources: []OLTSource{cliSrc(&opens, &runs, nil)}, Now: func() time.Time { return clock }}
	name := o.Sources[0].Name
	loggedFail := func(opened func()) error { opened(); return errors.New("maneuver stopped") }
	loginFail := func(opened func()) error { return errors.New("ssh: unable to authenticate") } // never reaches opened()
	ok := func(opened func()) error { opened(); return nil }
	if err := o.Exclusive(context.Background(), name, time.Minute, 2*time.Minute, loggedFail); err == nil {
		t.Fatal("the failure is returned")
	}
	clock = clock.Add(90 * time.Second) // inside the (shorter) cooldown
	if err := o.Exclusive(context.Background(), name, time.Minute, 2*time.Minute, ok); err == nil || !strings.Contains(err.Error(), "cooling down") {
		t.Fatalf("still cooling: %v", err)
	}
	clock = clock.Add(time.Minute) // 2m30s after the failure: the 15 min default would still block, the configured 2 min does not
	if err := o.Exclusive(context.Background(), name, time.Minute, 2*time.Minute, ok); err != nil {
		t.Fatalf("after the configured cooldown it runs: %v", err)
	}
	// a failed LOGIN keeps the full 15 min, whatever is configured
	clock = clock.Add(2 * time.Minute)
	if err := o.Exclusive(context.Background(), name, time.Minute, 2*time.Minute, loginFail); err == nil {
		t.Fatal("login failure")
	}
	clock = clock.Add(10 * time.Minute)
	if err := o.Exclusive(context.Background(), name, time.Minute, 2*time.Minute, ok); err == nil || !strings.Contains(err.Error(), "cooling down") {
		t.Fatalf("a failed login must keep the 15 min cooldown: %v", err)
	}
	// and the collector sees the same state
	if _, err := o.Collect(context.Background()); err == nil || !strings.Contains(err.Error(), "cooling down") {
		t.Fatalf("the collector shares the cooldown: %v", err)
	}
	clock = clock.Add(6 * time.Minute)
	if err := o.Exclusive(context.Background(), name, time.Minute, 0, ok); err != nil { // 16 min after the login failure
		t.Fatalf("after 15 min it runs: %v", err)
	}
	// nothing configured: the default (15 min) also applies after a logged-in failure
	clock = clock.Add(2 * time.Minute)
	if err := o.Exclusive(context.Background(), name, time.Minute, 0, loggedFail); err == nil {
		t.Fatal("failure")
	}
	clock = clock.Add(10 * time.Minute)
	if err := o.Exclusive(context.Background(), name, time.Minute, 0, ok); err == nil || !strings.Contains(err.Error(), "cooling down") {
		t.Fatalf("the default cooldown is 15 min: %v", err)
	}
	// a session that is not due (too soon after the last one) is reported, never run
	clock = clock.Add(10 * time.Minute)
	if err := o.Exclusive(context.Background(), name, time.Hour, 0, ok); !errors.Is(err, ErrOLTNotDue) {
		t.Fatalf("not due: %v", err)
	}
}
