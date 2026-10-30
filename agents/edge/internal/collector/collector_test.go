package collector

import (
	"bytes"
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"net/http"
	"net/http/httptest"
	"os"
	"path/filepath"
	"sort"
	"strings"
	"testing"
	"time"

	"github.com/keslleykledston/44-fibercore_ai/agents/edge/internal/nbi"
)

type fakeLister struct{ devs []nbi.Device }

func (f fakeLister) Devices(context.Context) ([]nbi.Device, error) { return f.devs, nil }

func dev(i int, serial string) nbi.Device {
	return nbi.Device{ID: fmt.Sprintf("OUI-PC-%d", i), DeviceID: nbi.DeviceID{Manufacturer: "Huawei", ProductClass: "HG8245H", SerialNumber: serial}}
}

func TestSnapshotShapeMatchesCloudContract(t *testing.T) {
	g := &GenieACS{EdgeID: "e1", ConnectorID: "genieacs-lab", Client: fakeLister{[]nbi.Device{dev(1, "SER00001"), dev(2, "")}},
		Now: func() time.Time { return time.Date(2026, 10, 28, 1, 2, 3, 0, time.UTC) }}
	items, err := g.Collect(context.Background())
	if err != nil || len(items) != 1 || items[0].Kind != "cpe_snapshot" {
		t.Fatalf("items=%v err=%v", items, err)
	}
	var snap map[string]any
	_ = json.Unmarshal(items[0].Payload, &snap)
	if snap["edge_id"] != "e1" || snap["observed_at"] != "2026-10-28T01:02:03Z" {
		t.Fatalf("snap=%v", snap)
	}
	cpes := snap["cpes"].([]any)
	if len(cpes) != 1 { // device without serial is skipped, identity never invented
		t.Fatalf("cpes=%v", cpes)
	}
	b := cpes[0].(map[string]any)["binding"].(map[string]any)
	if b["protocol"] != "tr069" || b["external_id"] != "OUI-PC-1" || b["connector_id"] != "genieacs-lab" {
		t.Fatalf("binding=%v", b)
	}
}

func TestBatchesAtCloudLimit(t *testing.T) {
	var devs []nbi.Device
	for i := 0; i < maxPerSnapshot+1; i++ {
		devs = append(devs, dev(i, fmt.Sprintf("SER%06d", i)))
	}
	items, _ := (&GenieACS{EdgeID: "e", ConnectorID: "c", Client: fakeLister{devs}}).Collect(context.Background())
	if len(items) != 2 {
		t.Fatalf("want 2 snapshots, got %d", len(items))
	}
}

// Structure of a real GenieACS /devices answer (captured read-only from the production-like server; ALL values here are synthetic):
// provisional DISCOVERYSERVICE identities with a random serial per Inform, a serial with a hyphen, a URL-encoded _id, an empty serial.
func TestRealNBIShapeSkipsPlaceholdersAndReportsOnlyCounts(t *testing.T) {
	raw, err := os.ReadFile("testdata/nbi_devices_structure.json")
	if err != nil {
		t.Fatal(err)
	}
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.Method != http.MethodGet || r.URL.Path != "/devices" || r.URL.Query().Get("projection") != "_id,_lastInform,_deviceId,InternetGatewayDevice.DeviceInfo.SoftwareVersion,Device.DeviceInfo.SoftwareVersion" {
			t.Errorf("unexpected request %s %s", r.Method, r.URL.String())
		}
		_, _ = w.Write(raw)
	}))
	defer srv.Close()
	c, err := nbi.New(srv.URL, srv.Client(), "")
	if err != nil {
		t.Fatal(err)
	}
	skips := map[string]int{}
	g := &GenieACS{EdgeID: "e1", ConnectorID: "genieacs-lab", Client: c, OnSkip: func(r string, n int) { skips[r] = n }}
	items, err := g.Collect(context.Background())
	if err != nil || len(items) != 1 {
		t.Fatalf("items=%d err=%v", len(items), err)
	}
	var snap struct {
		CPEs []struct {
			CanonicalSerial string `json:"canonical_serial"`
			Binding         struct {
				ExternalID string `json:"external_id"`
			} `json:"binding"`
		} `json:"cpes"`
	}
	if err := json.Unmarshal(items[0].Payload, &snap); err != nil {
		t.Fatal(err)
	}
	got := map[string]string{}
	for _, c := range snap.CPEs {
		got[c.CanonicalSerial] = c.Binding.ExternalID
	}
	want := map[string]string{"SYNLOW00001": "6666FF-ONT-SYNLOW", "SYN0000001": "AAAA00-HG8245H-SYN0000001", "SYN-00000002": "BBBB11-G3000E-SYN-00000002", "SYN0000003": "CCCC22-hAP%20lite-SYN0000003"}
	if len(got) != len(want) {
		t.Fatalf("got %v", got)
	}
	for k, v := range want {
		if got[k] != v {
			t.Fatalf("serial %s: external_id %q want %q", k, got[k], v)
		}
	}
	for _, bad := range []string{"SYNDUP0001", "<script>", "INJECT01", "SYNCASE0001", "synlow"} {
		if strings.Contains(string(items[0].Payload), bad) {
			t.Fatalf("hostile or conflicting claim %q reached the snapshot", bad)
		}
	}
	if strings.Contains(string(items[0].Payload), "DISCOVERYSERVICE") {
		t.Fatal("placeholder identity leaked into the snapshot")
	}
	if skips["placeholder_identity"] != 2 || skips["no_serial"] != 1 || skips["invalid_serial"] != 3 || skips["conflicting_serial"] != 4 {
		t.Fatalf("skips=%v", skips)
	}
}

