package collector

import (
	"context"
	"encoding/json"
	"fmt"
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
	g := &GenieACS{EdgeID: "e1", ConnectorID: "genieacs-lab", Client: fakeLister{[]nbi.Device{dev(1, "S1"), dev(2, "")}},
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
		devs = append(devs, dev(i, fmt.Sprintf("S%d", i)))
	}
	items, _ := (&GenieACS{EdgeID: "e", ConnectorID: "c", Client: fakeLister{devs}}).Collect(context.Background())
	if len(items) != 2 {
		t.Fatalf("want 2 snapshots, got %d", len(items))
	}
}
