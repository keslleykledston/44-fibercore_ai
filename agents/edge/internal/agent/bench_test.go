package agent

import (
	"context"
	"crypto/ed25519"
	"crypto/rand"
	"encoding/base64"
	"encoding/json"
	"io"
	"log/slog"
	"net/http"
	"net/http/httptest"
	"path/filepath"
	"strings"
	"sync"
	"testing"
	"time"

	"github.com/keslleykledston/44-fibercore_ai/agents/edge/internal/bench"
	"github.com/keslleykledston/44-fibercore_ai/agents/edge/internal/gateway"
	"github.com/keslleykledston/44-fibercore_ai/agents/edge/internal/jobs"
	"github.com/keslleykledston/44-fibercore_ai/agents/edge/internal/nbi"
	"github.com/keslleykledston/44-fibercore_ai/agents/edge/internal/queue"
)

const (
	bTenant = "22222222-2222-4222-8222-222222222222"
	bEdge   = "33333333-3333-4333-8333-333333333333"
	bRef    = "00259E-EG8145V5-48575443E2247AA5"
	bProd   = "00259E-EG8145V5-48575443AAAAAAAA"
	bAuth   = "55555555-5555-4555-8555-555555555555"
)

var bNow = time.Date(2026, 10, 30, 12, 0, 0, 0, time.UTC)

func signed(priv ed25519.PrivateKey, m map[string]any) []byte {
	raw, _ := json.Marshal(m)
	canon, _ := jobs.Canonical(raw)
	m["signature"] = base64.StdEncoding.EncodeToString(ed25519.Sign(priv, canon))
	out, _ := json.Marshal(m)
	return out
}

func benchEnvelope(priv ed25519.PrivateKey, ref string) []byte {
	return signed(priv, map[string]any{
		"schema_version": "1.0", "job_id": "11111111-1111-4111-8111-111111111111", "tenant_id": bTenant, "edge_id": bEdge,
		"target_id": "44444444-4444-4444-8444-444444444444", "target_ref": ref, "operation": "reboot_cpe", "idempotency_key": "bench-key-0001",
		"issued_at": bNow.Format(time.RFC3339), "expires_at": bNow.Add(2 * time.Minute).Format(time.RFC3339),
		"nonce": "abcdef0123456789abcdef0123456789", "intent_sha256": strings.Repeat("a", 64), "policy_version": "p", "approval_ids": []string{"x"},
		"authorization_id": bAuth, "authorization_ends_at": bNow.Add(10 * time.Minute).Format(time.RFC3339), "owner_epoch": 2,
	})
}

func leaseHeader(priv ed25519.PrivateKey, ref string) string {
	return base64.StdEncoding.EncodeToString(signed(priv, map[string]any{
		"schema": "bench-lease/1", "tenant_id": bTenant, "edge_id": bEdge, "issued_at": bNow.Format(time.RFC3339),
		"expires_at": bNow.Add(jobs.LeaseTTL).Format(time.RFC3339), "targets": []any{map[string]any{"target_ref": ref, "owner_epoch": 2}},
	}))
}

type recACS struct {
	mu      sync.Mutex
	reboots []string
	speeds  []nbi.SpeedRequest
}

func (r *recACS) RunBenchSpeed(_ context.Context, d nbi.BenchDevice, req nbi.SpeedRequest, _ time.Time, _, _ time.Duration, _ func() time.Time) (nbi.SpeedOutcome, error) {
	r.mu.Lock()
	defer r.mu.Unlock()
	r.speeds = append(r.speeds, req)
	n := int64(10_000_000)
	return nbi.SpeedOutcome{Attempted: true, Counters: &nbi.SpeedCounters{State: "Completed", BOM: "2026-10-30T12:00:01Z", EOM: "2026-10-30T12:00:09Z", TestBytesReceived: &n}}, nil
}

func (r *recACS) SetBenchSSID(context.Context, nbi.BenchDevice, string, func(string) bool, time.Time, string, func() time.Time) (nbi.SSIDOutcome, error) {
	return nbi.SSIDOutcome{}, nil
}
func (r *recACS) BenchIdentity(context.Context, nbi.BenchDevice, time.Time) error { return nil }
func (r *recACS) RebootBench(_ context.Context, d nbi.BenchDevice, _ time.Time, _, _ time.Duration, _ func() time.Time) (nbi.BenchOutcome, error) {
	r.mu.Lock()
	defer r.mu.Unlock()
	r.reboots = append(r.reboots, d.DeviceID)
	return nbi.BenchOutcome{Attempted: true, Accepted: true, PostcheckOK: true}, nil
}

type okG struct{}

func (okG) Reserve(string) error { return nil }

