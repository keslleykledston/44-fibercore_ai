package collector

import (
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"reflect"
	"sync"
	"testing"
	"time"

	"github.com/keslleykledston/44-fibercore_ai/agents/edge/internal/olt"
)

// ldCLI is a CLI driver whose ONU list the test changes between cycles.
type ldCLI struct{ onus *[]olt.ONU }

func (ldCLI) Vendor() string      { return "huawei" }
func (ldCLI) Allowed(string) bool { return true }
func (ldCLI) Identify(context.Context, olt.Session) (olt.Identity, error) {
	return olt.Identity{Vendor: "huawei", Model: "MA5608T", Firmware: "MA5600V800R015C00"}, nil
}
func (d ldCLI) Snapshot(context.Context, olt.Session, []string) (olt.Snapshot, error) {
	return olt.Snapshot{PONs: []olt.PON{{Path: "0/0/1", Status: "up"}, {Path: "0/0/2", Status: "up"}}, ONUs: append([]olt.ONU(nil), *d.onus...)}, nil
}

// ldSNMP records which PONs it was asked for and answers with the times of the ONUs it is told about.
type ldSNMP struct {
	calls *[][]string
	down  map[string]time.Time
	err   error
	hook  func() // runs while the read is "in flight" (before it answers)
}

func (ldSNMP) Vendor() string { return "huawei" }
func (ldSNMP) Identify(context.Context, olt.SNMPReader, []string) (olt.Identity, error) {
	return olt.Identity{}, nil
}
func (d ldSNMP) Snapshot(ctx context.Context, _ olt.SNMPReader, ports []string) (olt.Snapshot, error) {
	*d.calls = append(*d.calls, append([]string(nil), ports...))
	if d.hook != nil {
		d.hook()
	}
	if err := ctx.Err(); err != nil {
		return olt.Snapshot{}, err
	}
	if d.err != nil {
		return olt.Snapshot{}, d.err
	}
	var s olt.Snapshot
	for serial, t := range d.down {
		t := t
		s.ONUs = append(s.ONUs, olt.ONU{Serial: serial, PonPath: ports[0], Status: "offline", LastDownAt: &t})
	}
	// an ONU that is online for the OLT must not be given a time even if the driver mistakenly carried one
	online := time.Date(2020, 1, 1, 0, 0, 0, 0, time.UTC)
	s.ONUs = append(s.ONUs, olt.ONU{Serial: "ONLINE-1", PonPath: ports[0], Status: "online", LastDownAt: &online})
	return s, nil
}

// ldClock is a clock that tests move while background reads are running.
type ldClock struct {
	mu sync.Mutex
	t  time.Time
}

func (c *ldClock) now() time.Time { c.mu.Lock(); defer c.mu.Unlock(); return c.t }
func (c *ldClock) add(d time.Duration) {
	c.mu.Lock()
	c.t = c.t.Add(d)
	c.mu.Unlock()
}

type ldHarness struct {
	o      *OLT
	clock  *ldClock
	onus   *[]olt.ONU
	calls  *[][]string
	opens  *int
	driver *ldSNMP
}

func newLD(t *testing.T, snmpErr error) ldHarness {
	t.Helper()
	clock := &ldClock{t: time.Date(2026, 10, 30, 12, 0, 0, 0, time.UTC)}
	onus := []olt.ONU{
		{Serial: "HWTC00000001", PonPath: "0/0/1", Status: "offline"},
		{Serial: "HWTC00000002", PonPath: "0/0/2", Status: "online"},
	}
	var calls [][]string
	var opens int
	drv := &ldSNMP{calls: &calls, down: map[string]time.Time{"HWTC00000001": time.Date(2026, 10, 28, 8, 30, 0, 0, time.UTC)}, err: snmpErr}
	src := OLTSource{Name: "OLT-LD", Driver: ldCLI{&onus}, Ports: []string{"0/0/1", "0/0/2"}, AllowUnverified: true, Interval: 15 * time.Minute,
		SNMPKey: "10.0.0.9",
		Open: func(context.Context) (olt.Session, func(), error) {
			return countingSession{new(int), nil}, func() {}, nil
		},
		LastDown: &LastDownSource{Key: "last-down|10.0.0.9", Every: time.Hour, Driver: drv,
			Open: func(context.Context) (olt.SNMPReader, func(), error) { opens++; return nil, func() {}, nil }}}
	o := &OLT{EdgeID: "e", Sources: []OLTSource{src}, Now: clock.now}
	return ldHarness{o: o, clock: clock, onus: &onus, calls: &calls, opens: &opens, driver: drv}
}

