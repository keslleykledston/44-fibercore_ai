package collector

import (
	"context"
	"encoding/json"
	"errors"
	"time"

	"github.com/keslleykledston/44-fibercore_ai/agents/edge/internal/jobs"
	"github.com/keslleykledston/44-fibercore_ai/agents/edge/internal/olt"
	"github.com/keslleykledston/44-fibercore_ai/agents/edge/internal/oltquery"
)

// Queries runs the approved read-only `olt_query` jobs of ADR-0029 INSIDE the CLI session the periodic collection already holds: no session of its own,
// the same reservation, interval and cooldown of the guard, and only after the collection's own commands (the collection never waits for a query).
// Nothing here can fail the collection: a query that goes wrong ends the batch, and the snapshot that was already built is returned as it was.
type Queries struct {
	Store *oltquery.Store
	// Lease says which OLTs this Edge owns right now and with what epoch (the Cloud's signed lease, held in memory only). nil, or no lease for the OLT, runs
	// nothing: the same fail-closed rule as the bench writes.
	Lease LeaseChecker
	// Run executes one catalog query on the open session (olt.HuaweiR015.RunQuery); nil makes every query end as `no_driver`.
	Run func(ctx context.Context, s olt.Session, queryID string, p olt.Params) (olt.QueryResult, error)
	// SessionTimeout bounds the whole batch of one session (0 = 3 minutes).
	SessionTimeout time.Duration
	Now            func() time.Time
}

// LeaseChecker is the part of jobs.LeaseHolder the executor needs.
type LeaseChecker interface {
	Epoch(ref string) (int, bool)
	Check(ref string, epoch int) error
}

const (
	queryCommandsEach = 8       // identify + enable + config + enter + command + quit, with room: one query never exceeds this many commands
	queryMaxBytes     = 2 << 20 // bytes the batch may read in one session
	// minQueryWindow is the least time the collection must still have for a query to start (identify + modes + command + quit, each with a margin).
	minQueryWindow = 30 * time.Second
)

func (q *Queries) timeout() time.Duration {
	if q.SessionTimeout > 0 {
		return q.SessionTimeout
	}
	return 3 * time.Minute
}

// persistResult writes the typed result, retrying a transient disk error a few times, and if it still cannot, ends the entry as FAILED(persist_error) so it
// is reported instead of staying CLAIMED. If even that fails the entry is turned UNKNOWN by Store.ExpireDue once the claim is stale; it never runs again.
func (q *Queries) persistResult(jobID string, typed json.RawMessage) error {
	var err error
	for i := 0; i < 3; i++ {
		if err = q.Store.Complete(jobID, typed); err == nil {
			return nil
		}
		time.Sleep(time.Duration(i+1) * 50 * time.Millisecond)
	}
	_ = q.Store.Fail(jobID, "persist_error")
	return err
}

// windowLeft: the collection's time box is still open and holds at least minQueryWindow.
func windowLeft(ctx context.Context) bool {
	if ctx.Err() != nil {
		return false
	}
	dl, ok := ctx.Deadline()
	return !ok || time.Until(dl) >= minQueryWindow
}

// failureReason is the CATEGORY that may be recorded and reported; device text and error strings never are.
func failureReason(err error) string {
	switch {
	case errors.Is(err, olt.ErrQueryNotEnabled), errors.Is(err, olt.ErrUnknownQuery):
		return "query_not_enabled"
	case errors.Is(err, olt.ErrBadQueryParams):
		return "bad_params"
	case errors.Is(err, olt.ErrQueryFirmware):
		return "unsupported_firmware"
	case errors.Is(err, olt.ErrDeviceRejected):
		return "device_rejected"
	case errors.Is(err, olt.ErrPaginated):
		return "paginated"
	case errors.Is(err, olt.ErrNoParser):
		return "no_parser"
	case errors.Is(err, olt.ErrBadOutput):
		return "bad_output"
	case errors.Is(err, context.DeadlineExceeded), errors.Is(err, context.Canceled):
		return "timeout"
	case errors.Is(err, olt.ErrBudget):
		return "budget"
	}
	return "session_error"
}

// Drain runs the waiting queries of this OLT on `raw` (the session of the collection, allowlist and budget applied here again). It returns how many ran.
// `session` identifies this CLI session: the per-session budget is counted against it.
func (q *Queries) Drain(ctx context.Context, src OLTSource, raw olt.Session, cloudID, session string) (ran int) {
	if q == nil || q.Store == nil || cloudID == "" {
		return 0
	}
	if _, err := q.Store.ExpireDue(); err != nil {
		return 0 // an unreadable queue file means nothing is claimed
	}
	// Only inside the time the collection still has: a query never extends the round (ctx is the collection's own time box). Too little left = none starts.
	ctx, cancel := context.WithTimeout(ctx, q.timeout())
	defer cancel()
	sess := olt.NewBudget(olt.ReadOnlySession{Inner: raw, Allowed: src.Driver.Allowed}, queryCommandsEach*oltquery.PerSession, queryMaxBytes)
	for {
		// asked before EVERY claim, not once: whatever the previous query used, a new one starts only with the minimum window left
		if !windowLeft(ctx) {
			return ran
		}
		if q.Lease == nil {
			return ran
		}
		if _, ok := q.Lease.Epoch(cloudID); !ok { // no valid lease for this OLT (lost, withdrawn, mid-transfer, or the Edge just restarted): nothing is claimed
			return ran
		}
		e, err := q.Store.Claim(cloudID, session) // CLAIMED is on disk before anything is sent
		if err != nil {
			return ran
		}
		ran++
		if err := q.Lease.Check(cloudID, e.Intent.Epoch); err != nil { // the lease is asked again right at the claim, and for THIS query's epoch
			if errors.Is(err, jobs.ErrLeaseTarget) { // issued for another generation of the ownership: only THIS query is stale, the next one may be current
				_ = q.Store.Fail(e.JobID, "stale_owner")
				continue
			}
			_ = q.Store.Fail(e.JobID, "lease_lost") // the lease ran out between the check and the claim: nothing was sent, stop
			return ran
		}
		if !windowLeft(ctx) { // writing the claim took the time that was left: nothing was sent, and the query ends honestly instead of starting half-way
			_ = q.Store.Fail(e.JobID, "window_closed")
			return ran
		}
		fail := func(err error) int {
			_ = q.Store.Fail(e.JobID, failureReason(err))
			if !errors.Is(err, olt.ErrNoParser) { // a query that has nothing to run ends alone; any failure of the device or the session ends the batch
				_, _ = q.Store.AbortBatch(cloudID, "olt_busy")
				return -1
			}
			return 0
		}
		if q.Run == nil || !olt.HasParser(e.Intent.QueryID) {
			if q.Run == nil {
				_ = q.Store.Fail(e.JobID, "no_driver")
				_, _ = q.Store.AbortBatch(cloudID, "olt_busy")
				return ran
			}
			fail(olt.ErrNoParser)
			continue // nothing was sent to the device
		}
		res, err := q.Run(ctx, sess, e.Intent.QueryID, olt.Params{Slot: e.Intent.Slot, Port: e.Intent.Port, ONT: e.Intent.ONT})
		if err != nil {
			fail(err)
			return ran
		}
		typed, err := olt.ParseResult(e.Intent.QueryID, res.Output)
		if err == nil && res.Truncated {
			err = olt.ErrBadOutput // a cut listing is not a result
		}
		if err != nil {
			fail(err)
			return ran
		}
		if err := q.persistResult(e.JobID, typed); err != nil {
			_, _ = q.Store.AbortBatch(cloudID, "olt_busy")
			return ran
		}
	}
}
