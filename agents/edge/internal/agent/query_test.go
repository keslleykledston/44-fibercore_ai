package agent

import (
	"context"
	"crypto/ed25519"
	"crypto/rand"
	"encoding/json"
	"errors"
	"io"
	"log/slog"
	"net/http"
	"net/http/httptest"
	"path/filepath"
	"strings"
	"sync"
	"testing"
	"time"

	"github.com/keslleykledston/44-fibercore_ai/agents/edge/internal/gateway"
	"github.com/keslleykledston/44-fibercore_ai/agents/edge/internal/jobs"
	"github.com/keslleykledston/44-fibercore_ai/agents/edge/internal/olt"
	"github.com/keslleykledston/44-fibercore_ai/agents/edge/internal/oltquery"
	"github.com/keslleykledston/44-fibercore_ai/agents/edge/internal/queue"
)

const qOLTID = "8f14e45f-ceea-467a-9a36-4a1b5c3d2e10"

func queryEnvelope(t *testing.T, priv ed25519.PrivateKey, ref string) []byte {
	t.Helper()
	params := jobs.Params{"query_id": "olt.version", "olt_ref": ref, "catalog_version": olt.CatalogVersion()}
	h, err := jobs.IntentHash("olt_query", "olt", ref, params)
	if err != nil {
		t.Fatal(err)
	}
	return signed(priv, map[string]any{
		"schema_version": "1.0", "job_id": "11111111-1111-4111-8111-111111111111", "tenant_id": bTenant, "edge_id": bEdge,
		"target_id": ref, "operation": "olt_query", "idempotency_key": "query-key-0001",
		"issued_at": bNow.Format(time.RFC3339), "expires_at": bNow.Add(10 * time.Minute).Format(time.RFC3339),
		"nonce": "abcdef0123456789abcdef0123456789", "intent_sha256": h, "policy_version": "p", "approval_ids": []string{},
		"params": map[string]any(params),
	})
}

type qRig struct {
	a       *Agent
	store   *oltquery.Store
	results func() []string
}

func newQRig(t *testing.T, env []byte, pub ed25519.PublicKey, withStore bool) qRig {
	t.Helper()
	var mu sync.Mutex
	var res []string
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		switch {
		case r.URL.Path == "/v1/auth/service-token":
			_ = json.NewEncoder(w).Encode(map[string]string{"access_token": "t"})
		case r.URL.Path == "/v1/edge/jobs/next":
			_, _ = w.Write(env)
		case strings.HasSuffix(r.URL.Path, "/result"):
			b, _ := io.ReadAll(r.Body)
			mu.Lock()
			res = append(res, string(b))
			mu.Unlock()
			w.WriteHeader(204)
		default:
			w.WriteHeader(202)
		}
	}))
	t.Cleanup(srv.Close)
	q, _ := queue.Open(filepath.Join(t.TempDir(), "q.db"))
	t.Cleanup(func() { q.Close() })
	q.Now = func() time.Time { return bNow }
	known := map[string]bool{qOLTID: true}
	v := &jobs.Verifier{Pub: pub, EdgeID: bEdge, TenantID: bTenant, Allowed: map[string]bool{"olt_query": true}, Nonces: q, Now: func() time.Time { return bNow },
		QueryEnabled: true, QueryCheck: func(p map[string]any, target string) error {
			in, err := olt.ParseIntent(p)
			if err != nil {
				return err
			}
			if in.OLTRef != target || !known[in.OLTRef] {
				return errors.New("not an OLT of this edge")
			}
			return nil
		}}
	a := &Agent{EdgeID: bEdge, TenantID: bTenant, Version: "v", GW: gateway.New(srv.URL, "c", "s", srv.Client()), Q: q, Jobs: v,
		Log: slog.New(slog.NewTextHandler(io.Discard, nil))}
	rig := qRig{a: a, results: func() []string { mu.Lock(); defer mu.Unlock(); return append([]string(nil), res...) }}
	if withStore {
		rig.store = &oltquery.Store{Path: filepath.Join(t.TempDir(), "oq.json"), Now: func() time.Time { return bNow }}
		a.Queries = rig.store
	}
	return rig
}

func TestAnApprovedQueryIsQueuedNotRunAndItsTypedResultTravelsLater(t *testing.T) {
	pub, priv, _ := ed25519.GenerateKey(rand.Reader)
	r := newQRig(t, queryEnvelope(t, priv, qOLTID), pub, true)
	r.a.PollJob(context.Background())
	if got := r.results(); len(got) != 1 || !strings.Contains(got[0], `"accepted"`) {
		t.Fatalf("only the acceptance so far: %v", got)
	}
	e, ok, _ := r.store.Get("11111111-1111-4111-8111-111111111111")
	if !ok || e.State != oltquery.Queued || e.Intent.QueryID != "olt.version" || e.Intent.OLTRef != qOLTID {
		t.Fatalf("queued: %+v", e)
	}
	// the collector's session claims and runs it (simulated here), then the agent reports on its next turn
	if _, err := r.store.Claim(qOLTID, "s"); err != nil {
		t.Fatal(err)
	}
	if err := r.store.Complete(e.JobID, json.RawMessage(`{"product":"MA5608T"}`)); err != nil {
		t.Fatal(err)
	}
	r.a.PollJob(context.Background()) // (the replayed envelope is refused by the nonce store: nothing is queued twice)
	got := r.results()
	if len(got) != 2 || !strings.Contains(got[1], `"succeeded"`) || !strings.Contains(got[1], `"postcheck_ok":true`) || !strings.Contains(got[1], `"data":{"product":"MA5608T"}`) {
		t.Fatalf("typed result: %v", got)
	}
	if e, _, _ := r.store.Get(e.JobID); e.State != oltquery.Reported {
		t.Fatalf("%+v", e)
	}
	r.a.PollJob(context.Background())
	if len(r.results()) != 2 {
		t.Fatalf("a reported query is not reported again: %v", r.results())
	}
}

