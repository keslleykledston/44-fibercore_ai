package collector

import (
	"context"
	"encoding/json"
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
