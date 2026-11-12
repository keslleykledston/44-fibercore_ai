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
	"sync/atomic"
	"testing"
	"time"

	"github.com/keslleykledston/44-fibercore_ai/agents/edge/internal/collector"
	"github.com/keslleykledston/44-fibercore_ai/agents/edge/internal/gateway"
	"github.com/keslleykledston/44-fibercore_ai/agents/edge/internal/queue"
)

// blockingSecrets is a delivery loop that hangs (a slow Cloud, a slow disk): it must never hold back heartbeats or collection.
type blockingSecrets struct {
	started atomic.Int32
	release chan struct{}
}

func (b *blockingSecrets) Tick(ctx context.Context) {
	b.started.Add(1)
	select {
	case <-b.release:
	case <-ctx.Done():
	}
}

func TestAHangingSecretsLoopNeverDelaysHeartbeatsOrCollection(t *testing.T) {
	var mu sync.Mutex
	hb, snaps := 0, 0
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		switch r.URL.Path {
		case "/v1/auth/service-token":
			json.NewEncoder(w).Encode(map[string]string{"access_token": "t"})
		case "/v1/edge/heartbeat":
			mu.Lock()
			hb++
			mu.Unlock()
			w.WriteHeader(204)
		case "/v1/edge/cpe-snapshots":
			mu.Lock()
			snaps++
			mu.Unlock()
			w.WriteHeader(202)
		default:
			w.WriteHeader(202)
		}
	}))
	defer srv.Close()
	q, _ := queue.Open(filepath.Join(t.TempDir(), "q.db"))
	defer q.Close()
	sec := &blockingSecrets{release: make(chan struct{})}
	a := &Agent{EdgeID: "e", TenantID: "t", Version: "v", GW: gateway.New(srv.URL, "c", "s", srv.Client()), Q: q,
		Collectors: []collector.Collector{fixedCollector{payloads: []string{`{"a":1}`}}}, HeartbeatEvery: 40 * time.Millisecond, CollectEvery: 60 * time.Millisecond,
		Secrets: sec, SecretsEvery: 30 * time.Millisecond, Log: slog.New(slog.NewTextHandler(io.Discard, nil))}
	ctx, cancel := context.WithCancel(context.Background())
	done := make(chan struct{})
	go func() { a.Run(ctx); close(done) }()
	time.Sleep(500 * time.Millisecond) // the secrets loop is blocked the whole time
	mu.Lock()
	gotHB, gotSnaps := hb, snaps
	mu.Unlock()
	close(sec.release)
	cancel()
	<-done
	if gotHB < 5 || gotSnaps < 3 {
		t.Fatalf("heartbeats=%d snapshots=%d while the secrets loop hung", gotHB, gotSnaps)
	}
	if sec.started.Load() != 1 {
		t.Fatalf("only ONE round of the secrets loop may run at a time, started=%d", sec.started.Load())
	}
}

type countingSecrets struct{ n atomic.Int32 }

func (c *countingSecrets) Tick(context.Context) { c.n.Add(1) }

func TestSecretsLoopRunsAtStartAfterHeartbeatsAndOnItsTimer(t *testing.T) {
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.URL.Path == "/v1/auth/service-token" {
			json.NewEncoder(w).Encode(map[string]string{"access_token": "t"})
			return
		}
		w.WriteHeader(204)
	}))
	defer srv.Close()
	q, _ := queue.Open(filepath.Join(t.TempDir(), "q.db"))
	defer q.Close()
	sec := &countingSecrets{}
	a := &Agent{EdgeID: "e", TenantID: "t", Version: "v", GW: gateway.New(srv.URL, "c", "s", srv.Client()), Q: q, HeartbeatEvery: time.Hour, CollectEvery: time.Hour,
		Secrets: sec, SecretsEvery: 40 * time.Millisecond, Log: slog.New(slog.NewTextHandler(io.Discard, nil))}
	ctx, cancel := context.WithCancel(context.Background())
	done := make(chan struct{})
	go func() { a.Run(ctx); close(done) }()
	time.Sleep(300 * time.Millisecond)
	cancel()
	<-done
	if sec.n.Load() < 4 {
		t.Fatalf("rounds=%d (at start + every 40ms)", sec.n.Load())
	}
}

func TestWithoutASecretsLoopNothingChanges(t *testing.T) {
	cl := &cloud{}
	a := setup(t, cl, fixedCollector{payloads: []string{`{"a":1}`}})
	a.HeartbeatEvery, a.CollectEvery = 30*time.Millisecond, time.Hour
	if a.Secrets != nil {
		t.Fatal("off by default")
	}
	ctx, cancel := context.WithTimeout(context.Background(), 200*time.Millisecond)
	defer cancel()
	a.Run(ctx) // must not panic or block with Secrets == nil
}
