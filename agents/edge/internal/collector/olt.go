package collector

import (
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"time"

	"github.com/keslleykledston/44-fibercore_ai/agents/edge/internal/olt"
)

// OLTSource is one configured OLT. Open returns a raw CLI session (SSH) plus its closer.
type OLTSource struct {
	Name            string
	Driver          olt.Driver
	Ports           []string
	AllowUnverified bool // collect even if firmware has no fixture coverage; level stays "identified"
	Open            func(ctx context.Context) (olt.Session, func(), error)
}

const (
	oltTimeout     = 5 * time.Minute
	maxBytesPerOLT = 32 << 20
)

// commandBudget: worst case is 3 commands per PON (ZTE) plus Identify twice (collector + driver Snapshot) and slack.
func commandBudget(ports int) int { return 3*ports + 8 }

type OLT struct {
	EdgeID  string
	Sources []OLTSource
	Now     func() time.Time
}

func (o *OLT) Name() string { return "olt" }

type onuJSON struct {
	Serial string   `json:"serial"`
	Pon    string   `json:"pon_path,omitempty"`
	Status string   `json:"status"`
	Rx     *float64 `json:"rx_dbm"`
}
type ponJSON struct {
	Path   string `json:"pon_path"`
	Status string `json:"status"`
}
type oltSnapshotJSON struct {
	EdgeID      string    `json:"edge_id"`
	ObservedAt  string    `json:"observed_at"`
	Name        string    `json:"name"`
	Vendor      string    `json:"vendor"`
	Model       string    `json:"model,omitempty"`
	Firmware    string    `json:"firmware,omitempty"`
	DriverLevel string    `json:"driver_level"`
	PONs        []ponJSON `json:"pons"`
	ONUs        []onuJSON `json:"onus"`
}

// Collect gathers every OLT; one OLT failing never hides the others (partial items + joined error are returned).
func (o *OLT) Collect(ctx context.Context) ([]Item, error) {
	now := o.Now
	if now == nil {
		now = time.Now
	}
	var items []Item
	var errs []error
	for _, src := range o.Sources {
		its, err := o.collectOne(ctx, src, now().UTC().Format(time.RFC3339))
		if err != nil {
			errs = append(errs, fmt.Errorf("olt %s: %w", src.Name, err))
			continue
		}
		items = append(items, its...)
	}
	return items, errors.Join(errs...)
}

func (o *OLT) collectOne(ctx context.Context, src OLTSource, observed string) ([]Item, error) {
	raw, closeFn, err := src.Open(ctx)
	if err != nil {
		return nil, err
	}
	defer closeFn()
	// Per-OLT limits: wall-clock, commands and total bytes (worst case stays bounded regardless of port count).
	ctx, cancel := context.WithTimeout(ctx, oltTimeout)
	defer cancel()
	sess := olt.NewBudget(olt.ReadOnlySession{Inner: raw, Allowed: src.Driver.Allowed}, commandBudget(len(src.Ports)), maxBytesPerOLT)
	id, err := src.Driver.Identify(ctx, sess)
	if err != nil {
		return nil, err
	}
	level, lerr := olt.Lookup(id)
	if lerr != nil && !src.AllowUnverified {
		return nil, lerr // unknown firmware: refuse to parse output we have no evidence for
	}
	snap, err := src.Driver.Snapshot(ctx, sess, src.Ports)
	if err != nil {
		return nil, err
	}
	head := oltSnapshotJSON{
		EdgeID: o.EdgeID, ObservedAt: observed, Name: src.Name, Vendor: id.Vendor, Model: id.Model, Firmware: id.Firmware,
		DriverLevel: string(level), PONs: []ponJSON{}, ONUs: []onuJSON{},
	}
	for _, p := range snap.PONs {
		head.PONs = append(head.PONs, ponJSON{Path: p.Path, Status: p.Status})
	}
	var items []Item
	cur := head
	flush := func() error {
		b, err := json.Marshal(cur)
		if err != nil {
			return err
		}
		items = append(items, Item{Kind: "olt_snapshot", Key: "olt:" + src.Name, Payload: b})
		cur = head
		cur.PONs = []ponJSON{} // PONs travel with the first chunk only
		cur.ONUs = []onuJSON{}
		return nil
	}
	for _, u := range snap.ONUs {
		cur.ONUs = append(cur.ONUs, onuJSON{Serial: u.Serial, Pon: u.PonPath, Status: u.Status, Rx: u.RxDBm})
		if len(cur.ONUs) == maxPerSnapshot {
			if err := flush(); err != nil {
				return nil, err
			}
		}
	}
	if len(cur.ONUs) > 0 || len(items) == 0 {
		if err := flush(); err != nil {
			return nil, err
		}
	}
	return items, nil
}