func TestFailedAndUnknownQueriesAreReportedAsSuch(t *testing.T) {
	pub, priv, _ := ed25519.GenerateKey(rand.Reader)
	r := newQRig(t, queryEnvelope(t, priv, qOLTID), pub, true)
	r.a.PollJob(context.Background())
	id := "11111111-1111-4111-8111-111111111111"
	if _, err := r.store.Claim(qOLTID, "s"); err != nil {
		t.Fatal(err)
	}
	if _, _, err := r.store.Recover(); err != nil { // the process died after the claim
		t.Fatal(err)
	}
	r.a.PollJob(context.Background())
	got := r.results()
	if len(got) != 2 || !strings.Contains(got[1], `"postcheck_ok":false`) || !strings.Contains(got[1], "outcome unknown") || strings.Contains(got[1], `"data"`) {
		t.Fatalf("unknown outcome: %v", got)
	}
	_ = id
}

func TestWithoutAQueueTheQueryFailsClosedAndAForeignOLTIsDropped(t *testing.T) {
	pub, priv, _ := ed25519.GenerateKey(rand.Reader)
	r := newQRig(t, queryEnvelope(t, priv, qOLTID), pub, false)
	r.a.PollJob(context.Background())
	if got := r.results(); len(got) != 2 || !strings.Contains(got[1], `"failed"`) {
		t.Fatalf("no queue: %v", got)
	}
	other := "9a14e45f-ceea-467a-9a36-4a1b5c3d2e11"
	r = newQRig(t, queryEnvelope(t, priv, other), pub, true)
	r.a.PollJob(context.Background())
	if got := r.results(); len(got) != 0 {
		t.Fatalf("an OLT that is not this edge's: the envelope is dropped, nothing reported: %v", got)
	}
	if _, ok, _ := r.store.Get("11111111-1111-4111-8111-111111111111"); ok {
		t.Fatal("nothing may be queued")
	}
}

func TestAResultIsReportedOnlyWhenTheCloudAnswersAndIsResentIfItDoesNot(t *testing.T) {
	pub, _, _ := ed25519.GenerateKey(rand.Reader)
	var mu sync.Mutex
	down := true
	var got []string
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		switch {
		case r.URL.Path == "/v1/auth/service-token":
			_ = json.NewEncoder(w).Encode(map[string]string{"access_token": "t"})
		case r.URL.Path == "/v1/edge/jobs/next":
			w.WriteHeader(204)
		case strings.HasSuffix(r.URL.Path, "/result"):
			b, _ := io.ReadAll(r.Body)
			mu.Lock()
			defer mu.Unlock()
			if down {
				w.WriteHeader(503)
				return
			}
			got = append(got, string(b))
			w.WriteHeader(204)
		default:
			w.WriteHeader(202)
		}
	}))
	defer srv.Close()
	q, _ := queue.Open(filepath.Join(t.TempDir(), "q.db"))
	defer q.Close()
	q.Now = func() time.Time { return bNow }
	store := &oltquery.Store{Path: filepath.Join(t.TempDir(), "oq.json")}
	a := &Agent{EdgeID: bEdge, TenantID: bTenant, GW: gateway.New(srv.URL, "c", "s", srv.Client()), Q: q, Queries: store,
		Jobs: &jobs.Verifier{Pub: pub, EdgeID: bEdge, TenantID: bTenant, Allowed: map[string]bool{}, Nonces: q, Now: func() time.Time { return bNow }},
		Log:  slog.New(slog.NewTextHandler(io.Discard, nil))}
	id := "11111111-1111-4111-8111-111111111111"
	if err := store.Enqueue(id, oltquery.Intent{QueryID: "olt.version", OLTRef: qOLTID}, time.Now().Add(time.Hour)); err != nil {
		t.Fatal(err)
	}
	if _, err := store.Claim(qOLTID, "s"); err != nil {
		t.Fatal(err)
	}
	if err := store.Complete(id, json.RawMessage(`{"product":"MA5608T"}`)); err != nil {
		t.Fatal(err)
	}
	a.PollJob(context.Background()) // the Cloud is down: handed to the delivery queue, NOT reported
	if e, _, _ := store.Get(id); e.State != oltquery.Executed {
		t.Fatalf("not acknowledged yet: %+v", e)
	}
	a.PollJob(context.Background()) // still down and still in flight: not handed over twice
	mu.Lock()
	down = false
	mu.Unlock()
	a.Flush(context.Background())
	mu.Lock()
	n := len(got)
	mu.Unlock()
	if n != 1 {
		t.Fatalf("delivered %d times", n)
	}
	if e, _, _ := store.Get(id); e.State != oltquery.Reported {
		t.Fatalf("the Cloud answered: %+v", e)
	}
	// a result whose delivery-queue copy was lost is handed over again after queryResendAfter
	id2 := "22222222-2222-4222-8222-222222222222"
	_ = store.Enqueue(id2, oltquery.Intent{QueryID: "olt.version", OLTRef: qOLTID}, time.Now().Add(time.Hour))
	_, _ = store.Claim(qOLTID, "s2")
	_ = store.Complete(id2, json.RawMessage(`{"product":"MA5608T"}`))
	a.qmu.Lock()
	a.qInflight = map[string]time.Time{id2: time.Now().Add(-queryResendAfter - time.Minute)}
	a.qmu.Unlock()
	a.PollJob(context.Background())
	if e, _, _ := store.Get(id2); e.State != oltquery.Reported {
		t.Fatalf("resent and acknowledged: %+v", e)
	}
}
