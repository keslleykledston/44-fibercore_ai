package collector

import (
	"context"
	"encoding/json"
	"errors"
	"os"
	"path/filepath"
	"strings"
	"testing"
	"time"

	"github.com/keslleykledston/44-fibercore_ai/agents/edge/internal/jobs"
	"github.com/keslleykledston/44-fibercore_ai/agents/edge/internal/olt"
	"github.com/keslleykledston/44-fibercore_ai/agents/edge/internal/oltquery"
)

const qCloud = "8f14e45f-ceea-467a-9a36-4a1b5c3d2e10"

// qSession replays the real R015 captures (collection) plus the board listing, and records every command it is sent.
// fakeLease is a valid lease: OLT ref -> epoch.
type fakeLease map[string]int

func (l fakeLease) Epoch(ref string) (int, bool) { e, ok := l[ref]; return e, ok }
func (l fakeLease) Remaining(ref string) time.Duration {
	if _, ok := l[ref]; ok {
		return 2 * time.Minute
	}
	return 0
}
func (l fakeLease) Grant(ref string, epoch int) (time.Duration, error) {
	if e, ok := l[ref]; !ok {
		return 0, jobs.ErrNoLease
	} else if e != epoch {
		return 0, jobs.ErrLeaseTarget
	}
	return l.Remaining(ref), nil
}

type qSession struct {
	inner  r015Session
	sent   []string
	reject string            // a command the device refuses
	extra  map[string]string // replies for commands the replayed captures do not cover
}

func (q *qSession) Run(ctx context.Context, cmd string) (string, error) {
	q.sent = append(q.sent, cmd)
	if out, ok := q.extra[cmd]; ok {
		return out, nil
	}
	if cmd == q.reject {
		return "  Failure: Unknown command\n", nil
	}
	if cmd == "display board 0" {
		b, err := os.ReadFile(filepath.Join("..", "olt", "testdata", "huawei_ma5608t", "MA5600V800R015C00", "board_0.txt"))
		return string(b), err
	}
	return q.inner.Run(ctx, cmd)
}

func queryRig(t *testing.T, sess olt.Session) (*OLT, *oltquery.Store) {
	t.Helper()
	store := &oltquery.Store{Path: filepath.Join(t.TempDir(), "q.json")}
	drv := olt.HuaweiR015{}
	src := OLTSource{Name: "OLT-R015", Driver: drv, Ports: []string{"0/0/14"}, CloudID: qCloud, AllowUnverified: true,
		Open: func(context.Context) (olt.Session, func(), error) { return sess, func() {}, nil }}
	o := &OLT{EdgeID: "e", Sources: []OLTSource{src}, Queries: &Queries{Store: store, Run: drv.RunQueryInConfig, Lease: fakeLease{qCloud: 1}}}
	return o, store
}

func enqueue(t *testing.T, s *oltquery.Store, id, query string) {
	t.Helper()
	if err := s.Enqueue(id, oltquery.Intent{QueryID: query, OLTRef: qCloud, Epoch: 1}, time.Now().Add(10*time.Minute)); err != nil {
		t.Fatal(err)
	}
	time.Sleep(2 * time.Millisecond)
}

func TestQueriesRunInTheCollectionsOwnSessionAndReturnTypedResults(t *testing.T) {
	sess := &qSession{inner: r015Session{}}
	o, store := queryRig(t, sess)
	enqueue(t, store, "job-v", "olt.version")
	enqueue(t, store, "job-b", "olt.board")
	items, err := o.Collect(context.Background())
	if err != nil || len(items) != 1 {
		t.Fatalf("the collection must be unaffected: %d %v", len(items), err)
	}
	for id, want := range map[string]string{"job-v": `"product":"MA5608T"`, "job-b": `"name":"H801MCUD1"`} {
		e, ok, _ := store.Get(id)
		if !ok || e.State != oltquery.Executed || !strings.Contains(string(e.Result), want) {
			t.Fatalf("%s: %+v", id, e)
		}
	}
	// ONE session: the queries came after the collection's own commands, and `enable`/`config` were not sent a second time
	joined := strings.Join(sess.sent, "|")
	if strings.Count(joined, "enable") != 1 || strings.Count(joined, "config") != 1 {
		t.Fatalf("modes sent again: %v", sess.sent)
	}
	last := sess.sent[len(sess.sent)-1]
	if last != "display board 0" || strings.Index(joined, "display ont info 14 all") > strings.Index(joined, "display board 0") {
		t.Fatalf("queries must come after the collection: %v", sess.sent)
	}
}