// downOf returns serial -> last_down_at ("" when absent) from the payloads of one collection.
func (h ldHarness) collect(t *testing.T) map[string]string {
	t.Helper()
	items, err := h.o.Collect(context.Background())
	h.o.ldWG.Wait() // the side channel reads in the background
	if err != nil {
		t.Fatalf("a failing side channel must never fail the collection: %v", err)
	}
	out := map[string]string{}
	for _, it := range items {
		var p struct {
			ONUs []struct {
				Serial     string `json:"serial"`
				LastDownAt string `json:"last_down_at"`
			} `json:"onus"`
		}
		if err := json.Unmarshal(it.Payload, &p); err != nil {
			t.Fatal(err)
		}
		for _, u := range p.ONUs {
			out[u.Serial] = u.LastDownAt
		}
	}
	return out
}

func TestLastDownIsReadForPonsWithOfflineOnusAndTravelsWithTheNextSnapshot(t *testing.T) {
	h := newLD(t, nil)
	if got := h.collect(t); got["HWTC00000001"] != "" {
		t.Fatalf("the first snapshot cannot carry a time yet (the side channel runs AFTER the CLI read): %v", got)
	}
	// the same Collect call that saw the offline ONU then read its time: one call, only the PON that has an offline ONU
	if len(*h.calls) != 1 || !reflect.DeepEqual((*h.calls)[0], []string{"0/0/1"}) {
		t.Fatalf("SNMP must read only the PON that has an offline ONU: %v", *h.calls)
	}
	h.clock.add(16 * time.Minute)
	got := h.collect(t)
	if got["HWTC00000001"] != "2026-10-28T08:30:00Z" || got["HWTC00000002"] != "" {
		t.Fatalf("the next snapshot carries the OLT's time for the offline ONU only: %v", got)
	}
	if len(*h.calls) != 1 {
		t.Fatalf("one SNMP run per Every: %v", *h.calls)
	}
}

func TestLastDownIsForgottenWhenTheOnuComesBackAndNeverInheritedByANewDrop(t *testing.T) {
	h := newLD(t, nil)
	h.collect(t)
	h.clock.add(16 * time.Minute)
	h.collect(t) // carries the time
	(*h.onus)[0].Status = "online"
	h.clock.add(16 * time.Minute)
	if got := h.collect(t); got["HWTC00000001"] != "" {
		t.Fatalf("an online ONU has no down time: %v", got)
	}
	(*h.onus)[0].Status = "los"
	h.clock.add(16 * time.Minute)
	if got := h.collect(t); got["HWTC00000001"] != "" {
		t.Fatalf("a new drop must not inherit the previous time: %v", got)
	}
}

func TestLastDownFailureNeverFailsTheCollectionAndCoolsTheAgentDown(t *testing.T) {
	h := newLD(t, errors.New("snmp: timeout"))
	if got := h.collect(t); got["HWTC00000001"] != "" { // the CLI snapshot is delivered all the same
		t.Fatal("no time can be reported")
	}
	if got := h.collect(t); got == nil || len(*h.calls) != 1 { // same instant: cooling, nothing is sent
		t.Fatalf("a failed run must leave the agent alone: calls=%v", *h.calls)
	}
	h.clock.add(6 * time.Minute) // cooldown over, but a failed run still waits for the next Every: no retry storm on a sick agent
	h.collect(t)
	if len(*h.calls) != 1 {
		t.Fatalf("a failed run is retried at the next interval, not sooner: %v", *h.calls)
	}
	h.clock.add(time.Hour)
	h.collect(t)
	if len(*h.calls) != 2 {
		t.Fatalf("at the next interval the agent may be read again: %v", *h.calls)
	}
}

