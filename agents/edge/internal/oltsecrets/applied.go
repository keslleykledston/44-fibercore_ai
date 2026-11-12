package oltsecrets

import (
	"encoding/json"
	"errors"
	"fmt"
	"log/slog"
	"os"
	"path/filepath"
	"sort"
	"sync"
	"time"

	"github.com/keslleykledston/44-fibercore_ai/agents/edge/internal/credfile"
)

// Retention of the applied-delivery store (ADR-0045): ids are kept for at least 24 h and at most 1000.
const (
	KeepApplied    = 24 * time.Hour
	MaxApplied     = 1000
	appliedVersion = 1
	maxStoreBytes  = 1 << 20
)

// ErrStateUnreadable: the store exists but cannot be read or replaced (permissions, I/O). Fail closed: no delivery is applied while the Edge cannot tell whether it
// already did. (An ABSENT store is empty, and a CORRUPT one is moved aside and starts empty: both are in the ADR.)
var ErrStateUnreadable = errors.New("applied-delivery store is unreadable")

type appliedEntry struct {
	ID   string `json:"id"`
	OLT  string `json:"olt"`
	Kind string `json:"kind"`
	Exp  int64  `json:"exp"` // expires_at (unix) of the delivery
	At   int64  `json:"at"`  // when this Edge applied it (unix)
}

type lastEntry struct {
	OLT  string `json:"olt"`
	Kind string `json:"kind"`
	Exp  int64  `json:"exp"`
}

type appliedFile struct {
	V       int            `json:"v"`
	Applied []appliedEntry `json:"applied"`
	Last    []lastEntry    `json:"last"` // by OLT + kind: the expires_at of the newest applied delivery (anti-rollback)
}

// AppliedStore is the durable record of what this Edge already applied: delivery ids (idempotency) and, per OLT and kind, the expires_at of the last applied one
// (a delivery with an EARLIER expires_at is a rollback and is refused). It holds no secret. It is read from disk on every use, so what is checked is what is stored.
type AppliedStore struct {
	Path string
	Log  *slog.Logger
	Now  func() time.Time
	mu   sync.Mutex
}

func (s *AppliedStore) now() time.Time {
	if s.Now != nil {
		return s.Now()
	}
	return time.Now()
}

func (s *AppliedStore) load() (*appliedFile, error) {
	// the directory is ours and closed to writers, the file is ours, 0600 and not a link (checked on the open descriptor): anything else is unreadable (fail closed),
	// because another user could otherwise replace or delete the replay and anti-rollback state
	b, err := credfile.ReadStateFile(s.Path, maxStoreBytes)
	if credfile.IsNotExist(err) {
		if derr := credfile.CheckStateDir(filepath.Dir(s.Path)); derr != nil && !credfile.IsNotExist(derr) {
			return nil, fmt.Errorf("%w: %v", ErrStateUnreadable, derr)
		}
		return &appliedFile{V: appliedVersion}, nil
	}
	if err != nil {
		return nil, fmt.Errorf("%w: %v", ErrStateUnreadable, err)
	}
	var f appliedFile
	if json.Unmarshal(b, &f) != nil || f.V != appliedVersion || !validApplied(&f) {
		return s.moveAside()
	}
	return &f, nil
}

func validApplied(f *appliedFile) bool {
	for _, e := range f.Applied {
		if e.ID == "" || e.OLT == "" || e.Kind == "" || e.At <= 0 {
			return false
		}
	}
	for _, l := range f.Last {
		if l.OLT == "" || l.Kind == "" {
			return false
		}
	}
	return true
}

// moveAside renames a corrupt store out of the way (kept for the operator), warns, and starts empty. If it cannot be moved the store is unreadable (fail closed).
func (s *AppliedStore) moveAside() (*appliedFile, error) {
	dst := fmt.Sprintf("%s.corrupt-%d", s.Path, s.now().UnixNano())
	if err := os.Rename(s.Path, dst); err != nil {
		return nil, fmt.Errorf("%w: corrupt and could not be moved aside: %v", ErrStateUnreadable, err)
	}
	if s.Log != nil {
		s.Log.Warn("olt secrets: the applied-delivery store was corrupt; moved aside, starting empty (a rollback by an older delivery is limited only by its validity until the store is rebuilt)", "moved_to", dst)
	}
	return &appliedFile{V: appliedVersion}, nil
}

// Check says whether the delivery id was already applied and, if not, whether it is a rollback (stale): its expires_at is EARLIER than the last applied one of the
// same OLT and kind. An id that was applied always answers applied=true, whatever its age.
func (s *AppliedStore) Check(id, olt, kind string, exp int64) (applied, stale bool, err error) {
	s.mu.Lock()
	defer s.mu.Unlock()
	f, err := s.load()
	if err != nil {
		return false, false, err
	}
	for _, e := range f.Applied {
		if e.ID == id {
			return true, false, nil
		}
	}
	for _, l := range f.Last {
		if l.OLT == olt && l.Kind == kind && exp < l.Exp {
			return false, true, nil
		}
	}
	return false, false, nil
}

// Record stores the applied delivery (atomic replace of the file) and prunes: older than 24 h goes first, then the oldest beyond 1000.
func (s *AppliedStore) Record(id, olt, kind string, exp int64) error {
	s.mu.Lock()
	defer s.mu.Unlock()
	f, err := s.load()
	if err != nil {
		return err
	}
	now := s.now()
	for _, e := range f.Applied {
		if e.ID == id { // already there (a replay of the same record): nothing to add
			return nil
		}
	}
	f.Applied = append(f.Applied, appliedEntry{ID: id, OLT: olt, Kind: kind, Exp: exp, At: now.Unix()})
	cut := now.Add(-KeepApplied).Unix()
	kept := f.Applied[:0]
	for _, e := range f.Applied {
		if e.At >= cut {
			kept = append(kept, e)
		}
	}
	f.Applied = kept
	if len(f.Applied) > MaxApplied {
		sort.SliceStable(f.Applied, func(i, j int) bool { return f.Applied[i].At < f.Applied[j].At })
		f.Applied = f.Applied[len(f.Applied)-MaxApplied:]
	}
	found := false
	for i := range f.Last {
		if f.Last[i].OLT == olt && f.Last[i].Kind == kind {
			found = true
			if exp > f.Last[i].Exp {
				f.Last[i].Exp = exp
			}
		}
	}
	if !found {
		f.Last = append(f.Last, lastEntry{OLT: olt, Kind: kind, Exp: exp})
	}
	b, err := json.Marshal(f)
	if err != nil {
		return err
	}
	if err := os.MkdirAll(filepath.Dir(s.Path), 0o700); err != nil { // only creates what is missing; an existing directory is checked, never loosened or tightened
		return fmt.Errorf("%w: %v", ErrStateUnreadable, err)
	}
	if err := credfile.CheckStateDir(filepath.Dir(s.Path)); err != nil {
		return fmt.Errorf("%w: %v", ErrStateUnreadable, err)
	}
	if err := credfile.WriteAtomic(s.Path, b); err != nil {
		return fmt.Errorf("%w: %v", ErrStateUnreadable, err)
	}
	return nil
}