// Conflicting claims are classified over the WHOLE NBI answer, before it is split into Cloud-sized snapshots: a serial claimed by two
// different devices on opposite sides of the chunk boundary must be dropped, not accepted in whichever chunk happens to come first.
func TestConflictAcrossTheChunkBoundaryIsStillDropped(t *testing.T) {
	var devs []nbi.Device
	for i := 0; i < maxPerSnapshot+3; i++ {
		devs = append(devs, dev(i, fmt.Sprintf("SER%06d", i)))
	}
	devs[0].DeviceID.SerialNumber = "SPLIT-CLAIM-1"
	devs[maxPerSnapshot+1].DeviceID.SerialNumber = "split-claim-1" // same canonical serial, different _id, other side of the boundary
	items, err := (&GenieACS{EdgeID: "e", ConnectorID: "c", Client: fakeLister{devs}}).Collect(context.Background())
	if err != nil || len(items) != 2 {
		t.Fatalf("items=%d err=%v", len(items), err)
	}
	total := 0
	for _, it := range items {
		if strings.Contains(strings.ToUpper(string(it.Payload)), "SPLIT-CLAIM-1") {
			t.Fatalf("a conflicting claim survived chunking")
		}
		var snap struct {
			CPEs []json.RawMessage `json:"cpes"`
		}
		if err := json.Unmarshal(it.Payload, &snap); err != nil {
			t.Fatal(err)
		}
		total += len(snap.CPEs)
	}
	if total != maxPerSnapshot+3-2 {
		t.Fatalf("total cpes %d", total)
	}
}

type fakeParams struct {
	byID  map[string][]nbi.Metric
	err   error
	asked []string
	calls int
}

// CachedParams answers for the ids it is asked about and, on the FIRST call only, also for ids nobody asked about (a reader must not be trusted
// to stay inside the request).
func (f *fakeParams) CachedParams(_ context.Context, ids []string) ([]nbi.DeviceParams, error) {
	f.asked = append(f.asked, ids...)
	f.calls++
	if f.err != nil {
		return nil, f.err
	}
	asked := map[string]bool{}
	for _, id := range ids {
		asked[id] = true
	}
	var out []nbi.DeviceParams
	for id, ms := range f.byID {
		if asked[id] || f.calls == 1 {
			out = append(out, nbi.DeviceParams{ID: id, Metrics: ms})
		}
	}
	return out, nil
}

func stateNow() time.Time { return time.Date(2026, 10, 29, 12, 0, 0, 0, time.UTC) }

func metric(name, scope string, v any, at string) nbi.Metric {
	return nbi.Metric{Name: name, Scope: scope, Value: v, CapturedAt: at}
}

