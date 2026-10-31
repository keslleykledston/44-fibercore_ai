package main

import (
	"bytes"
	"io"
	"net/http"
	"net/http/httptest"
	"net/netip"
	"strings"
	"testing"
)

func testNode(t *testing.T, conc int) *node {
	t.Helper()
	n, err := newNode([]netip.Prefix{netip.MustParsePrefix("10.20.0.0/16")}, conc)
	if err != nil {
		t.Fatal(err)
	}
	return n
}

func do(n *node, method, target, remote string, body io.Reader) *httptest.ResponseRecorder {
	req := httptest.NewRequest(method, target, body)
	req.RemoteAddr = remote
	rr := httptest.NewRecorder()
	n.ServeHTTP(rr, req)
	return rr
}

const okRemote = "10.20.1.2:40000"

func TestHealthExactBody(t *testing.T) {
	rr := do(testNode(t, 2), "GET", "/health", okRemote, nil)
	if rr.Code != 200 || rr.Body.String() != "ok" || rr.Header().Get("Content-Length") != "2" {
		t.Fatalf("health: %d %q", rr.Code, rr.Body.String())
	}
	if rr := do(testNode(t, 2), "POST", "/health", okRemote, nil); rr.Code != 405 {
		t.Fatalf("health POST: %d", rr.Code)
	}
}

func TestDownloadExactBytesAndHeaders(t *testing.T) {
	rr := do(testNode(t, 2), "GET", "/dl/10mb", okRemote, nil)
	if rr.Code != 200 || int64(rr.Body.Len()) != 10_000_000 || rr.Header().Get("Content-Length") != "10000000" {
		t.Fatalf("dl: %d len=%d cl=%q", rr.Code, rr.Body.Len(), rr.Header().Get("Content-Length"))
	}
	if rr.Header().Get("Content-Encoding") != "" || !strings.Contains(rr.Header().Get("Cache-Control"), "no-store") {
		t.Fatalf("dl headers: %v", rr.Header())
	}
	// Not a run of identical bytes: an in-path compressor must not be able to shrink it.
	if bytes.Count(rr.Body.Bytes()[:chunkSize], []byte{rr.Body.Bytes()[0]}) > chunkSize/2 {
		t.Fatal("download body is not incompressible-looking")
	}
}

func TestUploadDiscardsAndEnforcesProfile(t *testing.T) {
	n := testNode(t, 2)
	orig := profileBytes["10mb"]
	profileBytes["10mb"] = 1000
	defer func() { profileBytes["10mb"] = orig }()
	if rr := do(n, "PUT", "/ul/10mb", okRemote, bytes.NewReader(make([]byte, 1000))); rr.Code != 200 || rr.Body.Len() != 0 {
		t.Fatalf("ul exact: %d", rr.Code)
	}
	if rr := do(n, "PUT", "/ul/10mb", okRemote, bytes.NewReader(make([]byte, 1001))); rr.Code != 413 {
		t.Fatalf("ul declared over: %d", rr.Code)
	}
	// Undeclared length (chunked) over the profile: still refused.
	req := httptest.NewRequest("PUT", "/ul/10mb", io.MultiReader(bytes.NewReader(make([]byte, 600)), bytes.NewReader(make([]byte, 600))))
	req.ContentLength = -1
	req.RemoteAddr = okRemote
	rr := httptest.NewRecorder()
	n.ServeHTTP(rr, req)
	if rr.Code != 413 {
		t.Fatalf("ul undeclared over: %d", rr.Code)
	}
	if rr := do(n, "POST", "/ul/10mb", okRemote, bytes.NewReader(nil)); rr.Code != 405 {
		t.Fatalf("ul POST: %d", rr.Code)
	}
	if rr := do(n, "GET", "/ul/10mb", okRemote, nil); rr.Code != 405 {
		t.Fatalf("ul GET: %d", rr.Code)
	}
}

func TestProfilesOutsideTheListAre404(t *testing.T) {
	n := testNode(t, 2)
	for _, p := range []string{"/dl/1mb", "/dl/10MB", "/dl/", "/dl/10mb.bin", "/ul/500mb", "/ul/", "/download/10MiB.bin", "/healthz", "/", "/dl"} {
		if rr := do(n, "GET", p, okRemote, nil); rr.Code != 404 {
			t.Fatalf("%s: %d", p, rr.Code)
		}
	}
}

