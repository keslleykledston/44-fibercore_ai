package oltquery

import (
	"encoding/json"
	"errors"
	"fmt"
	"os"
	"path/filepath"
	"sync"
	"testing"
	"time"
)

const olt1, olt2 = "8f14e45f-ceea-467a-9a36-4a1b5c3d2e10", "9a14e45f-ceea-467a-9a36-4a1b5c3d2e11"

type clock struct{ t time.Time }

func (c *clock) now() time.Time { return c.t }

func newStore(t *testing.T) (*Store, *clock) {
	t.Helper()
	c := &clock{t: time.Date(2026, 10, 30, 12, 0, 0, 0, time.UTC)}
	return &Store{Path: filepath.Join(t.TempDir(), "oltquery.json"), Now: c.now}, c
}

func in(ref string) Intent { return Intent{QueryID: "olt.version", OLTRef: ref, Epoch: 1} }

func enq(t *testing.T, s *Store, c *clock, id, ref string) {
	t.Helper()
	if err := s.Enqueue(id, in(ref), c.t.Add(15*time.Minute)); err != nil {
		t.Fatal(err)
	}
	c.t = c.t.Add(time.Second) // distinct enqueue instants: the order is the order of arrival
}

func TestLifecycleAndPersistenceAcrossRestarts(t *testing.T) {
	s, c := newStore(t)
	enq(t, s, c, "j1", olt1)
	s2 := &Store{Path: s.Path, Now: c.now} // a restart: a new process reads the same file
	e, err := s2.Claim(olt1, "sess-1")
	if err != nil || e.JobID != "j1" || e.State != Claimed {
		t.Fatalf("claim: %+v %v", e, err)
	}
	if err := s2.Complete("j1", json.RawMessage(`{"version":"R015"}`)); err != nil {
		t.Fatal(err)
	}
	p, _ := s.PendingReports()
	if len(p) != 1 || p[0].State != Executed || string(p[0].Result) != `{"version":"R015"}` {
		t.Fatalf("pending: %+v", p)
	}
	if err := s.MarkReported("j1"); err != nil {
		t.Fatal(err)
	}
	if p, _ := s.PendingReports(); len(p) != 0 {
		t.Fatalf("reported entries are not pending: %+v", p)
	}
	if err := s.Complete("j1", json.RawMessage(`{}`)); !errors.Is(err, ErrBadState) {
		t.Fatalf("a finished query cannot be completed again: %v", err)
	}
	if fi, _ := os.Stat(s.Path); fi.Mode().Perm() != 0o600 {
		t.Fatalf("state file mode %v", fi.Mode().Perm())
	}
}

func TestEnqueueIsIdempotentAndBounded(t *testing.T) {
	s, c := newStore(t)
	exp := c.t.Add(15 * time.Minute)
	for i := 0; i < 2; i++ { // the same envelope delivered twice
		if err := s.Enqueue("j1", in(olt1), exp); err != nil {
			t.Fatal(err)
		}
	}
	if err := s.Enqueue("j1", Intent{QueryID: "olt.board", OLTRef: olt1, Epoch: 1}, c.t.Add(time.Hour)); !errors.Is(err, ErrConflict) {
		t.Fatalf("the same job id with another intent must be refused: %v", err)
	}
	e1, _ := s.Claim(olt1, "s")
	if _, err := s.Claim(olt1, "s"); !errors.Is(err, ErrNothingToDo) {
		t.Fatalf("one entry, one claim: %v %v", e1, err)
	}
	for i := 0; i < MaxQueuedPerOLT; i++ {
		enq(t, s, c, fmt.Sprintf("q%d", i), olt2)
	}
	if err := s.Enqueue("overflow", in(olt2), c.t.Add(time.Minute)); !errors.Is(err, ErrQueueFull) {
		t.Fatalf("queue must be bounded per OLT: %v", err)
	}
	if err := s.Enqueue("other-olt", in(olt1), c.t.Add(time.Minute)); err != nil {
		t.Fatalf("another OLT is not affected: %v", err)
	}
}

