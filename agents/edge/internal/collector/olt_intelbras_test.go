package collector

import (
	"context"
	"encoding/json"
	"errors"
	"os"
	"path/filepath"
	"testing"

	"github.com/keslleykledston/44-fibercore_ai/agents/edge/internal/olt"
	"github.com/keslleykledston/44-fibercore_ai/agents/edge/internal/oltquery"
)

// ibFileSession serves the sanitized Intelbras 8820 fixtures and, like the Telnet session, carries the login banner.
type ibFileSession struct{ sent []string }

func (f *ibFileSession) Banner() string { return "Intelbras Embedded Platform 16.2 olt8820plus\n" }

func (f *ibFileSession) Run(_ context.Context, cmd string) (string, error) {
	f.sent = append(f.sent, cmd)
	m := map[string]string{"card stats": "card_stats.txt", "olt show port": "olt_show_port.txt", "onu status": "onu_status.txt"}
	n, ok := m[cmd]
	if !ok {
		return "", errors.New("unexpected " + cmd)
	}
	b, err := os.ReadFile(filepath.Join("..", "olt", "testdata", "intelbras_8820", n))
	return string(b), err
}

func TestOLTIntelbrasSnapshotIsIdentifiedNeverComplete(t *testing.T) {
	raw := &ibFileSession{}
	c := &OLT{EdgeID: "e1", Sources: []OLTSource{{
		Name: "OLT-IB", Driver: olt.Intelbras{},
		Open: func(context.Context) (olt.Session, func(), error) { return raw, func() {}, nil },
	}}}
	items, err := c.Collect(context.Background())
	if err != nil || len(items) != 1 {
		t.Fatalf("items=%d err=%v", len(items), err)
	}
	var snap struct {
		Vendor, Model, Firmware string
		DriverLevel             string `json:"driver_level"`
		PONs                    []struct {
			Path     string `json:"pon_path"`
			Status   string
			Complete bool
		} `json:"pons"`
		ONUs []struct {
			Serial string
			Pon    string `json:"pon_path"`
			Status string
			Rx     *float64 `json:"rx_dbm"`
		} `json:"onus"`
	}
	if err := json.Unmarshal(items[0].Payload, &snap); err != nil {
		t.Fatal(err)
	}
	if snap.Vendor != "intelbras" || snap.Model != "OLT8820PLUS" || snap.Firmware != "2.112" || snap.DriverLevel != "identified" {
		t.Fatalf("head = %+v", snap)
	}
	if len(snap.PONs) != 3 || len(snap.ONUs) != 16 {
		t.Fatalf("pons=%d onus=%d", len(snap.PONs), len(snap.ONUs))
	}
	for _, p := range snap.PONs {
		if p.Complete || (p.Status != "up" && p.Status != "down" && p.Status != "unknown") {
			t.Errorf("PON %+v: identified level must never be complete; status in up|down|unknown", p)
		}
	}
	for _, u := range snap.ONUs {
		if len(u.Serial) < 1 || len(u.Serial) > 128 || u.Pon == "" || (u.Rx != nil && (*u.Rx < -50 || *u.Rx > 10)) {
			t.Errorf("ONU %+v breaks the ingest contract", u)
		}
	}
	for _, cmd := range raw.sent {
		if !olt.IntelbrasAllowed(cmd) {
			t.Errorf("collector sent %q", cmd)
		}
	}
}

func TestCommandBudgetCoversDiscoveredPONs(t *testing.T) {
	if got := commandBudget(0); got < 128 {
		t.Fatalf("budget with discovered PONs = %d, must cover a full chassis", got)
	}
	if commandBudget(2) != 16 {
		t.Fatalf("listed ports keep the tight budget: %d", commandBudget(2))
	}
}

// ADR-0053: a driver without the query catalog answers ONLY the connection test, with its own identity read, in the collection's session.
func TestConnectionTestOnADriverWithoutTheCatalogReturnsTheIdentityOnly(t *testing.T) {
	raw := &ibFileSession{}
	store := &oltquery.Store{Path: filepath.Join(t.TempDir(), "q.json")}
	src := OLTSource{Name: "OLT-IB", Driver: olt.Intelbras{}, CloudID: qCloud,
		Open: func(context.Context) (olt.Session, func(), error) { return raw, func() {}, nil }}
	c := &OLT{EdgeID: "e1", Sources: []OLTSource{src}, Queries: &Queries{Store: store, Lease: fakeLease{qCloud: 1}}}
	enqueue(t, store, "job-conn", oltquery.TestQueryID)
	enqueue(t, store, "job-board", "olt.board")
	if items, err := c.Collect(context.Background()); err != nil || len(items) != 1 {
		t.Fatalf("the collection must be unaffected: %d %v", len(items), err)
	}
	e, ok, _ := store.Get("job-conn")
	if !ok || e.State != oltquery.Executed {
		t.Fatalf("connection test: %+v", e)
	}
	var got map[string]any
	if err := json.Unmarshal(e.Result, &got); err != nil || got["product"] != "OLT8820PLUS" || got["version"] != "2.112" || got["patch"] != nil || got["uptime_seconds"] != nil || len(got) != 4 {
		t.Fatalf("typed result = %v (%v)", got, err)
	}
	// another query is refused alone and nothing extra is sent to the device
	if b, ok, _ := store.Get("job-board"); !ok || b.State == oltquery.Executed {
		t.Fatalf("an olt.board query must not run on this driver: %+v", b)
	}
	for _, cmd := range raw.sent {
		if !olt.IntelbrasAllowed(cmd) {
			t.Fatalf("non allowlisted command %q", cmd)
		}
	}
}