func TestStateFollowsInventoryAndOnlyCarriesKeptDevices(t *testing.T) {
	ok := dev(1, "SER00001")
	placeholder := nbi.Device{ID: "DISCOVERYSERVICE-DISCOVERYSERVICE-x", DeviceID: nbi.DeviceID{OUI: "DISCOVERYSERVICE", Manufacturer: "DISCOVERYSERVICE", ProductClass: "DISCOVERYSERVICE", SerialNumber: "x1234"}}
	noSerial := dev(3, "")
	p := &fakeParams{byID: map[string][]nbi.Metric{
		ok.ID:          {metric("wan_link_status", "link/1", "Up", "2026-10-29T11:59:00Z"), metric("wifi_channel", "radio/5", 36.0, "2026-10-29T11:59:01Z")},
		placeholder.ID: {metric("wan_link_status", "link/1", "Up", "2026-10-29T11:59:00Z")}, // a reader that answers for a device never asked about
		"OUI-PC-999":   {metric("wan_link_status", "link/1", "Up", "2026-10-29T11:59:00Z")},
	}}
	g := &GenieACS{EdgeID: "e1", ConnectorID: "genieacs-lab", Client: fakeLister{[]nbi.Device{ok, placeholder, noSerial}}, Params: p, Now: stateNow}
	items, err := g.Collect(context.Background())
	if err != nil || len(items) != 2 || items[0].Kind != "cpe_snapshot" || items[1].Kind != "cpe_state" || items[1].Key != "cpe_state:genieacs-lab" {
		t.Fatalf("%v %+v", err, items)
	}
	if len(p.asked) != 1 || p.asked[0] != ok.ID {
		t.Fatalf("state may only be requested for devices kept in the inventory, asked %v", p.asked)
	}
	var got map[string]any
	if err := json.Unmarshal(items[1].Payload, &got); err != nil {
		t.Fatal(err)
	}
	states := got["states"].([]any)
	if got["edge_id"] != "e1" || got["observed_at"] != "2026-10-29T12:00:00Z" || len(states) != 1 {
		t.Fatalf("%v", got)
	}
	st := states[0].(map[string]any)
	b := st["binding"].(map[string]any)
	if b["protocol"] != "tr069" || b["external_id"] != ok.ID || b["connector_id"] != "genieacs-lab" || len(st["metrics"].([]any)) != 2 {
		t.Fatalf("%v", st)
	}
	m0 := st["metrics"].([]any)[0].(map[string]any)
	for _, k := range []string{"name", "scope", "value", "captured_at"} {
		if _, has := m0[k]; !has || len(m0) != 4 {
			t.Fatalf("metric must have exactly name/scope/value/captured_at, got %v", m0)
		}
	}
}

func TestStateReadFailureNeverCostsTheInventory(t *testing.T) {
	skips := map[string]int{}
	g := &GenieACS{EdgeID: "e1", ConnectorID: "c", Client: fakeLister{[]nbi.Device{dev(1, "SER00001")}},
		Params: &fakeParams{err: errors.New("acs down")}, Now: stateNow, OnSkip: func(r string, n int) { skips[r] = n }}
	items, err := g.Collect(context.Background())
	if err != nil || len(items) != 1 || items[0].Kind != "cpe_snapshot" || skips["state_read_failed"] != 1 {
		t.Fatalf("%v %+v %v", err, items, skips)
	}
}

func TestStateWithNoMetricsOrFutureClockSendsNothingForThatDevice(t *testing.T) {
	a, b, c := dev(1, "SER00001"), dev(2, "SER00002"), dev(3, "SER00003")
	skips := map[string]int{}
	p := &fakeParams{byID: map[string][]nbi.Metric{
		a.ID: nil,                                                                                                                       // nothing cached yet
		b.ID: {metric("wan_link_status", "link/1", "Up", "2026-10-29T12:30:00Z")},                                                       // 30 min ahead: dropped
		c.ID: {metric("wan_link_status", "link/1", "Up", "not a time"), metric("wifi_channel", "radio/1", 6.0, "2026-10-29T12:00:30Z")}, // 30 s ahead is within skew
	}}
	g := &GenieACS{EdgeID: "e", ConnectorID: "c", Client: fakeLister{[]nbi.Device{a, b, c}}, Params: p, Now: stateNow, OnSkip: func(r string, n int) { skips[r] = n }}
	items, err := g.Collect(context.Background())
	if err != nil || len(items) != 2 {
		t.Fatalf("%v %+v", err, items)
	}
	var got cpeStateSnapshot
	if err := json.Unmarshal(items[1].Payload, &got); err != nil || len(got.States) != 1 || got.States[0].Binding.ExternalID != c.ID || len(got.States[0].Metrics) != 1 || got.States[0].Metrics[0].Name != "wifi_channel" {
		t.Fatalf("%v %+v", err, got)
	}
	if skips["state_future_timestamp"] != 2 {
		t.Fatalf("future/invalid timestamps must be counted, got %v", skips)
	}
	// nothing at all to send: no empty cpe_state item
	g.Params = &fakeParams{byID: map[string][]nbi.Metric{}}
	if items, _ := g.Collect(context.Background()); len(items) != 1 {
		t.Fatalf("an empty state round must not produce an item: %+v", items)
	}
}

