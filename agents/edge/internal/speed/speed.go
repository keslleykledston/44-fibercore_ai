// Package speed holds the Edge's LOCAL half of the TR-143 throughput test (ADR-0038): the catalog that maps a logical endpoint id to the address the CPE
// is pointed at, the checks that address must pass, the closed list of file-size profiles, and the health probe.
//
// The Cloud only ever names an endpoint by id and a profile by name. Everything that can send traffic somewhere lives in this host's configuration, is
// validated when the configuration is loaded (an invalid one means the module does not start), and is built from fixed templates: there is no
// configurable path, query, credential, scheme or hostname, so nothing the Cloud sends can steer the CPE to an arbitrary place.
package speed

import (
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"net"
	"net/http"
	"net/netip"
	"regexp"
	"sort"
	"strconv"
	"time"
)

const (
	KindCore     = "CORE"
	KindInternet = "INTERNET"
	maxEndpoints = 8
)

// ProfileBytes is the closed list of file sizes (identical to the Cloud's). A size outside it is never requested.
var ProfileBytes = map[string]int64{"10mb": 10_000_000, "50mb": 50_000_000, "200mb": 200_000_000}

// IDRe is the logical endpoint id (identical to the Cloud's).
var IDRe = regexp.MustCompile(`^[a-z0-9][a-z0-9-]{1,30}$`)

// The WAN interface of the bench CPE is written by the owner into the local configuration (the service WAN, NOT the management WAN), in one of the two
// data-model shapes. Anything else is refused.
var (
	ifaceTR181 = regexp.MustCompile(`^Device\.IP\.Interface\.[0-9]{1,3}$`)
	ifaceTR098 = regexp.MustCompile(`^InternetGatewayDevice\.WANDevice\.[0-9]{1,2}\.WANConnectionDevice\.[0-9]{1,3}\.(WANIPConnection|WANPPPConnection)\.[0-9]{1,3}$`)
)

// InterfaceRoot returns the data-model root ("tr181" or "tr098") the interface path belongs to, or an error for any other shape.
func InterfaceRoot(path string) (string, error) {
	switch {
	case ifaceTR181.MatchString(path):
		return "tr181", nil
	case ifaceTR098.MatchString(path):
		return "tr098", nil
	}
	return "", errors.New("speed: wan interface outside the accepted shapes")
}

// EndpointConfig is one entry of the local `speed.endpoints` list. Host is an IP LITERAL (no name to resolve, so no rebinding).
type EndpointConfig struct {
	ID   string `json:"id"`
	Kind string `json:"kind"` // CORE | INTERNET
	Host string `json:"host"`
	Port int    `json:"port"`
}

// Config is the local `speed` section.
type Config struct {
	Enabled   bool             `json:"enabled"`
	CoreCIDRs []string         `json:"core_cidrs"` // where a CORE endpoint may live; required with any CORE endpoint
	Endpoints []EndpointConfig `json:"endpoints"`
}

// Endpoint is a validated destination.
type Endpoint struct {
	ID   string
	Kind string
	Addr netip.AddrPort
}

// DownloadURL, UploadURL and HealthURL come from fixed templates over the pinned address: no path, query or credential is configurable.
func (e Endpoint) DownloadURL(profile string) string {
	return "http://" + e.Addr.String() + "/dl/" + profile
}
func (e Endpoint) UploadURL(profile string) string {
	return "http://" + e.Addr.String() + "/ul/" + profile
}
func (e Endpoint) HealthURL() string { return "http://" + e.Addr.String() + "/health" }

// Catalog is the set of validated endpoints.
type Catalog struct {
	byID map[string]Endpoint
}

// denyAlways are never valid as a test destination, whatever the kind: unspecified, loopback, link-local (this includes the cloud metadata addresses),
// multicast, broadcast, reserved, and the other well-known metadata addresses.
var denyAlways = mustPrefixes("0.0.0.0/8", "127.0.0.0/8", "169.254.0.0/16", "224.0.0.0/4", "240.0.0.0/4", "192.0.0.0/24", "100.100.100.200/32",
	"::/128", "::1/128", "fe80::/10", "ff00::/8", "fd00:ec2::/32")

// notInternet are ranges an INTERNET destination can never be in: private, CGNAT, benchmarking, documentation, unique-local.
var notInternet = mustPrefixes("10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16", "100.64.0.0/10", "198.18.0.0/15",
	"192.0.2.0/24", "198.51.100.0/24", "203.0.113.0/24", "fc00::/7", "2001:db8::/32")

func mustPrefixes(s ...string) []netip.Prefix {
	out := make([]netip.Prefix, len(s))
	for i, v := range s {
		out[i] = netip.MustParsePrefix(v)
	}
	return out
}

func inAny(a netip.Addr, ps []netip.Prefix) bool {
	for _, p := range ps {
		if p.Contains(a) {
			return true
		}
	}
	return false
}

