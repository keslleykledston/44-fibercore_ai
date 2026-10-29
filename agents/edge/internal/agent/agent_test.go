package agent

import (
	"context"
	"crypto/ed25519"
	"encoding/base64"
	"encoding/json"
	"errors"
	"io"
	"log/slog"
	"net/http"
	"net/http/httptest"
	"os"
	"path/filepath"
	"strings"
	"sync"
	"testing"
	"time"

	"github.com/keslleykledston/44-fibercore_ai/agents/edge/internal/collector"
	"github.com/keslleykledston/44-fibercore_ai/agents/edge/internal/gateway"
	"github.com/keslleykledston/44-fibercore_ai/agents/edge/internal/jobs"
	"github.com/keslleykledston/44-fibercore_ai/agents/edge/internal/nbi"
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

type slowCollector struct{ release chan struct{} }

func (s slowCollector) Name() string { return "slow" }
func (s slowCollector) Collect(ctx context.Context) ([]collector.Item, error) {
	select {
	case <-s.release:
	case <-ctx.Done():
	}
	return nil, nil
}

func TestHeartbeatContinuesWhileCollectorIsSlow(t *testing.T) {
	var mu sync.Mutex
	hb := 0
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		switch r.URL.Path {
		case "/v1/auth/service-token":
			json.NewEncoder(w).Encode(map[string]string{"access_token": "t"})
		case "/v1/edge/heartbeat":
			mu.Lock()
			hb++
			mu.Unlock()
			w.WriteHeader(204)
		default:
			w.WriteHeader(202)
		}
	}))
	defer srv.Close()
	q, _ := queue.Open(filepath.Join(t.TempDir(), "q.db"))
	defer q.Close()
	release := make(chan struct{})
	a := &Agent{EdgeID: "e", TenantID: "t", Version: "v", GW: gateway.New(srv.URL, "c", "s", srv.Client()), Q: q,
		Collectors: []collector.Collector{slowCollector{release}}, HeartbeatEvery: 50 * time.Millisecond, CollectEvery: time.Hour,
		Log: slog.New(slog.NewTextHandler(io.Discard, nil))}
	ctx, cancel := context.WithCancel(context.Background())
	done := make(chan struct{})
	go func() { a.Run(ctx); close(done) }()
	time.Sleep(400 * time.Millisecond) // collector is blocked the whole time
	mu.Lock()
	got := hb
	mu.Unlock()
	close(release)
	cancel()
	<-done
	if got < 3 {
		t.Fatalf("heartbeats while collector blocked = %d, want >= 3", got)
	}
}

func goldenJobServer(t *testing.T, env []byte) (*httptest.Server, *[]string) {
	var mu sync.Mutex
	var results []string
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		switch {
		case r.URL.Path == "/v1/auth/service-token":
			json.NewEncoder(w).Encode(map[string]string{"access_token": "t"})
		case r.URL.Path == "/v1/edge/jobs/next":
			w.Write(env)
		case len(r.URL.Path) > 20 && r.URL.Path[len(r.URL.Path)-7:] == "/result":
			b, _ := io.ReadAll(r.Body)
			mu.Lock()
			results = append(results, string(b))
			mu.Unlock()
			w.WriteHeader(204)
		default:
			w.WriteHeader(202)
		}
	}))
	t.Cleanup(srv.Close)
	return srv, &results
}

func TestPollJobExecutesVerifiedReadOnlyJobOnceAndRejectsReplayAndForgery(t *testing.T) {
	b, err := os.ReadFile(filepath.Join("..", "..", "..", "..", "tests", "fixtures", "edge", "job_envelope_signed.golden.json"))
	if err != nil {
		t.Fatal(err)
	}
	var g struct {
		PublicKey string         `json:"public_key_b64"`
		Envelope  map[string]any `json:"envelope"`
	}
	_ = json.Unmarshal(b, &g)
	pub, _ := jobs.ParsePublicKey(g.PublicKey)
	envBytes, _ := json.Marshal(g.Envelope)
	srv, results := goldenJobServer(t, envBytes)
	q, _ := queue.Open(filepath.Join(t.TempDir(), "q.db"))
	defer q.Close()
	// the golden envelope is valid only around 2026-10-28T10:00Z: the nonce store must use the same fixed clock as the verifier,
	// otherwise real time prunes the nonce as expired and the replay is (wrongly) allowed once the wall clock passes the fixture
	q.Now = func() time.Time { return time.Date(2026, 10, 28, 10, 5, 0, 0, time.UTC) }
	a := &Agent{EdgeID: "33333333-3333-4333-8333-333333333333", TenantID: "22222222-2222-4222-8222-222222222222", Version: "v",
		GW: gateway.New(srv.URL, "c", "s", srv.Client()), Q: q,
		Collectors: []collector.Collector{fixedCollector{[]string{`{"n":1}`}}},
		Jobs: &jobs.Verifier{Pub: pub, EdgeID: "33333333-3333-4333-8333-333333333333", TenantID: "22222222-2222-4222-8222-222222222222",
			Allowed: map[string]bool{"collect": true}, Nonces: q, Now: func() time.Time { return time.Date(2026, 10, 28, 10, 5, 0, 0, time.UTC) }},
		Log: slog.New(slog.NewTextHandler(io.Discard, nil))}
	ctx := context.Background()
	a.PollJob(ctx)
	if len(*results) != 2 || !strings.Contains((*results)[0], `"accepted"`) || !strings.Contains((*results)[1], `"succeeded"`) || !strings.Contains((*results)[1], `"postcheck_ok":true`) {
		t.Fatalf("results=%v", *results)
	}
	a.PollJob(ctx) // same envelope again => replay => no execution, no report
	if len(*results) != 2 {
		t.Fatalf("replay executed: %v", *results)
	}
	// forged operation: signature no longer matches => dropped silently (no report, no collection)
	g.Envelope["operation"] = "reboot_cpe"
	g.Envelope["nonce"] = "ffffffffffffffffffffffffffffffff"
	forged, _ := json.Marshal(g.Envelope)
	srv2, results2 := goldenJobServer(t, forged)
	a.GW = gateway.New(srv2.URL, "c", "s", srv2.Client())
	a.PollJob(ctx)
	if len(*results2) != 0 {
		t.Fatalf("forged job produced reports: %v", *results2)
	}
}

