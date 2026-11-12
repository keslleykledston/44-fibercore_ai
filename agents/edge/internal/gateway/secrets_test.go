package gateway

import (
	"context"
	"encoding/json"
	"errors"
	"io"
	"net/http"
	"strings"
	"testing"
	"time"
)

const sid = "33333333-3333-4333-8333-333333333333"

func TestPublishSealKey(t *testing.T) {
	var gotBody, gotBackoff string
	srv, _ := fake(t, func(w http.ResponseWriter, r *http.Request, _ int32) {
		b, _ := io.ReadAll(r.Body)
		gotBody, gotBackoff = string(b), r.Header.Get("X-Edge-Backoff")
		if r.URL.Path != "/v1/edge/seal-key" || r.Method != http.MethodPost || r.Header.Get("Authorization") != "Bearer tok1" {
			w.WriteHeader(400)
			return
		}
		w.WriteHeader(204)
	})
	c := New(srv.URL, "cid", "sec", srv.Client())
	if o, st, err := c.PublishSealKey(context.Background(), "PUBKEY"); o != Delivered || st != 204 || err != nil {
		t.Fatalf("%v %d %v", o, st, err)
	}
	if gotBody != `{"public_key":"PUBKEY"}` {
		t.Fatalf("body %s", gotBody)
	}
	if gotBackoff != "" {
		t.Fatal("the intake-budget opt-in header must not be sent on the secrets routes")
	}
}

func TestPublishSealKeyOutcomes(t *testing.T) {
	for status, want := range map[int]Outcome{200: Delivered, 403: Rejected, 409: Rejected, 422: Rejected, 500: Retry, 503: Retry, 408: Retry, 429: Throttled} {
		srv, _ := fake(t, func(w http.ResponseWriter, r *http.Request, _ int32) { w.WriteHeader(status) })
		c := New(srv.URL, "cid", "sec", srv.Client())
		if o, _, _ := c.PublishSealKey(context.Background(), "K"); o != want {
			t.Errorf("%d: got %v want %v", status, o, want)
		}
	}
}

func TestNextSecretDelivery(t *testing.T) {
	srv, _ := fake(t, func(w http.ResponseWriter, r *http.Request, _ int32) {
		if r.URL.Path != "/v1/edge/secret-deliveries/next" || r.Method != http.MethodGet || r.Header.Get("X-Edge-Backoff") != "" {
			w.WriteHeader(400)
			return
		}
		json.NewEncoder(w).Encode(map[string]any{"id": sid, "lease_token": "L", "olt_name": "OLT-1", "kind": "ssh_login", "key_id": "0123456789abcdef", "expires_at": 1893456000, "sealed": "AAAA", "signature": "BBBB", "future_field": 1})
	})
	c := New(srv.URL, "cid", "sec", srv.Client())
	d, err := c.NextSecretDelivery(context.Background())
	if err != nil || d == nil || d.ID != sid || d.LeaseToken != "L" || d.OLTName != "OLT-1" || d.Kind != "ssh_login" || string(d.ExpiresAt) != "1893456000" || d.Sealed != "AAAA" || d.Signature != "BBBB" {
		t.Fatalf("%+v %v", d, err)
	}
}

func TestNextSecretDeliveryStatuses(t *testing.T) {
	status := 204
	var body string
	srv, _ := fake(t, func(w http.ResponseWriter, r *http.Request, _ int32) {
		if status == 429 {
			w.Header().Set("Retry-After", "7")
		}
		w.WriteHeader(status)
		io.WriteString(w, body)
	})
	c := New(srv.URL, "cid", "sec", srv.Client())
	ctx := context.Background()
	if d, err := c.NextSecretDelivery(ctx); d != nil || err != nil {
		t.Fatalf("204: %v %v", d, err)
	}
	for _, st := range []int{500, 502, 503, 404, 403} {
		status = st
		if d, err := c.NextSecretDelivery(ctx); d != nil || err == nil || errors.Is(err, ErrSecretsThrottled) {
			t.Fatalf("%d: %v %v", st, d, err)
		}
	}
	status, body = 200, `{"id":"`+sid+`","olt_name":"SEGREDO`
	if d, err := c.NextSecretDelivery(ctx); d != nil || err == nil || strings.Contains(err.Error(), "SEGREDO") {
		t.Fatalf("malformed body must be a fixed error: %v %v", d, err)
	}
	status, body = 200, `{}`
	if d, err := c.NextSecretDelivery(ctx); d != nil || err == nil {
		t.Fatalf("no id: %v %v", d, err)
	}
	status, body = 200, `{"id":"`+sid+`","pad":"`+strings.Repeat("x", 20<<10)+`"}`
	if d, err := c.NextSecretDelivery(ctx); d != nil || err == nil {
		t.Fatalf("oversized: %v %v", d, err)
	}
	// 429: its own window, bounded; the ingestion window is untouched
	status = 429
	before := time.Now()
	if _, err := c.NextSecretDelivery(ctx); !errors.Is(err, ErrSecretsThrottled) {
		t.Fatalf("%v", err)
	}
	until := c.SecretsWaitUntil()
	if until.Before(before.Add(6*time.Second)) || until.After(before.Add(9*time.Second)) {
		t.Fatalf("wait until %v", until.Sub(before))
	}
	if !c.ThrottledUntil().IsZero() {
		t.Fatal("a 429 of the secrets routes must not hold back the delivery of snapshots")
	}
}