func TestAClaimedQueryNeverRunsAgainAfterARestart(t *testing.T) {
	s, c := newStore(t)
	enq(t, s, c, "j1", olt1)
	enq(t, s, c, "j2", olt1)
	if _, err := s.Claim(olt1, "s"); err != nil { // j1 claimed, then the process dies before any result
		t.Fatal(err)
	}
	s2 := &Store{Path: s.Path, Now: c.now}
	u, x, err := s2.Recover()
	if err != nil || u != 1 || x != 0 {
		t.Fatalf("recover: %d %d %v", u, x, err)
	}
	if e, _, _ := s2.Get("j1"); e.State != Unknown || e.Reason != "restart_after_claim" {
		t.Fatalf("j1: %+v", e)
	}
	got, err := s2.Claim(olt1, "s2")
	if err != nil || got.JobID != "j2" {
		t.Fatalf("only the waiting one may run: %+v %v", got, err)
	}
	if _, err := s2.Claim(olt1, "s3"); !errors.Is(err, ErrNothingToDo) {
		t.Fatalf("UNKNOWN must never be claimed: %v", err)
	}
	if p, _ := s2.PendingReports(); len(p) != 1 || p[0].JobID != "j1" {
		t.Fatalf("the unknown outcome is reported: %+v", p)
	}
}

func TestBudgetPerSessionAndPerHour(t *testing.T) {
	s, c := newStore(t)
	for i := 0; i < 8; i++ {
		enq(t, s, c, fmt.Sprintf("a%d", i), olt1)
	}
	n := 0
	for {
		e, err := s.Claim(olt1, "sess-A")
		if err != nil {
			break
		}
		_ = s.Complete(e.JobID, json.RawMessage(`{}`))
		n++
	}
	if n != PerSession {
		t.Fatalf("a session may run %d queries, ran %d", PerSession, n)
	}
	// next sessions: the hourly budget (20) caps the total on this OLT
	total := n
	for sess := 0; sess < 10; sess++ {
		for i := 0; i < 8; i++ {
			enq(t, s, c, fmt.Sprintf("b%d-%d", sess, i), olt1)
		}
		for {
			e, err := s.Claim(olt1, fmt.Sprintf("sess-%d", sess))
			if err != nil {
				break
			}
			_ = s.Complete(e.JobID, json.RawMessage(`{}`))
			total++
		}
		_, _ = s.AbortBatch(olt1, "olt_busy") // what the session does when the budget stops it: the rest ends, nothing is retried inside the window
	}
	if total != PerHour {
		t.Fatalf("an OLT may run %d queries in an hour, ran %d", PerHour, total)
	}
	c.t = c.t.Add(61 * time.Minute) // the window rolls
	enq(t, s, c, "late", olt1)
	if e, err := s.Claim(olt1, "sess-late"); err != nil || e.JobID == "" {
		t.Fatalf("budget must come back after the hour: %v", err)
	}
	other := &Store{Path: s.Path, Now: c.now}
	enq(t, other, c, "x", olt2)
	if _, err := other.Claim(olt2, "s"); err != nil {
		t.Fatalf("the budget is per OLT: %v", err)
	}
}

func TestExpiryAndBatchAbort(t *testing.T) {
	s, c := newStore(t)
	enq(t, s, c, "old", olt1)
	c.t = c.t.Add(16 * time.Minute)
	if _, err := s.Claim(olt1, "s"); !errors.Is(err, ErrNothingToDo) {
		t.Fatalf("a query past its deadline is not run: %v", err)
	}
	if n, _ := s.ExpireDue(); n != 1 {
		t.Fatalf("expired %d", n)
	}
	enq(t, s, c, "a", olt1)
	enq(t, s, c, "b", olt1)
	enq(t, s, c, "c", olt2)
	n, err := s.AbortBatch(olt1, "olt_busy")
	if err != nil || n != 2 {
		t.Fatalf("abort: %d %v", n, err)
	}
	if e, _, _ := s.Get("a"); e.State != Failed || e.Reason != "olt_busy" {
		t.Fatalf("a: %+v", e)
	}
	if e, _, _ := s.Get("c"); e.State != Queued {
		t.Fatalf("another OLT untouched: %+v", e)
	}
}

func TestACorruptFileSpendsTheBudget(t *testing.T) {
	s, c := newStore(t)
	enq(t, s, c, "j1", olt1)
	for _, junk := range []string{"not json", "null", `{"entries":null}`, "", `{"entries":{}}`, `{"entries":{},"claims":null}`, `{"entries":{},"claims":{"x":["0001-01-01T00:00:00Z"]}}`, `{"entries":{"j1":null}}`, `{"entries":{"j1":{}}}`,
		`{"entries":{"j1":{"job_id":"other","state":"QUEUED","intent":{"olt_ref":"x"}}}}`, `{"entries":{"j1":{"job_id":"j1","state":"WEIRD","intent":{"olt_ref":"x"}}}}`} {
		if err := os.WriteFile(s.Path, []byte(junk), 0o600); err != nil {
			t.Fatal(err)
		}
		if _, err := s.Claim(olt1, "s"); !errors.Is(err, ErrCorrupt) {
			t.Errorf("%q: claim must refuse: %v", junk, err)
		}
		if err := s.Enqueue("j2", in(olt1), c.t.Add(time.Minute)); !errors.Is(err, ErrCorrupt) {
			t.Errorf("%q: enqueue must refuse: %v", junk, err)
		}
	}
}

