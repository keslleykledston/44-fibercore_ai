package collector

import (
	"context"
	"os"
	"path/filepath"
	"strings"
	"testing"
	"time"

	"github.com/keslleykledston/44-fibercore_ai/agents/edge/internal/olt"
	"github.com/keslleykledston/44-fibercore_ai/agents/edge/internal/oltquery"
)

type capEvent struct {
	id      string
	bytes   int
	outcome string
}

func captureRig(t *testing.T, sess *qSession, ids ...string) (*OLT, *Capture, *[]capEvent) {
	t.Helper()
	enabled := map[string]bool{}
	var items []CaptureItem
	for _, id := range ids {
		enabled[id] = true
		items = append(items, CaptureItem{QueryID: id})
	}
	drv := olt.HuaweiR015{Queries: olt.QueryPolicy{Enabled: enabled}}
	store := &oltquery.Store{Path: filepath.Join(t.TempDir(), "q.json")}
	events := &[]capEvent{}
	cp := &Capture{Dir: filepath.Join(t.TempDir(), "captures"), Items: map[string][]CaptureItem{qCloud: items}, Store: store, Lease: fakeLease{qCloud: 1},
		Run: drv.RunQueryInConfig, OnCapture: func(id string, n int, _ time.Duration, outcome string) {
			*events = append(*events, capEvent{id, n, outcome})
		}}
	src := OLTSource{Name: "OLT-R015", Driver: drv, Ports: []string{"0/0/14"}, CloudID: qCloud, AllowUnverified: true,
		Open: func(context.Context) (olt.Session, func(), error) { return sess, func() {}, nil }}
	return &OLT{EdgeID: "e", Sources: []OLTSource{src}, Queries: &Queries{Store: store, Run: drv.RunQueryInConfig, Lease: fakeLease{qCloud: 1}}, Capture: cp}, cp, events
}

const rawTime = "display time\n  2026-10-30 21:15:41-04:00\n  serial HWTC00000099 customer-name Maria\nOLT-TEST-1(config)#"

func TestACaptureWritesTheRawOutputOnlyToAPrivateFileAndRunsOnce(t *testing.T) {
	sess := &qSession{inner: r015Session{}, extra: map[string]string{"display time": rawTime}}
	o, cp, events := captureRig(t, sess, "olt.time")
	if items, err := o.Collect(context.Background()); err != nil || len(items) != 1 {
		t.Fatalf("the collection must be unaffected: %d %v", len(items), err)
	}
	fi, _ := os.Stat(cp.Dir)
	if fi.Mode().Perm() != 0o700 {
		t.Fatalf("dir mode %v", fi.Mode().Perm())
	}
	ents, _ := os.ReadDir(cp.Dir)
	var raw string
	for _, e := range ents {
		if strings.HasSuffix(e.Name(), ".txt") {
			info, _ := e.Info()
			if info.Mode().Perm() != 0o600 {
				t.Fatalf("file mode %v", info.Mode().Perm())
			}
			b, _ := os.ReadFile(filepath.Join(cp.Dir, e.Name()))
			raw = string(b)
		}
	}
	if !strings.Contains(raw, "customer-name Maria") {
		t.Fatalf("the raw output must be kept as it came: %q", raw)
	}
	if len(*events) != 1 || (*events)[0].outcome != "ok" || (*events)[0].bytes != len(raw) {
		t.Fatalf("events %v", *events)
	}
	if n, _ := cp.Store.PendingReports(); len(n) != 0 { // nothing about it goes to the Cloud queue
		t.Fatalf("pending reports %v", n)
	}
	sess.sent = nil
	if _, err := o.Collect(context.Background()); err != nil {
		t.Fatal(err)
	}
	if strings.Contains(strings.Join(sess.sent, "|"), "display time") {
		t.Fatalf("a capture runs ONCE, even after a restart of the loop: %v", sess.sent)
	}
	restarted := &Capture{Dir: cp.Dir, Items: cp.Items, Store: cp.Store, Lease: cp.Lease, Run: cp.Run}
	if n := restarted.Do(context.Background(), o.Sources[0], sess, qCloud, "s2"); n != 0 {
		t.Fatalf("done marker is on disk: %d", n)
	}
}

func TestOnlyTheListedUnvalidatedQueriesReachTheDevice(t *testing.T) {
	sess := &qSession{inner: r015Session{}, extra: map[string]string{"display time": rawTime, "display temperature 0": "temp"}}
	o, _, _ := captureRig(t, sess, "olt.time") // temperature is in the catalog, NOT listed
	if _, err := o.Collect(context.Background()); err != nil {
		t.Fatal(err)
	}
	if strings.Contains(strings.Join(sess.sent, "|"), "display temperature") {
		t.Fatalf("%v", sess.sent)
	}
	// and the session allowlist refuses it even if something asked
	if _, err := (olt.HuaweiR015{Queries: olt.QueryPolicy{Enabled: map[string]bool{"olt.time": true}}}).RunQueryInConfig(context.Background(), sess, "olt.temperature", olt.Params{}); err == nil {
		t.Fatal("an unlisted unvalidated query must be refused")
	}
}