func TestJobResultSurvivesCloudOutageAndIsRetried(t *testing.T) {
	b, _ := os.ReadFile(filepath.Join("..", "..", "..", "..", "tests", "fixtures", "edge", "job_envelope_signed.golden.json"))
	var g struct {
		PublicKey string         `json:"public_key_b64"`
		Envelope  map[string]any `json:"envelope"`
	}
	_ = json.Unmarshal(b, &g)
	pub, _ := jobs.ParsePublicKey(g.PublicKey)
	envBytes, _ := json.Marshal(g.Envelope)
	var mu sync.Mutex
	down := true
	var results []string
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		mu.Lock()
		defer mu.Unlock()
		switch {
		case r.URL.Path == "/v1/auth/service-token":
			json.NewEncoder(w).Encode(map[string]string{"access_token": "t"})
		case r.URL.Path == "/v1/edge/jobs/next":
			w.Write(envBytes)
		case strings.HasSuffix(r.URL.Path, "/result"):
			if down {
				w.WriteHeader(503)
				return
			}
			bb, _ := io.ReadAll(r.Body)
			results = append(results, string(bb))
			w.WriteHeader(204)
		default:
			w.WriteHeader(202)
		}
	}))
	defer srv.Close()
	q, _ := queue.Open(filepath.Join(t.TempDir(), "q.db"))
	defer q.Close()
	a := &Agent{EdgeID: "33333333-3333-4333-8333-333333333333", TenantID: "22222222-2222-4222-8222-222222222222", Version: "v",
		GW: gateway.New(srv.URL, "c", "s", srv.Client()), Q: q, Collectors: []collector.Collector{fixedCollector{[]string{`{"n":1}`}}},
		Jobs: &jobs.Verifier{Pub: pub, EdgeID: "33333333-3333-4333-8333-333333333333", TenantID: "22222222-2222-4222-8222-222222222222",
			Allowed: map[string]bool{"collect": true}, Nonces: q, Now: func() time.Time { return time.Date(2026, 10, 28, 10, 5, 0, 0, time.UTC) }},
		Log: slog.New(slog.NewTextHandler(io.Discard, nil))}
	ctx := context.Background()
	a.PollJob(ctx) // Cloud rejects result reports (503): outcome must stay queued, not vanish
	if p, d, _ := q.Counts(ctx); p == 0 || d != 0 {
		t.Fatalf("results must remain queued: pending=%d dead=%d", p, d)
	}
	mu.Lock()
	down = false
	mu.Unlock()
	a.Flush(ctx)
	mu.Lock()
	defer mu.Unlock()
	if len(results) != 2 || !strings.Contains(results[0], "accepted") || !strings.Contains(results[1], "state") {
		t.Fatalf("results after recovery=%v", results)
	}
}

type countingCollector struct{ runs *int }

func (c countingCollector) Name() string { return "counting" }
func (c countingCollector) Collect(context.Context) ([]collector.Item, error) {
	*c.runs++
	return []collector.Item{{Kind: "cpe_snapshot", Payload: []byte(`{"n":1}`)}}, nil
}

