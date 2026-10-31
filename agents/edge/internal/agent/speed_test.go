package agent

import (
	"context"
	"crypto/ed25519"
	"crypto/rand"
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
	"github.com/keslleykledston/44-fibercore_ai/agents/edge/internal/speed"
)

func speedEnvelopeBytes(priv ed25519.PrivateKey, params map[string]any, op string) []byte {
	const targetID = "44444444-4444-4444-8444-444444444444"
	h, _ := jobs.IntentHash(op, "cpe", targetID, jobs.Params(params))
	return signed(priv, map[string]any{
		"schema_version": "1.0", "job_id": "11111111-1111-4111-8111-111111111111", "tenant_id": bTenant, "edge_id": bEdge,
		"target_id": targetID, "target_ref": bRef, "operation": op, "idempotency_key": "speed-key-0001",
		"issued_at": bNow.Format(time.RFC3339), "expires_at": bNow.Add(2 * time.Minute).Format(time.RFC3339),
		"nonce": "abcdef0123456789abcdef0123456789", "intent_sha256": h, "policy_version": "p", "approval_ids": []string{"x"},
		"authorization_id": bAuth, "authorization_ends_at": bNow.Add(10 * time.Minute).Format(time.RFC3339), "owner_epoch": 2,
		"params": params,
	})
}

func speedAgentRun(t *testing.T, env []byte, lease string, pub ed25519.PublicKey, withSpeed bool) (results []string, acs *recACS) {
	var mu sync.Mutex
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		switch {
		case r.URL.Path == "/v1/auth/service-token":
			_ = json.NewEncoder(w).Encode(map[string]string{"access_token": "t"})
		case r.URL.Path == "/v1/edge/jobs/next":
			w.Header().Set(gateway.LeaseHeader, lease)
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
	cat, err := speed.New(speed.Config{Enabled: true, CoreCIDRs: []string{"10.20.0.0/16"}, Endpoints: []speed.EndpointConfig{{ID: "core-sp-1", Kind: "CORE", Host: "10.20.5.9", Port: 8080}}})
	if err != nil {
		t.Fatal(err)
	}
	v := &jobs.Verifier{Pub: pub, EdgeID: bEdge, TenantID: bTenant, Allowed: map[string]bool{"speed_test_download": true, "speed_test_upload": true}, BenchEnabled: true, Nonces: q, Now: now}
	if withSpeed {
		v.SpeedEnabled, v.SpeedCheck = true, cat.Check
	}
	a := &Agent{EdgeID: bEdge, TenantID: bTenant, Version: "v", GW: gateway.New(srv.URL, "c", "s", srv.Client()), Q: q, Jobs: v, Log: slog.New(slog.NewTextHandler(io.Discard, nil))}
	a.Bench = &bench.Runner{Devices: map[string]nbi.BenchDevice{bRef: {DeviceID: bRef, OUI: "00259E", ProductClass: "EG8145V5", Serial: "48575443E2247AA5"}},
		Lease: &jobs.LeaseHolder{Pub: pub, EdgeID: bEdge, TenantID: bTenant, Now: now}, Claims: claims, Guard: okG{}, ACS: acs, Now: now,
		Speed: cat, WANInterface: map[string]string{bRef: "Device.IP.Interface.1"}}
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

func TestSpeedTestEndToEndDeliversTheClosedReport(t *testing.T) {
	pub, priv, _ := ed25519.GenerateKey(rand.Reader)
	env := speedEnvelopeBytes(priv, map[string]any{"target": "core-sp-1", "profile": "10mb"}, "speed_test_download")
	res, acs := speedAgentRun(t, env, leaseHeader(priv, bRef), pub, true)
	if len(res) != 2 {
		t.Fatalf("%v", res)
	}
	var got struct {
		State       string         `json:"state"`
		Detail      string         `json:"detail"`
		PostcheckOK bool           `json:"postcheck_ok"`
		Data        map[string]any `json:"data"`
	}
	if err := json.Unmarshal([]byte(res[1]), &got); err != nil {
		t.Fatal(err)
	}
	if got.State != "succeeded" || !got.PostcheckOK || got.Detail != "speed_done" || got.Data["direction"] != "download" || got.Data["target"] != "core-sp-1" ||
		got.Data["profile"] != "10mb" || got.Data["state"] != "Completed" || got.Data["test_bytes_received"] != float64(10_000_000) {
		t.Fatalf("%s", res[1])
	}
	if len(acs.speeds) != 1 || acs.speeds[0].URL != "http://10.20.5.9:8080/dl/10mb" || acs.speeds[0].Interface != "Device.IP.Interface.1" {
		t.Fatalf("%+v", acs.speeds)
	}
	if strings.Contains(res[1], "10.20.5.9") || strings.Contains(res[1], "http://") {
		t.Fatalf("an address must never travel to the Cloud: %s", res[1])
	}
}

func TestSpeedEnvelopeIsDroppedWhenTheLocalSectionIsOffOrTheNamesAreUnknown(t *testing.T) {
	pub, priv, _ := ed25519.GenerateKey(rand.Reader)
	good := speedEnvelopeBytes(priv, map[string]any{"target": "core-sp-1", "profile": "10mb"}, "speed_test_download")
	if res, acs := speedAgentRun(t, good, leaseHeader(priv, bRef), pub, false); len(res) != 0 || len(acs.speeds) != 0 {
		t.Fatalf("speed off locally: %v %v", res, acs.speeds)
	}
	for name, params := range map[string]map[string]any{
		"unknown endpoint": {"target": "other-node", "profile": "10mb"},
		"unknown profile":  {"target": "core-sp-1", "profile": "1gb"},
		"a url":            {"target": "http://10.0.0.1/f", "profile": "10mb"},
	} {
		env := speedEnvelopeBytes(priv, params, "speed_test_download")
		if res, acs := speedAgentRun(t, env, leaseHeader(priv, bRef), pub, true); len(res) != 0 || len(acs.speeds) != 0 {
			t.Errorf("%s: %v %v", name, res, acs.speeds)
		}
	}
}
