package nbi

import (
	"context"
	"encoding/json"
	"fmt"
	"io"
	"net/http"
	"net/url"
	"regexp"
	"sort"
	"strconv"
	"strings"
	"time"
)

// SD-001 / ADR-SD-002: reads a CLOSED allowlist of leaf parameters from what GenieACS already has cached (GET only, never a task).
// Nothing generic leaves this file: a value is kept only if its path is in the table below AND it has the expected type/enum; anything else
// (including a PSK, PPPoE user, SSID or MAC that a hostile or buggy device put under an allowlisted path) is dropped and counted.

// Metric is one validated observation. Value is a float64 (numbers) or a string from a fixed list (states).
type Metric struct {
	Name       string `json:"name"`
	Scope      string `json:"scope"` // e.g. "ppp/1/1", "radio/5"; digits and slashes only, never free text
	Value      any    `json:"value"`
	CapturedAt string `json:"captured_at"` // device-side timestamp kept by the ACS; a metric without a valid one is dropped
}

type kind int

const (
	kEnum kind = iota
	kInt
	kBool
)

type spec struct {
	metric string
	kind   kind
	enum   map[string]string // accepted value -> reported state (also normalises case)
	min    int64
	max    int64
}

func set(v ...string) map[string]string {
	m := map[string]string{}
	for _, s := range v {
		m[s] = s
	}
	return m
}

var (
	connStatus = spec{metric: "wan_connection_status", kind: kEnum, enum: set("Unconfigured", "Connecting", "Connected", "PendingDisconnect", "Disconnecting", "Disconnected")}
	linkStatus = spec{metric: "wan_link_status", kind: kEnum, enum: set("Up", "Down", "Initializing", "Unavailable")}
	ppp181     = spec{metric: "wan_connection_status", kind: kEnum, enum: set("Up", "Down", "Dormant", "NotPresent", "LowerLayerDown", "Error", "Unknown")}
	uptime     = spec{metric: "uptime_seconds", kind: kInt, min: 0, max: 1 << 31}
	radioOn    = spec{metric: "wifi_radio_enabled", kind: kBool}
	channel    = spec{metric: "wifi_channel", kind: kInt, min: 0, max: 196}
)

type param struct {
	path  string
	scope string
	spec  spec
}

// allowlist is built from templates with SMALL fixed instance ranges: GenieACS projections take exact paths, and we never project a
// subtree (that would pull PSK/passphrase/username siblings through the wire).
// maxWANConnDevices bounds the WANConnectionDevice instances read. Observed on a real EG8145V5 (LAB bench, 2026-10-29): the WAN that carries
// the PPP connection was instance 3, so 1..2 missed it; instances are numbered by creation order and are not stable across CPEs.
const maxWANConnDevices = 4

var allowlist = buildAllowlist()

func buildAllowlist() map[string]param {
	m := map[string]param{}
	add := func(path, scope string, s spec) { m[path] = param{path: path, scope: scope, spec: s} }
	const tr098 = "InternetGatewayDevice."
	add(tr098+"WANDevice.1.WANCommonInterfaceConfig.PhysicalLinkStatus", "link/1", linkStatus)
	for cd := 1; cd <= maxWANConnDevices; cd++ {
		for c := 1; c <= 2; c++ {
			for _, t := range []string{"ppp", "ip"} {
				node := map[string]string{"ppp": "WANPPPConnection", "ip": "WANIPConnection"}[t]
				base := fmt.Sprintf("%sWANDevice.1.WANConnectionDevice.%d.%s.%d.", tr098, cd, node, c)
				sc := fmt.Sprintf("%s/%d/%d", t, cd, c)
				add(base+"ConnectionStatus", sc, connStatus)
				add(base+"Uptime", sc, uptime)
			}
		}
	}
	for i := 1; i <= 8; i++ {
		base := fmt.Sprintf("%sLANDevice.1.WLANConfiguration.%d.", tr098, i)
		add(base+"Enable", fmt.Sprintf("radio/%d", i), radioOn)
		add(base+"Channel", fmt.Sprintf("radio/%d", i), channel)
	}
	for i := 1; i <= 2; i++ {
		add(fmt.Sprintf("Device.PPP.Interface.%d.Status", i), fmt.Sprintf("ppp/%d", i), ppp181)
	}
	for i := 1; i <= 3; i++ {
		base := fmt.Sprintf("Device.WiFi.Radio.%d.", i)
		add(base+"Enable", fmt.Sprintf("radio/%d", i), radioOn)
		add(base+"Channel", fmt.Sprintf("radio/%d", i), channel)
	}
	add("Device.DeviceInfo.UpTime", "device/0", uptime)
	return m
}

// ProjectionPaths returns the exact leaf paths requested from the NBI, sorted (stable query, stable tests).
func ProjectionPaths() []string {
	out := make([]string, 0, len(allowlist))
	for p := range allowlist {
		out = append(out, p)
	}
	sort.Strings(out)
	return out
}

var scopeRe = regexp.MustCompile(`^[a-z]+(/[0-9]+)+$`)

// ExtractMetrics walks ONLY the allowlisted paths in a device document and returns validated metrics plus how many allowlisted values were
// rejected (wrong type, value outside the fixed list, missing/invalid timestamp). It never iterates the document, so unknown branches are
// never even looked at.
func ExtractMetrics(doc map[string]any) (metrics []Metric, rejected int) {
	for _, path := range ProjectionPaths() {
		leaf, ok := lookup(doc, strings.Split(path, "."))
		if !ok {
			continue
		}
		p := allowlist[path]
		val, ts, ok := leafValue(leaf)
		if !ok {
			rejected++
			continue
		}
		v, ok := normalise(p.spec, val)
		if !ok || !scopeRe.MatchString(p.scope) {
			rejected++
			continue
		}
		metrics = append(metrics, Metric{Name: p.spec.metric, Scope: p.scope, Value: v, CapturedAt: ts})
	}
	return metrics, rejected
}

