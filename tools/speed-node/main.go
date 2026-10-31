// Command speed-node is the throughput test node for the Speed Diagnostics module (ADR-0038).
//
// It speaks exactly the contract the Edge's fixed URL templates use and nothing else:
//
//	GET /health        -> 200, body "ok"
//	GET /dl/<profile>  -> 200, exactly <profile> bytes of incompressible data
//	PUT /ul/<profile>  -> 200, body discarded (never stored), at most <profile> bytes
//
// Everything else answers 404 or 405. It NEVER redirects (a CPE that follows a 3xx could be steered elsewhere), never compresses, never caches, and
// never logs a client address. It refuses to start without an explicit listen address and an explicit source allow-list, and it limits concurrent
// transfers. It is a lab/provider test node, not a general file server.
package main

import (
	"crypto/rand"
	"errors"
	"flag"
	"fmt"
	"io"
	"log"
	"net"
	"net/http"
	"net/netip"
	"os"
	"strconv"
	"strings"
	"time"
)

// profileBytes is the closed list of sizes (identical to the Cloud's and the Edge's). A var so tests can shrink it.
var profileBytes = map[string]int64{"10mb": 10_000_000, "50mb": 50_000_000, "200mb": 200_000_000}

const chunkSize = 64 * 1024

type node struct {
	allow   []netip.Prefix
	sem     chan struct{}
	pattern []byte
}

func newNode(allow []netip.Prefix, maxConcurrent int) (*node, error) {
	if len(allow) == 0 {
		return nil, errors.New("speed-node: the source allow-list must not be empty")
	}
	if maxConcurrent < 1 || maxConcurrent > 8 {
		return nil, errors.New("speed-node: max concurrent transfers must be 1 to 8")
	}
	n := &node{allow: allow, sem: make(chan struct{}, maxConcurrent), pattern: make([]byte, chunkSize)}
	// Random bytes: a middlebox that compresses or deduplicates cannot inflate the measurement.
	if _, err := rand.Read(n.pattern); err != nil {
		return nil, err
	}
	return n, nil
}

// ParseAllow parses a comma-separated list of canonical prefixes. A prefix that would allow "everyone" (/0) or a very broad range is refused: the
// owner names the networks the test traffic may come from.
func ParseAllow(s string) ([]netip.Prefix, error) {
	var out []netip.Prefix
	for _, raw := range strings.Split(s, ",") {
		raw = strings.TrimSpace(raw)
		if raw == "" {
			continue
		}
		p, err := netip.ParsePrefix(raw)
		if err != nil || p != p.Masked() {
			return nil, fmt.Errorf("speed-node: allow entry %q is not a canonical prefix", raw)
		}
		if (p.Addr().Is4() && p.Bits() < 8) || (p.Addr().Is6() && p.Bits() < 32) {
			return nil, fmt.Errorf("speed-node: allow entry %q is too broad (IPv4 at least /8, IPv6 at least /32)", raw)
		}
		out = append(out, p)
	}
	if len(out) == 0 {
		return nil, errors.New("speed-node: the source allow-list must not be empty")
	}
	return out, nil
}

// ParseListen refuses a wildcard address: the node binds to one named interface address.
func ParseListen(s string) (string, error) {
	ap, err := netip.ParseAddrPort(s)
	if err != nil || ap.Port() == 0 {
		return "", errors.New("speed-node: listen must be <ip>:<port>")
	}
	if ap.Addr().IsUnspecified() {
		return "", errors.New("speed-node: refusing to listen on a wildcard address; name the interface address")
	}
	return ap.String(), nil
}

func (n *node) allowed(remote string) bool {
	ap, err := netip.ParseAddrPort(remote)
	if err != nil {
		return false
	}
	a := ap.Addr().Unmap()
	for _, p := range n.allow {
		if p.Contains(a) {
			return true
		}
	}
	return false
}

func fail(w http.ResponseWriter, code int) {
	w.Header().Set("Cache-Control", "no-store")
	http.Error(w, http.StatusText(code), code)
}