func TestSecretsWaitRespectsBothWindowsAndIsBounded(t *testing.T) {
	c := New("http://x", "a", "b", nil)
	if !c.SecretsWaitUntil().IsZero() {
		t.Fatal("no wait by default")
	}
	c.ThrottleForTest(time.Minute) // the intake budget wait (existing)
	if d := time.Until(c.SecretsWaitUntil()); d < 50*time.Second {
		t.Fatalf("the existing wait must be respected: %v", d)
	}
	c.secretThrottle("999999")
	if d := time.Until(c.SecretsWaitUntil()); d > maxThrottle+time.Second {
		t.Fatalf("bounded: %v", d)
	}
	c.ResetThrottleForTest()
	c.secretThrottle("garbage")
	if d := time.Until(c.SecretsWaitUntil()); d <= 0 || d > 2*time.Second {
		t.Fatalf("garbage Retry-After = the minimum: %v", d)
	}
}

func TestSecretDeliveryResult(t *testing.T) {
	var gotPath, gotBody string
	status := 204
	srv, _ := fake(t, func(w http.ResponseWriter, r *http.Request, _ int32) {
		b, _ := io.ReadAll(r.Body)
		gotPath, gotBody = r.URL.Path, string(b)
		w.WriteHeader(status)
	})
	c := New(srv.URL, "cid", "sec", srv.Client())
	ctx := context.Background()
	if o, _, err := c.SecretDeliveryResult(ctx, sid, "LEASE", "applied", ""); o != Delivered || err != nil {
		t.Fatalf("%v %v", o, err)
	}
	if gotPath != "/v1/edge/secret-deliveries/"+sid+"/result" || gotBody != `{"lease_token":"LEASE","outcome":"applied"}` {
		t.Fatalf("%s %s", gotPath, gotBody)
	}
	if _, _, err := c.SecretDeliveryResult(ctx, sid, "LEASE", "failed", "bad_signature"); err != nil || !strings.Contains(gotBody, `"code":"bad_signature"`) {
		t.Fatalf("%s %v", gotBody, err)
	}
	status = 409
	if o, st, err := c.SecretDeliveryResult(ctx, sid, "OLD", "applied", ""); !errors.Is(err, ErrStaleLease) || st != 409 || o != Rejected {
		t.Fatalf("%v %d %v", o, st, err)
	}
	status = 503
	if o, _, err := c.SecretDeliveryResult(ctx, sid, "L", "applied", ""); o != Retry || err == nil {
		t.Fatalf("%v %v", o, err)
	}
	status = 429
	if o, _, err := c.SecretDeliveryResult(ctx, sid, "L", "applied", ""); o != Throttled || !errors.Is(err, ErrSecretsThrottled) {
		t.Fatalf("%v %v", o, err)
	}
	if _, _, err := c.SecretDeliveryResult(ctx, "../../etc/passwd", "L", "applied", ""); err == nil {
		t.Fatal("a delivery id that is not a UUID must never reach a URL")
	}
}

func TestSecretsRoutesReloginOnceOn401(t *testing.T) {
	srv, logins := fake(t, func(w http.ResponseWriter, r *http.Request, _ int32) {
		if r.Header.Get("Authorization") == "Bearer tok1" {
			w.WriteHeader(401)
			return
		}
		w.WriteHeader(204)
	})
	c := New(srv.URL, "cid", "sec", srv.Client())
	if d, err := c.NextSecretDelivery(context.Background()); d != nil || err != nil {
		t.Fatalf("%v %v", d, err)
	}
	if *logins != 2 {
		t.Fatalf("logins=%d", *logins)
	}
}
