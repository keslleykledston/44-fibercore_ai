package olt

import (
	"context"
	"errors"
	"os"
	"path/filepath"
	"strings"
	"testing"
)

// fixtureSession answers commands from testdata files and records everything that reaches the device.
type fixtureSession struct {
	dir   string
	files map[string]string
	sent  []string
}

func (f *fixtureSession) Run(_ context.Context, cmd string) (string, error) {
	f.sent = append(f.sent, cmd)
	name, ok := f.files[cmd]
	if !ok {
		return "", errors.New("fixture: no output for " + cmd)
	}
	b, err := os.ReadFile(filepath.Join("testdata", f.dir, name))
	return string(b), err
}

func huaweiFixture() *fixtureSession {
	return &fixtureSession{dir: "huawei_ma5800/R018", files: map[string]string{
		"display version":                    "display_version.txt",
		"display ont info summary 0/1/0":     "ont_info_summary_0_1_0.txt",
		"display ont optical-info 0/1/0 all": "ont_optical_0_1_0.txt",
	}}
}

func zteFixture() *fixtureSession {
	return &fixtureSession{dir: "zte_c300/V2.1", files: map[string]string{
		"show version":                          "show_version.txt",
		"show gpon onu state gpon-olt_1/2/1":    "onu_state_1_2_1.txt",
		"show gpon onu baseinfo gpon-olt_1/2/1": "onu_baseinfo_1_2_1.txt",
		"show pon power onu-rx gpon-olt_1/2/1":  "onu_rx_1_2_1.txt",
	}}
}

func f(v float64) *float64 { return &v }

func TestHuaweiSnapshotGolden(t *testing.T) {
	raw := huaweiFixture()
	s := ReadOnlySession{Inner: raw, Allowed: Huawei{}.Allowed}
	snap, err := Huawei{}.Snapshot(context.Background(), s, []string{"0/1/0"})
	if err != nil {
		t.Fatal(err)
	}
	if snap.Identity != (Identity{Vendor: "huawei", Model: "MA5800-X7", Firmware: "R018"}) {
		t.Fatalf("identity=%+v", snap.Identity)
	}
	if len(snap.PONs) != 1 || snap.PONs[0] != (PON{"0/1/0", "up"}) || len(snap.ONUs) != 3 {
		t.Fatalf("snap=%+v", snap)
	}
	want := []ONU{
		{"48575443A1B2C3D4", "0/1/0", "online", f(-21.5)},
		{"48575443A1B2C3D5", "0/1/0", "offline", nil},
		{"48575443A1B2C3D6", "0/1/0", "online", f(-27.8)}, // serial upper-cased
	}
	for i, w := range want {
		g := snap.ONUs[i]
		if g.Serial != w.Serial || g.PonPath != w.PonPath || g.Status != w.Status || (g.RxDBm == nil) != (w.RxDBm == nil) ||
			(w.RxDBm != nil && *g.RxDBm != *w.RxDBm) {
			t.Errorf("onu[%d]=%+v want %+v", i, g, w)
		}
	}
}

func TestZTESnapshotGolden(t *testing.T) {
	raw := zteFixture()
	s := ReadOnlySession{Inner: raw, Allowed: ZTE{}.Allowed}
	snap, err := ZTE{}.Snapshot(context.Background(), s, []string{"1/2/1"})
	if err != nil {
		t.Fatal(err)
	}
	if snap.Identity != (Identity{Vendor: "zte", Model: "C300", Firmware: "V2.1.0P3"}) {
		t.Fatalf("identity=%+v", snap.Identity)
	}
	// ONU :5 has state but no serial => skipped (identity never invented)
	if len(snap.ONUs) != 4 {
		t.Fatalf("onus=%+v", snap.ONUs)
	}
	gotStatus := map[string]string{}
	for _, o := range snap.ONUs {
		gotStatus[o.Serial] = o.Status
	}
	for serial, st := range map[string]string{"ZTEGC0000001": "online", "ZTEGC0000002": "los", "ZTEGC0000003": "dying_gasp", "ZTEGC0000004": "offline"} {
		if gotStatus[serial] != st {
			t.Errorf("%s: %s want %s", serial, gotStatus[serial], st)
		}
	}
	if snap.ONUs[0].RxDBm == nil || *snap.ONUs[0].RxDBm != -21.5 || snap.ONUs[1].RxDBm != nil {
		t.Errorf("rx mapping wrong: %+v", snap.ONUs[:2])
	}
}

