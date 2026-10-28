package allowlist

import (
	"context"
	"errors"
	"net"
	"net/http"
	"net/http/httptest"
	"testing"
	"time"
)

func TestAllowedExactMatchOnly(t *testing.T) {
	l, err := New([]string{"genieacs.lab:7557", "10.0.0.5:7557"})
	if err != nil {
		t.Fatal(err)
	}
	for addr, want := range map[string]bool{
		"genieacs.lab:7557": true, "GENIEACS.LAB:7557": true, "10.0.0.5:7557": true,
		"genieacs.lab:80": false, "evil.example:7557": false, "169.254.169.254:80": false, "10.0.0.5": false,
	} {
		if got := l.Allowed(addr); got != want {
			t.Errorf("Allowed(%q)=%v want %v", addr, got, want)
		}
	}
	if _, err := New([]string{"no-port"}); err == nil {
		t.Error("entry without port must be rejected")
	}
}

func TestDialDeniesUnlistedAndMetadata(t *testing.T) {
	l, _ := New([]string{"127.0.0.1:1"})
	for _, addr := range []string{"169.254.169.254:80", "example.com:443", "127.0.0.1:2"} {
		_, err := l.DialContext(context.Background(), "tcp", addr)
		if !errors.Is(err, ErrDenied) {
			t.Errorf("dial %s: want ErrDenied, got %v", addr, err)
		}
	}
}

func TestRedirectsAreNotFollowedAndOnlyListedHostReached(t *testing.T) {
	hit := false
	other := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) { hit = true }))
	defer other.Close()
	src := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		http.Redirect(w, r, other.URL, http.StatusFound)
	}))
	defer src.Close()
	host := src.Listener.Addr().String()
	l, _ := New([]string{host})
	resp, err := l.HTTPClient(2 * time.Second).Get(src.URL)
	if err != nil {
		t.Fatal(err)
	}
	resp.Body.Close()
	if resp.StatusCode != http.StatusFound || hit {
		t.Fatalf("redirect must not be followed (status=%d, otherHit=%v)", resp.StatusCode, hit)
	}
	// and a direct request to the unlisted server is refused at dial time
	if _, err := l.HTTPClient(2 * time.Second).Get(other.URL); err == nil {
		t.Fatal("unlisted destination must be denied")
	}
}

func TestDangerousResolvedRanges(t *testing.T) {
	for _, s := range []string{"169.254.169.254", "fe80::1", "0.0.0.0", "224.0.0.1"} {
		if !dangerous(net.ParseIP(s)) {
			t.Errorf("%s must be dangerous", s)
		}
	}
	if dangerous(net.ParseIP("10.1.2.3")) || dangerous(net.ParseIP("127.0.0.1")) {
		t.Error("private/loopback must not be flagged")
	}
}