func TestOnlyClaimedQueriesTakeResultsAndTheyAreBounded(t *testing.T) {
	s, c := newStore(t)
	enq(t, s, c, "j1", olt1)
	if err := s.Complete("j1", json.RawMessage(`{}`)); !errors.Is(err, ErrBadState) {
		t.Fatalf("a query nobody claimed has no result: %v", err)
	}
	if err := s.Fail("nope", "x"); !errors.Is(err, ErrBadState) {
		t.Fatalf("unknown job: %v", err)
	}
	if _, err := s.Claim(olt1, "s"); err != nil {
		t.Fatal(err)
	}
	if err := s.Complete("j1", make([]byte, MaxResultBytes+1)); !errors.Is(err, ErrResultSize) {
		t.Fatalf("oversized result: %v", err)
	}
	if err := s.Fail("j1", "device_rejected"); err != nil {
		t.Fatal(err)
	}
	if e, _, _ := s.Get("j1"); e.State != Failed || len(e.Result) != 0 {
		t.Fatalf("%+v", e)
	}
}

func TestConcurrentClaimsGiveEachQueryToExactlyOne(t *testing.T) {
	s, c := newStore(t)
	for i := 0; i < PerSession; i++ {
		enq(t, s, c, fmt.Sprintf("j%d", i), olt1)
	}
	var mu sync.Mutex
	got := map[string]int{}
	var wg sync.WaitGroup
	for g := 0; g < 8; g++ {
		wg.Add(1)
		go func() {
			defer wg.Done()
			for {
				e, err := s.Claim(olt1, "s")
				if err != nil {
					return
				}
				mu.Lock()
				got[e.JobID]++
				mu.Unlock()
			}
		}()
	}
	wg.Wait()
	if len(got) != PerSession {
		t.Fatalf("claimed %v", got)
	}
	for id, n := range got {
		if n != 1 {
			t.Fatalf("%s claimed %d times", id, n)
		}
	}
}

func TestReportedEntriesAreDroppedAfterADay(t *testing.T) {
	s, c := newStore(t)
	enq(t, s, c, "j1", olt1)
	enq(t, s, c, "j2", olt1)
	for _, id := range []string{"j1", "j2"} {
		e, _ := s.Claim(olt1, "s")
		_ = s.Complete(e.JobID, json.RawMessage(`{}`))
		_ = id
	}
	_ = s.MarkReported("j1")
	c.t = c.t.Add(25 * time.Hour)
	_ = s.MarkReported("j2")
	if _, ok, _ := s.Get("j1"); ok {
		t.Fatal("j1 reported over a day ago must be gone")
	}
	if e, ok, _ := s.Get("j2"); !ok || e.State != Reported {
		t.Fatalf("j2 just reported stays: %+v %v", e, ok)
	}
}

func TestTwoStoresOnTheSameFileNeverGiveTheSameQueryTwice(t *testing.T) {
	a, c := newStore(t)
	b := &Store{Path: a.Path, Now: c.now} // another instance (another process would be the same to the file lock)
	for i := 0; i < PerSession; i++ {
		enq(t, a, c, fmt.Sprintf("j%d", i), olt1)
	}
	var mu sync.Mutex
	got := map[string]int{}
	var wg sync.WaitGroup
	for _, s := range []*Store{a, b, a, b, a, b} {
		wg.Add(1)
		go func(s *Store) {
			defer wg.Done()
			for {
				e, err := s.Claim(olt1, "s")
				if err != nil {
					return
				}
				mu.Lock()
				got[e.JobID]++
				mu.Unlock()
			}
		}(s)
	}
	wg.Wait()
	if len(got) != PerSession {
		t.Fatalf("claimed %v", got)
	}
	for id, n := range got {
		if n != 1 {
			t.Fatalf("%s handed out %d times", id, n)
		}
	}
}

