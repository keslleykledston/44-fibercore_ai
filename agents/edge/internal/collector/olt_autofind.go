package collector

import (
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"time"

	"github.com/keslleykledston/44-fibercore_ai/agents/edge/internal/olt"
)

// Autofind (ADR-0055) reads, on a schedule of its own, the list of ONTs the OLT has detected and nobody has authorised, and queues it for the Cloud. It is deliberately LIGHT on the
// device: one short CLI session (login, a version check, `enable`, ONE listing; at most autofindCommands commands and autofindMaxBytes bytes) every few minutes, never the full
// ONT walk of the collection.
//
// It shares the physical device's in-flight lock with the collection (never two sessions at once) but keeps its OWN pacing and cooldown, so a read every 10 minutes cannot
// push the collection's 15-minute window forward. It also stays away while the collection of the same OLT is cooling down after a failure (a bad login is never retried by two
// paths). Nothing here writes to a device.
type Autofind struct {
	EdgeID  string
	OLT     *OLT // the collector whose guard (lock, pacing file) this one shares
	Sources []AutofindSource
	// Timeout bounds one read, the login included (0 = 90 s).
	Timeout time.Duration
}

// AutofindSource is one OLT to read: the very source the collection uses (driver, session opener, device key) and how often.
type AutofindSource struct {
	Src   OLTSource
	Every time.Duration
}

const (
	autofindCommands = 6
	autofindMaxBytes = 256 << 10
	// autofindSlack: the tick that finds the read due can come a little before Last+Every (the ticks are sequential and the round itself takes time); the pacing is that much shorter
	// so a 10-minute read is not silently turned into a 15-minute one.
	autofindSlack = 30 * time.Second
)

func (a *Autofind) Name() string { return "olt-autofind" }

type autofindJSON struct {
	EdgeID     string          `json:"edge_id"`
	ObservedAt string          `json:"observed_at"`
	Name       string          `json:"name"`
	Entries    json.RawMessage `json:"entries"`
}

func (a *Autofind) timeout() time.Duration {
	if a.Timeout > 0 {
		return a.Timeout
	}
	return 90 * time.Second
}

func (a *Autofind) Collect(ctx context.Context) ([]Item, error) {
	var items []Item
	var errs []error
	for _, as := range a.Sources {
		reader, ok := as.Src.Driver.(olt.AutofindReader)
		if !ok || as.Every <= 0 || as.Src.Open == nil {
			continue
		}
		dev := as.Src.SNMPKey
		if dev == "" {
			dev = as.Src.Name
		}
		if a.OLT.cooling(dev) { // the collection of this OLT is cooling after a failure: nobody logs in again through another door
			continue
		}
		interval := as.Every - autofindSlack
		if interval < time.Minute {
			interval = time.Minute
		}
		syn := OLTSource{Name: as.Src.Name + "/autofind", SNMPKey: dev + "#autofind", Interval: interval, Cooldown: as.Src.Cooldown, busyKey: dev}
		its, err := a.OLT.guarded(ctx, syn, func() ([]Item, error) { return a.readOne(ctx, as.Src, reader) })
		if err != nil {
			errs = append(errs, fmt.Errorf("olt %s autofind: %w", as.Src.Name, err))
			continue
		}
		items = append(items, its...)
	}
	return items, errors.Join(errs...)
}

func (a *Autofind) readOne(ctx context.Context, src OLTSource, reader olt.AutofindReader) ([]Item, error) {
	ctx, cancel := context.WithTimeout(ctx, a.timeout())
	defer cancel()
	raw, closeFn, err := src.Open(ctx)
	if err != nil {
		return nil, err
	}
	defer closeFn()
	sess := olt.NewBudget(olt.ReadOnlySession{Inner: raw, Allowed: src.Driver.Allowed}, autofindCommands, autofindMaxBytes)
	typed, err := reader.ReadAutofind(ctx, sess)
	if err != nil {
		return nil, err
	}
	var list struct {
		Entries json.RawMessage `json:"entries"`
	}
	if err := json.Unmarshal(typed, &list); err != nil || len(list.Entries) == 0 {
		return nil, olt.ErrBadOutput
	}
	payload, err := json.Marshal(autofindJSON{EdgeID: a.EdgeID, ObservedAt: a.OLT.now().UTC().Format(time.RFC3339), Name: src.Name, Entries: list.Entries})
	if err != nil {
		return nil, err
	}
	// a Gauge: this is the CURRENT list of the OLT, so once queued it supersedes the older queued reads of the same OLT
	return []Item{{Kind: "olt_autofind", Key: "olt-autofind:" + src.Name, Payload: payload, Gauge: true}}, nil
}

// cooling reports whether the device is inside the cooldown that follows a failed session of the collection (false while the state is not loaded yet: the guard decides then).
func (o *OLT) cooling(key string) bool {
	o.mu.Lock()
	defer o.mu.Unlock()
	if !o.loaded {
		return false
	}
	return o.now().Before(o.st[key].CoolUntil)
}