func signRefresh(t *testing.T, priv ed25519.PrivateKey, ref string) []byte {
	t.Helper()
	m := map[string]any{
		"schema_version": "1.0", "job_id": "11111111-1111-4111-8111-111111111111", "tenant_id": "22222222-2222-4222-8222-222222222222",
		"edge_id": "33333333-3333-4333-8333-333333333333", "target_id": "44444444-4444-4444-8444-444444444444", "operation": "refresh",
		"idempotency_key": "refresh-key-0001", "issued_at": "2026-10-28T10:00:00+00:00", "expires_at": "2026-10-28T10:15:00+00:00",
		"nonce": "abcdef0123456789abcdef0123456789", "intent_sha256": strings.Repeat("a", 64), "policy_version": "p", "approval_ids": []string{},
	}
	if ref != "" {
		m["target_ref"] = ref
	}
	raw, _ := json.Marshal(m)
	canon, err := jobs.Canonical(raw)
	if err != nil {
		t.Fatal(err)
	}
	m["signature"] = base64.StdEncoding.EncodeToString(ed25519.Sign(priv, canon))
	out, _ := json.Marshal(m)
	return out
}

func TestRefreshJobThatNamesADeviceRunsTheRefresherFirstAndFailsClosed(t *testing.T) {
	pub, priv, _ := ed25519.GenerateKey(nil)
	now := time.Date(2026, 10, 28, 10, 5, 0, 0, time.UTC)
	type outcome struct {
		results  []string
		runs     int
		refreshs []string
	}
	run := func(ref string, rf RefreshFunc) outcome {
		srv, results := goldenJobServer(t, signRefresh(t, priv, ref))
		q, _ := queue.Open(filepath.Join(t.TempDir(), "q.db"))
		defer q.Close()
		q.Now = func() time.Time { return now }
		var o outcome
		a := &Agent{EdgeID: "33333333-3333-4333-8333-333333333333", TenantID: "22222222-2222-4222-8222-222222222222", Version: "v",
			GW: gateway.New(srv.URL, "c", "s", srv.Client()), Q: q, Collectors: []collector.Collector{countingCollector{&o.runs}},
			Jobs: &jobs.Verifier{Pub: pub, EdgeID: "33333333-3333-4333-8333-333333333333", TenantID: "22222222-2222-4222-8222-222222222222",
				Allowed: map[string]bool{"refresh": true}, Nonces: q, Now: func() time.Time { return now }},
			Log: slog.New(slog.NewTextHandler(io.Discard, nil))}
		if rf != nil {
			a.Refresher = func(ctx context.Context, r string) (string, error) {
				o.refreshs = append(o.refreshs, r)
				return rf(ctx, r)
			}
		}
		a.PollJob(context.Background())
		o.results = *results
		return o
	}
	// success: the refresher gets the signed ref, then the round runs, and the detail (counts only) is reported
	o := run("AAAA00-ONT-SN1", func(context.Context, string) (string, error) { return "acs refresh: groups=5 completed=5", nil })
	if len(o.refreshs) != 1 || o.refreshs[0] != "AAAA00-ONT-SN1" || o.runs != 1 || len(o.results) != 2 ||
		!strings.Contains(o.results[1], `"succeeded"`) || !strings.Contains(o.results[1], "groups=5") {
		t.Fatalf("%+v", o)
	}
	// refresher error: no collection, failed with a category and NOTHING of the raw error or the device id
	o = run("AAAA00-ONT-SN1", func(context.Context, string) (string, error) {
		return "", errors.New("dial tcp 10.1.2.3:7557: secret-token AAAA00-ONT-SN1")
	})
	if o.runs != 0 || len(o.results) != 2 || !strings.Contains(o.results[1], `"failed"`) ||
		strings.Contains(o.results[1], "10.1.2.3") || strings.Contains(o.results[1], "secret-token") || strings.Contains(o.results[1], "AAAA00") {
		t.Fatalf("%+v", o)
	}
	o = run("AAAA00-ONT-SN1", func(context.Context, string) (string, error) { return "", nbi.ErrRefreshTooSoon })
	if o.runs != 0 || !strings.Contains(o.results[1], "refreshed too recently") {
		t.Fatalf("%+v", o)
	}
	o = run("AAAA00-ONT-SN1", func(context.Context, string) (string, error) { return "", nbi.ErrRefreshUncleaned })
	if o.runs != 0 || !strings.Contains(o.results[1], `"failed"`) || !strings.Contains(o.results[1], "operator check required") {
		t.Fatalf("an unclean refresh must fail the job and say an operator must check: %+v", o)
	}
	// feature off: a refresh that names a device fails closed, never degrades into a plain collection
	o = run("AAAA00-ONT-SN1", nil)
	if o.runs != 0 || len(o.results) != 2 || !strings.Contains(o.results[1], `"failed"`) || !strings.Contains(o.results[1], "not enabled") {
		t.Fatalf("%+v", o)
	}
	// legacy refresh (no ref) keeps behaving as a plain collection and never calls the refresher
	o = run("", func(context.Context, string) (string, error) {
		t.Fatal("refresher must not run without a ref")
		return "", nil
	})
	if o.runs != 1 || len(o.refreshs) != 0 || !strings.Contains(o.results[1], `"succeeded"`) {
		t.Fatalf("%+v", o)
	}
}