func TestAnAbandonedClaimBecomesUnknownWithoutARestart(t *testing.T) {
	s, c := newStore(t)
	enq(t, s, c, "j1", olt1)
	if _, err := s.Claim(olt1, "s"); err != nil {
		t.Fatal(err)
	}
	c.t = c.t.Add(10 * time.Minute)
	if n, _ := s.ExpireDue(); n != 0 {
		t.Fatalf("a claim that may still be running is left alone: %d", n)
	}
	c.t = c.t.Add(10 * time.Minute)
	if n, _ := s.ExpireDue(); n != 1 {
		t.Fatalf("expired %d", n)
	}
	if e, _, _ := s.Get("j1"); e.State != Unknown || e.Reason != "claim_abandoned" {
		t.Fatalf("%+v", e)
	}
	if _, err := s.Claim(olt1, "s2"); !errors.Is(err, ErrNothingToDo) {
		t.Fatal("never claimed again")
	}
}

func TestRefusedAndAcknowledgedEntriesAreBothPrunedAfterADay(t *testing.T) {
	s, c := newStore(t)
	for _, id := range []string{"ok", "refused"} {
		enq(t, s, c, id, olt1)
		e, _ := s.Claim(olt1, "s")
		_ = s.Complete(e.JobID, json.RawMessage(`{}`))
	}
	if err := s.MarkReported("ok"); err != nil {
		t.Fatal(err)
	}
	if err := s.MarkRejected("refused"); err != nil {
		t.Fatal(err)
	}
	if e, _, _ := s.Get("refused"); e.Reason != "cloud_rejected" || len(e.Result) == 0 {
		t.Fatalf("%+v", e)
	}
	c.t = c.t.Add(25 * time.Hour)
	if _, err := s.ExpireDue(); err != nil { // the periodic sweep, whatever the Cloud answered
		t.Fatal(err)
	}
	for _, id := range []string{"ok", "refused"} {
		if _, ok, _ := s.Get(id); ok {
			t.Fatalf("%s must be pruned", id)
		}
	}
}

func TestAnEnvelopeOfAnOlderOwnerGenerationIsRefusedAndTheGenerationOnlyGoesUp(t *testing.T) {
	s, c := newStore(t)
	exp := c.t.Add(10 * time.Minute)
	if err := s.Enqueue("a", Intent{QueryID: "olt.version", OLTRef: olt1, Epoch: 3}, exp); err != nil {
		t.Fatal(err)
	}
	if err := s.Enqueue("b", Intent{QueryID: "olt.version", OLTRef: olt1, Epoch: 2}, exp); !errors.Is(err, ErrStaleOwner) {
		t.Fatalf("a lower epoch belongs to an owner that was replaced: %v", err)
	}
	if err := s.Enqueue("c", Intent{QueryID: "olt.version", OLTRef: olt1, Epoch: 0}, exp); !errors.Is(err, ErrStaleOwner) {
		t.Fatalf("epoch 0 does not exist: %v", err)
	}
	restarted := &Store{Path: s.Path, Now: c.now} // the highest epoch seen is on disk, not in memory
	if err := restarted.Enqueue("d", Intent{QueryID: "olt.version", OLTRef: olt1, Epoch: 2}, exp); !errors.Is(err, ErrStaleOwner) {
		t.Fatalf("after a restart: %v", err)
	}
	if err := restarted.Enqueue("e", Intent{QueryID: "olt.version", OLTRef: olt1, Epoch: 4}, exp); err != nil {
		t.Fatal(err)
	}
	if err := restarted.Enqueue("f", Intent{QueryID: "olt.version", OLTRef: olt1, Epoch: 3}, exp); !errors.Is(err, ErrStaleOwner) {
		t.Fatalf("4 was seen: 3 is stale now: %v", err)
	}
	if err := restarted.Enqueue("g", Intent{QueryID: "olt.version", OLTRef: olt2, Epoch: 1}, exp); err != nil {
		t.Fatalf("epochs are per OLT: %v", err)
	}
	if err := os.WriteFile(s.Path, []byte(`{"entries":{},"claims":{},"epochs":{"x":0}}`), 0o600); err != nil {
		t.Fatal(err)
	}
	if _, err := s.Claim(olt1, "s"); !errors.Is(err, ErrCorrupt) {
		t.Fatalf("a malformed epoch table is corruption: %v", err)
	}
}

