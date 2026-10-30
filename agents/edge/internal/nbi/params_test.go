package nbi

import (
	"context"
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"regexp"
	"strings"
	"testing"
)

func doc(t *testing.T, s string) map[string]any {
	t.Helper()
	var m map[string]any
	if err := json.Unmarshal([]byte(s), &m); err != nil {
		t.Fatal(err)
	}
	return m
}

func leaf(v string) string {
	return `{"_value":` + v + `,"_type":"x","_timestamp":"2026-10-29T10:00:00.000Z"}`
}

func TestAllowlistIsExactLeavesOnlyAndNeverNamesSecrets(t *testing.T) {
	paths := ProjectionPaths()
	if len(paths) < 20 {
		t.Fatalf("allowlist suspiciously small: %d", len(paths))
	}
	banned := []string{"password", "passphrase", "presharedkey", "keypassphrase", "wepkey", "username", "ssid", "macaddress", "ipaddress", "dns", "secret", "psk"}
	set := map[string]bool{}
	for _, p := range paths {
		set[p] = true
		l := strings.ToLower(p)
		for _, b := range banned {
			if strings.Contains(l, b) {
				t.Fatalf("allowlisted path names something sensitive (%s): %s", b, p)
			}
		}
		if strings.HasSuffix(p, ".") || strings.Contains(p, "*") {
			t.Fatalf("not an exact leaf: %s", p)
		}
	}
	for _, p := range paths { // no path is an ancestor of another: a subtree projection would drag siblings along
		for _, q := range paths {
			if p != q && strings.HasPrefix(q, p+".") {
				t.Fatalf("%s is an ancestor of %s", p, q)
			}
		}
	}
}

type obj = map[string]any

func lf(v any) obj { return obj{"_value": v, "_type": "x", "_timestamp": "2026-10-29T10:00:00.000Z"} }

func TestExtractKeepsOnlyValidatedAllowlistedValues(t *testing.T) {
	const secret = "S3nh4-Super-Secreta!"
	d := obj{"_id": "X", "InternetGatewayDevice": obj{
		"WANDevice": obj{"1": obj{
			"WANConnectionDevice": obj{"1": obj{"WANPPPConnection": obj{"1": obj{
				"ConnectionStatus": lf("Connected"), "Uptime": lf("3600"), "Username": lf(secret), "Password": lf(secret)}}}},
			"WANCommonInterfaceConfig": obj{"PhysicalLinkStatus": lf("Up")}}},
		"LANDevice": obj{"1": obj{"WLANConfiguration": obj{"1": obj{
			"Enable": lf(true), "Channel": lf(float64(11)), "SSID": lf(secret), "KeyPassphrase": lf(secret),
			"PreSharedKey": obj{"1": obj{"KeyPassphrase": lf(secret)}}}}}}}}
	got, rej := ExtractMetrics(d)
	if rej != 0 {
		t.Fatalf("rejected=%d", rej)
	}
	by := map[string]Metric{}
	for _, m := range got {
		by[m.Name+"@"+m.Scope] = m
	}
	for k, want := range map[string]any{
		"wan_connection_status@ppp/1/1": "Connected", "uptime_seconds@ppp/1/1": float64(3600), "wan_link_status@link/1": "Up",
		"wifi_radio_enabled@radio/1": "Enabled", "wifi_channel@radio/1": float64(11),
	} {
		if by[k].Value != want {
			t.Fatalf("%s = %v, want %v (all: %+v)", k, by[k].Value, want, got)
		}
	}
	b, _ := json.Marshal(got)
	if strings.Contains(string(b), secret) {
		t.Fatalf("a secret reached the output: %s", b)
	}
	if len(got) != 5 {
		t.Fatalf("only the 5 allowlisted leaves must come out, got %d", len(got))
	}
}