func lookup(doc map[string]any, parts []string) (map[string]any, bool) {
	var cur any = doc
	for _, k := range parts {
		m, ok := cur.(map[string]any)
		if !ok {
			return nil, false
		}
		if cur, ok = m[k]; !ok {
			return nil, false
		}
	}
	m, ok := cur.(map[string]any)
	return m, ok
}

func leafValue(leaf map[string]any) (any, string, bool) {
	v, ok := leaf["_value"]
	if !ok {
		return nil, "", false
	}
	raw, _ := leaf["_timestamp"].(string)
	t, err := time.Parse(time.RFC3339, raw)
	if err != nil {
		return nil, "", false // unknown age is useless for a diagnosis
	}
	return v, t.UTC().Format(time.RFC3339), true
}

func normalise(s spec, v any) (any, bool) {
	switch s.kind {
	case kEnum:
		str, ok := v.(string)
		if !ok {
			return nil, false
		}
		out, ok := s.enum[str]
		return out, ok
	case kBool:
		switch b := v.(type) {
		case bool:
			return stateBool(b), true
		case string:
			switch b {
			case "1", "true":
				return stateBool(true), true
			case "0", "false":
				return stateBool(false), true
			}
		}
		return nil, false
	default:
		var n int64
		switch x := v.(type) {
		case float64:
			if x != float64(int64(x)) {
				return nil, false
			}
			n = int64(x)
		case string:
			i, err := strconv.ParseInt(x, 10, 64)
			if err != nil {
				return nil, false
			}
			n = i
		default:
			return nil, false
		}
		if n < s.min || n > s.max {
			return nil, false
		}
		return float64(n), true
	}
}

func stateBool(b bool) string {
	if b {
		return "Enabled"
	}
	return "Disabled"
}

// DeviceParams is the validated, device-keyed result.
type DeviceParams struct {
	ID       string
	Metrics  []Metric
	Rejected int
}

const (
	maxIDsPerRequest = 25   // keeps the URL small (the projection alone is ~4 KB) and each ACS query cheap
	maxIDsPerCall    = 5000 // same ceiling as a cloud snapshot
	maxIDLen         = 200
)

// CachedParams reads the allowlisted leaves GenieACS ALREADY holds for the given device ids, in bounded batches. GET only: it does not ask
// the CPE for anything (a getParameterValues task is a different, separately authorised operation). Fails closed, before any request, when
// the list is too long or an id is empty, oversized or has control characters.
func (c *Client) CachedParams(ctx context.Context, ids []string) ([]DeviceParams, error) {
	if len(ids) == 0 {
		return nil, nil
	}
	if len(ids) > maxIDsPerCall {
		return nil, fmt.Errorf("nbi: %d ids exceeds the %d per call limit", len(ids), maxIDsPerCall)
	}
	for _, id := range ids {
		if id == "" || len(id) > maxIDLen || strings.ContainsFunc(id, func(r rune) bool { return r < 0x20 || r == 0x7f }) {
			return nil, fmt.Errorf("nbi: invalid device id")
		}
	}
	var out []DeviceParams
	for start := 0; start < len(ids); start += maxIDsPerRequest {
		end := start + maxIDsPerRequest
		if end > len(ids) {
			end = len(ids)
		}
		part, err := c.cachedBatch(ctx, ids[start:end])
		if err != nil {
			return nil, err
		}
		out = append(out, part...)
	}
	return out, nil
}

func (c *Client) cachedBatch(ctx context.Context, ids []string) ([]DeviceParams, error) {
	q, err := json.Marshal(map[string]any{"_id": map[string]any{"$in": ids}})
	if err != nil {
		return nil, err
	}
	u := *c.base
	u.Path = strings.TrimRight(u.Path, "/") + "/devices"
	u.RawQuery = url.Values{"query": {string(q)}, "projection": {"_id," + strings.Join(ProjectionPaths(), ",")}}.Encode()
	req, err := http.NewRequestWithContext(ctx, http.MethodGet, u.String(), nil)
	if err != nil {
		return nil, err
	}
	if c.authUser != "" {
		req.SetBasicAuth(c.authUser, c.authPass)
	}
	resp, err := c.http.Do(req)
	if err != nil {
		return nil, err
	}
	defer resp.Body.Close()
	if resp.StatusCode != http.StatusOK {
		return nil, fmt.Errorf("nbi: unexpected status %d", resp.StatusCode)
	}
	body, err := io.ReadAll(io.LimitReader(resp.Body, maxBody+1))
	if err != nil {
		return nil, err
	}
	if len(body) > maxBody {
		return nil, fmt.Errorf("nbi: response exceeds %d bytes", maxBody)
	}
	var docs []map[string]any
	if err := json.Unmarshal(body, &docs); err != nil {
		return nil, fmt.Errorf("nbi: decode: %w", err)
	}
	out := make([]DeviceParams, 0, len(docs))
	for _, d := range docs {
		id, _ := d["_id"].(string)
		if id == "" {
			continue
		}
		m, rej := ExtractMetrics(d)
		out = append(out, DeviceParams{ID: id, Metrics: m, Rejected: rej})
	}
	return out, nil
}
