// Package oltquery is the Edge's durable queue of read-only OLT queries (ADR-0029 item 3): what was approved, what ran, what the Cloud still has to be told.
//
// Every state change is written to disk (fsync, atomic rename) BEFORE the thing it records can happen, so a crash can lose a report but never repeat a
// command: QUEUED -> CLAIMED (written before the CLI session is used) -> EXECUTED/FAILED (typed result) -> REPORTED (the Cloud acknowledged). A CLAIMED entry
// found after a restart has an unknown outcome (the OLT may have received the command) and becomes UNKNOWN: it is never run again. The budget (5 per
// session, 20 per rolling hour, per OLT) lives in the same file, and an unreadable file means the budget is spent: nothing is claimed until it is fixed.
package oltquery

import (
	"encoding/json"
	"errors"
	"fmt"
	"os"
	"path/filepath"
	"sort"
	"sync"
	"time"
)

type State string

const (
	Queued   State = "QUEUED"
	Claimed  State = "CLAIMED"
	Executed State = "EXECUTED"
	Failed   State = "FAILED"
	Expired  State = "EXPIRED"
	Unknown  State = "UNKNOWN"
	Reported State = "REPORTED"
)

const (
	PerSession = 5  // on-demand queries per CLI session (class cap)
	PerHour    = 20 // on-demand queries per hour per OLT (class cap)
	// ADR-0032 item 5: the AGGREGATE budget of one CLI session (on-demand + routines + captures) and the class caps of the captures.
	MaxPerSession      = 8
	CapturesPerSession = 2
	CapturesPerHour    = 4
	MaxQueuedPerOLT    = 50
	KeepReported       = 24 * time.Hour
	// StaleClaim: a CLAIMED entry older than this belongs to a session that cannot still be running (a session lives at most ~12 minutes), so its outcome
	// is unknown and it becomes UNKNOWN without waiting for a restart.
	StaleClaim = 15 * time.Minute
	// MaxResultBytes bounds a typed result kept on disk (the parsers produce small closed objects; ADR-0029 item 5 caps what leaves the Edge).
	MaxResultBytes = 64 << 10
)

var (
	ErrCorrupt     = errors.New("oltquery: state file is unreadable; the budget is treated as spent")
	ErrConflict    = errors.New("oltquery: this job id is already queued with a different intent")
	ErrBudget      = errors.New("oltquery: the session or hour budget of this class is spent")
	ErrStaleOwner  = errors.New("oltquery: the query was issued for an older owner of this OLT")
	ErrQueueFull   = errors.New("oltquery: too many queries waiting for this OLT")
	ErrBadState    = errors.New("oltquery: illegal state transition")
	ErrResultSize  = errors.New("oltquery: result too large")
	ErrNothingToDo = errors.New("oltquery: nothing to claim")
)

// Intent is the validated intent the entry will execute (the envelope's signed params, already checked against the catalog).
type Intent struct {
	QueryID string `json:"query_id"`
	OLTRef  string `json:"olt_ref"`
	Epoch   int    `json:"epoch"` // owner epoch of the OLT the Cloud issued the query for (ADR-0029 item 3)
	Slot    int    `json:"slot"`
	Port    int    `json:"port"`
	ONT     int    `json:"ont"`
}

type Entry struct {
	JobID      string          `json:"job_id"`
	Intent     Intent          `json:"intent"`
	State      State           `json:"state"`
	Enqueued   time.Time       `json:"enqueued"`
	ExpiresAt  time.Time       `json:"expires_at"`
	ClaimedAt  time.Time       `json:"claimed_at,omitempty"`
	SessionID  string          `json:"session_id,omitempty"`
	Result     json.RawMessage `json:"result,omitempty"` // typed object produced by the query's parser; never raw device output
	Reason     string          `json:"reason,omitempty"` // category of a failure (olt_busy, device_rejected, expired, restart...), never device text
	FinishedAt time.Time       `json:"finished_at,omitempty"`
	HandedAt   time.Time       `json:"handed_at,omitempty"` // when the outcome was last handed to the delivery queue and is waiting for the Cloud's answer (durable: survives a restart)
}