func TestNeverRedirects(t *testing.T) {
	n := testNode(t, 2)
	for _, p := range []string{"//dl/10mb", "/dl//10mb", "/dl/./10mb", "/dl/../health", "/dl/10mb/", "/health/", "/%2e%2e/health", "/ul/10mb/..", "//health"} {
		for _, m := range []string{"GET", "PUT", "HEAD", "POST", "DELETE", "OPTIONS"} {
			rr := do(n, m, p, okRemote, bytes.NewReader(nil))
			if rr.Code >= 300 && rr.Code < 400 {
				t.Fatalf("%s %s redirected: %d", m, p, rr.Code)
			}
			if rr.Header().Get("Location") != "" {
				t.Fatalf("%s %s sent a Location header", m, p)
			}
		}
	}
}

func TestSourceAllowList(t *testing.T) {
	n := testNode(t, 2)
	for _, remote := range []string{"192.0.2.9:1", "10.21.0.1:1", "[2001:db8::1]:1", "garbage", ""} {
		for _, p := range []string{"/health", "/dl/10mb", "/ul/10mb"} {
			if rr := do(n, "GET", p, remote, nil); rr.Code != 403 {
				t.Fatalf("%s from %q: %d", p, remote, rr.Code)
			}
		}
	}
	if rr := do(n, "GET", "/health", "[::ffff:10.20.3.4]:5", nil); rr.Code != 200 {
		t.Fatalf("v4-mapped source inside the prefix: %d", rr.Code)
	}
}

func TestConcurrencyLimitAndHealthStaysUp(t *testing.T) {
	n := testNode(t, 1)
	n.sem <- struct{}{} // one transfer in flight
	if rr := do(n, "GET", "/dl/10mb", okRemote, nil); rr.Code != 429 || rr.Header().Get("Retry-After") == "" {
		t.Fatalf("second transfer: %d", rr.Code)
	}
	if rr := do(n, "PUT", "/ul/10mb", okRemote, bytes.NewReader(nil)); rr.Code != 429 {
		t.Fatalf("second upload: %d", rr.Code)
	}
	if rr := do(n, "GET", "/health", okRemote, nil); rr.Code != 200 {
		t.Fatalf("health must not be blocked by a running transfer: %d", rr.Code)
	}
	<-n.sem
	if rr := do(n, "GET", "/dl/10mb", okRemote, nil); rr.Code != 200 {
		t.Fatalf("slot released: %d", rr.Code)
	}
}

func TestStartupRefusals(t *testing.T) {
	for _, s := range []string{"", "0.0.0.0:8080", "[::]:8080", ":8080", "10.20.0.5", "10.20.0.5:0", "localhost:80"} {
		if _, err := ParseListen(s); err == nil {
			t.Fatalf("listen %q should be refused", s)
		}
	}
	if a, err := ParseListen("10.20.0.5:8080"); err != nil || a != "10.20.0.5:8080" {
		t.Fatalf("listen ok: %v %v", a, err)
	}
	for _, s := range []string{"", ",", "0.0.0.0/0", "::/0", "10.0.0.0/7", "10.20.1.2/16", "2001:db8::/16", "nonsense"} {
		if _, err := ParseAllow(s); err == nil {
			t.Fatalf("allow %q should be refused", s)
		}
	}
	if p, err := ParseAllow("10.20.0.0/16, 192.0.2.7/32"); err != nil || len(p) != 2 {
		t.Fatalf("allow ok: %v %v", p, err)
	}
	if _, err := newNode(nil, 2); err == nil {
		t.Fatal("empty allow-list must be refused")
	}
	for _, c := range []int{0, 9, -1} {
		if _, err := newNode([]netip.Prefix{netip.MustParsePrefix("10.20.0.0/16")}, c); err == nil {
			t.Fatalf("max concurrent %d should be refused", c)
		}
	}
}

// A real listener round trip, so a regression in how net/http frames the response (e.g. a redirect or a chunked download) shows up.
func TestOverARealSocket(t *testing.T) {
	n, err := newNode([]netip.Prefix{netip.MustParsePrefix("127.0.0.0/8")}, 2)
	if err != nil {
		t.Fatal(err)
	}
	ts := httptest.NewServer(n)
	defer ts.Close()
	cl := &http.Client{CheckRedirect: func(*http.Request, []*http.Request) error { return http.ErrUseLastResponse }}
	resp, err := cl.Get(ts.URL + "/dl/10mb")
	if err != nil {
		t.Fatal(err)
	}
	defer resp.Body.Close()
	got, _ := io.Copy(io.Discard, resp.Body)
	if resp.StatusCode != 200 || got != 10_000_000 || resp.ContentLength != 10_000_000 || len(resp.TransferEncoding) != 0 {
		t.Fatalf("socket dl: %d got=%d cl=%d te=%v", resp.StatusCode, got, resp.ContentLength, resp.TransferEncoding)
	}
}
