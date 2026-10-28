// Package allowlist restricts every outbound connection of the Edge to locally configured host:port
// pairs. Redirects and environment proxies are disabled, and resolved addresses in dangerous ranges
// (link-local/metadata, multicast, unspecified) are refused unless that exact IP literal is allowlisted.
package allowlist

import (
	"context"
	"errors"
	"fmt"
	"net"
	"net/http"
	"strings"
	"time"
)

type List struct{ entries map[string]struct{} }

var ErrDenied = errors.New("destination not in local allowlist")

func New(entries []string) (*List, error) {
	l := &List{entries: map[string]struct{}{}}
	for _, e := range entries {
		h, p, err := net.SplitHostPort(strings.TrimSpace(e))
		if err != nil || h == "" || p == "" {
			return nil, fmt.Errorf("allowlist entry %q must be host:port", e)
		}
		l.entries[strings.ToLower(net.JoinHostPort(h, p))] = struct{}{}
	}
	return l, nil
}

func (l *List) Allowed(hostport string) bool {
	h, p, err := net.SplitHostPort(hostport)
	if err != nil {
		return false
	}
	_, ok := l.entries[strings.ToLower(net.JoinHostPort(h, p))]
	return ok
}

func dangerous(ip net.IP) bool {
	return ip.IsUnspecified() || ip.IsMulticast() || ip.IsLinkLocalUnicast() || ip.IsLinkLocalMulticast()
}

// DialContext validates the requested address against the list BEFORE resolving, then refuses
// dangerous resolved IPs (DNS rebinding to metadata endpoints) unless the entry is that IP literal.
func (l *List) DialContext(ctx context.Context, network, addr string) (net.Conn, error) {
	if !l.Allowed(addr) {
		return nil, fmt.Errorf("%w: %s", ErrDenied, addr)
	}
	host, port, _ := net.SplitHostPort(addr)
	literal := net.ParseIP(host)
	var ips []net.IP
	if literal != nil {
		ips = []net.IP{literal}
	} else {
		res, err := net.DefaultResolver.LookupIPAddr(ctx, host)
		if err != nil {
			return nil, err
		}
		for _, r := range res {
			ips = append(ips, r.IP)
		}
	}
	d := &net.Dialer{Timeout: 10 * time.Second}
	var last error
	for _, ip := range ips {
		if literal == nil && dangerous(ip) {
			last = fmt.Errorf("%w: %s resolves to restricted address %s", ErrDenied, host, ip)
			continue
		}
		c, err := d.DialContext(ctx, network, net.JoinHostPort(ip.String(), port))
		if err == nil {
			return c, nil
		}
		last = err
	}
	if last == nil {
		last = ErrDenied
	}
	return nil, last
}

// HTTPClient returns a client bound to the list: no proxies, no redirects, bounded timeout.
func (l *List) HTTPClient(timeout time.Duration) *http.Client {
	return &http.Client{
		Timeout: timeout,
		Transport: &http.Transport{
			Proxy:                 nil,
			DialContext:           l.DialContext,
			TLSHandshakeTimeout:   10 * time.Second,
			ResponseHeaderTimeout: timeout,
			MaxIdleConns:          4,
		},
		CheckRedirect: func(*http.Request, []*http.Request) error { return http.ErrUseLastResponse },
	}
}