func benchRun(t *testing.T, env []byte, lease string, benchEnabled bool, pub ed25519.PublicKey) (results []string, acs *recACS) {
	var mu sync.Mutex
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		switch {
		case r.URL.Path == "/v1/auth/service-token":
			_ = json.NewEncoder(w).Encode(map[string]string{"access_token": "t"})
		case r.URL.Path == "/v1/edge/jobs/next":
			if lease != "" {
				w.Header().Set(gateway.LeaseHeader, lease)
			}
			_, _ = w.Write(env)
		case strings.HasSuffix(r.URL.Path, "/result"):
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
	q, _ := queue.Open(filepath.Join(t.TempDir(), "q.db"))
	t.Cleanup(func() { q.Close() })
	q.Now = func() time.Time { return bNow }
	acs = &recACS{}
	claims, err := jobs.OpenClaims(filepath.Join(t.TempDir(), "claims.json"))
	if err != nil {
		t.Fatal(err)
	}
	now := func() time.Time { return bNow }
	a := &Agent{EdgeID: bEdge, TenantID: bTenant, Version: "v", GW: gateway.New(srv.URL, "c", "s", srv.Client()), Q: q,
		Jobs: &jobs.Verifier{Pub: pub, EdgeID: bEdge, TenantID: bTenant, Allowed: map[string]bool{"reboot_cpe": true}, BenchEnabled: benchEnabled, Nonces: q, Now: now},
		Log:  slog.New(slog.NewTextHandler(io.Discard, nil))}
	if benchEnabled {
		a.Bench = &bench.Runner{Devices: map[string]nbi.BenchDevice{bRef: {DeviceID: bRef, OUI: "00259E", ProductClass: "EG8145V5", Serial: "48575443E2247AA5"}},
			Lease: &jobs.LeaseHolder{Pub: pub, EdgeID: bEdge, TenantID: bTenant, Now: now}, Claims: claims, Guard: okG{}, ACS: acs, Now: now}
	}
	a.PollJob(context.Background())
	deadline := time.Now().Add(3 * time.Second)
	for time.Now().Before(deadline) {
		mu.Lock()
		n := len(results)
		mu.Unlock()
		if n >= 2 {
			break
		}
		time.Sleep(20 * time.Millisecond)
	}
	mu.Lock()
	defer mu.Unlock()
	return append([]string(nil), results...), acs
}

func TestBenchRebootEndToEnd(t *testing.T) {
	pub, priv, _ := ed25519.GenerateKey(rand.Reader)
	res, acs := benchRun(t, benchEnvelope(priv, bRef), leaseHeader(priv, bRef), true, pub)
	if len(res) != 2 || !strings.Contains(res[1], `"succeeded"`) || !strings.Contains(res[1], `"postcheck_ok":true`) {
		t.Fatalf("%v", res)
	}
	if len(acs.reboots) != 1 || acs.reboots[0] != bRef {
		t.Fatalf("reboots %v", acs.reboots)
	}
}

func TestBenchRefusedWithoutLeaseOrOffTheList(t *testing.T) {
	pub, priv, _ := ed25519.GenerateKey(rand.Reader)
	res, acs := benchRun(t, benchEnvelope(priv, bRef), "", true, pub)
	if len(res) != 2 || !strings.Contains(res[1], `"failed"`) || len(acs.reboots) != 0 {
		t.Fatalf("no lease: %v %v", res, acs.reboots)
	}
	res, acs = benchRun(t, benchEnvelope(priv, bProd), leaseHeader(priv, bProd), true, pub)
	if len(res) != 2 || !strings.Contains(res[1], `"failed"`) || len(acs.reboots) != 0 {
		t.Fatalf("production device: %v %v", res, acs.reboots)
	}
	// a lease signed by someone else is not a lease
	_, other, _ := ed25519.GenerateKey(rand.Reader)
	res, acs = benchRun(t, benchEnvelope(priv, bRef), leaseHeader(other, bRef), true, pub)
	if len(res) != 2 || !strings.Contains(res[1], `"failed"`) || len(acs.reboots) != 0 {
		t.Fatalf("forged lease: %v %v", res, acs.reboots)
	}
}

func TestBenchEnvelopeRejectedWhenBenchDisabledLocally(t *testing.T) {
	pub, priv, _ := ed25519.GenerateKey(rand.Reader)
	res, acs := benchRun(t, benchEnvelope(priv, bRef), leaseHeader(priv, bRef), false, pub)
	if len(res) != 0 || acs != nil && len(acs.reboots) != 0 {
		t.Fatalf("a signed bench envelope must be dropped when the Edge has bench disabled: %v", res)
	}
}