func TestACaptureBudgetIsTwoPerSessionAndTheRestWaits(t *testing.T) {
	sess := &qSession{inner: r015Session{}, extra: map[string]string{"display time": rawTime, "display data sync state": "sync ok", "display temperature 0": "temp 30", "display ont autofind all": "none"}}
	o, cp, _ := captureRig(t, sess, "olt.time", "olt.sync", "olt.temperature", "olt.autofind")
	if _, err := o.Collect(context.Background()); err != nil {
		t.Fatal(err)
	}
	ents, _ := os.ReadDir(cp.Dir)
	n := 0
	for _, e := range ents {
		if strings.HasSuffix(e.Name(), ".txt") {
			n++
		}
	}
	if n != oltquery.CapturesPerSession {
		t.Fatalf("a session captures %d, captured %d", oltquery.CapturesPerSession, n)
	}
	if _, err := o.Collect(context.Background()); err != nil { // next session: the next two
		t.Fatal(err)
	}
	ents, _ = os.ReadDir(cp.Dir)
	n = 0
	for _, e := range ents {
		if strings.HasSuffix(e.Name(), ".txt") {
			n++
		}
	}
	if n != 4 {
		t.Fatalf("after the second session: %d files", n)
	}
}

func TestADeviceRefusalEndsTheCaptureBatchAndIsNotRepeated(t *testing.T) {
	sess := &qSession{inner: r015Session{}, extra: map[string]string{"display time": "  Failure: Unknown command\n", "display data sync state": "sync ok"}}
	o, cp, events := captureRig(t, sess, "olt.time", "olt.sync")
	if _, err := o.Collect(context.Background()); err != nil {
		t.Fatal(err)
	}
	if len(*events) != 1 || (*events)[0].outcome != "device_rejected" {
		t.Fatalf("%v", *events)
	}
	if strings.Contains(strings.Join(sess.sent, "|"), "display data sync state") {
		t.Fatalf("the batch ends at the first anomaly: %v", sess.sent)
	}
	files, _ := filepath.Glob(filepath.Join(cp.Dir, "*.txt"))
	if len(files) != 0 {
		t.Fatalf("a refused capture leaves no file: %v", files)
	}
	sess.sent = nil
	if _, err := o.Collect(context.Background()); err != nil {
		t.Fatal(err)
	}
	if strings.Contains(strings.Join(sess.sent, "|"), "display time") {
		t.Fatalf("an attempted capture is not repeated: %v", sess.sent)
	}
}

func TestTheSweepDeletesOldCapturesAndRefusesWhenFull(t *testing.T) {
	sess := &qSession{inner: r015Session{}, extra: map[string]string{"display time": rawTime}}
	o, cp, _ := captureRig(t, sess, "olt.time")
	if err := os.MkdirAll(cp.Dir, 0o700); err != nil {
		t.Fatal(err)
	}
	old := filepath.Join(cp.Dir, "20250101T000000Z-olt_alarm_active.txt")
	tmp := filepath.Join(cp.Dir, ".tmp-leftover")
	for _, f := range []string{old, tmp} {
		if err := os.WriteFile(f, []byte("customer data"), 0o600); err != nil {
			t.Fatal(err)
		}
	}
	past := time.Now().Add(-25 * time.Hour)
	_ = os.Chtimes(old, past, past)
	if _, err := o.Collect(context.Background()); err != nil {
		t.Fatal(err)
	}
	for _, f := range []string{old, tmp} {
		if _, err := os.Stat(f); !os.IsNotExist(err) {
			t.Fatalf("%s must be gone", f)
		}
	}
	// a full directory (10 files) makes the capture wait: the person has to collect and delete first
	sess2 := &qSession{inner: r015Session{}, extra: map[string]string{"display time": rawTime}}
	o2, cp2, _ := captureRig(t, sess2, "olt.time")
	_ = os.MkdirAll(cp2.Dir, 0o700)
	for i := 0; i < captureMaxFiles; i++ {
		_ = os.WriteFile(filepath.Join(cp2.Dir, "f"+string(rune('a'+i))+".txt"), []byte("x"), 0o600)
	}
	if _, err := o2.Collect(context.Background()); err != nil {
		t.Fatal(err)
	}
	if strings.Contains(strings.Join(sess2.sent, "|"), "display time") {
		t.Fatalf("a full captures/ runs nothing: %v", sess2.sent)
	}
}

func TestNoCaptureWithoutALeaseOrOnAnUnreadableQueue(t *testing.T) {
	sess := &qSession{inner: r015Session{}, extra: map[string]string{"display time": rawTime}}
	o, cp, _ := captureRig(t, sess, "olt.time")
	cp.Lease = fakeLease{}
	if _, err := o.Collect(context.Background()); err != nil {
		t.Fatal(err)
	}
	if strings.Contains(strings.Join(sess.sent, "|"), "display time") {
		t.Fatalf("no lease, no capture: %v", sess.sent)
	}
	cp.Lease = fakeLease{qCloud: 1}
	if err := os.WriteFile(cp.Store.Path, []byte("{"), 0o600); err != nil {
		t.Fatal(err)
	}
	if _, err := o.Collect(context.Background()); err != nil {
		t.Fatal(err)
	}
	if strings.Contains(strings.Join(sess.sent, "|"), "display time") {
		t.Fatalf("an unreadable budget file means the budget is spent: %v", sess.sent)
	}
}