func TestStateIsSplitIntoBoundedItems(t *testing.T) {
	var devs []nbi.Device
	p := &batchParams{byID: map[string][]nbi.Metric{}}
	for i := 1; i <= 450; i++ {
		d := dev(i, fmt.Sprintf("SER%05d", i))
		devs = append(devs, d)
		p.byID[d.ID] = []nbi.Metric{metric("wan_link_status", "link/1", "Up", "2026-10-29T11:59:00Z")}
	}
	items, err := (&GenieACS{EdgeID: "e", ConnectorID: "c", Client: fakeLister{devs}, Params: p, Now: stateNow}).Collect(context.Background())
	if err != nil || len(items) != 1+3 { // one inventory snapshot + 200 + 200 + 50
		t.Fatalf("%v items=%d", err, len(items))
	}
	for _, it := range items[1:] {
		var s cpeStateSnapshot
		if json.Unmarshal(it.Payload, &s) != nil || len(s.States) > maxStatesPerItem || it.Kind != "cpe_state" {
			t.Fatalf("%+v", it)
		}
	}
}

func lf(v any) map[string]any {
	return map[string]any{"_value": v, "_type": "x", "_timestamp": "2026-10-29T11:59:00.000Z"}
}

// The payload below is produced by the REAL parser from a realistic ACS document (every metric, both data models) and compared with the golden
// file the Cloud tests post verbatim (apps/api/tests/test_inventory_cpe_state.py): both sides agree on value formats, not only on names.
// Regenerate with UPDATE_GOLDEN=1 after a deliberate change.
func TestCPEStatePayloadFromTheRealParserMatchesTheGoldenTheCloudAccepts(t *testing.T) {
	doc := map[string]any{"_id": "OUI-PC-1",
		"InternetGatewayDevice": map[string]any{
			"WANDevice": map[string]any{"1": map[string]any{
				"WANCommonInterfaceConfig": map[string]any{"PhysicalLinkStatus": lf("Up")},
				"WANConnectionDevice": map[string]any{
					"3": map[string]any{"WANPPPConnection": map[string]any{"1": map[string]any{"ConnectionStatus": lf("Connected"), "Uptime": lf("5844")}}},
					"2": map[string]any{"WANIPConnection": map[string]any{"1": map[string]any{"ConnectionStatus": lf("Disconnected"), "Uptime": lf(float64(0))}}}}}},
			"LANDevice": map[string]any{"1": map[string]any{"WLANConfiguration": map[string]any{
				"1": map[string]any{"Enable": lf(true), "Channel": lf(float64(1))},
				"5": map[string]any{"Enable": lf(false), "Channel": lf(float64(36))}}}}},
		"Device": map[string]any{
			"DeviceInfo": map[string]any{"UpTime": lf(float64(86400))},
			"PPP":        map[string]any{"Interface": map[string]any{"1": map[string]any{"Status": lf("LowerLayerDown")}}}}}
	ms, rej := nbi.ExtractMetrics(doc)
	if rej != 0 || len(ms) != 11 {
		t.Fatalf("metrics=%d rejected=%d: %+v", len(ms), rej, ms)
	}
	sort.Slice(ms, func(i, j int) bool { return ms[i].Name+"@"+ms[i].Scope < ms[j].Name+"@"+ms[j].Scope })
	g := &GenieACS{EdgeID: "e1", ConnectorID: "genieacs-lab", Client: fakeLister{[]nbi.Device{dev(1, "SER00001")}},
		Params: &fakeParams{byID: map[string][]nbi.Metric{"OUI-PC-1": ms}}, Now: stateNow}
	items, err := g.Collect(context.Background())
	if err != nil || len(items) != 2 || items[1].Kind != "cpe_state" {
		t.Fatalf("%v %+v", err, items)
	}
	var pretty bytes.Buffer
	if err := json.Indent(&pretty, items[1].Payload, "", "  "); err != nil {
		t.Fatal(err)
	}
	pretty.WriteByte('\n')
	golden := filepath.Join("..", "..", "..", "..", "tests", "fixtures", "cpe_state", "edge-payload.json")
	if os.Getenv("UPDATE_GOLDEN") != "" {
		if err := os.WriteFile(golden, pretty.Bytes(), 0o644); err != nil {
			t.Fatal(err)
		}
	}
	want, err := os.ReadFile(golden)
	if err != nil || !bytes.Equal(want, pretty.Bytes()) {
		t.Fatalf("golden payload differs (run with UPDATE_GOLDEN=1 after a deliberate change): err=%v\n%s", err, pretty.String())
	}
}