// capSess counts the captures that ran in one CLI session.
type capSess struct {
	N  int       `json:"n"`
	At time.Time `json:"at"`
}

type file struct {
	Entries map[string]*Entry `json:"entries"`
	// Captures (ADR-0032 item 5): the supervised captures of unvalidated queries have their OWN persisted class budget, apart from the on-demand one.
	Captures    map[string][]time.Time `json:"captures,omitempty"`     // by olt_ref: instants of captures in the last hour
	CaptureSess map[string]capSess     `json:"capture_sess,omitempty"` // by session id: how many captures ran in it
	Epochs      map[string]int         `json:"epochs"`                 // highest owner epoch ever seen per OLT: an envelope of a lower one belongs to an owner that was replaced
	Claims      map[string][]time.Time `json:"claims"`                 // by olt_ref: the instants of claims in the last hour
}

// Store is the durable queue. All methods are safe for concurrent use.
type Store struct {
	Path string
	Now  func() time.Time
	mu   sync.Mutex
}

func (s *Store) now() time.Time {
	if s.Now != nil {
		return s.Now()
	}
	return time.Now()
}

func (s *Store) load() (*file, error) {
	b, err := os.ReadFile(s.Path)
	if errors.Is(err, os.ErrNotExist) {
		return &file{Entries: map[string]*Entry{}, Claims: map[string][]time.Time{}, Epochs: map[string]int{}}, nil
	}
	if err != nil {
		return nil, fmt.Errorf("%w: %v", ErrCorrupt, err)
	}
	var f file
	if err := json.Unmarshal(b, &f); err != nil || f.Entries == nil {
		return nil, fmt.Errorf("%w: not a queue file (%v)", ErrCorrupt, err)
	}
	if f.Claims == nil { // a file that lost its budget history would hand out a fresh budget: it is corrupt, not new
		return nil, fmt.Errorf("%w: no claims history", ErrCorrupt)
	}
	if f.Captures == nil {
		f.Captures = map[string][]time.Time{}
	}
	if f.CaptureSess == nil {
		f.CaptureSess = map[string]capSess{}
	}
	if f.Epochs == nil { // a file from before ownership epochs existed: nothing was ever seen, which is the truth
		f.Epochs = map[string]int{}
	}
	for ref, n := range f.Epochs {
		if ref == "" || n < 1 {
			return nil, fmt.Errorf("%w: malformed epochs", ErrCorrupt)
		}
	}
	for ref, ts := range f.Claims {
		for _, t := range ts {
			if ref == "" || t.IsZero() {
				return nil, fmt.Errorf("%w: malformed claims history", ErrCorrupt)
			}
		}
	}
	for id, e := range f.Entries { // one bad entry makes the whole file untrustworthy: nothing is claimed from a file that cannot be understood
		if e == nil || e.JobID != id || e.Intent.OLTRef == "" || !validState(e.State) {
			return nil, fmt.Errorf("%w: entry %q is malformed", ErrCorrupt, id)
		}
	}
	return &f, nil
}

func validState(st State) bool {
	switch st {
	case Queued, Claimed, Executed, Failed, Expired, Unknown, Reported:
		return true
	}
	return false
}

func (s *Store) save(f *file) error {
	b, err := json.Marshal(f)
	if err != nil {
		return err
	}
	tmp, err := os.CreateTemp(filepath.Dir(s.Path), ".oltquery-*")
	if err != nil {
		return err
	}
	name := tmp.Name()
	defer os.Remove(name)
	if err := tmp.Chmod(0o600); err != nil {
		tmp.Close()
		return err
	}
	if _, err := tmp.Write(b); err != nil {
		tmp.Close()
		return err
	}
	if err := tmp.Sync(); err != nil {
		tmp.Close()
		return err
	}
	if err := tmp.Close(); err != nil {
		return err
	}
	if err := os.Rename(name, s.Path); err != nil {
		return err
	}
	// the rename itself must survive a power cut, or a CLAIMED already acted upon could come back as QUEUED and run twice
	return syncDir(filepath.Dir(s.Path))
}

