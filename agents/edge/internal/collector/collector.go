// Package collector turns read-only observations into Cloud snapshot payloads.
package collector

import (
	"context"
	"encoding/json"
	"regexp"
	"strings"
	"time"

	"github.com/keslleykledston/44-fibercore_ai/agents/edge/internal/nbi"
)

// Item is a ready-to-queue payload.
type Item struct {
	Kind    string
	Key     string // logical stream; a newer complete round of the same Key supersedes older queued items
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
	// OnSkip, when set, receives how many devices were left out and why ("no_serial", "placeholder_identity"); nothing identifying.
	OnSkip func(reason string, n int)

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

// placeholderID is the identity GenieACS/CPEs use BEFORE a device is really known (observed on the real server: Huawei ONTs informing
// as DISCOVERYSERVICE with a fresh random serial each time). It is not an inventory identity: ingesting it would create a new fake CPE
// per Inform. Counts of what was dropped are reported through OnSkip, never the identifiers.
const placeholderID = "DISCOVERYSERVICE"

// A serial is a CLAIM made by the device itself (CWMP is reachable by anyone who finds the port). Only a plain identifier is accepted; the
// rest (control characters, huge strings, markup) is dropped and counted.
var serialRe = regexp.MustCompile(`^[A-Z0-9][A-Z0-9._-]{3,63}$`)

// canonicalSerial is the ONE form the Cloud stores (trimmed, upper case); grouping and validation use it so case/space variants of a
// serial collapse into the same claim instead of looking like two devices.
func canonicalSerial(s string) string { return strings.ToUpper(strings.TrimSpace(s)) }

func isPlaceholder(d nbi.Device) bool {
	return d.DeviceID.OUI == placeholderID || d.DeviceID.Manufacturer == placeholderID || d.DeviceID.ProductClass == placeholderID
}

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
		items = append(items, Item{Kind: "cpe_snapshot", Key: "cpe:" + g.ConnectorID, Payload: b})
		batch = nil
		return nil
	}
	skipped := map[string]int{}
	defer func() {
		if g.OnSkip != nil {
			for _, r := range []string{"no_serial", "invalid_serial", "placeholder_identity", "conflicting_serial"} {
				if skipped[r] > 0 {
					g.OnSkip(r, skipped[r])
				}
			}
		}
	}()
	// Two DIFFERENT devices claiming the same serial cannot both be true and nothing here can tell which one is: drop every claim.
	claims := map[string]map[string]bool{}
	for _, d := range devs {
		if !isPlaceholder(d) && d.ID != "" {
			k := canonicalSerial(d.DeviceID.SerialNumber)
			if claims[k] == nil {
				claims[k] = map[string]bool{}
			}
			claims[k][d.ID] = true
		}
	}
	for _, d := range devs {
		if isPlaceholder(d) {
			skipped["placeholder_identity"]++
			continue
		}
		serial := canonicalSerial(d.DeviceID.SerialNumber)
		if serial == "" || d.ID == "" {
			skipped["no_serial"]++
			continue // cannot be keyed canonically; skip rather than invent identity
		}
		if !serialRe.MatchString(serial) {
			skipped["invalid_serial"]++
			continue
		}
		if len(claims[serial]) > 1 {
			skipped["conflicting_serial"]++
			continue
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
