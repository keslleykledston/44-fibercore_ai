package speed

import (
	"context"
	"net"
	"net/http"
	"net/http/httptest"
	"net/netip"
	"os"
	"strings"
	"testing"
)

func cfg(core []string, eps ...EndpointConfig) Config {
	return Config{Enabled: true, CoreCIDRs: core, Endpoints: eps}
}

func ep(id, kind, host string, port int) EndpointConfig {
	return EndpointConfig{ID: id, Kind: kind, Host: host, Port: port}
}

func TestAValidConfigurationBuildsOnlyFixedTemplates(t *testing.T) {
	c, err := New(cfg([]string{"10.20.0.0/16"}, ep("core-sp-1", "CORE", "10.20.5.9", 8080), ep("net-sp-1", "INTERNET", "8.8.4.4", 80)))
	if err != nil {
		t.Fatal(err)
	}
	e, ok := c.Endpoint("core-sp-1")
	if !ok {
		t.Fatal("endpoint missing")
	}
	if got := e.DownloadURL("10mb"); got != "http://10.20.5.9:8080/dl/10mb" {
		t.Fatalf("download url %q", got)
	}
	if got := e.UploadURL("50mb"); got != "http://10.20.5.9:8080/ul/50mb" {
		t.Fatalf("upload url %q", got)
	}
	if got := e.HealthURL(); got != "http://10.20.5.9:8080/health" {
		t.Fatalf("health url %q", got)
	}
	if _, ok := c.Endpoint("does-not-exist"); ok {
		t.Fatal("unknown id must not resolve")
	}
	if hp := strings.Join(c.HostPorts(), ","); hp != "10.20.5.9:8080,8.8.4.4:80" {
		t.Fatalf("host ports %q", hp)
	}
	v6, err := New(cfg([]string{"2a01:db8::/32"}, ep("core-v6", "CORE", "2a01:db8::10", 8080)))
	if err != nil {
		t.Fatal(err)
	}
	if e, _ := v6.Endpoint("core-v6"); e.DownloadURL("10mb") != "http://[2a01:db8::10]:8080/dl/10mb" {
		t.Fatalf("v6 url %q", e.DownloadURL("10mb"))
	}
}

func TestEveryUnsafeDestinationIsRefused(t *testing.T) {
	core := []string{"10.20.0.0/16"}
	for name, c := range map[string]Config{
		"no endpoints":           cfg(core),
		"too many":               cfg(core, ep("a-1", "CORE", "10.20.0.1", 80), ep("a-2", "CORE", "10.20.0.2", 80), ep("a-3", "CORE", "10.20.0.3", 80), ep("a-4", "CORE", "10.20.0.4", 80), ep("a-5", "CORE", "10.20.0.5", 80), ep("a-6", "CORE", "10.20.0.6", 80), ep("a-7", "CORE", "10.20.0.7", 80), ep("a-8", "CORE", "10.20.0.8", 80), ep("a-9", "CORE", "10.20.0.9", 80)),
		"duplicate id":           cfg(core, ep("dup-1", "CORE", "10.20.0.1", 80), ep("dup-1", "CORE", "10.20.0.2", 80)),
		"bad id":                 cfg(core, ep("Core1", "CORE", "10.20.0.1", 80)),
		"id is a url":            cfg(core, ep("http://x", "CORE", "10.20.0.1", 80)),
		"bad kind":               cfg(core, ep("ok-1", "WAN", "10.20.0.1", 80)),
		"host is a name":         cfg(core, ep("ok-1", "CORE", "speedtest.example.com", 80)),
		"host with port":         cfg(core, ep("ok-1", "CORE", "10.20.0.1:80", 80)),
		"host is a url":          cfg(core, ep("ok-1", "CORE", "http://10.20.0.1", 80)),
		"ipv6 zone":              cfg(core, ep("ok-1", "CORE", "fe80::1%eth0", 80)),
		"v4-mapped v6":           cfg(core, ep("ok-1", "INTERNET", "::ffff:8.8.8.8", 80)),
		"port zero":              cfg(core, ep("ok-1", "CORE", "10.20.0.1", 0)),
		"port too high":          cfg(core, ep("ok-1", "CORE", "10.20.0.1", 65536)),
		"loopback":               cfg([]string{"10.20.0.0/16"}, ep("ok-1", "INTERNET", "127.0.0.1", 80)),
		"loopback as core":       cfg(core, ep("ok-1", "CORE", "127.0.0.1", 80)),
		"unspecified":            cfg(core, ep("ok-1", "INTERNET", "0.0.0.0", 80)),
		"cloud metadata":         cfg(core, ep("ok-1", "INTERNET", "169.254.169.254", 80)),
		"link-local as core":     cfg(core, ep("ok-1", "CORE", "169.254.10.10", 80)),
		"alibaba metadata":       cfg(core, ep("ok-1", "INTERNET", "100.100.100.200", 80)),
		"multicast":              cfg(core, ep("ok-1", "INTERNET", "224.0.0.1", 80)),
		"broadcast":              cfg(core, ep("ok-1", "INTERNET", "255.255.255.255", 80)),
		"ipv6 loopback":          cfg(core, ep("ok-1", "INTERNET", "::1", 80)),
		"ipv6 link-local":        cfg(core, ep("ok-1", "INTERNET", "fe80::1", 80)),
		"aws ipv6 metadata":      cfg([]string{"fd00::/8"}, ep("ok-1", "CORE", "fd00:ec2::254", 80)),
		"internet is private":    cfg(core, ep("ok-1", "INTERNET", "10.20.0.1", 80)),
		"internet is rfc1918b":   cfg(core, ep("ok-1", "INTERNET", "172.16.4.4", 80)),
		"internet is rfc1918c":   cfg(core, ep("ok-1", "INTERNET", "192.168.1.1", 80)),
		"internet is cgnat":      cfg(core, ep("ok-1", "INTERNET", "100.64.3.3", 80)),
		"internet is ula":        cfg(core, ep("ok-1", "INTERNET", "fd12:3456::1", 80)),
		"internet is doc":        cfg(core, ep("ok-1", "INTERNET", "203.0.113.5", 80)),
		"core outside cidrs":     cfg(core, ep("ok-1", "CORE", "10.99.0.1", 80)),
		"core without cidrs":     cfg(nil, ep("ok-1", "CORE", "10.20.0.1", 80)),
		"cidr not canonical":     cfg([]string{"10.20.1.1/16"}, ep("ok-1", "CORE", "10.20.0.1", 80)),
		"cidr too wide":          cfg([]string{"10.0.0.0/7"}, ep("ok-1", "CORE", "10.20.0.1", 80)),
		"cidr is everything":     cfg([]string{"0.0.0.0/0"}, ep("ok-1", "CORE", "10.20.0.1", 80)),
		"cidr covers link-local": cfg([]string{"169.254.0.0/16"}, ep("ok-1", "CORE", "169.254.0.5", 80)),
		"cidr covers loopback":   cfg([]string{"127.0.0.0/8"}, ep("ok-1", "CORE", "127.0.0.1", 80)),
		"cidr not a prefix":      cfg([]string{"10.20.0.1"}, ep("ok-1", "CORE", "10.20.0.1", 80)),
	} {
		if _, err := New(c); err == nil {
			t.Errorf("%s: must be refused", name)
		}
	}
}