// update runs fn on the loaded file and persists the result. Nothing observable happens before the write succeeds.
func (s *Store) update(fn func(f *file) error) error {
	s.mu.Lock()
	defer s.mu.Unlock()
	unlock, err := lockFile(s.Path) // across every Store (and process) sharing the file, not just this value
	if err != nil {
		return err
	}
	defer unlock()
	f, err := s.load()
	if err != nil {
		return err
	}
	if err := fn(f); err != nil {
		return err
	}
	return s.save(f)
}

// ReserveCapture spends ONE capture from the class budget (2 per session, 4 per hour per OLT) and from the aggregate one of the session (on-demand queries
// already run in it + captures <= 8), writing the reservation to disk BEFORE the command can be sent. ErrBudget = nothing may run now.
func (s *Store) ReserveCapture(oltRef, session string) error {
	return s.update(func(f *file) error {
		now := s.now()
		keep := make([]time.Time, 0, len(f.Captures[oltRef])+1)
		for _, t := range f.Captures[oltRef] {
			if now.Sub(t) < time.Hour {
				keep = append(keep, t)
			}
		}
		f.Captures[oltRef] = keep
		for id, c := range f.CaptureSess { // sessions older than 2 h are forgotten
			if now.Sub(c.At) > 2*time.Hour {
				delete(f.CaptureSess, id)
			}
		}
		onDemand := 0
		for _, e := range f.Entries {
			if e.SessionID == session && e.State != Queued {
				onDemand++
			}
		}
		c := f.CaptureSess[session]
		if len(keep) >= CapturesPerHour || c.N >= CapturesPerSession || onDemand+c.N >= MaxPerSession {
			return ErrBudget
		}
		f.Captures[oltRef] = append(keep, now)
		f.CaptureSess[session] = capSess{N: c.N + 1, At: now}
		return nil
	})
}

// Enqueue records an approved query. The same job twice changes nothing (the Cloud may redeliver an envelope the Edge already has).
func (s *Store) Enqueue(jobID string, in Intent, expires time.Time) error {
	return s.update(func(f *file) error {
		if old, ok := f.Entries[jobID]; ok {
			if old.Intent != in || !old.ExpiresAt.Equal(expires) { // only an identical redelivery is a no-op; the same id with another intent is a conflict
				return ErrConflict
			}
			return nil
		}
		if in.Epoch < 1 || in.Epoch < f.Epochs[in.OLTRef] {
			return ErrStaleOwner
		}
		f.Epochs[in.OLTRef] = in.Epoch // remembered even if the query is then refused for room: the owner generation only goes up
		n := 0
		for _, e := range f.Entries {
			if e.State == Queued && e.Intent.OLTRef == in.OLTRef {
				n++
			}
		}
		if n >= MaxQueuedPerOLT {
			return ErrQueueFull
		}
		f.Entries[jobID] = &Entry{JobID: jobID, Intent: in, State: Queued, Enqueued: s.now(), ExpiresAt: expires}
		return nil
	})
}

