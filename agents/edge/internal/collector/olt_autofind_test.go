package collector

import (
	"context"
	"encoding/json"
	"errors"
	"reflect"
	"testing"
	"time"

	"github.com/keslleykledston/44-fibercore_ai/agents/edge/internal/olt"
)

func afSource(raw olt.Session) OLTSource {
	return OLTSource{Name: "OLT-MA58", Driver: olt.HuaweiMA58{}, SNMPKey: "dev-ma58", Interval: 15 * time.Minute,
		Open: func(context.Context) (olt.Session, func(), error) { return raw, func() {}, nil }}
}

func afCollector(src OLTSource, now *time.Time) (*Autofind, *OLT) {
	oc := &OLT{EdgeID: "e1", Sources: []OLTSource{src}, Now: func() time.Time { return *now }}
	return &Autofind{EdgeID: "e1", OLT: oc, Sources: []AutofindSource{{Src: src, Every: 10 * time.Minute}}}, oc
}

// One short session, three read commands, one typed item for the Cloud; the empty list (the real answer of both MA5800 on 2026-11-14) is a valid, queued answer.
func TestAutofindReadsTheListInAShortPacedSession(t *testing.T) {
	raw := &ma58QuerySession{}
	now := time.Date(2026, 11, 14, 12, 0, 0, 0, time.UTC)
	a, _ := afCollector(afSource(raw), &now)
	items, err := a.Collect(context.Background())
	if err != nil || len(items) != 1 {
		t.Fatalf("items=%d err=%v", len(items), err)
	}
	it := items[0]
	if it.Kind != "olt_autofind" || it.Key != "olt-autofind:OLT-MA58" || !it.Gauge {
		t.Fatalf("item %+v", it)
	}
	var got struct {
		EdgeID, ObservedAt, Name string
		Entries                  []json.RawMessage
	}
	var m map[string]json.RawMessage
	if err := json.Unmarshal(it.Payload, &m); err != nil {
		t.Fatal(err)
	}
	if string(m["entries"]) != "[]" || string(m["name"]) != `"OLT-MA58"` || string(m["edge_id"]) != `"e1"` || string(m["observed_at"]) != `"2026-11-14T12:00:00Z"` || len(m) != 4 {
		t.Fatalf("payload %s (%v)", it.Payload, got)
	}
	if want := []string{"display version", "enable", "display ont autofind all"}; !reflect.DeepEqual(raw.sent, want) {
		t.Fatalf("commands %v, want %v", raw.sent, want)
	}
}

// Its pacing is its own: a read 10 minutes later runs, one 5 minutes later does not, and none of it moves the collection's window.
func TestAutofindPacingIsItsOwnAndLeavesTheCollectionWindowAlone(t *testing.T) {
	raw := &ma58QuerySession{}
	now := time.Date(2026, 11, 14, 12, 0, 0, 0, time.UTC)
	a, oc := afCollector(afSource(raw), &now)
	if items, _ := a.Collect(context.Background()); len(items) != 1 {
		t.Fatal("the first read must run")
	}
	n := len(raw.sent)
	now = now.Add(5 * time.Minute)
	if items, err := a.Collect(context.Background()); err != nil || len(items) != 0 || len(raw.sent) != n {
		t.Fatalf("5 min later nothing may run: items=%d err=%v sent=%d", len(items), err, len(raw.sent))
	}
	now = now.Add(5*time.Minute + time.Second) // 10 min + 1 s since the first read
	if items, err := a.Collect(context.Background()); err != nil || len(items) != 1 {
		t.Fatalf("10 min later it must run: items=%d err=%v", len(items), err)
	}
	if _, touched := oc.st["dev-ma58"]; touched {
		t.Fatalf("the collection's pacing key was touched: %+v", oc.st["dev-ma58"])
	}
	if _, own := oc.st["dev-ma58#autofind"]; !own {
		t.Fatal("it must keep its own pacing key")
	}
}

// While the collection of the same OLT is cooling down after a failure, the autofind read stays away too (no second door for a refused login).
func TestAutofindStaysAwayWhileTheCollectionIsCooling(t *testing.T) {
	raw := &ma58QuerySession{}
	now := time.Date(2026, 11, 14, 12, 0, 0, 0, time.UTC)
	a, oc := afCollector(afSource(raw), &now)
	oc.mu.Lock()
	oc.st = map[string]GuardState{"dev-ma58": {Last: now.Add(-time.Minute), CoolUntil: now.Add(10 * time.Minute)}}
	oc.loaded = true
	oc.mu.Unlock()
	if items, err := a.Collect(context.Background()); err != nil || len(items) != 0 || len(raw.sent) != 0 {
		t.Fatalf("items=%d err=%v sent=%v", len(items), err, raw.sent)
	}
}

// A failed read queues nothing, keeps its own cooldown (the collection's key stays free) and reports the error.
func TestAutofindFailureQueuesNothingAndCoolsOnlyItself(t *testing.T) {
	now := time.Date(2026, 11, 14, 12, 0, 0, 0, time.UTC)
	src := afSource(nil)
	src.Open = func(context.Context) (olt.Session, func(), error) { return nil, nil, errors.New("connection refused") }
	a, oc := afCollector(src, &now)
	items, err := a.Collect(context.Background())
	if err == nil || len(items) != 0 {
		t.Fatalf("items=%d err=%v", len(items), err)
	}
	if !oc.st["dev-ma58#autofind"].CoolUntil.After(now) {
		t.Fatal("the failed read must cool down")
	}
	if oc.st["dev-ma58"].CoolUntil.After(now) {
		t.Fatal("the collection must not be cooled by a failed autofind")
	}
}

// A driver that cannot read the list is simply left out, and an unknown layout is a bad output (nothing queued).
func TestAutofindSkipsDriversWithoutAReaderAndRefusesAnUnknownLayout(t *testing.T) {
	now := time.Date(2026, 11, 14, 12, 0, 0, 0, time.UTC)
	ib := &ibFileSession{}
	src := OLTSource{Name: "OLT-IB", Driver: olt.Intelbras{}, Open: func(context.Context) (olt.Session, func(), error) { return ib, func() {}, nil }}
	a, _ := afCollector(src, &now)
	if items, err := a.Collect(context.Background()); err != nil || len(items) != 0 || len(ib.sent) != 0 {
		t.Fatalf("items=%d err=%v sent=%v", len(items), err, ib.sent)
	}
	weird := &weirdAutofind{}
	a2, _ := afCollector(afSource(weird), &now)
	if items, err := a2.Collect(context.Background()); err == nil || len(items) != 0 {
		t.Fatalf("an unknown layout must fail closed: items=%d err=%v", len(items), err)
	}
}

type weirdAutofind struct{ ma58QuerySession }

func (w *weirdAutofind) Run(ctx context.Context, cmd string) (string, error) {
	if cmd == "display ont autofind all" {
		w.sent = append(w.sent, cmd)
		return "  Some layout nobody has seen\n", nil
	}
	return w.ma58QuerySession.Run(ctx, cmd)
}