func TestLastDownIsNotTouchedWhenNothingIsOffline(t *testing.T) {
	h := newLD(t, nil)
	(*h.onus)[0].Status = "online"
	h.collect(t)
	h.clock.add(2 * time.Hour)
	h.collect(t)
	if *h.opens != 0 {
		t.Fatalf("no offline ONU, no SNMP traffic at all: opens=%d", *h.opens)
	}
}

func TestLastDownNeverBlocksTheRoundAndALateAnswerNeverRevivesAClearedTime(t *testing.T) {
	h := newLD(t, nil)
	release := make(chan struct{})
	h.driver.hook = func() { <-release }
	done := make(chan struct{})
	go func() { _, _ = h.o.Collect(context.Background()); close(done) }()
	select {
	case <-done: // the round did not wait for the paced SNMP read
	case <-time.After(5 * time.Second):
		t.Fatal("Collect must not wait for the last-down read")
	}
	// while the read is in flight a newer CLI snapshot sees the ONU online: the answer that arrives afterwards predates that
	(*h.onus)[0].Status = "online"
	h.clock.add(16 * time.Minute)
	if _, err := h.o.Collect(context.Background()); err != nil {
		t.Fatal(err)
	}
	close(release)
	h.o.ldWG.Wait()
	(*h.onus)[0].Status = "offline"
	h.clock.add(16 * time.Minute)
	h.driver.hook = nil
	h.driver.down = map[string]time.Time{} // the next run (not due yet) would not know it either
	if got := h.collect(t); got["HWTC00000001"] != "" {
		t.Fatalf("a late answer must not give the new drop the previous outage's time: %v", got)
	}
}

func TestLastDownContinuesWhereTheBudgetRanOutInsteadOfRereadingTheSamePons(t *testing.T) {
	var snapOnus []olt.ONU
	var ports []string
	for i := 0; i < 20; i++ {
		p := fmt.Sprintf("0/1/%02d", i)
		ports = append(ports, p)
		snapOnus = append(snapOnus, olt.ONU{Serial: fmt.Sprintf("HWTC%08d", i), PonPath: p, Status: "offline"})
	}
	var calls [][]string
	slow := true
	drv := &ldSNMP{calls: &calls, down: map[string]time.Time{}}
	drv.hook = func() {
		if slow && len(calls) == 2 { // the second chunk of the first run never answers in time
			time.Sleep(120 * time.Millisecond)
		}
	}
	src := OLTSource{Name: "OLT-ROT", LastDown: &LastDownSource{Key: "k", Every: time.Hour, Driver: drv, Timeout: 60 * time.Millisecond,
		Open: func(context.Context) (olt.SNMPReader, func(), error) { return nil, func() {}, nil }}}
	o := &OLT{}
	o.applyLastDown(src, &olt.Snapshot{ONUs: snapOnus})
	if err := o.readLastDown(context.Background(), src, ports, 1); err != nil {
		t.Fatalf("running out of OUR budget is not a failure of the agent: %v", err)
	}
	if len(calls) != 2 || len(calls[0]) != lastDownChunk {
		t.Fatalf("first run: one full chunk, then the budget ends: %v", calls)
	}
	slow = false
	calls = nil
	if err := o.readLastDown(context.Background(), src, ports, 1); err != nil {
		t.Fatal(err)
	}
	if len(calls) == 0 || calls[0][0] != ports[lastDownChunk] {
		t.Fatalf("the next run must start after the last PON that was finished (%s), not at the first again: %v", ports[lastDownChunk-1], calls)
	}
	if got := rotate([]string{"a", "b", "c"}, "b"); !reflect.DeepEqual(got, []string{"c", "a", "b"}) {
		t.Fatalf("rotate: %v", got)
	}
	if got := rotate([]string{"a", "b"}, "z"); !reflect.DeepEqual(got, []string{"a", "b"}) {
		t.Fatalf("a cursor past the end wraps to the start: %v", got)
	}
}