func TestExtractRejectsHostileValuesUnderAllowlistedPaths(t *testing.T) {
	const secret = "S3nh4-Super-Secreta!"
	base := `{"InternetGatewayDevice":{"WANDevice":{"1":{"WANConnectionDevice":{"1":{"WANPPPConnection":{"1":{"ConnectionStatus":%s}}}}}}}}`
	for name, v := range map[string]string{
		"free text in an enum":  leaf(`"` + secret + `"`),
		"enum in another case":  leaf(`"connected"`),
		"number for an enum":    leaf(`1`),
		"null":                  leaf(`null`),
		"object":                `{"_value":{"a":1},"_timestamp":"2026-10-29T10:00:00Z"}`,
		"no timestamp":          `{"_value":"Connected"}`,
		"unparseable timestamp": `{"_value":"Connected","_timestamp":"ontem"}`,
		"no _value":             `{"_timestamp":"2026-10-29T10:00:00Z"}`,
	} {
		d := doc(t, strings.Replace(base, "%s", v, 1))
		got, rej := ExtractMetrics(d)
		if len(got) != 0 || rej != 1 {
			t.Fatalf("%s: metrics=%v rejected=%d", name, got, rej)
		}
	}
	chan1 := `{"InternetGatewayDevice":{"LANDevice":{"1":{"WLANConfiguration":{"1":{"Channel":%s,"Enable":%s}}}}}}`
	for _, c := range []string{leaf(`9999`), leaf(`-1`), leaf(`1.5`), leaf(`"abc"`), leaf(`"` + secret + `"`)} {
		got, rej := ExtractMetrics(doc(t, strings.NewReplacer("%s", c).Replace(strings.Replace(chan1, "%s", c, 1))))
		for _, m := range got {
			if m.Name == "wifi_channel" {
				t.Fatalf("channel %s accepted: %+v", c, m)
			}
		}
		if rej == 0 {
			t.Fatalf("channel %s not counted as rejected", c)
		}
	}
	if got, _ := ExtractMetrics(doc(t, strings.Replace(chan1, "%s", leaf(`"1"`), 2))); len(got) != 2 {
		t.Fatalf(`numeric string "1" must be accepted for channel and as a boolean: %v`, got)
	}
}

func TestExtractIgnoresDocumentsWithoutTheTree(t *testing.T) {
	got, rej := ExtractMetrics(doc(t, `{"_id":"X","_lastInform":"2026-10-29T10:00:00Z","Device":{"DeviceInfo":{"SoftwareVersion":`+leaf(`"1"`)+`}}}`))
	if len(got) != 0 || rej != 0 {
		t.Fatalf("got=%v rej=%d", got, rej)
	}
}

func TestCachedParamsIsGETWithExactProjectionAndNoTask(t *testing.T) {
	var method, path, proj, query, user string
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		method, path, proj, query = r.Method, r.URL.Path, r.URL.Query().Get("projection"), r.URL.Query().Get("query")
		user, _, _ = r.BasicAuth()
		_, _ = w.Write([]byte(`[{"_id":"A","Device":{"DeviceInfo":{"UpTime":` + leaf(`120`) + `}}},{"_id":"B"},{"noid":true}]`))
	}))
	defer srv.Close()
	c, err := New(srv.URL, srv.Client(), "u:p")
	if err != nil {
		t.Fatal(err)
	}
	res, err := c.CachedParams(context.Background(), []string{"A", "B"})
	if err != nil {
		t.Fatal(err)
	}
	if method != http.MethodGet || path != "/devices" || strings.Contains(path, "tasks") || user != "u" {
		t.Fatalf("method=%s path=%s user=%s", method, path, user)
	}
	if !strings.Contains(query, `"$in"`) || !strings.HasPrefix(proj, "_id,") || proj != "_id,"+strings.Join(ProjectionPaths(), ",") {
		t.Fatalf("query=%s projection=%s", query, proj)
	}
	if len(res) != 2 || res[0].ID != "A" || len(res[0].Metrics) != 1 || res[0].Metrics[0].Name != "uptime_seconds" || len(res[1].Metrics) != 0 {
		t.Fatalf("result=%+v", res)
	}
	if r, err := c.CachedParams(context.Background(), nil); r != nil || err != nil {
		t.Fatalf("no ids must be a no-op: %v %v", r, err)
	}
}

