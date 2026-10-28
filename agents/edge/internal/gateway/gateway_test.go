package gateway

import (
	"context"
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"sync/atomic"
	"testing"
)

func fake(t *testing.T, post func(w http.ResponseWriter, r *http.Request, logins int32)) (*httptest.Server, *int32) {
	var logins int32
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.URL.Path == "/v1/auth/service-token" {
			var b map[string]string
			json.NewDecoder(r.Body).Decode(&b)
			if b["client_id"] != "cid" || b["client_secret"] != "sec" {
				w.WriteHeader(401)
				return
			}
			n := atomic.AddInt32(&logins, 1)
			json.NewEncoder(w).Encode(map[string]string{"access_token": "tok" + string(rune('0'+n))})
			return
		}
		post(w, r, atomic.LoadInt32(&logins))
	}))
	t.Cleanup(srv.Close)
	return srv, &logins
}

func TestDeliverLogsInAndSendsBearer(t *testing.T) {
	srv, _ := fake(t, func(w http.ResponseWriter, r *http.Request, _ int32) {
		if r.Header.Get("Authorization") != "Bearer tok1" || r.URL.Path != "/v1/edge/olt-snapshots" {
			w.WriteHeader(400)
			return
		}
		w.WriteHeader(202)
	})
	c := New(srv.URL, "cid", "sec", srv.Client())
	if o, err := c.Deliver(context.Background(), "olt_snapshot", []byte(`{}`)); o != Delivered {
		t.Fatalf("o=%v err=%v", o, err)
	}
}

func TestExpiredTokenTriggersSingleRelogin(t *testing.T) {
	srv, logins := fake(t, func(w http.ResponseWriter, r *http.Request, _ int32) {
		if r.Header.Get("Authorization") == "Bearer tok1" {
			w.WriteHeader(401) // first token "expired"
			return
		}
		w.WriteHeader(202)
	})
	c := New(srv.URL, "cid", "sec", srv.Client())
	if o, _ := c.Deliver(context.Background(), "cpe_snapshot", []byte(`{}`)); o != Delivered {
		t.Fatalf("o=%v", o)
	}
	if atomic.LoadInt32(logins) != 2 {
		t.Fatalf("logins=%d", *logins)
	}
}

func TestOutcomeClassification(t *testing.T) {
	for status, want := range map[int]Outcome{202: Delivered, 500: Retry, 429: Retry, 408: Retry, 400: Rejected, 403: Rejected, 409: Rejected, 422: Rejected} {
		st := status
		srv, _ := fake(t, func(w http.ResponseWriter, r *http.Request, _ int32) { w.WriteHeader(st) })
		c := New(srv.URL, "cid", "sec", srv.Client())
		if o, _ := c.Deliver(context.Background(), "olt_snapshot", []byte(`{}`)); o != want {
			t.Errorf("status %d: got %v want %v", st, o, want)
		}
	}
}

func TestBadLoginIsRetryAndUnknownKindRejected(t *testing.T) {
	srv, _ := fake(t, func(w http.ResponseWriter, r *http.Request, _ int32) { w.WriteHeader(202) })
	c := New(srv.URL, "cid", "WRONG", srv.Client())
	if o, _ := c.Deliver(context.Background(), "olt_snapshot", []byte(`{}`)); o != Retry {
		t.Fatalf("o=%v", o)
	}
	if o, _ := c.Deliver(context.Background(), "shell_exec", []byte(`{}`)); o != Rejected {
		t.Fatalf("unknown kind must be rejected, got %v", o)
	}
}

func TestHeartbeatPayload(t *testing.T) {
	var got Heartbeat
	srv, _ := fake(t, func(w http.ResponseWriter, r *http.Request, _ int32) {
		json.NewDecoder(r.Body).Decode(&got)
		w.WriteHeader(204)
	})
	c := New(srv.URL, "cid", "sec", srv.Client())
	if o, _ := c.Heartbeat(context.Background(), "e1", "t1", "0.1.0"); o != Delivered || got.EdgeID != "e1" || got.TenantID != "t1" || got.SentAt == "" {
		t.Fatalf("o=%v got=%+v", o, got)
	}
}