func TestOneBadEntryRefusesTheWholeSection(t *testing.T) {
	if _, err := New(cfg([]string{"10.20.0.0/16"}, ep("good-1", "CORE", "10.20.0.1", 80), ep("bad-1", "CORE", "10.99.0.1", 80))); err == nil {
		t.Fatal("a partly valid configuration must not start the module")
	}
}

func TestProfilesAreTheClosedListOfTheCloud(t *testing.T) {
	want := map[string]int64{"10mb": 10_000_000, "50mb": 50_000_000, "200mb": 200_000_000}
	if len(ProfileBytes) != len(want) {
		t.Fatalf("%v", ProfileBytes)
	}
	for k, v := range want {
		if ProfileBytes[k] != v {
			t.Fatalf("%s=%d", k, ProfileBytes[k])
		}
	}
}

func TestInterfaceShapes(t *testing.T) {
	for p, root := range map[string]string{
		"Device.IP.Interface.1": "tr181", "Device.IP.Interface.12": "tr181",
		"InternetGatewayDevice.WANDevice.1.WANConnectionDevice.2.WANIPConnection.1":  "tr098",
		"InternetGatewayDevice.WANDevice.1.WANConnectionDevice.1.WANPPPConnection.1": "tr098",
	} {
		if got, err := InterfaceRoot(p); err != nil || got != root {
			t.Errorf("%s: %q %v", p, got, err)
		}
	}
	for _, p := range []string{"", "Device.IP.Interface.", "Device.IP.Interface.1.", "Device.IP.Interface.1234", "Device.Ethernet.Interface.1", "Device.IP.Interface.1; rm",
		"InternetGatewayDevice.WANDevice.1.WANConnectionDevice.1", "InternetGatewayDevice.WANDevice.1.WANConnectionDevice.1.WANIPConnection.1.Username",
		"InternetGatewayDevice.LANDevice.1", "http://10.0.0.1"} {
		if _, err := InterfaceRoot(p); err == nil {
			t.Errorf("%q must be refused", p)
		}
	}
}

