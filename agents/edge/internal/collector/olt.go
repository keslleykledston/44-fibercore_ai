package collector

import (
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"sync"
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
	// SNMP transport (alternative to Open): when OpenSNMP is set the OLT is read by SNMPDriver and Open/Driver are unused.
	OpenSNMP   func(ctx context.Context) (olt.SNMPReader, func(), error)
	SNMPDriver olt.SNMPDriver
	// SNMPKey identifies the PHYSICAL agent (canonical ip:port). The per-device lock and cooldown are keyed by it, so two
	// configured names for one agent cannot evade them. Empty falls back to Name.
	SNMPKey string
}

const (
	oltTimeout     = 5 * time.Minute
	maxBytesPerOLT = 32 << 20
)

// ponComplete: a PON is complete only when the driver is observed AND either the transport proves where each command ends
// or the driver proved the listing complete in band (the CLI's own total matched the parsed rows).
func ponComplete(level olt.Level, raw olt.Session, p olt.PON) bool {
	return level == olt.LevelObserved && (olt.EndProven(raw) || p.Verified)
}

func commandBudget(ports int) int { return 4*ports + 8 }

type OLT struct {
	EdgeID  string
	Sources []OLTSource
	Now     func() time.Time

	mu   sync.Mutex
	cool map[string]time.Time // SNMP: OLT name -> do not touch before this instant
	busy map[string]bool      // SNMP: OLT names with a collection in flight
}

// snmpCooldown: after ANY failed SNMP collection of an OLT the Edge leaves its agent alone for this long. The measured
// MA5608T agent goes mute for over a minute once its rate limit trips, and retrying into a mute agent only prolongs it (and
// starves the operator's own monitoring that shares the community).
const snmpCooldown = 5 * time.Minute

func (o *OLT) Name() string { return "olt" }

type onuJSON struct {
	Serial string   `json:"serial"`
	Pon    string   `json:"pon_path,omitempty"`
	Status string   `json:"status"`
	Rx     *float64 `json:"rx_dbm"`
}
type ponJSON struct {
	Path     string `json:"pon_path"`
	Status   string `json:"status"`
	Complete bool   `json:"complete"` // every ONU of the port is listed AND the driver can prove it (observed level only)
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
	if src.OpenSNMP != nil {
		return o.collectSNMPCooled(ctx, src, observed)
	}
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
	return o.buildItems(src.Name, observed, id, level, snap, func(p olt.PON) bool { return ponComplete(level, raw, p) })
}

func (o *OLT) now() time.Time {
	if o.Now != nil {
		return o.Now()
	}
	return time.Now()
}

// collectSNMPCooled guards every SNMP collection of an OLT: ONE at a time (reserved under the lock BEFORE any I/O, so the
// periodic worker and a job cannot both talk to the agent) and none during the cooldown that follows a failure. While
// reserved or cooling, nothing is sent to the device.
func (o *OLT) collectSNMPCooled(ctx context.Context, src OLTSource, observed string) ([]Item, error) {
	key := src.SNMPKey
	if key == "" {
		key = src.Name
	}
	o.mu.Lock()
	if o.busy[key] {
		o.mu.Unlock()
		return nil, errors.New("snmp collection already running for this olt")
	}
	if now, until := o.now(), o.cool[key]; now.Before(until) {
		o.mu.Unlock()
		return nil, fmt.Errorf("snmp cooling down after a failure (%s left)", until.Sub(now).Round(time.Second))
	}
	if o.busy == nil {
		o.busy = map[string]bool{}
	}
	o.busy[key] = true
	o.mu.Unlock()

	items, err := o.collectSNMP(ctx, src, observed)

	o.mu.Lock()
	delete(o.busy, key)
	if err != nil {
		if o.cool == nil {
			o.cool = map[string]time.Time{}
		}
		o.cool[key] = o.now().Add(snmpCooldown)
	}
	o.mu.Unlock()
	return items, err
}

// collectSNMP reads an OLT over SNMP. The end of an SNMP table is unambiguous, so completeness is whatever the driver proved
// in band (PON.Verified), and still requires an observed driver level.
func (o *OLT) collectSNMP(ctx context.Context, src OLTSource, observed string) ([]Item, error) {
	r, closeFn, err := src.OpenSNMP(ctx)
	if err != nil {
		return nil, err
	}
	defer closeFn()
	ctx, cancel := context.WithTimeout(ctx, oltTimeout)
	defer cancel()
	id, err := src.SNMPDriver.Identify(ctx, r, src.Ports)
	if err != nil {
		return nil, err
	}
	level, lerr := olt.Lookup(id)
	if lerr != nil && !src.AllowUnverified {
		return nil, lerr
	}
	snap, err := src.SNMPDriver.Snapshot(ctx, r, src.Ports)
	if err != nil {
		return nil, err
	}
	return o.buildItems(src.Name, observed, id, level, snap, func(p olt.PON) bool { return level == olt.LevelObserved && p.Verified })
}

// buildItems turns a snapshot into chunked payload items. complete decides, per PON, whether it may be reported complete
// (it drives mass-outage incident correlation, so it must be backed by proof, never assumed).
func (o *OLT) buildItems(name, observed string, id olt.Identity, level olt.Level, snap olt.Snapshot, complete func(olt.PON) bool) ([]Item, error) {
	head := oltSnapshotJSON{
		EdgeID: o.EdgeID, ObservedAt: observed, Name: name, Vendor: id.Vendor, Model: id.Model, Firmware: id.Firmware,
		DriverLevel: string(level), PONs: []ponJSON{}, ONUs: []onuJSON{},
	}
	// Completeness drives mass-outage incident correlation, so it is only asserted for drivers whose parsers were validated
	// against real captures (observed). Synthetic-fixture drivers cannot tell a full listing from one cut without a pager
	// prompt, so their PONs are reported as not complete and can neither open nor close an incident.
	for _, p := range snap.PONs {
		head.PONs = append(head.PONs, ponJSON{Path: p.Path, Status: p.Status, Complete: complete(p)})
	}
	var items []Item
	cur := head
	flush := func() error {
		b, err := json.Marshal(cur)
		if err != nil {
			return err
		}
		items = append(items, Item{Kind: "olt_snapshot", Key: "olt:" + name, Payload: b})
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
