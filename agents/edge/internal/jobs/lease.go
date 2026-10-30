package jobs

import (
	"bytes"
	"crypto/ed25519"
	"encoding/base64"
	"encoding/json"
	"errors"
	"fmt"
	"sync"
	"time"
)

// LeaseTTL is the longest a bench lease is honoured after it was received. The Cloud renews it on every poll; if the Edge loses the Cloud (or the
// Cloud withdraws the target, e.g. `bench-unlock` pending, ownership moved) the lease dies by itself and no bench write can start (ADR-0030 item 4).
const LeaseTTL = 2 * time.Minute

var (
	ErrNoLease     = errors.New("no valid bench lease")
	ErrLeaseTarget = errors.New("bench lease does not cover this target/epoch")
)

type LeaseTarget struct {
	TargetRef  string `json:"target_ref"`
	OwnerEpoch int    `json:"owner_epoch"`
}

type Lease struct {
	Schema    string        `json:"schema"`
	TenantID  string        `json:"tenant_id"`
	EdgeID    string        `json:"edge_id"`
	IssuedAt  string        `json:"issued_at"`
	ExpiresAt string        `json:"expires_at"`
	Targets   []LeaseTarget `json:"targets"`
	Signature string        `json:"signature"`
}

// LeaseHolder keeps the Cloud's latest signed lease in MEMORY ONLY: a restart starts without one. Expiry is measured on the local (monotonic)
// clock from the moment of receipt, never from the Cloud's wall clock alone.
type LeaseHolder struct {
	// Schema is the lease family this holder accepts: "" = the bench lease; "olt-lease/1" = the ownership lease of the OLTs (ADR-0029). A lease of the
	// other family does not parse here.
	Schema   string
	Pub      ed25519.PublicKey
	EdgeID   string
	TenantID string
	Now      func() time.Time

	mu       sync.Mutex
	targets  map[string]int
	issued   time.Time
	deadline time.Time
}

func (h *LeaseHolder) now() time.Time {
	if h.Now != nil {
		return h.Now()
	}
	return time.Now()
}

// Accept installs the lease carried by a poll response header (base64 JSON). An empty header withdraws any lease held. A malformed, unsigned,
// foreign, stale or over-long lease also withdraws it: the safe state is "no lease". A lease issued before the one held is ignored.
func (h *LeaseHolder) Accept(header string) error {
	h.mu.Lock()
	defer h.mu.Unlock()
	if header == "" {
		h.targets, h.deadline = nil, time.Time{}
		return nil
	}
	l, err := h.parse(header)
	if err != nil {
		h.targets, h.deadline = nil, time.Time{}
		return err
	}
	iss, _ := time.Parse(time.RFC3339, l.IssuedAt)
	if !h.issued.IsZero() && iss.Before(h.issued) && h.targets != nil {
		return nil
	}
	exp, _ := time.Parse(time.RFC3339, l.ExpiresAt)
	wall := h.now()
	left := exp.Sub(wall)
	if left > LeaseTTL {
		left = LeaseTTL
	}
	t := make(map[string]int, len(l.Targets))
	for _, x := range l.Targets {
		t[x.TargetRef] = x.OwnerEpoch
	}
	h.targets, h.issued, h.deadline = t, iss, h.now().Add(left)
	return nil
}

func (h *LeaseHolder) parse(header string) (*Lease, error) {
	raw, err := base64.StdEncoding.DecodeString(header)
	if err != nil || len(raw) > 1<<14 {
		return nil, fmt.Errorf("%w: malformed", ErrNoLease)
	}
	canon, err := Canonical(raw)
	if err != nil {
		return nil, fmt.Errorf("%w: malformed", ErrNoLease)
	}
	var l Lease
	dec := json.NewDecoder(bytes.NewReader(raw))
	dec.DisallowUnknownFields()
	if err := dec.Decode(&l); err != nil || l.Schema != h.schema() {
		return nil, fmt.Errorf("%w: unknown or missing fields", ErrNoLease)
	}
	sig, err := base64.StdEncoding.DecodeString(l.Signature)
	if err != nil || !ed25519.Verify(h.Pub, canon, sig) {
		return nil, fmt.Errorf("%w: signature", ErrNoLease)
	}
	if l.EdgeID != h.EdgeID || l.TenantID != h.TenantID {
		return nil, fmt.Errorf("%w: bound to another edge/tenant", ErrNoLease)
	}
	iss, e1 := time.Parse(time.RFC3339, l.IssuedAt)
	exp, e2 := time.Parse(time.RFC3339, l.ExpiresAt)
	now := h.now()
	if e1 != nil || e2 != nil || !exp.After(now) || iss.After(now.Add(clockSkew)) || exp.Sub(iss) > LeaseTTL+time.Second {
		return nil, fmt.Errorf("%w: expired or not valid now", ErrNoLease)
	}
	for _, t := range l.Targets {
		if !targetRefRe.MatchString(t.TargetRef) || t.OwnerEpoch < 1 {
			return nil, fmt.Errorf("%w: bad target", ErrNoLease)
		}
	}
	return &l, nil
}

// Check says whether a lease, valid right now, names this target with exactly this owner epoch.
func (h *LeaseHolder) Check(targetRef string, epoch int) error {
	h.mu.Lock()
	defer h.mu.Unlock()
	if h.targets == nil || !h.now().Before(h.deadline) {
		return ErrNoLease
	}
	if e, ok := h.targets[targetRef]; !ok || e != epoch {
		return ErrLeaseTarget
	}
	return nil
}

func (h *LeaseHolder) schema() string {
	if h.Schema != "" {
		return h.Schema
	}
	return "bench-lease/1"
}

// Epoch returns the owner epoch the lease, valid right now, gives for this target.
func (h *LeaseHolder) Epoch(targetRef string) (int, bool) {
	h.mu.Lock()
	defer h.mu.Unlock()
	if h.targets == nil || !h.now().Before(h.deadline) {
		return 0, false
	}
	e, ok := h.targets[targetRef]
	return e, ok
}
