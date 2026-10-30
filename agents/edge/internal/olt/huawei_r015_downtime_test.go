package olt

import (
	"context"
	"errors"
	"reflect"
	"strconv"
	"strings"
	"testing"
	"time"
)

func TestParseLastDownTakesTheNewestDownTimeAndChecksTheONU(t *testing.T) {
	gp := r015Text(t, "register_info_14_0_offline_dying_gasp.txt")
	got, err := ParseLastDown(gp, "4857544320000077")
	want := time.Date(2026, 1, 4, 4, 0, 0, 0, time.UTC) // 2026-01-04 00:00:00-04:00: the greater of the two DownTimes, whatever the listing order
	if err != nil || !got.Equal(want) {
		t.Fatalf("got %v %v want %v", got, err, want)
	}
	if got2, err := ParseLastDown(strings.Replace(gp, "4857544320000077", "485754432000007a", 2), "485754432000007A"); err != nil || !got2.Equal(want) {
		t.Fatalf("serial case must not matter: %v %v", got2, err)
	}
	for name, c := range map[string]struct{ out, serial string }{
		"another ONU":              {gp, "4857544320000099"},
		"never went down":          {r015Text(t, "register_info_14_7_online.txt"), "4857544320000078"},
		"empty answer":             {"display ont register-info 14 0\n", "4857544320000077"},
		"footer says more records": {strings.Replace(gp, "Total :  2", "Total :  3", 1), "4857544320000077"},
		"footer missing":           {strings.Replace(gp, "Total :  2", "", 1), "4857544320000077"},
		"up again after the down":  {strings.Replace(gp, "UpTime              : 2026-01-03", "UpTime              : 2026-02-03", 1), "4857544320000077"},
		"newest record has no DownTime (older one valid)": {strings.Replace(gp, "DownTime            : 2026-01-04 00:00:00-04:00", "DownTime            : -", 1), "4857544320000077"},
		"newest record DownTime malformed (older valid)":  {strings.Replace(gp, "DownTime            : 2026-01-04 00:00:00-04:00", "DownTime            : 2026-13-45 00:00:00-04:00", 1), "4857544320000077"},
		"an older record is malformed":                    {strings.Replace(gp, "UpTime              : 2026-01-01 00:00:00-04:00", "UpTime              : ???", 1), "4857544320000077"},
		"a record without DownTime line":                  {strings.Replace(gp, "  DownTime            : 2026-01-02 00:00:00-04:00\n", "", 1), "4857544320000077"},
		"two records registered at the same instant":      {strings.Replace(gp, "UpTime              : 2026-01-03", "UpTime              : 2026-01-01", 1), "4857544320000077"},
		"year out of range":                               {strings.ReplaceAll(gp, "2026-01-0", "1999-01-0"), "4857544320000077"},
		"not a time":                                      {strings.ReplaceAll(gp, "DownTime            : 2026", "DownTime            : soon 2026"), "4857544320000077"},
	} {
		if got, err := ParseLastDown(c.out, c.serial); err == nil || !errors.Is(err, ErrNoDownRecord) {
			t.Errorf("%s: want ErrNoDownRecord, got %v %v", name, got, err)
		}
	}
}

func TestR015AllowlistRegisterInfoOnlyWithTheOptIn(t *testing.T) {
	off, on := HuaweiR015{}, HuaweiR015{DownTimes: true}
	for cmd, want := range map[string]bool{
		"display ont register-info 14 0": true, "display ont register-info 15 127": true, "display ont register-info 16 0": false,
		"display ont register-info 14 128": false, "display ont register-info 14 007": false, "display ont register-info 14": false,
		"display ont register-info 14 0 1": false, "display ont register-info 14 0; reload": false, "display ont register-info 14 all": false,
	} {
		if got := on.Allowed(cmd); got != want {
			t.Errorf("DownTimes on: Allowed(%q)=%v want %v", cmd, got, want)
		}
		if off.Allowed(cmd) {
			t.Errorf("DownTimes off: %q must not be allowed", cmd)
		}
	}
}

// regSession serves the R015 fixtures and a register-info answer per ONT-ID.
type regSession struct {
	t     *testing.T
	sent  []string
	reg   map[string]string // command -> answer
	fail  string            // command that returns a session error
	reply string            // answer for every register-info command when reg has none
}

func (r *regSession) Run(_ context.Context, cmd string) (string, error) {
	r.sent = append(r.sent, cmd)
	switch {
	case cmd == "display version":
		return r015Text(r.t, "display_version.txt"), nil
	case cmd == "display ont info 14 all":
		return r015Text(r.t, "ont_info_14_all_paged.txt"), nil
	case cmd == "display ont optical-info 14 all":
		return r015Text(r.t, "ont_optical_info_14_all.txt"), nil
	case cmd == r.fail:
		return "", errors.New("session broke")
	case strings.HasPrefix(cmd, "display ont register-info"):
		if a, ok := r.reg[cmd]; ok {
			return a, nil
		}
		return r.reply, nil
	}
	return "", nil
}

