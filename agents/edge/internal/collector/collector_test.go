package collector

import (
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"net/http"
	"net/http/httptest"
	"os"
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
		if r.Method != http.MethodGet || r.URL.Path != "/devices" || r.URL.Query().Get("projection") != "_id,_lastInform,_deviceId" {
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
}

func (f *fakeParams) CachedParams(_ context.Context, ids []string) ([]nbi.DeviceParams, error) {
	f.asked = append(f.asked, ids...)
	if f.err != nil {
		return nil, f.err
	}
	var out []nbi.DeviceParams
	for id, ms := range f.byID { // includes ids that were NOT asked for, on purpose
		out = append(out, nbi.DeviceParams{ID: id, Metrics: ms})
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
	p := &fakeParams{byID: map[string][]nbi.Metric{}}
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