// Claim hands out the oldest waiting query of this OLT for the given CLI session, within the budget, after writing CLAIMED to disk. The caller runs it
// only if Claim returned it. ErrNothingToDo covers an empty queue and a spent budget alike (the rest wait for the next window).
func (s *Store) Claim(oltRef, sessionID string) (Entry, error) {
	var out Entry
	err := s.update(func(f *file) error {
		now := s.now()
		keep := make([]time.Time, 0, len(f.Claims[oltRef])+1)
		for _, t := range f.Claims[oltRef] {
			if now.Sub(t) < time.Hour {
				keep = append(keep, t)
			}
		}
		f.Claims[oltRef] = keep
		if len(keep) >= PerHour {
			return ErrNothingToDo
		}
		inSession := 0
		var cand []*Entry
		for _, e := range f.Entries {
			if e.Intent.OLTRef != oltRef {
				continue
			}
			switch {
			case e.SessionID == sessionID && e.State != Queued:
				inSession++
			case e.State == Queued && e.ExpiresAt.After(now):
				cand = append(cand, e)
			}
		}
		if inSession >= PerSession || len(cand) == 0 {
			return ErrNothingToDo
		}
		sort.Slice(cand, func(i, j int) bool {
			if !cand[i].Enqueued.Equal(cand[j].Enqueued) {
				return cand[i].Enqueued.Before(cand[j].Enqueued)
			}
			return cand[i].JobID < cand[j].JobID
		})
		e := cand[0]
		e.State, e.ClaimedAt, e.SessionID = Claimed, now, sessionID
		f.Claims[oltRef] = append(f.Claims[oltRef], now)
		out = *e
		return nil
	})
	return out, err
}

func transition(e *Entry, from []State, to State) error {
	for _, s := range from {
		if e.State == s {
			e.State = to
			return nil
		}
	}
	return fmt.Errorf("%w: %s -> %s", ErrBadState, e.State, to)
}

// Complete stores the typed result of a claimed query.
func (s *Store) Complete(jobID string, result json.RawMessage) error {
	if len(result) > MaxResultBytes {
		return ErrResultSize
	}
	return s.update(func(f *file) error {
		e, ok := f.Entries[jobID]
		if !ok {
			return fmt.Errorf("%w: unknown job", ErrBadState)
		}
		if err := transition(e, []State{Claimed}, Executed); err != nil {
			return err
		}
		e.Result, e.FinishedAt = result, s.now()
		return nil
	})
}

// Fail ends a claimed query with a failure category (never device text).
func (s *Store) Fail(jobID, reason string) error {
	return s.update(func(f *file) error {
		e, ok := f.Entries[jobID]
		if !ok {
			return fmt.Errorf("%w: unknown job", ErrBadState)
		}
		if err := transition(e, []State{Claimed}, Failed); err != nil {
			return err
		}
		e.Reason, e.FinishedAt = reason, s.now()
		return nil
	})
}

// AbortBatch ends every query still waiting for this OLT after a session failure or a cooldown: none is retried inside the cooldown.
func (s *Store) AbortBatch(oltRef, reason string) (int, error) {
	n := 0
	err := s.update(func(f *file) error {
		for _, e := range f.Entries {
			if e.Intent.OLTRef == oltRef && e.State == Queued {
				e.State, e.Reason, e.FinishedAt = Failed, reason, s.now()
				n++
			}
		}
		return nil
	})
	return n, err
}

// Recover is called once at start: a CLAIMED entry has no known outcome and is never run again; waiting entries past their deadline expire.
func (s *Store) Recover() (unknown, expired int, err error) {
	err = s.update(func(f *file) error {
		now := s.now()
		for _, e := range f.Entries {
			switch {
			case e.State == Claimed:
				e.State, e.Reason, e.FinishedAt = Unknown, "restart_after_claim", now
				unknown++
			case e.State == Queued && !e.ExpiresAt.After(now):
				e.State, e.Reason, e.FinishedAt = Expired, "expired", now
				expired++
			}
		}
		return nil
	})
	return
}

// ExpireDue ends waiting queries whose deadline passed (the window did not open in time) and turns long-abandoned claims into UNKNOWN (never run again).
func (s *Store) ExpireDue() (int, error) {
	n := 0
	err := s.update(func(f *file) error {
		now := s.now()
		for _, e := range f.Entries {
			switch {
			case e.State == Queued && !e.ExpiresAt.After(now):
				e.State, e.Reason, e.FinishedAt = Expired, "expired", now
				n++
			case e.State == Claimed && now.Sub(e.ClaimedAt) > StaleClaim:
				e.State, e.Reason, e.FinishedAt = Unknown, "claim_abandoned", now
				n++
			}
		}
		s.pruneReported(f)
		return nil
	})
	return n, err
}