func TestADeviceRefusalEndsTheBatchAndNeverTheCollection(t *testing.T) {
	sess := &qSession{inner: r015Session{}, reject: "display board 0"}
	o, store := queryRig(t, sess)
	enqueue(t, store, "job-b", "olt.board")
	enqueue(t, store, "job-v", "olt.version")
	items, err := o.Collect(context.Background())
	if err != nil || len(items) != 1 {
		t.Fatalf("a failing query must not fail the collection: %d %v", len(items), err)
	}
	if e, _, _ := store.Get("job-b"); e.State != oltquery.Failed || e.Reason != "device_rejected" {
		t.Fatalf("job-b: %+v", e)
	}
	if e, _, _ := store.Get("job-v"); e.State != oltquery.Failed || e.Reason != "olt_busy" {
		t.Fatalf("the rest of the batch ends without running: %+v", e)
	}
}

func TestAQueryWithoutParserNeverReachesTheDevice(t *testing.T) {
	sess := &qSession{inner: r015Session{}}
	o, store := queryRig(t, sess)
	enqueue(t, store, "job-x", "olt.alarm.history") // in the catalog, not validated: no parser
	enqueue(t, store, "job-v", "olt.version")
	if _, err := o.Collect(context.Background()); err != nil {
		t.Fatal(err)
	}
	if e, _, _ := store.Get("job-x"); e.State != oltquery.Failed || e.Reason != "no_parser" {
		t.Fatalf("%+v", e)
	}
	if strings.Contains(strings.Join(sess.sent, "|"), "display alarm history") {
		t.Fatalf("sent to the device: %v", sess.sent)
	}
	if e, _, _ := store.Get("job-v"); e.State != oltquery.Executed {
		t.Fatalf("an unrelated query still runs: %+v", e)
	}
}

func TestNothingRunsWithoutACloudIDOrOnAnUnreadableQueue(t *testing.T) {
	sess := &qSession{inner: r015Session{}}
	o, store := queryRig(t, sess)
	enqueue(t, store, "job-v", "olt.version")
	o.Sources[0].CloudID = ""
	if _, err := o.Collect(context.Background()); err != nil {
		t.Fatal(err)
	}
	if e, _, _ := store.Get("job-v"); e.State != oltquery.Queued {
		t.Fatalf("an OLT with no cloud_id takes no query: %+v", e)
	}
	o.Sources[0].CloudID = qCloud
	if err := os.WriteFile(store.Path, []byte("{"), 0o600); err != nil {
		t.Fatal(err)
	}
	o2 := &OLT{EdgeID: "e", Sources: o.Sources, Queries: o.Queries}
	sess.sent = nil
	if items, err := o2.Collect(context.Background()); err != nil || len(items) != 1 {
		t.Fatalf("an unreadable queue must not break the collection: %v", err)
	}
	if strings.Contains(strings.Join(sess.sent, "|"), "display board") || sess.sent[len(sess.sent)-1] != "quit" { // the collection's own last command
		t.Fatalf("nothing is claimed from an unreadable queue: %v", sess.sent)
	}
}

func TestQueriesNeverExceedTheSessionBudget(t *testing.T) {
	sess := &qSession{inner: r015Session{}}
	o, store := queryRig(t, sess)
	for i := 0; i < 8; i++ {
		enqueue(t, store, "j"+string(rune('a'+i)), "olt.version")
	}
	if _, err := o.Collect(context.Background()); err != nil {
		t.Fatal(err)
	}
	done := 0
	for i := 0; i < 8; i++ {
		if e, _, _ := store.Get("j" + string(rune('a'+i))); e.State == oltquery.Executed {
			done++
		}
	}
	if done != oltquery.PerSession {
		t.Fatalf("a session runs %d queries, ran %d", oltquery.PerSession, done)
	}
}

func TestFailureReasonsAreCategoriesNeverDeviceText(t *testing.T) {
	for err, want := range map[error]string{olt.ErrDeviceRejected: "device_rejected", olt.ErrPaginated: "paginated", context.DeadlineExceeded: "timeout",
		olt.ErrBudget: "budget", errors.New("login as admin/secret failed on 10.0.0.1"): "session_error"} {
		if got := failureReason(err); got != want {
			t.Errorf("%v -> %s, want %s", err, got, want)
		}
	}
	_ = json.RawMessage(nil)
}