type batchParams struct {
	failFor string // any read whose ids include this one fails
	sizes   []int
	byID    map[string][]nbi.Metric
}

func (f *batchParams) CachedParams(_ context.Context, ids []string) ([]nbi.DeviceParams, error) {
	f.sizes = append(f.sizes, len(ids))
	var out []nbi.DeviceParams
	for _, id := range ids {
		if id == f.failFor {
			return nil, errors.New("response too large")
		}
		out = append(out, nbi.DeviceParams{ID: id, Metrics: f.byID[id]})
	}
	return out, nil
}

// One failing read (an oversized ACS answer) costs only its own 25 devices; every other read is kept, and reads never exceed the NBI client's size.
func TestStateReadsAreBatchedAndOneFailureOnlyCostsItsOwnBatch(t *testing.T) {
	var devs []nbi.Device
	p := &batchParams{failFor: "OUI-PC-30", byID: map[string][]nbi.Metric{}}
	for i := 1; i <= 60; i++ {
		d := dev(i, fmt.Sprintf("SER%05d", i))
		devs = append(devs, d)
		p.byID[d.ID] = []nbi.Metric{metric("wan_link_status", "link/1", "Up", "2026-10-29T11:59:00Z")}
	}
	skips := map[string]int{}
	items, err := (&GenieACS{EdgeID: "e", ConnectorID: "c", Client: fakeLister{devs}, Params: p, Now: stateNow,
		OnSkip: func(r string, n int) { skips[r] = n }}).Collect(context.Background())
	if err != nil || len(items) != 2 || skips["state_read_failed"] != 1 {
		t.Fatalf("%v items=%d skips=%v", err, len(items), skips)
	}
	if fmt.Sprint(p.sizes) != "[25 25 10]" {
		t.Fatalf("reads must be batched by 25, got %v", p.sizes)
	}
	var s cpeStateSnapshot
	if err := json.Unmarshal(items[1].Payload, &s); err != nil || len(s.States) != 35 { // 60 devices minus the failed batch of 25 (devices 26..50)
		t.Fatalf("%v states=%d", err, len(s.States))
	}
}

func TestSnapshotCarriesTheFirmwareTheAcsHoldsAndOmitsAnythingElse(t *testing.T) {
	devs := []nbi.Device{
		{ID: "00259E-EG8145V5-SYN0000001", DeviceID: nbi.DeviceID{Manufacturer: "Huawei Technologies Co., Ltd", OUI: "00259E", ProductClass: "EG8145V5", SerialNumber: "SYN0000001"}},
		{ID: "00259E-EG8145V5-SYN0000002", DeviceID: nbi.DeviceID{Manufacturer: "Huawei Technologies Co., Ltd", OUI: "00259E", ProductClass: "EG8145V5", SerialNumber: "SYN0000002"}},
	}
	if err := json.Unmarshal([]byte(`{"InternetGatewayDevice":{"DeviceInfo":{"SoftwareVersion":{"_value":"V5R019C10S350"}}}}`), &devs[0]); err != nil {
		t.Fatal(err)
	}
	items, err := (&GenieACS{EdgeID: "e", ConnectorID: "c", Client: fakeLister{devs}}).Collect(context.Background())
	if err != nil || len(items) != 1 {
		t.Fatalf("items=%d err=%v", len(items), err)
	}
	var snap struct {
		CPEs []struct {
			CanonicalSerial string `json:"canonical_serial"`
			Firmware        string `json:"firmware"`
		} `json:"cpes"`
	}
	if err := json.Unmarshal(items[0].Payload, &snap); err != nil {
		t.Fatal(err)
	}
	fw := map[string]string{}
	for _, c := range snap.CPEs {
		fw[c.CanonicalSerial] = c.Firmware
	}
	if fw["SYN0000001"] != "V5R019C10S350" || fw["SYN0000002"] != "" {
		t.Fatalf("firmware %v", fw)
	}
}