// ServeHTTP dispatches on the exact path. There is deliberately no http.ServeMux: it redirects unclean paths (301/308), and this node must never
// answer a 3xx.
func (n *node) ServeHTTP(w http.ResponseWriter, r *http.Request) {
	if !n.allowed(r.RemoteAddr) {
		fail(w, http.StatusForbidden)
		return
	}
	path := r.URL.Path
	switch {
	case path == "/health":
		if r.Method != http.MethodGet {
			w.Header().Set("Allow", "GET")
			fail(w, http.StatusMethodNotAllowed)
			return
		}
		w.Header().Set("Content-Type", "text/plain")
		w.Header().Set("Content-Length", "2")
		w.Header().Set("Cache-Control", "no-store")
		_, _ = io.WriteString(w, "ok")
	case strings.HasPrefix(path, "/dl/"):
		size, ok := profileBytes[strings.TrimPrefix(path, "/dl/")]
		if !ok {
			fail(w, http.StatusNotFound)
			return
		}
		if r.Method != http.MethodGet {
			w.Header().Set("Allow", "GET")
			fail(w, http.StatusMethodNotAllowed)
			return
		}
		n.transfer(w, func() { n.download(w, size) })
	case strings.HasPrefix(path, "/ul/"):
		size, ok := profileBytes[strings.TrimPrefix(path, "/ul/")]
		if !ok {
			fail(w, http.StatusNotFound)
			return
		}
		if r.Method != http.MethodPut {
			w.Header().Set("Allow", "PUT")
			fail(w, http.StatusMethodNotAllowed)
			return
		}
		n.transfer(w, func() { n.upload(w, r, size) })
	default:
		fail(w, http.StatusNotFound)
	}
}

// transfer admits at most cap(sem) concurrent transfers; the health probe is not counted, so the Edge can still see the node while a test runs.
func (n *node) transfer(w http.ResponseWriter, fn func()) {
	select {
	case n.sem <- struct{}{}:
		defer func() { <-n.sem }()
	default:
		w.Header().Set("Retry-After", "5")
		fail(w, http.StatusTooManyRequests)
		return
	}
	fn()
}

func (n *node) download(w http.ResponseWriter, size int64) {
	h := w.Header()
	h.Set("Content-Type", "application/octet-stream")
	h.Set("Content-Length", strconv.FormatInt(size, 10))
	h.Set("Cache-Control", "no-store, no-transform")
	h.Set("X-Content-Type-Options", "nosniff")
	for left := size; left > 0; {
		c := int64(len(n.pattern))
		if left < c {
			c = left
		}
		wrote, err := w.Write(n.pattern[:c])
		left -= int64(wrote)
		if err != nil {
			return
		}
	}
}

func (n *node) upload(w http.ResponseWriter, r *http.Request, size int64) {
	if r.ContentLength > size {
		fail(w, http.StatusRequestEntityTooLarge)
		return
	}
	// Read one byte past the profile to tell "exactly the profile" from "more than the profile" when the length is not declared (chunked).
	got, err := io.Copy(io.Discard, io.LimitReader(r.Body, size+1))
	if err != nil {
		fail(w, http.StatusBadRequest)
		return
	}
	if got > size {
		fail(w, http.StatusRequestEntityTooLarge)
		return
	}
	w.Header().Set("Content-Length", "0")
	w.Header().Set("Cache-Control", "no-store")
	w.WriteHeader(http.StatusOK)
}

func main() {
	listen := flag.String("listen", os.Getenv("SPEED_NODE_LISTEN"), "<ip>:<port> to bind (wildcard refused)")
	allow := flag.String("allow", os.Getenv("SPEED_NODE_ALLOW"), "comma-separated source prefixes (the CPE's service network and the Edge host)")
	conc := flag.Int("max-concurrent", 2, "maximum concurrent transfers (1-8)")
	flag.Parse()
	addr, err := ParseListen(*listen)
	if err != nil {
		log.Fatal(err)
	}
	pfx, err := ParseAllow(*allow)
	if err != nil {
		log.Fatal(err)
	}
	n, err := newNode(pfx, *conc)
	if err != nil {
		log.Fatal(err)
	}
	srv := &http.Server{
		Addr: addr, Handler: n, MaxHeaderBytes: 8 << 10,
		ReadHeaderTimeout: 5 * time.Second, ReadTimeout: 10 * time.Minute, WriteTimeout: 10 * time.Minute, IdleTimeout: 10 * time.Second,
		ErrorLog: log.New(io.Discard, "", 0),
	}
	srv.SetKeepAlivesEnabled(false)
	ln, err := net.Listen("tcp", addr)
	if err != nil {
		log.Fatal(err)
	}
	log.Printf("speed-node listening; %d allowed prefix(es); max %d concurrent transfer(s); no redirects, no client addresses logged", len(pfx), *conc)
	log.Fatal(srv.Serve(ln))
}