func TestQueriesNeverOutliveTheCollectionsTimeBox(t *testing.T) {
	sess := &qSession{inner: r015Session{}}
	o, store := queryRig(t, sess)
	enqueue(t, store, "job-v", "olt.version")
	// a collection that has almost no time left starts no query (and claims nothing: the query waits for the next window)
	ctx, cancel := context.WithTimeout(context.Background(), 10*time.Second)
	defer cancel()
	src := o.Sources[0]
	if n := o.Queries.Drain(ctx, src, sess, qCloud, "s"); n != 0 {
		t.Fatalf("ran %d", n)
	}
	if e, _, _ := store.Get("job-v"); e.State != oltquery.Queued {
		t.Fatalf("%+v", e)
	}
	// with time left it runs, and its own deadline never exceeds the collection's
	ctx2, cancel2 := context.WithTimeout(context.Background(), 2*time.Minute)
	defer cancel2()
	if n := o.Queries.Drain(ctx2, src, sess, qCloud, "s"); n != 1 {
		t.Fatalf("ran %d", n)
	}
	cancelled, c3 := context.WithCancel(context.Background())
	c3()
	enqueue(t, store, "job-w", "olt.version")
	if n := o.Queries.Drain(cancelled, src, sess, qCloud, "s2"); n != 0 {
		t.Fatalf("a cancelled collection starts nothing: %d", n)
	}
}

func TestTheWindowIsAskedBeforeEveryClaim(t *testing.T) {
	sess := &qSession{inner: r015Session{}}
	o, store := queryRig(t, sess)
	for _, id := range []string{"a", "b", "c"} {
		enqueue(t, store, id, "olt.version")
	}
	// the box has 40 s left: the first query starts (>= 30 s), and the running clock is shortened by a context that ends right after it
	ctx, cancel := context.WithTimeout(context.Background(), 40*time.Second)
	defer cancel()
	o.Queries.Run = func(c context.Context, s olt.Session, id string, p olt.Params) (olt.QueryResult, error) {
		res, err := olt.HuaweiR015{}.RunQueryInConfig(c, s, id, p)
		cancel() // the time is gone when the query returns
		return res, err
	}
	if n := o.Queries.Drain(ctx, o.Sources[0], sess, qCloud, "s"); n != 1 {
		t.Fatalf("only the first query may start: %d", n)
	}
	waiting := 0
	for _, id := range []string{"a", "b", "c"} {
		if e, _, _ := store.Get(id); e.State == oltquery.Queued {
			waiting++
		}
	}
	if waiting != 2 {
		t.Fatalf("the others wait for the next window, unclaimed: %d", waiting)
	}
}

func TestAClaimThatEatsTheWindowSendsNothing(t *testing.T) {
	sess := &qSession{inner: r015Session{}}
	o, store := queryRig(t, sess)
	enqueue(t, store, "job-v", "olt.version")
	// 31 s left when the claim starts; the store's clock makes writing it "take" the rest (the deadline passes during the claim)
	ctx, cancel := context.WithTimeout(context.Background(), 31*time.Second)
	defer cancel()
	calls := 0
	store.Now = func() time.Time { // ExpireDue reads the clock first, the claim second: the collection's time is gone right at the claim
		if calls++; calls >= 2 {
			cancel()
		}
		return time.Now()
	}
	if n := o.Queries.Drain(ctx, o.Sources[0], sess, qCloud, "s"); n != 1 {
		t.Fatalf("claimed %d", n)
	}
	if len(sess.sent) != 0 {
		t.Fatalf("nothing may reach the device once the window closed: %v", sess.sent)
	}
	if e, _, _ := store.Get("job-v"); e.State != oltquery.Failed || e.Reason != "window_closed" {
		t.Fatalf("%+v", e)
	}
}

func TestNothingIsClaimedWithoutAValidLeaseForThisOLT(t *testing.T) {
	for name, lease := range map[string]LeaseChecker{"no checker": nil, "no lease at all": fakeLease{}, "a lease for another OLT": fakeLease{"9a14e45f-ceea-467a-9a36-4a1b5c3d2e11": 1}} {
		sess := &qSession{inner: r015Session{}}
		o, store := queryRig(t, sess)
		o.Queries.Lease = lease
		enqueue(t, store, "job-v", "olt.version")
		items, err := o.Collect(context.Background())
		if err != nil || len(items) != 1 {
			t.Fatalf("%s: the collection must be unaffected: %v", name, err)
		}
		if e, _, _ := store.Get("job-v"); e.State != oltquery.Queued {
			t.Errorf("%s: %+v", name, e)
		}
		if sess.sent[len(sess.sent)-1] != "quit" {
			t.Errorf("%s: nothing after the collection's own commands: %v", name, sess.sent)
		}
	}
}