// PendingReports lists finished entries the Cloud has not acknowledged yet, oldest first. Re-sending them never executes anything.
func (s *Store) PendingReports() ([]Entry, error) {
	s.mu.Lock()
	defer s.mu.Unlock()
	unlock, err := lockFile(s.Path)
	if err != nil {
		return nil, err
	}
	defer unlock()
	f, err := s.load()
	if err != nil {
		return nil, err
	}
	var out []Entry
	for _, e := range f.Entries {
		if e.State == Executed || e.State == Failed || e.State == Expired || e.State == Unknown {
			out = append(out, *e)
		}
	}
	sort.Slice(out, func(i, j int) bool {
		return out[i].FinishedAt.Before(out[j].FinishedAt) || (out[i].FinishedAt.Equal(out[j].FinishedAt) && out[i].JobID < out[j].JobID)
	})
	return out, nil
}

// pruneReported drops REPORTED entries (acknowledged or refused) older than KeepReported: the file stays small whatever the Cloud answered.
func (s *Store) pruneReported(f *file) {
	for id, x := range f.Entries {
		if x.State == Reported && s.now().Sub(x.FinishedAt) > KeepReported {
			delete(f.Entries, id)
		}
	}
}

// MarkHanded records, durably, that the outcome of a finished query was handed to the delivery queue now.
func (s *Store) MarkHanded(jobID string) error {
	return s.update(func(f *file) error {
		e, ok := f.Entries[jobID]
		if !ok || e.State == Queued || e.State == Claimed || e.State == Reported {
			return fmt.Errorf("%w: not waiting for a report", ErrBadState)
		}
		e.HandedAt = s.now()
		return nil
	})
}

// MarkRejected ends the reporting of a finished query whose result the Cloud refused for good (a 4xx such as "illegal transition": the job is no longer in
// a state that can take it, e.g. it expired there). Resending would only loop. The entry is kept with its result and the reason `cloud_rejected` for
// KeepReported, and the delivery queue's dead-letter table holds the sent copy: a person can see it, it is not silently the same as an acknowledged report.
func (s *Store) MarkRejected(jobID string) error {
	return s.update(func(f *file) error {
		e, ok := f.Entries[jobID]
		if !ok {
			return fmt.Errorf("%w: unknown job", ErrBadState)
		}
		if err := transition(e, []State{Executed, Failed, Expired, Unknown}, Reported); err != nil {
			return err
		}
		e.Reason, e.FinishedAt = "cloud_rejected", s.now()
		s.pruneReported(f)
		return nil
	})
}

// MarkReported records the Cloud's acknowledgement and drops reported entries older than KeepReported (the file stays small).
func (s *Store) MarkReported(jobID string) error {
	return s.update(func(f *file) error {
		e, ok := f.Entries[jobID]
		if !ok {
			return fmt.Errorf("%w: unknown job", ErrBadState)
		}
		if e.State == Reported {
			return nil
		}
		if err := transition(e, []State{Executed, Failed, Expired, Unknown}, Reported); err != nil {
			return err
		}
		e.FinishedAt = s.now()
		s.pruneReported(f)
		return nil
	})
}

// Get returns a copy of one entry.
func (s *Store) Get(jobID string) (Entry, bool, error) {
	s.mu.Lock()
	defer s.mu.Unlock()
	unlock, err := lockFile(s.Path)
	if err != nil {
		return Entry{}, false, err
	}
	defer unlock()
	f, err := s.load()
	if err != nil {
		return Entry{}, false, err
	}
	e, ok := f.Entries[jobID]
	if !ok {
		return Entry{}, false, nil
	}
	return *e, true, nil
}