func probeEndpoint(t *testing.T, h http.Handler) (Endpoint, func(context.Context, string, string) (net.Conn, error)) {
	srv := httptest.NewServer(h)
	t.Cleanup(srv.Close)
	ap := netip.MustParseAddrPort(strings.TrimPrefix(srv.URL, "http://"))
	var dialed []string
	d := &net.Dialer{}
	return Endpoint{ID: "probe-1", Kind: KindCore, Addr: ap}, func(ctx context.Context, n, a string) (net.Conn, error) {
		dialed = append(dialed, a)
		if a != ap.String() {
			t.Errorf("dialed %s, want only the pinned %s", a, ap)
		}
		return d.DialContext(ctx, n, a)
	}
}

func TestProbeAcceptsOnlyAnExactOkAndNeverFollowsARedirect(t *testing.T) {
	good := http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.URL.Path != "/health" || r.Method != http.MethodGet {
			w.WriteHeader(404)
			return
		}
		_, _ = w.Write([]byte("ok"))
	})
	e, dial := probeEndpoint(t, good)
	if err := Probe(context.Background(), e, dial); err != nil {
		t.Fatal(err)
	}
	for name, h := range map[string]http.HandlerFunc{
		"wrong body": func(w http.ResponseWriter, r *http.Request) { _, _ = w.Write([]byte("okay")) },
		"empty":      func(w http.ResponseWriter, r *http.Request) {},
		"500":        func(w http.ResponseWriter, r *http.Request) { w.WriteHeader(500); _, _ = w.Write([]byte("ok")) },
		"redirect": func(w http.ResponseWriter, r *http.Request) {
			http.Redirect(w, r, "http://169.254.169.254/latest", http.StatusFound)
		},
		"big body": func(w http.ResponseWriter, r *http.Request) { _, _ = w.Write([]byte(strings.Repeat("ok", 100))) },
		"redirect ok": func(w http.ResponseWriter, r *http.Request) {
			w.Header().Set("Location", "/x")
			w.WriteHeader(301)
			_, _ = w.Write([]byte("ok"))
		},
	} {
		e, dial := probeEndpoint(t, h)
		if err := Probe(context.Background(), e, dial); err == nil {
			t.Errorf("%s: must fail", name)
		}
	}
}

func TestProbeFailsWhenNothingListens(t *testing.T) {
	e := Endpoint{ID: "dead-1", Kind: KindCore, Addr: netip.MustParseAddrPort("127.0.0.1:1")}
	if err := Probe(context.Background(), e, (&net.Dialer{}).DialContext); err == nil {
		t.Fatal("must fail")
	}
}

func TestSourceCannotBuildAnythingButTheFixedTemplates(t *testing.T) {
	b, err := os.ReadFile("speed.go")
	if err != nil {
		t.Fatal(err)
	}
	s := string(b)
	for _, bad := range []string{"LookupHost", "LookupIP", "ResolveIPAddr", "net.ParseCIDR(os", "os.Getenv", "RawQuery", "User:", "url.UserPassword"} {
		if strings.Contains(s, bad) {
			t.Errorf("speed.go must not contain %q", bad)
		}
	}
	if strings.Count(s, `"http://"`) != 3 {
		t.Error("exactly three URL templates (download, upload, health)")
	}
}

func TestHealthPayloadCarriesOnlyIdsAndOkOrDown(t *testing.T) {
	up := http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) { _, _ = w.Write([]byte("ok")) })
	eu, dial := probeEndpoint(t, up)
	eu.ID = "up-node"
	ed := Endpoint{ID: "dead-node", Kind: KindInternet, Addr: netip.MustParseAddrPort("127.0.0.1:1")}
	cat := &Catalog{byID: map[string]Endpoint{eu.ID: eu, ed.ID: ed}}
	b := cat.HealthPayload(context.Background(), func(ctx context.Context, n, a string) (net.Conn, error) {
		return (&net.Dialer{}).DialContext(ctx, n, a)
	})
	_ = dial
	s := string(b)
	if s != `{"endpoints":[{"id":"dead-node","health":"down"},{"id":"up-node","health":"ok"}]}` {
		t.Fatalf("%s", s)
	}
	if strings.Contains(s, "127.0.0.1") || strings.Contains(s, "http") || strings.Contains(s, ":1") {
		t.Fatalf("an address leaked into the report: %s", s)
	}
}

func TestCheckKnowsOnlyTheConfiguredIdsAndTheClosedProfiles(t *testing.T) {
	c, err := New(cfg([]string{"10.20.0.0/16"}, ep("core-sp-1", "CORE", "10.20.5.9", 8080)))
	if err != nil {
		t.Fatal(err)
	}
	if err := c.Check("core-sp-1", "200mb"); err != nil {
		t.Fatal(err)
	}
	for _, p := range [][2]string{{"other-node", "10mb"}, {"core-sp-1", "1gb"}, {"", ""}, {"http://10.20.5.9:8080", "10mb"}} {
		if c.Check(p[0], p[1]) == nil {
			t.Errorf("%v must be refused", p)
		}
	}
}
