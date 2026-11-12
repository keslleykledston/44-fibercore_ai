package gateway

import (
	"context"
	"net/http"
	"testing"
)

// ADR-0046 D2: the ACS report goes to its own route; a 404 there (older Cloud, feature off, id not registered) is "Unknown" (drop, never a dead letter),
// while 5xx and 429 stay transient and every other 4xx stays a permanent refusal. A 404 on any other kind keeps meaning "rejected".
func TestACSStatusRouteAndOutcomes(t *testing.T) {
	var path string
	for status, want := range map[int]Outcome{204: Delivered, 404: Unknown, 500: Retry, 503: Retry, 429: Throttled, 422: Rejected, 403: Rejected, 409: Rejected} {
		st := status
		srv, _ := fake(t, func(w http.ResponseWriter, r *http.Request, _ int32) { path = r.URL.Path; w.WriteHeader(st) })
		c := New(srv.URL, "cid", "sec", srv.Client())
		if o, _ := c.Deliver(context.Background(), "acs_status", []byte(`{}`)); o != want {
			t.Errorf("acs_status %d: got %v want %v", st, o, want)
		}
		if path != "/v1/edge/acs-status" {
			t.Errorf("path=%s", path)
		}
	}
	srv, _ := fake(t, func(w http.ResponseWriter, r *http.Request, _ int32) { w.WriteHeader(404) })
	c := New(srv.URL, "cid", "sec", srv.Client())
	for _, kind := range []string{"olt_snapshot", "cpe_snapshot", "cpe_state"} {
		if o, _ := c.Deliver(context.Background(), kind, []byte(`{}`)); o != Rejected {
			t.Errorf("%s 404 must stay Rejected, got %v", kind, o)
		}
	}
}