func offlineOf(t *testing.T) []ONU {
	t.Helper()
	snap, err := HuaweiR015{}.Snapshot(context.Background(), &regSession{t: t}, []string{"0/0/14"})
	if err != nil {
		t.Fatal(err)
	}
	var off []ONU
	for _, u := range snap.ONUs {
		if u.Status == "offline" {
			off = append(off, u)
		}
	}
	if len(off) < 3 {
		t.Fatalf("fixture has %d offline ONUs", len(off))
	}
	return off
}

func registerFor(t *testing.T, serial, down string) string {
	t.Helper()
	return "display ont register-info\n ------\n  Index               : 1\n  SN                  : " + serial + " (HWTC-00000000)\n" +
		"  UpTime              : 2026-01-01 00:00:00-04:00\n  DownTime            : " + down + "\n  DownCause           : ONT dying-gasp\n ------\n Total :  1\n"
}

func TestSnapshotWithDownTimesReadsOnlyThePickedOfflineONUsInTheSameSession(t *testing.T) {
	off := offlineOf(t)
	r := &regSession{t: t, reg: map[string]string{}}
	pick := off[:2]
	for _, u := range pick {
		r.reg["display ont register-info 14 "+itoa(u.OntID)] = registerFor(t, u.Serial, "2026-03-01 10:00:00-03:00")
	}
	done := map[string]*time.Time{}
	var listing []ONU
	snap, err := HuaweiR015{DownTimes: true}.SnapshotWithDownTimes(context.Background(), r, []string{"0/0/14"}, DownReads{
		Pick: func(l []ONU) []ONU {
			listing = l
			return append([]ONU{{Serial: "X", PonPath: "0/0/14", Status: "online", OntID: 1, HasOntID: true}}, pick...)
		},
		Done: func(s string, at *time.Time) { done[s] = at },
	})
	if err != nil || len(snap.ONUs) != 12 || len(listing) != 12 {
		t.Fatalf("snapshot: %v onus=%d listing=%d", err, len(snap.ONUs), len(listing))
	}
	for _, u := range pick {
		at := done[u.Serial]
		if at == nil || !at.Equal(time.Date(2026, 3, 1, 13, 0, 0, 0, time.UTC)) {
			t.Errorf("%s: %v", u.Serial, at)
		}
	}
	if len(done) != 2 {
		t.Errorf("an online ONU picked by mistake must be ignored, done=%v", done)
	}
	tail := r.sent[len(r.sent)-6:]
	want := []string{"quit", "interface gpon 0/0", "display ont register-info 14 " + itoa(pick[0].OntID), "display ont register-info 14 " + itoa(pick[1].OntID), "quit"}
	if !reflect.DeepEqual(tail[1:], want) {
		t.Fatalf("commands after the listing:\n got %v\nwant %v", tail[1:], want)
	}
	for _, c := range r.sent { // everything sent must be allowed by the driver itself
		if !(HuaweiR015{DownTimes: true}).Allowed(c) {
			t.Errorf("sent a command the driver does not allow: %q", c)
		}
	}
}

func TestSnapshotWithDownTimesIsBestEffortAndOffByDefault(t *testing.T) {
	off := offlineOf(t)
	reads := func(done map[string]*time.Time) DownReads {
		return DownReads{Pick: func([]ONU) []ONU { return off[:3] }, Done: func(s string, at *time.Time) { done[s] = at }}
	}
	// a session error in the middle ends the reads but keeps the listing; the failed ONU is not reported (it is asked again later)
	r := &regSession{t: t, reply: "x", fail: "display ont register-info 14 " + itoa(off[1].OntID)}
	done := map[string]*time.Time{}
	snap, err := HuaweiR015{DownTimes: true}.SnapshotWithDownTimes(context.Background(), r, []string{"0/0/14"}, reads(done))
	if err != nil || len(snap.ONUs) != 12 {
		t.Fatalf("listing must survive: %v %d", err, len(snap.ONUs))
	}
	if len(done) != 1 || done[off[0].Serial] != nil {
		t.Errorf("only the ONU read before the failure is reported, with no time (garbage answer): %v", done)
	}
	// a device rejection also ends the reads without reporting the ONU
	r = &regSession{t: t, reply: "% Unknown command, the error locates at '^'\n"}
	done = map[string]*time.Time{}
	if _, err := (HuaweiR015{DownTimes: true}).SnapshotWithDownTimes(context.Background(), r, []string{"0/0/14"}, reads(done)); err != nil || len(done) != 0 {
		t.Errorf("rejection: %v %v", err, done)
	}
	// DownTimes off: nothing but the listing is sent
	r = &regSession{t: t}
	done = map[string]*time.Time{}
	if _, err := (HuaweiR015{}).SnapshotWithDownTimes(context.Background(), r, []string{"0/0/14"}, reads(done)); err != nil || len(done) != 0 {
		t.Fatalf("off: %v %v", err, done)
	}
	for _, c := range r.sent {
		if strings.Contains(c, "register-info") {
			t.Fatalf("register-info sent with the option off: %q", c)
		}
	}
}

func itoa(n int) string { return strconv.Itoa(n) }