// New validates the section. Any problem is an error: the module must not start with a partly valid configuration.
func New(c Config) (*Catalog, error) {
	if len(c.Endpoints) < 1 || len(c.Endpoints) > maxEndpoints {
		return nil, fmt.Errorf("speed: endpoints must list 1 to %d entries", maxEndpoints)
	}
	var core []netip.Prefix
	for _, s := range c.CoreCIDRs {
		p, err := netip.ParsePrefix(s)
		if err != nil || p != p.Masked() || (p.Addr().Is4() && p.Bits() < 8) || (p.Addr().Is6() && p.Bits() < 32) {
			return nil, fmt.Errorf("speed: core_cidrs entry %q is not a canonical prefix (IPv4 at least /8, IPv6 at least /32)", s)
		}
		for _, d := range denyAlways {
			if p.Overlaps(d) {
				return nil, fmt.Errorf("speed: core_cidrs entry %q overlaps a range that is never a valid destination", s)
			}
		}
		core = append(core, p)
	}
	cat := &Catalog{byID: map[string]Endpoint{}}
	for _, e := range c.Endpoints {
		if !IDRe.MatchString(e.ID) {
			return nil, errors.New("speed: endpoint id must be a lower-case logical name")
		}
		if _, dup := cat.byID[e.ID]; dup {
			return nil, fmt.Errorf("speed: endpoint %q listed twice", e.ID)
		}
		if e.Kind != KindCore && e.Kind != KindInternet {
			return nil, fmt.Errorf("speed: endpoint %q kind must be CORE or INTERNET", e.ID)
		}
		ip, err := netip.ParseAddr(e.Host)
		if err != nil || ip.Zone() != "" || ip.Is4In6() {
			return nil, fmt.Errorf("speed: endpoint %q host must be an IP literal", e.ID)
		}
		if e.Port < 1 || e.Port > 65535 {
			return nil, fmt.Errorf("speed: endpoint %q port out of range", e.ID)
		}
		switch {
		case inAny(ip, denyAlways):
			return nil, fmt.Errorf("speed: endpoint %q address is never a valid destination (loopback, link-local, metadata, multicast or reserved)", e.ID)
		case e.Kind == KindInternet && inAny(ip, notInternet):
			return nil, fmt.Errorf("speed: endpoint %q is INTERNET but the address is private, CGNAT, documentation or unique-local", e.ID)
		case e.Kind == KindCore && !inAny(ip, core):
			return nil, fmt.Errorf("speed: endpoint %q is CORE but the address is outside core_cidrs", e.ID)
		}
		cat.byID[e.ID] = Endpoint{ID: e.ID, Kind: e.Kind, Addr: netip.AddrPortFrom(ip, uint16(e.Port))}
	}
	return cat, nil
}

// Endpoint returns the validated destination for a logical id.
func (c *Catalog) Endpoint(id string) (Endpoint, bool) {
	e, ok := c.byID[id]
	return e, ok
}

// All returns the endpoints in a stable order.
func (c *Catalog) All() []Endpoint {
	out := make([]Endpoint, 0, len(c.byID))
	for _, e := range c.byID {
		out = append(out, e)
	}
	sort.Slice(out, func(i, j int) bool { return out[i].ID < out[j].ID })
	return out
}

// HostPorts are the addresses the Edge's outbound allowlist must contain for the health probe.
func (c *Catalog) HostPorts() []string {
	var out []string
	for _, e := range c.All() {
		out = append(out, net.JoinHostPort(e.Addr.Addr().String(), strconv.Itoa(int(e.Addr.Port()))))
	}
	return out
}

// ErrProbe is any failed health probe.
var ErrProbe = errors.New("speed: endpoint health probe failed")

// Probe asks the endpoint's /health: exactly one small GET to the pinned address, no redirect followed, status 200 and the exact body "ok". `dial` is the
// Edge's allowlisted dialer. The probe proves the node is up and answers as expected; it says nothing about what a CPE's client would do with a 3xx
// (that is a homologation fact, recorded in the registry).
func Probe(ctx context.Context, e Endpoint, dial func(ctx context.Context, network, addr string) (net.Conn, error)) error {
	tr := &http.Transport{
		Proxy: nil,
		DialContext: func(ctx context.Context, network, _ string) (net.Conn, error) {
			return dial(ctx, network, e.Addr.String())
		},
		DisableKeepAlives: true,
	}
	hc := &http.Client{Transport: tr, Timeout: 5 * time.Second, CheckRedirect: func(*http.Request, []*http.Request) error { return http.ErrUseLastResponse }}
	req, err := http.NewRequestWithContext(ctx, http.MethodGet, e.HealthURL(), nil)
	if err != nil {
		return ErrProbe
	}
	resp, err := hc.Do(req)
	if err != nil {
		return ErrProbe
	}
	defer resp.Body.Close()
	b, err := io.ReadAll(io.LimitReader(resp.Body, 8))
	if err != nil || resp.StatusCode != http.StatusOK || string(b) != "ok" {
		return ErrProbe
	}
	return nil
}

// HealthPayload probes every endpoint once and returns the closed report for the Cloud: only the logical id and `ok`/`down`. No address, no reason.
func (c *Catalog) HealthPayload(ctx context.Context, dial func(ctx context.Context, network, addr string) (net.Conn, error)) []byte {
	type item struct {
		ID     string `json:"id"`
		Health string `json:"health"`
	}
	items := []item{}
	for _, e := range c.All() {
		h := "ok"
		if Probe(ctx, e, dial) != nil {
			h = "down"
		}
		items = append(items, item{e.ID, h})
	}
	b, _ := json.Marshal(map[string]any{"endpoints": items})
	return b
}

// Check is the Verifier's view of the catalog: an envelope may name only an endpoint and a profile this Edge itself knows.
func (c *Catalog) Check(target, profile string) error {
	if _, ok := c.byID[target]; !ok {
		return errors.New("speed: endpoint not configured on this edge")
	}
	if _, ok := ProfileBytes[profile]; !ok {
		return errors.New("speed: profile outside the closed list")
	}
	return nil
}