func TestCaptureBudgetIsItsOwnClassAndFitsTheAggregate(t *testing.T) {
	s, c := newStore(t)
	for i := 0; i < CapturesPerSession; i++ {
		if err := s.ReserveCapture(olt1, "sess-A"); err != nil {
			t.Fatalf("capture %d: %v", i, err)
		}
	}
	if err := s.ReserveCapture(olt1, "sess-A"); !errors.Is(err, ErrBudget) {
		t.Fatalf("a session holds %d captures: %v", CapturesPerSession, err)
	}
	if err := s.ReserveCapture(olt1, "sess-B"); err != nil {
		t.Fatal(err)
	}
	if err := s.ReserveCapture(olt1, "sess-B"); err != nil {
		t.Fatal(err)
	}
	if err := s.ReserveCapture(olt1, "sess-C"); !errors.Is(err, ErrBudget) {
		t.Fatalf("the hour holds %d captures: %v", CapturesPerHour, err)
	}
	if err := s.ReserveCapture(olt2, "sess-C"); err != nil {
		t.Fatalf("another OLT has its own budget: %v", err)
	}
	restarted := &Store{Path: s.Path, Now: c.now}
	if err := restarted.ReserveCapture(olt1, "sess-D"); !errors.Is(err, ErrBudget) {
		t.Fatalf("the spent budget survives a restart: %v", err)
	}
	c.t = c.t.Add(61 * time.Minute)
	if err := restarted.ReserveCapture(olt1, "sess-E"); err != nil {
		t.Fatalf("the hour rolled: %v", err)
	}
	// captures never take the on-demand class: the on-demand budget of a session is untouched by them
	s2, c2 := newStore(t)
	_ = s2.ReserveCapture(olt1, "S")
	_ = s2.ReserveCapture(olt1, "S")
	for i := 0; i < PerSession; i++ {
		enq(t, s2, c2, fmt.Sprintf("j%d", i), olt1)
	}
	n := 0
	for {
		if _, err := s2.Claim(olt1, "S"); err != nil {
			break
		}
		n++
	}
	if n != PerSession || n+CapturesPerSession > MaxPerSession {
		t.Fatalf("on-demand ran %d with 2 captures in the same session (aggregate cap %d)", n, MaxPerSession)
	}
	// the aggregate: with on-demand queries already filling the session, a capture is refused when the sum would pass the cap
	s3, c3 := newStore(t)
	for i := 0; i < MaxPerSession; i++ {
		enq(t, s3, c3, fmt.Sprintf("a%d", i), olt1)
	}
	for i := 0; i < PerSession; i++ {
		_, _ = s3.Claim(olt1, "T")
	}
	f, _ := s3.load()
	for i := 0; i < 4; i++ { // pretend three more executions were counted in the session (routines of the future)
		f.Entries[fmt.Sprintf("x%d", i)] = &Entry{JobID: fmt.Sprintf("x%d", i), Intent: Intent{OLTRef: olt1}, State: Failed, SessionID: "T"}
	}
	if err := s3.save(f); err != nil {
		t.Fatal(err)
	}
	if err := s3.ReserveCapture(olt1, "T"); !errors.Is(err, ErrBudget) {
		t.Fatalf("9 executions already counted in the session: a capture would pass the aggregate cap: %v", err)
	}
}

func TestCapturesOfTheSessionCountTowardTheAggregateCapOfOnDemandClaims(t *testing.T) {
	s, c := newStore(t)
	for i := 0; i < CapturesPerSession; i++ {
		if err := s.ReserveCapture(olt1, "S"); err != nil {
			t.Fatal(err)
		}
	}
	for i := 0; i < MaxPerSession; i++ {
		enq(t, s, c, fmt.Sprintf("j%d", i), olt1)
	}
	n := 0
	for {
		if _, err := s.Claim(olt1, "S"); err != nil {
			break
		}
		n++
	}
	if n+CapturesPerSession > MaxPerSession {
		t.Fatalf("%d on-demand + %d captures pass the aggregate cap %d", n, CapturesPerSession, MaxPerSession)
	}
}

func TestTheAggregateCapIsPerSessionAcrossOLTs(t *testing.T) {
	s, c := newStore(t)
	for i := 0; i < PerSession; i++ {
		enq(t, s, c, fmt.Sprintf("a%d", i), olt1)
	}
	for i := 0; i < PerSession; i++ {
		if _, err := s.Claim(olt1, "S"); err != nil {
			t.Fatal(err)
		}
	}
	// the same session id used for another OLT (an alias or a shared id): 5 already ran, 2 captures fit (7), a 3rd execution of any kind does not pass 8
	for i := 0; i < CapturesPerSession; i++ {
		if err := s.ReserveCapture(olt2, "S"); err != nil {
			t.Fatal(err)
		}
	}
	for i := 0; i < 4; i++ {
		enq(t, s, c, fmt.Sprintf("b%d", i), olt2)
	}
	n := 0
	for {
		if _, err := s.Claim(olt2, "S"); err != nil {
			break
		}
		n++
	}
	if PerSession+CapturesPerSession+n > MaxPerSession {
		t.Fatalf("session total %d passes the cap %d", PerSession+CapturesPerSession+n, MaxPerSession)
	}
}
