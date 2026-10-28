package agent

import (
	"context"
	"encoding/json"
	"io"
	"log/slog"
	"net/http"
	"net/http/httptest"
	"path/filepath"
	"sync"
	"testing"

	"github.com/keslleykledston/44-fibercore_ai/agents/edge/internal/collector"
	"github.com/keslleykledston/44-fibercore_ai/agents/edge/internal/gateway"
	"github.com/keslleykledston/44-fibercore_ai/agents/edge/internal/queue"
)

type cloud struct {
	mu       sync.Mutex
	status   int
	received []string
}

func (c *cloud) handler(w http.ResponseWriter, r *http.Request) {
	if r.URL.Path == "/v1/auth/service-token" {
		json.NewEncoder(w).Encode(map[string]string{"access_token": "t"})
		return
	}
	b, _ := io.ReadAll(r.Body)
	c.mu.Lock()
	defer c.mu.Unlock()
	if c.status >= 300 {
		w.WriteHeader(c.status)
		return
	}
	c.received = append(c.received, string(b))
	w.WriteHeader(202)
}

type fixedCollector struct{ payloads []string }

func (f fixedCollector) Name() string { return "fixed" }
func (f fixedCollector) Collect(context.Context) ([]collector.Item, error) {
	var out []collector.Item
	for _, p := range f.payloads {
		out = append(out, collector.Item{Kind: "cpe_snapshot", Payload: []byte(p)})
	}
	return out, nil
}

type failingCollector struct{}

func (failingCollector) Name() string { return "failing" }
func (failingCollector) Collect(context.Context) ([]collector.Item, error) {
	return nil, io.ErrUnexpectedEOF
}

func setup(t *testing.T, cl *cloud, cols ...collector.Collector) *Agent {
	srv := httptest.NewServer(http.HandlerFunc(cl.handler))
	t.Cleanup(srv.Close)
	q, err := queue.Open(filepath.Join(t.TempDir(), "q.db"))
	if err != nil {
		t.Fatal(err)
	}
	t.Cleanup(func() { q.Close() })
	return &Agent{EdgeID: "e", TenantID: "t", Version: "v", GW: gateway.New(srv.URL, "c", "s", srv.Client()), Q: q,
		Collectors: cols, Log: slog.New(slog.NewTextHandler(io.Discard, nil))}
}

func TestStoreAndForwardKeepsOrderAcrossOutage(t *testing.T) {
	ctx := context.Background()
	cl := &cloud{status: 503}
	a := setup(t, cl, fixedCollector{[]string{`{"n":1}`, `{"n":2}`, `{"n":3}`}})
	_ = a.CollectOnce(ctx)
	a.Flush(ctx) // cloud down: nothing lost, nothing delivered
	if p, _, _ := a.Q.Counts(ctx); p != 3 || len(cl.received) != 0 {
		t.Fatalf("pending=%d received=%d", p, len(cl.received))
	}
	cl.mu.Lock()
	cl.status = 202
	cl.mu.Unlock()
	a.Flush(ctx)
	if p, _, _ := a.Q.Counts(ctx); p != 0 {
		t.Fatalf("pending after recovery=%d", p)
	}
	if len(cl.received) != 3 || cl.received[0] != `{"n":1}` || cl.received[2] != `{"n":3}` {
		t.Fatalf("order broken: %v", cl.received)
	}
}

func TestPermanentRejectionIsDeadLetteredAndDoesNotBlockQueue(t *testing.T) {
	ctx := context.Background()
	cl := &cloud{status: 422}
	a := setup(t, cl, fixedCollector{[]string{`{"bad":1}`}})
	_ = a.CollectOnce(ctx)
	a.Flush(ctx)
	p, d, _ := a.Q.Counts(ctx)
	if p != 0 || d != 1 {
		t.Fatalf("pending=%d dead=%d", p, d)
	}
}

func TestFailingCollectorDoesNotStopOthers(t *testing.T) {
	ctx := context.Background()
	cl := &cloud{status: 202}
	a := setup(t, cl, failingCollector{}, fixedCollector{[]string{`{"ok":1}`}})
	if err := a.CollectOnce(ctx); err == nil {
		t.Fatal("round with a failing collector must be reported incomplete")
	}
	a.Flush(ctx)
	if len(cl.received) != 1 {
		t.Fatalf("received=%v", cl.received)
	}
}

func TestEnqueueFailureMarksRoundIncomplete(t *testing.T) {
	cl := &cloud{status: 202}
	a := setup(t, cl, fixedCollector{[]string{`{"n":1}`}})
	a.Q.Close() // simulate disk/SQLite failure
	if err := a.CollectOnce(context.Background()); err == nil {
		t.Fatal("persistence failure must surface as an incomplete round")
	}
}
