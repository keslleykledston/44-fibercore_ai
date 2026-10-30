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
	failCooldown    func(error) time.Duration // internal: see Exclusive
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
	// Interval is the minimum time between two attempts on this OLT (success or failure). The Edge's collection tick is shared with
	// the NBI and with the sooner retry after an incomplete round, so without it a real OLT would be logged into on every tick.
	// 0 = every call (tests, SNMP).
	Interval time.Duration
	// Cooldown is how long the OLT is left alone after ANY failed collection. 0 = the transport default (snmpCooldown / cliCooldown).
	Cooldown time.Duration
	// Timeout overrides the wall-clock budget of one attempt (opening the session included). 0 = oltTimeout(len(Ports)).
	Timeout time.Duration
}

func (s OLTSource) budget() time.Duration {
	if s.Timeout > 0 {
		return s.Timeout
	}
	return oltTimeout(len(s.Ports))
}

const (
	maxBytesPerOLT = 32 << 20
	// The Agent cancels a whole collection round after 10 minutes, so a single OLT never gets more than this.
	oltTimeoutMax = 9 * time.Minute
)

// oltTimeout is the wall-clock budget of one OLT collection. A shell session answers about one command per second and the pager
// adds a few pages per PON, so a fixed 5 minutes is enough for a handful of PONs but not for a full 32-PON chassis.
func oltTimeout(ports int) time.Duration {
	d := time.Minute + time.Duration(ports)*15*time.Second
	if d < 5*time.Minute {
		d = 5 * time.Minute
	}
	if d > oltTimeoutMax {
		d = oltTimeoutMax
	}
	return d
}

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

	// Guard persists the pacing state (last attempt, cooldown) so a restart cannot reopen the window. nil = in memory only (tests).
	Guard GuardStore
	// OnCollected, when set, is told how every attempt that reached the device ended (never called for skips): the only way an
	// operator can see how long a real OLT takes and whether it answered. err is the collection error, never device output.
	OnCollected func(name string, took time.Duration, items int, err error)

	mu      sync.Mutex
	st      map[string]GuardState // device key -> pacing state
	busy    map[string]bool       // device keys with a collection in flight
	loaded  bool
	corrupt bool // the state file could not be trusted: a device with no entry is treated as touched just now
}

// ErrOLTNotDue: the shared OLT guard says the last session on this device is too recent for another one now.
var ErrOLTNotDue = errors.New("olt session not due yet (guard interval)")

// Exclusive runs `run` as the ONE session on the named OLT, under the SAME guard as the collections: one at a time, reserved on disk before any
// I/O, not before `minGap` has passed since the last session of any kind, and the usual cooldown after a failure. The bench maneuvers use it so
// a maneuver and a collection can never talk to the device together.
//
// cooldown is how long the device is left alone after a session that FAILED AFTER a successful login (a maneuver that stopped on a question or on a
// check): 0 = the usual CLI default of 15 min. A failure BEFORE the login completes (refused credentials, unreachable, host key) always keeps the
// default, so repeated failed logins can never lock the account that the operator's own tools share. `run` calls `opened()` right after the login.
// The reservation made before the session is the default one in every case (a crash or kill keeps the long cooldown).
func (o *OLT) Exclusive(ctx context.Context, name string, minGap, cooldown time.Duration, run func(opened func()) error) error {
	for _, src := range o.Sources {
		if src.Name != name {
			continue
		}
		src.Interval = minGap
		src.Cooldown = cliCooldown // the reservation and every failure before the login keep the CLI default, whatever the OLT's own (collection) cooldown is
		loggedIn := false
		if cooldown > 0 {
			src.failCooldown = func(error) time.Duration {
				if loggedIn {
					return cooldown
				}
				return 0 // default
			}
		}
		ran := false
		_, err := o.guarded(ctx, src, func() ([]Item, error) {
			ran = true
			return nil, run(func() { loggedIn = true })
		})
		if err == nil && !ran {
			return ErrOLTNotDue
		}
		return err
	}
	return fmt.Errorf("olt %q is not configured", name)
}

// snmpCooldown: after ANY failed SNMP collection of an OLT the Edge leaves its agent alone for this long. The measured
// MA5608T agent goes mute for over a minute once its rate limit trips, and retrying into a mute agent only prolongs it (and
// starves the operator's own monitoring that shares the community).
const snmpCooldown = 5 * time.Minute

// cliCooldown: after a failed CLI collection (bad login, timeout, pager, refused session) the Edge stays away longer than for
// SNMP: repeated failed logins can lock the read-only account that the operator's own tools share.
const cliCooldown = 15 * time.Minute

func (o *OLT) Name() string { return "olt" }

type onuJSON struct {
	Serial string   `json:"serial"`
	Pon    string   `json:"pon_path,omitempty"`
	Status string   `json:"status"`
	Rx     *float64 `json:"rx_dbm"`
	// LastDownAt (UTC, RFC 3339): when the OLT says this OFFLINE ONU last went down (SNMP). Absent = the OLT did not say.
	LastDownAt string `json:"last_down_at,omitempty"`
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
	return o.guarded(ctx, src, func() ([]Item, error) {
		if src.OpenSNMP != nil {
			return o.collectSNMP(ctx, src, observed)
		}
		return o.collectCLI(ctx, src, observed)
	})
}

