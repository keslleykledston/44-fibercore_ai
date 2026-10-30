package jobs

import (
	"encoding/json"
	"errors"
	"fmt"
	"os"
	"path/filepath"
	"sync"
)

// Claim states. A claim is written BEFORE anything is sent to the device; a claim that never got a result (crash, restart) is UNKNOWN and is
// never executed again: the single-use authorization is spent the moment the claim exists (ADR-0030, durable claim unique by authorization).
const (
	ClaimClaimed = "CLAIMED"
	ClaimDone    = "DONE"
	ClaimFailed  = "FAILED"
	ClaimUnknown = "UNKNOWN"
)

var (
	ErrClaimTaken    = errors.New("authorization already claimed on this edge")
	ErrClaimStore    = errors.New("claim store unreadable or unwritable")
	ErrStaleEpoch    = errors.New("owner epoch older than the highest seen")
	maxClaimsKept    = 512
	claimFileVersion = 1
)

type claimRec struct {
	JobID string `json:"job_id"`
	State string `json:"state"`
	Epoch int    `json:"epoch"`
}

type claimFile struct {
	Version  int                 `json:"version"`
	MaxEpoch map[string]int      `json:"max_epoch"` // per target_ref
	Claims   map[string]claimRec `json:"claims"`    // by authorization_id
}

// Claims is the Edge-side durable record of spent bench authorizations. Unreadable or corrupt store = refuse everything (fail closed).
type Claims struct {
	mu   sync.Mutex
	path string
	data claimFile
}

// OpenClaims loads the store (creating an empty one if the file is absent). Any other read/parse problem is an error: the caller must not run bench writes.
func OpenClaims(path string) (*Claims, error) {
	c := &Claims{path: path, data: claimFile{Version: claimFileVersion, MaxEpoch: map[string]int{}, Claims: map[string]claimRec{}}}
	b, err := os.ReadFile(path)
	switch {
	case errors.Is(err, os.ErrNotExist):
		if err := c.save(); err != nil {
			return nil, err
		}
		return c, nil
	case err != nil:
		return nil, fmt.Errorf("%w: %v", ErrClaimStore, err)
	}
	var f claimFile
	if err := json.Unmarshal(b, &f); err != nil || f.Version != claimFileVersion || f.MaxEpoch == nil || f.Claims == nil {
		return nil, fmt.Errorf("%w: corrupt", ErrClaimStore)
	}
	c.data = f
	// A claim left CLAIMED by a previous run never completed to a known result: its outcome is uncertain and it is never retried.
	changed := false
	for id, r := range c.data.Claims {
		if r.State == ClaimClaimed {
			r.State = ClaimUnknown
			c.data.Claims[id] = r
			changed = true
		}
	}
	if changed {
		if err := c.save(); err != nil {
			return nil, err
		}
	}
	return c, nil
}

// Claim spends the authorization for this job and records the epoch, durably, before any command. A second claim of the same authorization
// (any job id, any state) is refused; so is an epoch lower than the highest seen for the target.
func (c *Claims) Claim(authID, jobID, targetRef string, epoch int) error {
	c.mu.Lock()
	defer c.mu.Unlock()
	if _, ok := c.data.Claims[authID]; ok {
		return ErrClaimTaken
	}
	if epoch < c.data.MaxEpoch[targetRef] {
		return ErrStaleEpoch
	}
	if len(c.data.Claims) >= maxClaimsKept {
		c.prune()
	}
	prevMax, hadMax := c.data.MaxEpoch[targetRef]
	c.data.Claims[authID] = claimRec{JobID: jobID, State: ClaimClaimed, Epoch: epoch}
	c.data.MaxEpoch[targetRef] = epoch
	if err := c.save(); err != nil {
		delete(c.data.Claims, authID)
		if hadMax {
			c.data.MaxEpoch[targetRef] = prevMax
		} else {
			delete(c.data.MaxEpoch, targetRef)
		}
		return err
	}
	return nil
}

// Finish records the known outcome of a claim. A failure to persist leaves the claim CLAIMED on disk, which reads back as UNKNOWN: still never re-run.
func (c *Claims) Finish(authID, state string) error {
	if state != ClaimDone && state != ClaimFailed && state != ClaimUnknown {
		return fmt.Errorf("invalid claim state %q", state)
	}
	c.mu.Lock()
	defer c.mu.Unlock()
	r, ok := c.data.Claims[authID]
	if !ok {
		return fmt.Errorf("unknown claim")
	}
	r.State = state
	c.data.Claims[authID] = r
	return c.save()
}

// State returns the recorded state of an authorization ("" if never claimed).
func (c *Claims) State(authID string) string {
	c.mu.Lock()
	defer c.mu.Unlock()
	return c.data.Claims[authID].State
}

// MaxEpoch is the highest owner epoch ever claimed for the target.
func (c *Claims) MaxEpoch(targetRef string) int {
	c.mu.Lock()
	defer c.mu.Unlock()
	return c.data.MaxEpoch[targetRef]
}

// prune keeps the store bounded: only finished claims are dropped (never CLAIMED/UNKNOWN), and the epoch memory is never dropped.
func (c *Claims) prune() {
	for id, r := range c.data.Claims {
		if len(c.data.Claims) < maxClaimsKept/2 {
			return
		}
		if r.State == ClaimDone {
			delete(c.data.Claims, id)
		}
	}
}

func (c *Claims) save() error {
	b, err := json.Marshal(c.data)
	if err != nil {
		return fmt.Errorf("%w: %v", ErrClaimStore, err)
	}
	tmp, err := os.CreateTemp(filepath.Dir(c.path), ".claims-*")
	if err != nil {
		return fmt.Errorf("%w: %v", ErrClaimStore, err)
	}
	defer os.Remove(tmp.Name())
	if err := tmp.Chmod(0o600); err != nil {
		tmp.Close()
		return fmt.Errorf("%w: %v", ErrClaimStore, err)
	}
	if _, err := tmp.Write(b); err != nil {
		tmp.Close()
		return fmt.Errorf("%w: %v", ErrClaimStore, err)
	}
	if err := tmp.Sync(); err != nil {
		tmp.Close()
		return fmt.Errorf("%w: %v", ErrClaimStore, err)
	}
	if err := tmp.Close(); err != nil {
		return fmt.Errorf("%w: %v", ErrClaimStore, err)
	}
	if err := os.Rename(tmp.Name(), c.path); err != nil {
		return fmt.Errorf("%w: %v", ErrClaimStore, err)
	}
	if d, err := os.Open(filepath.Dir(c.path)); err == nil {
		_ = d.Sync()
		d.Close()
	}
	return nil
}
