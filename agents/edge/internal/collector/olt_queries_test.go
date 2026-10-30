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

	"github.com/keslleykledston/44-fibercore_ai/agents/edge/internal/olt"
	"github.com/keslleykledston/44-fibercore_ai/agents/edge/internal/oltquery"
)

const qCloud = "8f14e45f-ceea-467a-9a36-4a1b5c3d2e10"

// qSession replays the real R015 captures (collection) plus the board listing, and records every command it is sent.
type qSession struct {
	inner  r015Session
	sent   []string
	reject string // a command the device refuses
}

func (q *qSession) Run(ctx context.Context, cmd string) (string, error) {
	q.sent = append(q.sent, cmd)
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
	o := &OLT{EdgeID: "e", Sources: []OLTSource{src}, Queries: &Queries{Store: store, Run: drv.RunQueryInConfig}}
	return o, store
}

func enqueue(t *testing.T, s *oltquery.Store, id, query string) {
	t.Helper()
	if err := s.Enqueue(id, oltquery.Intent{QueryID: query, OLTRef: qCloud}, time.Now().Add(10*time.Minute)); err != nil {
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
	enqueue(t, store, "job-x", "olt.time") // in the catalog, not validated: no parser
	enqueue(t, store, "job-v", "olt.version")
	if _, err := o.Collect(context.Background()); err != nil {
		t.Fatal(err)
	}
	if e, _, _ := store.Get("job-x"); e.State != oltquery.Failed || e.Reason != "no_parser" {
		t.Fatalf("%+v", e)
	}
	if strings.Contains(strings.Join(sess.sent, "|"), "display time") {
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
	if strings.Contains(strings.Join(sess.sent, "|"), "display board") || strings.Count(strings.Join(sess.sent, "|"), "display version") != 1 {
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
