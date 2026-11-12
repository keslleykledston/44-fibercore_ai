package oltsecrets

import (
	"context"
	"log/slog"
	"sort"
	"sync"
	"time"

	"github.com/keslleykledston/44-fibercore_ai/agents/edge/internal/gateway"
	"github.com/keslleykledston/44-fibercore_ai/agents/edge/internal/managedolts"
)

// Timings of the state report.
const (
	// ReportEvery: the report is repeated at least this often even when nothing changed (the Cloud may have lost it, or the Edge restarted).
	ReportEvery = 5 * time.Minute
	// OldCloudRetry: after a 404 (a Cloud that does not know the route yet) the Edge asks again this much later.
	OldCloudRetry = time.Hour
	// RefusedBackoff (shared with the seal key) is the wait after any other 4xx.
)

// StateCloud is the part of the gateway the reporter uses (the real *gateway.Client, or a fake in tests).
type StateCloud interface {
	ReportManagedState(ctx context.Context, items []gateway.ManagedState) (gateway.Outcome, int, error)
	SecretsWaitUntil() time.Time
}

// StateReporter tells the Cloud, per managed OLT, whether it awaits the local trust or is trusted (and, once, that one was removed), on every change and every ReportEvery
// (ADR-0046 D6). The "removed" states come from the durable tombstones of the store (removed.json), which are cleared only after the Cloud has accepted the report, so a
// restart between a `remove` and the report loses nothing. It is best-effort and never a failure of a delivery: 5xx, 429 and network errors are retried at the next round;
// a 404 means "an older Cloud" and is logged once; any other refusal waits a few minutes. It sends nothing at all while the registry is empty and nothing was removed.
type StateReporter struct {
	Store *managedolts.Store
	Cloud StateCloud
	Log   *slog.Logger
	Now   func() time.Time

	mu           sync.Mutex
	last         map[string]string // cloud_id -> state of the last report that went through
	lastAt       time.Time         // when that was
	blockedUntil time.Time
	oldCloud     bool // the 404 was already logged
	badState     bool // the unreadable-state warning was already logged
}

func (r *StateReporter) now() time.Time {
	if r.Now != nil {
		return r.Now()
	}
	return time.Now()
}

func (r *StateReporter) log() *slog.Logger {
	if r.Log != nil {
		return r.Log
	}
	return slog.New(slog.NewJSONHandler(discard{}, nil))
}

func sameStates(a, b map[string]string) bool {
	if len(a) != len(b) {
		return false
	}
	for k, v := range a {
		if b[k] != v {
			return false
		}
	}
	return true
}

// Tick sends the report when there is something to say and it is time.
func (r *StateReporter) Tick(ctx context.Context) {
	r.mu.Lock()
	defer r.mu.Unlock()
	now := r.now()
	if now.Before(r.blockedUntil) || time.Now().Before(r.Cloud.SecretsWaitUntil()) {
		return
	}
	list, err := r.Store.List()
	if err != nil {
		if !r.badState {
			r.badState = true
			r.log().Warn("managed olts: the registry cannot be read; the state is not reported", "err", err)
		}
		return
	}
	cur := make(map[string]string, len(list))
	for _, it := range list {
		cur[it.Entry.CloudID] = it.State()
	}
	tomb, terr := r.Store.Tombstones()
	if terr != nil { // a state that cannot be read cannot be reported; the live states still go out
		if !r.badState {
			r.badState = true
			r.log().Warn("managed olts: the removal records cannot be read; \"removed\" is not reported until they can", "err", terr)
		}
		tomb = nil
	} else {
		r.badState = false
	}
	var removed, stale []string
	for _, id := range tomb {
		if _, back := cur[id]; back { // added again: it is not "removed"
			stale = append(stale, id)
			continue
		}
		removed = append(removed, id)
	}
	if len(stale) > 0 {
		_ = r.Store.ClearTombstones(stale)
	}
	if len(cur) == 0 && len(removed) == 0 {
		r.last = cur
		return
	}
	if sameStates(cur, r.last) && len(removed) == 0 && now.Sub(r.lastAt) < ReportEvery {
		return
	}
	items := make([]gateway.ManagedState, 0, len(cur)+len(removed))
	ids := make([]string, 0, len(cur))
	for id := range cur {
		ids = append(ids, id)
	}
	sort.Strings(ids)
	for _, id := range ids {
		items = append(items, gateway.ManagedState{CloudID: id, State: cur[id]})
	}
	for _, id := range removed {
		items = append(items, gateway.ManagedState{CloudID: id, State: managedolts.StateRemoved})
	}
	for start := 0; start < len(items); start += gateway.MaxManagedStateItems {
		end := start + gateway.MaxManagedStateItems
		if end > len(items) {
			end = len(items)
		}
		out, status, rerr := r.Cloud.ReportManagedState(ctx, items[start:end])
		switch out {
		case gateway.Delivered:
			continue
		case gateway.Throttled:
			return // the gateway recorded the wait
		case gateway.Rejected:
			if status == 404 { // a Cloud that does not have the route yet: an older Cloud, not an error
				if !r.oldCloud {
					r.oldCloud = true
					r.log().Info("managed olts: the Cloud does not know the state route (an older Cloud); the state is not reported until it does", "retry_in", OldCloudRetry.String())
				}
				r.blockedUntil = now.Add(OldCloudRetry)
				return
			}
			r.log().Warn("managed olts: the Cloud refused the state report; trying again later", "status", status)
			r.blockedUntil = now.Add(RefusedBackoff)
			return
		default:
			r.log().Warn("managed olts: the state report did not go through; trying again next round", "status", status, "err", rerr)
			return
		}
	}
	r.oldCloud = false
	r.last, r.lastAt = cur, now
	if err := r.Store.ClearTombstones(removed); err != nil { // reported again next round (idempotent in the Cloud)
		r.log().Warn("managed olts: the removal records could not be cleared", "err", err)
	}
}