func TestCachedParamsFailsClosedOnBadStatusAndOversizeOrGarbage(t *testing.T) {
	for name, h := range map[string]http.HandlerFunc{
		"500":     func(w http.ResponseWriter, r *http.Request) { w.WriteHeader(500) },
		"garbage": func(w http.ResponseWriter, r *http.Request) { _, _ = w.Write([]byte("<html>")) },
	} {
		srv := httptest.NewServer(h)
		c, _ := New(srv.URL, srv.Client(), "")
		if _, err := c.CachedParams(context.Background(), []string{"A"}); err == nil {
			t.Fatalf("%s must error", name)
		}
		srv.Close()
	}
}

func TestCachedParamsBatchesAndRejectsUnboundedOrInvalidIDs(t *testing.T) {
	var reqs, maxURL, maxIDs int
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		reqs++
		if n := len(r.URL.String()); n > maxURL {
			maxURL = n
		}
		var q struct {
			ID struct {
				In []string `json:"$in"`
			} `json:"_id"`
		}
		_ = json.Unmarshal([]byte(r.URL.Query().Get("query")), &q)
		if len(q.ID.In) > maxIDs {
			maxIDs = len(q.ID.In)
		}
		_, _ = w.Write([]byte(`[]`))
	}))
	defer srv.Close()
	c, _ := New(srv.URL, srv.Client(), "")
	ids := make([]string, 60)
	for i := range ids {
		ids[i] = "OUI-CLASS-SERIAL" + strings.Repeat("X", 100)
	}
	if _, err := c.CachedParams(context.Background(), ids); err != nil {
		t.Fatal(err)
	}
	if reqs != 3 || maxIDs > 25 || maxURL > 16<<10 {
		t.Fatalf("requests=%d max ids per request=%d max url=%d", reqs, maxIDs, maxURL)
	}
	reqs = 0
	big := make([]string, maxIDsPerCall+1)
	for i := range big {
		big[i] = "A"
	}
	for name, in := range map[string][]string{"too many": big, "empty id": {"A", ""}, "oversized id": {strings.Repeat("A", maxIDLen+1)}, "control char": {"A\nB"}} {
		if _, err := c.CachedParams(context.Background(), in); err == nil {
			t.Fatalf("%s must be rejected", name)
		}
	}
	if reqs != 0 {
		t.Fatalf("a rejected call must not reach the network (requests=%d)", reqs)
	}
}

// The Cloud accepts a scope only if it is closed PER METRIC (apps/api/app/api/cpe_state.py and the CHECK of migration 0019). Every scope this
// reader can emit must be in it, or a whole batch of state would be refused; a test on the Cloud side compares these patterns with its own.
var cloudScopeByMetric = map[string]*regexp.Regexp{
	"wan_link_status":       regexp.MustCompile(`^link/[0-9]{1,3}$`),
	"wan_connection_status": regexp.MustCompile(`^(ppp|ip)(/[0-9]{1,3}){1,2}$`),
	"uptime_seconds":        regexp.MustCompile(`^((ppp|ip)(/[0-9]{1,3}){1,2}|device/0)$`),
	"wifi_radio_enabled":    regexp.MustCompile(`^radio/[0-9]{1,3}$`),
	"wifi_channel":          regexp.MustCompile(`^radio/[0-9]{1,3}$`),
}

func TestEveryScopeTheReaderCanEmitFitsTheCloudScopeForItsMetric(t *testing.T) {
	for path, p := range allowlist {
		re, ok := cloudScopeByMetric[p.spec.metric]
		if !ok || !re.MatchString(p.scope) {
			t.Fatalf("%s: metric %q scope %q is not accepted by the Cloud", path, p.spec.metric, p.scope)
		}
	}
}