func TestDriversOnlyIssueAllowlistedReadCommands(t *testing.T) {
	for name, tc := range map[string]struct {
		d   Driver
		raw *fixtureSession
		pon string
	}{"huawei": {Huawei{}, huaweiFixture(), "0/1/0"}, "zte": {ZTE{}, zteFixture(), "1/2/1"}} {
		if _, err := tc.d.Snapshot(context.Background(), ReadOnlySession{Inner: tc.raw, Allowed: tc.d.Allowed}, []string{tc.pon}); err != nil {
			t.Fatalf("%s: %v", name, err)
		}
		for _, c := range tc.raw.sent {
			if !tc.d.Allowed(c) || !SafeCommand(c) {
				t.Errorf("%s sent non-allowlisted command %q", name, c)
			}
			for _, bad := range []string{"config", "undo", "reboot", "reset", "shutdown", "delete", "add", "set", "save", "commit"} {
				if strings.Contains(strings.ToLower(c), bad) {
					t.Errorf("%s sent write-looking command %q", name, c)
				}
			}
		}
	}
}

func TestReadOnlySessionBlocksEverythingElse(t *testing.T) {
	raw := &fixtureSession{dir: "x", files: map[string]string{}}
	for _, d := range []Driver{Huawei{}, ZTE{}} {
		s := ReadOnlySession{Inner: raw, Allowed: d.Allowed}
		for _, cmd := range []string{
			"reboot", "config", "undo ont", "display version; reboot", "display version | include x", "display version\nreboot",
			"display version && reboot", "display ont info summary 0/1/0 ; shutdown", "display ont info summary 0/1/0 extra",
			"show version `id`", "show version $(id)", " display version", "display version ", "", strings.Repeat("a", 200),
			"display ont info summary 0/1/x", "show gpon onu state gpon-olt_1/2/1 > /tmp/x",
		} {
			if _, err := s.Run(context.Background(), cmd); !errors.Is(err, ErrCommandDenied) {
				t.Errorf("%T: %q must be denied, got %v", d, cmd, err)
			}
		}
	}
	if len(raw.sent) != 0 {
		t.Fatalf("denied commands reached the device: %v", raw.sent)
	}
}

func TestInvalidPonPortRejectedBeforeAnyCommandBuilt(t *testing.T) {
	raw := huaweiFixture()
	s := ReadOnlySession{Inner: raw, Allowed: Huawei{}.Allowed}
	if _, err := (Huawei{}).Snapshot(context.Background(), s, []string{"0/1/0; reboot"}); err == nil {
		t.Fatal("expected error")
	}
	for _, c := range raw.sent {
		if strings.Contains(c, "reboot") {
			t.Fatalf("injected command reached device: %q", c)
		}
	}
}

func TestFirmwareGate(t *testing.T) {
	lvl, err := Lookup(Identity{Vendor: "huawei", Model: "MA5800-X7", Firmware: "R018"})
	if err != nil || lvl != LevelIdentified { // synthetic fixtures => never "observed"
		t.Fatalf("lvl=%s err=%v", lvl, err)
	}
	if _, err := Lookup(Identity{Vendor: "huawei", Model: "MA5800-X7", Firmware: "R019"}); !errors.Is(err, ErrUnsupportedFirmware) {
		t.Fatalf("unknown firmware must be refused: %v", err)
	}
	if _, err := Lookup(Identity{Vendor: "zte", Model: "C600", Firmware: "V2.1.0"}); !errors.Is(err, ErrUnsupportedFirmware) {
		t.Fatalf("unknown model must be refused: %v", err)
	}
	for _, h := range Registry {
		if h.Level == LevelObserved && strings.Contains(h.Evidence, "synthetic") {
			t.Fatalf("synthetic evidence cannot justify observed: %+v", h)
		}
	}
}

func TestBudgetStopsRunawayCollection(t *testing.T) {
	raw := huaweiFixture()
	b := NewBudget(ReadOnlySession{Inner: raw, Allowed: Huawei{}.Allowed}, 2, 1<<20)
	if _, err := (Huawei{}).Snapshot(context.Background(), b, []string{"0/1/0"}); !errors.Is(err, ErrBudget) {
		t.Fatalf("command budget not enforced: %v", err)
	}
	b = NewBudget(ReadOnlySession{Inner: huaweiFixture(), Allowed: Huawei{}.Allowed}, 100, 50)
	if _, err := (Huawei{}).Snapshot(context.Background(), b, []string{"0/1/0"}); !errors.Is(err, ErrBudget) {
		t.Fatalf("byte budget not enforced: %v", err)
	}
}
