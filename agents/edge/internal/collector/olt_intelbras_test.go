package collector

import (
	"context"
	"encoding/json"
	"errors"
	"os"
	"path/filepath"
	"testing"

	"github.com/keslleykledston/44-fibercore_ai/agents/edge/internal/olt"
)

// ibFileSession serves the sanitized Intelbras 8820 fixtures and, like the Telnet session, carries the login banner.
type ibFileSession struct{ sent []string }

func (f *ibFileSession) Banner() string { return "Intelbras Embedded Platform 16.2 olt8820plus\n" }

func (f *ibFileSession) Run(_ context.Context, cmd string) (string, error) {
	f.sent = append(f.sent, cmd)
	m := map[string]string{"card stats": "card_stats.txt", "olt show port": "olt_show_port.txt", "onu status": "onu_status.txt"}
	n, ok := m[cmd]
	if !ok {
		return "", errors.New("unexpected " + cmd)
	}
	b, err := os.ReadFile(filepath.Join("..", "olt", "testdata", "intelbras_8820", n))
	return string(b), err
}

func TestOLTIntelbrasSnapshotIsIdentifiedNeverComplete(t *testing.T) {
	raw := &ibFileSession{}
	c := &OLT{EdgeID: "e1", Sources: []OLTSource{{
		Name: "OLT-IB", Driver: olt.Intelbras{},
		Open: func(context.Context) (olt.Session, func(), error) { return raw, func() {}, nil },
	}}}
	items, err := c.Collect(context.Background())
	if err != nil || len(items) != 1 {
		t.Fatalf("items=%d err=%v", len(items), err)
	}
	var snap struct {
		Vendor, Model, Firmware string
		DriverLevel             string `json:"driver_level"`
		PONs                    []struct {
			Path     string `json:"pon_path"`
			Status   string
			Complete bool
		} `json:"pons"`
		ONUs []struct {
			Serial string
			Pon    string `json:"pon_path"`
			Status string
			Rx     *float64 `json:"rx_dbm"`
		} `json:"onus"`
	}
	if err := json.Unmarshal(items[0].Payload, &snap); err != nil {
		t.Fatal(err)
	}
	if snap.Vendor != "intelbras" || snap.Model != "OLT8820PLUS" || snap.Firmware != "2.112" || snap.DriverLevel != "identified" {
		t.Fatalf("head = %+v", snap)
	}
	if len(snap.PONs) != 3 || len(snap.ONUs) != 16 {
		t.Fatalf("pons=%d onus=%d", len(snap.PONs), len(snap.ONUs))
	}
	for _, p := range snap.PONs {
		if p.Complete || (p.Status != "up" && p.Status != "down" && p.Status != "unknown") {
			t.Errorf("PON %+v: identified level must never be complete; status in up|down|unknown", p)
		}
	}
	for _, u := range snap.ONUs {
		if len(u.Serial) < 1 || len(u.Serial) > 128 || u.Pon == "" || (u.Rx != nil && (*u.Rx < -50 || *u.Rx > 10)) {
			t.Errorf("ONU %+v breaks the ingest contract", u)
		}
	}
	for _, cmd := range raw.sent {
		if !olt.IntelbrasAllowed(cmd) {
			t.Errorf("collector sent %q", cmd)
		}
	}
}
