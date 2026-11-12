package agent

import (
	"context"
	"encoding/json"
	"log/slog"
	"net/http"
	"net/http/httptest"
	"path/filepath"
	"strings"
	"sync"
	"testing"

	"github.com/keslleykledston/44-fibercore_ai/agents/edge/internal/collector"
	"github.com/keslleykledston/44-fibercore_ai/agents/edge/internal/gateway"
	"github.com/keslleykledston/44-fibercore_ai/agents/edge/internal/queue"
)

type acsCollector struct{}

func (acsCollector) Name() string { return "acs" }
func (acsCollector) Collect(context.Context) ([]collector.Item, error) {
	return []collector.Item{{Kind: "acs_status", Key: "acs_status:x", Payload: []byte(`{"acs_id":"x"}`)}}, nil
}

// ADR-0046 D2: a Cloud that answers 404 to acs-status (older Cloud, feature off, id not registered) is not an error of the Edge: the item is dropped, never dead-lettered or retried, the rest of the
// queue keeps flowing, and the explanation is logged ONCE however many rounds meet it.
func TestACSStatusNotKnownToTheCloudIsDroppedAndLoggedOnce(t *testing.T) {
	ctx := context.Background()
	var mu sync.Mutex
	var paths []string
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.URL.Path == "/v1/auth/service-token" {
			json.NewEncoder(w).Encode(map[string]string{"access_token": "t"})
			return
		}
		mu.Lock()
		paths = append(paths, r.URL.Path)
		mu.Unlock()
		if r.URL.Path == "/v1/edge/acs-status" {
			w.WriteHeader(404)
			return
		}
		w.WriteHeader(202)
	}))
	defer srv.Close()
	q, _ := queue.Open(filepath.Join(t.TempDir(), "q.db"))
	defer q.Close()
	var logs strings.Builder
	a := &Agent{EdgeID: "e", TenantID: "t", Version: "v", GW: gateway.New(srv.URL, "c", "s", srv.Client()), Q: q,
		Collectors: []collector.Collector{acsCollector{}, fixedCollector{[]string{`{"n":1}`}}}, Log: slog.New(slog.NewTextHandler(&logs, nil))}
	for round := 0; round < 3; round++ {
		if err := a.CollectOnce(ctx); err != nil {
			t.Fatal(err)
		}
		a.Flush(ctx)
	}
	if p, d, _ := q.Counts(ctx); p != 0 || d != 0 {
		t.Fatalf("pending=%d dead=%d: a 404 on acs-status is dropped, not kept and not dead-lettered", p, d)
	}
	mu.Lock()
	defer mu.Unlock()
	acs, snaps := 0, 0
	for _, p := range paths {
		if p == "/v1/edge/acs-status" {
			acs++
		} else if p == "/v1/edge/cpe-snapshots" {
			snaps++
		}
	}
	if acs != 3 || snaps != 3 {
		t.Fatalf("acs=%d snapshots=%d: the other items keep flowing and nothing is retried", acs, snaps)
	}
	if n := strings.Count(logs.String(), "does not know this ACS report"); n != 1 {
		t.Fatalf("the explanation must be logged exactly once, got %d:\n%s", n, logs.String())
	}
	if strings.Contains(logs.String(), "level=ERROR") {
		t.Fatalf("not an error:\n%s", logs.String())
	}
}

// 5xx and 429 on acs-status are transient: the item stays (order kept), is retried, and is NOT counted as unknown.
func TestACSStatusTransientFailuresKeepTheItem(t *testing.T) {
	ctx := context.Background()
	for _, status := range []int{500, 503, 429} {
		cl := &cloud{status: status}
		a := setup(t, cl, acsCollector{})
		_ = a.CollectOnce(ctx)
		a.Flush(ctx)
		if p, d, _ := a.Q.Counts(ctx); p != 1 || d != 0 {
			t.Fatalf("status %d: pending=%d dead=%d, want the item kept", status, p, d)
		}
		if a.acsUnknownLogged.Load() {
			t.Fatalf("status %d must not be treated as unknown", status)
		}
	}
}
