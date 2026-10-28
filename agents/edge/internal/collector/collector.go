// Package collector turns read-only observations into Cloud snapshot payloads.
package collector

import (
	"context"
	"encoding/json"
	"time"

	"github.com/keslleykledston/44-fibercore_ai/agents/edge/internal/nbi"
)

// Item is a ready-to-queue payload.
type Item struct {
	Kind    string
	Payload []byte
}

// Collector gathers one read-only observation round. Implementations MUST NOT write to devices.
type Collector interface {
	Name() string
	Collect(ctx context.Context) ([]Item, error)
}

type DeviceLister interface {
	Devices(ctx context.Context) ([]nbi.Device, error)
}

type GenieACS struct {
	EdgeID      string
	ConnectorID string
	Client      DeviceLister
	Now         func() time.Time
}

func (g *GenieACS) Name() string { return "genieacs" }

type cpeBinding struct {
	Protocol    string `json:"protocol"`
	ExternalID  string `json:"external_id"`
	ConnectorID string `json:"connector_id"`
}
type cpeIn struct {
	CanonicalSerial string     `json:"canonical_serial"`
	Vendor          string     `json:"vendor,omitempty"`
	Model           string     `json:"model,omitempty"`
	Binding         cpeBinding `json:"binding"`
}
type cpeSnapshot struct {
	EdgeID     string  `json:"edge_id"`
	ObservedAt string  `json:"observed_at"`
	CPEs       []cpeIn `json:"cpes"`
}

const maxPerSnapshot = 5000 // keep in sync with the Cloud limit

func (g *GenieACS) Collect(ctx context.Context) ([]Item, error) {
	devs, err := g.Client.Devices(ctx)
	if err != nil {
		return nil, err
	}
	now := g.Now
	if now == nil {
		now = time.Now
	}
	observed := now().UTC().Format(time.RFC3339)
	var items []Item
	var batch []cpeIn
	flush := func() error {
		if len(batch) == 0 {
			return nil
		}
		b, err := json.Marshal(cpeSnapshot{EdgeID: g.EdgeID, ObservedAt: observed, CPEs: batch})
		if err != nil {
			return err
		}
		items = append(items, Item{Kind: "cpe_snapshot", Payload: b})
		batch = nil
		return nil
	}
	for _, d := range devs {
		serial := d.DeviceID.SerialNumber
		if serial == "" || d.ID == "" {
			continue // cannot be keyed canonically; skip rather than invent identity
		}
		batch = append(batch, cpeIn{
			CanonicalSerial: serial, Vendor: d.DeviceID.Manufacturer, Model: d.DeviceID.ProductClass,
			Binding: cpeBinding{Protocol: "tr069", ExternalID: d.ID, ConnectorID: g.ConnectorID},
		})
		if len(batch) == maxPerSnapshot {
			if err := flush(); err != nil {
				return nil, err
			}
		}
	}
	return items, flush()
}