func TestConnectionIdentityRefusesWhatTheCloudWouldNotAccept(t *testing.T) {
	if _, err := ConnectionIdentity(olt.Identity{Model: "DM4610 HW2", Firmware: "5.8.0-065-r1"}); err != nil {
		t.Fatalf("a model with a space is real (DM4610 HW2): %v", err)
	}
	for _, id := range []olt.Identity{{Model: "", Firmware: "2.112"}, {Model: "OLT8820", Firmware: ""}, {Model: "OLT;8820", Firmware: "2.112"}, {Model: "OLT8820", Firmware: "2.1\n12"}} {
		if _, err := ConnectionIdentity(id); err == nil {
			t.Fatalf("%+v must be refused", id)
		}
	}
}

// A profile whose snapshot ends the session (MA5800 sends `quit`) must still answer the connection test: it uses the identity the snapshot already read, with no new command.
func TestConnectionTestUsesTheIdentityTheSnapshotAlreadyRead(t *testing.T) {
	raw := &ibFileSession{}
	store := &oltquery.Store{Path: filepath.Join(t.TempDir(), "q.json")}
	src := OLTSource{Name: "OLT-IB", Driver: olt.Intelbras{}, CloudID: qCloud,
		Open: func(context.Context) (olt.Session, func(), error) { return raw, func() {}, nil }}
	c := &OLT{EdgeID: "e1", Sources: []OLTSource{src}, Queries: &Queries{Store: store, Lease: fakeLease{qCloud: 1}}}
	enqueue(t, store, "job-conn", oltquery.TestQueryID)
	if _, err := c.Collect(context.Background()); err != nil {
		t.Fatal(err)
	}
	cards := 0
	for _, cmd := range raw.sent {
		if cmd == "card stats" {
			cards++
		}
	}
	if e, ok, _ := store.Get("job-conn"); !ok || e.State != oltquery.Executed {
		t.Fatalf("%+v", e)
	}
	base := &ibFileSession{} // the same collection with no query waiting: the query must have added no command at all
	plain := &OLT{EdgeID: "e1", Sources: []OLTSource{{Name: "OLT-IB", Driver: olt.Intelbras{}, Open: func(context.Context) (olt.Session, func(), error) { return base, func() {}, nil }}}}
	if _, err := plain.Collect(context.Background()); err != nil {
		t.Fatal(err)
	}
	if cards != func() int {
		n := 0
		for _, cmd := range base.sent {
			if cmd == "card stats" {
				n++
			}
		}
		return n
	}() || len(raw.sent) != len(base.sent) {
		t.Fatalf("the connection test sent extra commands: %v vs %v", raw.sent, base.sent)
	}
}

// MA5800 session: serves the real (sanitized) `display version` and the real empty autofind answer, and records every command.
type ma58QuerySession struct{ sent []string }

func (f *ma58QuerySession) Run(_ context.Context, cmd string) (string, error) {
	f.sent = append(f.sent, cmd)
	dir := filepath.Join("..", "olt", "testdata", "huawei_ma5800_r02x")
	n := map[string]string{"display version": "display_version_user_r024c11.txt", "enable": "enable_ok.txt", "display ont autofind all": "display_ont_autofind_all_empty.txt"}[cmd]
	if n == "" {
		return "", errors.New("unexpected " + cmd)
	}
	b, err := os.ReadFile(filepath.Join(dir, n))
	return string(b), err
}

// The MA5800 answers `olt.autofind` (the ONTs waiting for authorisation) over the session the collection holds, and nothing else of the catalog.
func TestMA58AutofindQueryRunsInTheCollectionSession(t *testing.T) {
	raw := &ma58QuerySession{}
	store := &oltquery.Store{Path: filepath.Join(t.TempDir(), "q.json")}
	src := OLTSource{Name: "OLT-MA58", Driver: olt.HuaweiMA58{}, CloudID: qCloud,
		Open: func(context.Context) (olt.Session, func(), error) { return raw, func() {}, nil }}
	c := &OLT{EdgeID: "e1", Sources: []OLTSource{src}, Queries: &Queries{Store: store, Lease: fakeLease{qCloud: 1}}}
	enqueue(t, store, "job-af", "olt.autofind")
	enqueue(t, store, "job-board", "olt.board")
	if _, err := c.Collect(context.Background()); err != nil {
		t.Fatal(err)
	}
	e, ok, _ := store.Get("job-af")
	if !ok || e.State != oltquery.Executed || len(e.Result) == 0 {
		t.Fatalf("autofind: %+v", e)
	}
	if b, ok, _ := store.Get("job-board"); !ok || b.State == oltquery.Executed {
		t.Fatalf("olt.board must not run on the MA5800: %+v", b)
	}
	for _, cmd := range raw.sent {
		if cmd != "display version" && cmd != "display ont autofind all" && cmd != "enable" {
			t.Fatalf("unexpected command %q", cmd)
		}
	}
}