func TestAQueryOfAnotherOwnerGenerationEndsAloneAndTheCurrentOneRuns(t *testing.T) {
	sess := &qSession{inner: r015Session{}}
	o, store := queryRig(t, sess)
	o.Queries.Lease = fakeLease{qCloud: 5}
	if err := store.Enqueue("old", oltquery.Intent{QueryID: "olt.version", OLTRef: qCloud, Epoch: 4}, time.Now().Add(10*time.Minute)); err != nil {
		t.Fatal(err)
	}
	time.Sleep(2 * time.Millisecond)
	if err := store.Enqueue("new", oltquery.Intent{QueryID: "olt.board", OLTRef: qCloud, Epoch: 5}, time.Now().Add(10*time.Minute)); err != nil {
		t.Fatal(err)
	}
	if _, err := o.Collect(context.Background()); err != nil {
		t.Fatal(err)
	}
	if e, _, _ := store.Get("old"); e.State != oltquery.Failed || e.Reason != "stale_owner" {
		t.Fatalf("old: %+v", e)
	}
	if e, _, _ := store.Get("new"); e.State != oltquery.Executed {
		t.Fatalf("new: %+v", e)
	}
	if strings.Count(strings.Join(sess.sent, "|"), "display version") != 3 { // two by the collection itself + one by the current query; the stale one sent nothing
		t.Fatalf("%v", sess.sent)
	}
}

// a lease that is valid when the loop asks, and gone when the claim is checked
type flakyLease struct{ asked int }

func (l *flakyLease) Epoch(string) (int, bool)                 { return 1, true }
func (l *flakyLease) Grant(string, int) (time.Duration, error) { return 0, jobs.ErrNoLease }
func (l *flakyLease) Remaining(string) time.Duration           { return 2 * time.Minute }

func TestALeaseLostBetweenTheAskAndTheClaimSendsNothing(t *testing.T) {
	sess := &qSession{inner: r015Session{}}
	o, store := queryRig(t, sess)
	o.Queries.Lease = &flakyLease{}
	enqueue(t, store, "job-v", "olt.version")
	enqueue(t, store, "job-b", "olt.board")
	if _, err := o.Collect(context.Background()); err != nil {
		t.Fatal(err)
	}
	if e, _, _ := store.Get("job-v"); e.State != oltquery.Failed || e.Reason != "lease_lost" {
		t.Fatalf("%+v", e)
	}
	if e, _, _ := store.Get("job-b"); e.State != oltquery.Queued {
		t.Fatalf("the rest waits for a lease: %+v", e)
	}
	if sess.sent[len(sess.sent)-1] != "quit" {
		t.Fatalf("%v", sess.sent)
	}
}

// a lease with 40 s left at the start: the query gets AT MOST that long, never the batch's 3 minutes
type shortLease struct {
	fakeLease
	left time.Duration
}

func (l shortLease) Remaining(string) time.Duration { return l.left }
func (l shortLease) Grant(ref string, epoch int) (time.Duration, error) {
	if _, err := l.fakeLease.Grant(ref, epoch); err != nil {
		return 0, err
	}
	return l.left, nil
}

func TestAQueryNeverOutlivesTheLeaseItStartedUnder(t *testing.T) {
	var deadline time.Time
	sess := &qSession{inner: r015Session{}}
	o, store := queryRig(t, sess)
	o.Queries.Lease = shortLease{fakeLease{qCloud: 1}, 40 * time.Second}
	o.Queries.Run = func(c context.Context, s olt.Session, id string, p olt.Params) (olt.QueryResult, error) {
		deadline, _ = c.Deadline()
		return olt.HuaweiR015{}.RunQueryInConfig(c, s, id, p)
	}
	enqueue(t, store, "job-v", "olt.version")
	start := time.Now()
	if _, err := o.Collect(context.Background()); err != nil {
		t.Fatal(err)
	}
	if deadline.IsZero() || deadline.Sub(start) > 41*time.Second {
		t.Fatalf("the query's own deadline must be the lease's end, got %v after start", deadline.Sub(start))
	}
	// with less than the minimum window of lease left, nothing is claimed at all
	o.Queries.Lease = shortLease{fakeLease{qCloud: 1}, 10 * time.Second}
	enqueue(t, store, "job-b", "olt.board")
	if _, err := o.Collect(context.Background()); err != nil {
		t.Fatal(err)
	}
	if e, _, _ := store.Get("job-b"); e.State != oltquery.Queued {
		t.Fatalf("%+v", e)
	}
}