func (o *OLT) collectCLI(ctx context.Context, src OLTSource, observed string) ([]Item, error) {
	// Per-OLT limits: wall-clock (the login included), commands and total bytes (bounded regardless of port count).
	ctx, cancel := context.WithTimeout(ctx, src.budget())
	defer cancel()
	raw, closeFn, err := src.Open(ctx)
	if err != nil {
		return nil, err
	}
	defer closeFn()
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

func (o *OLT) persistLocked() error {
	if o.Guard == nil {
		return nil
	}
	return o.Guard.Save(o.st)
}

func (o *OLT) now() time.Time {
	if o.Now != nil {
		return o.Now()
	}
	return time.Now()
}

// guarded wraps EVERY collection of a physical OLT (SSH or SNMP): ONE at a time (reserved under the lock BEFORE any I/O, so the
// periodic worker and a job cannot both talk to the device), not before Interval has passed since the last attempt, and none
// during the cooldown that follows a failure. While reserved, not due or cooling, nothing is sent to the device. A collection
// that is simply not due yields nothing and no error (the round is not incomplete); a cooling or busy OLT is reported.
func (o *OLT) guarded(ctx context.Context, src OLTSource, run func() ([]Item, error)) ([]Item, error) {
	key := src.SNMPKey
	if key == "" {
		key = src.Name
	}
	cooldown := src.Cooldown
	if cooldown <= 0 {
		cooldown = cliCooldown
		if src.OpenSNMP != nil {
			cooldown = snmpCooldown
		}
	}
	o.mu.Lock()
	now := o.now()
	if !o.loaded {
		o.st = map[string]GuardState{}
		if o.Guard != nil {
			m, err := o.Guard.Load()
			if err != nil {
				o.corrupt = true
			} else {
				o.st = m
			}
		}
		o.loaded = true
	}
	if o.busy[key] {
		o.mu.Unlock()
		return nil, errors.New("collection already running for this olt")
	}
	cur, known := o.st[key]
	// A clock that jumped (or a tampered file) must neither block the device forever nor be trusted blindly: a timestamp more than
	// a day ahead is pulled back to a normal cooldown from now.
	if limit := now.Add(24 * time.Hour); cur.CoolUntil.After(limit) || cur.Last.After(limit) {
		cur = GuardState{Last: now, CoolUntil: now.Add(cooldown)}
		o.st[key] = cur
		if err := o.persistLocked(); err != nil { // the correction must survive a restart, or the implausible value comes back
			o.mu.Unlock()
			return nil, fmt.Errorf("olt guard cannot persist its state: %w", err)
		}
	}
	if now.Before(cur.CoolUntil) {
		o.mu.Unlock()
		return nil, fmt.Errorf("olt cooling down after a failure (%s left)", cur.CoolUntil.Sub(now).Round(time.Second))
	}
	if o.corrupt && !known { // unknown history (any transport, any interval): behave as if a failure had just happened
		o.st[key] = GuardState{Last: now, CoolUntil: now.Add(cooldown)}
		err := o.persistLocked()
		o.mu.Unlock()
		return nil, err
	}
	if src.Interval > 0 && known && now.Before(cur.Last.Add(src.Interval)) {
		o.mu.Unlock()
		return nil, nil
	}
	// Reserve BEFORE any I/O, pessimistically: the attempt time AND a cooldown as if it were going to fail. A crash, a kill or a
	// failed save after the attempt then cannot reopen the window; only a success (below) lifts the cooldown.
	o.st[key] = GuardState{Last: now, CoolUntil: now.Add(cooldown)}
	if err := o.persistLocked(); err != nil { // fail closed: an attempt that cannot be remembered must not be made
		o.st[key] = cur
		o.mu.Unlock()
		return nil, fmt.Errorf("olt guard cannot persist its state: %w", err)
	}
	if o.busy == nil {
		o.busy = map[string]bool{}
	}
	o.busy[key] = true
	o.mu.Unlock()

	started := o.now()
	items, err := run()
	if o.OnCollected != nil {
		o.OnCollected(src.Name, o.now().Sub(started), len(items), err)
	}

	o.mu.Lock()
	delete(o.busy, key)
	if err == nil {
		o.st[key] = GuardState{Last: o.st[key].Last} // success lifts the pessimistic cooldown; if the save fails the file stays cooled (safe side)
	} else {
		failFor := cooldown
		if src.failCooldown != nil { // a failure AFTER the login may be shorter (bench maneuvers); 0 keeps the default
			if d := src.failCooldown(err); d > 0 {
				failFor = d
			}
		}
		o.st[key] = GuardState{Last: o.st[key].Last, CoolUntil: o.now().Add(failFor)} // counted from the END of the failed attempt
	}
	_ = o.persistLocked() // best effort: the pessimistic reservation already on disk is the floor if this save fails
	o.mu.Unlock()
	return items, err
}

// collectSNMP reads an OLT over SNMP. The end of an SNMP table is unambiguous, so completeness is whatever the driver proved
// in band (PON.Verified), and still requires an observed driver level.
func (o *OLT) collectSNMP(ctx context.Context, src OLTSource, observed string) ([]Item, error) {
	ctx, cancel := context.WithTimeout(ctx, src.budget())
	defer cancel()
	r, closeFn, err := src.OpenSNMP(ctx)
	if err != nil {
		return nil, err
	}
	defer closeFn()
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
		j := onuJSON{Serial: u.Serial, Pon: u.PonPath, Status: u.Status, Rx: u.RxDBm}
		if u.LastDownAt != nil && u.Status != "online" && u.Status != "unknown" {
			j.LastDownAt = u.LastDownAt.UTC().Format(time.RFC3339)
		}
		cur.ONUs = append(cur.ONUs, j)
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
