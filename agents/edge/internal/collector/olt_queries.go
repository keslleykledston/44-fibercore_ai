package collector

import (
	"context"
	"errors"
	"time"

	"github.com/keslleykledston/44-fibercore_ai/agents/edge/internal/olt"
	"github.com/keslleykledston/44-fibercore_ai/agents/edge/internal/oltquery"
)

// Queries runs the approved read-only `olt_query` jobs of ADR-0029 INSIDE the CLI session the periodic collection already holds: no session of its own,
// the same reservation, interval and cooldown of the guard, and only after the collection's own commands (the collection never waits for a query).
// Nothing here can fail the collection: a query that goes wrong ends the batch, and the snapshot that was already built is returned as it was.
type Queries struct {
	Store *oltquery.Store
	// Run executes one catalog query on the open session (olt.HuaweiR015.RunQuery); nil makes every query end as `no_driver`.
	Run func(ctx context.Context, s olt.Session, queryID string, p olt.Params) (olt.QueryResult, error)
	// SessionTimeout bounds the whole batch of one session (0 = 3 minutes).
	SessionTimeout time.Duration
	Now            func() time.Time
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
	if dl, ok := ctx.Deadline(); ok && time.Until(dl) < minQueryWindow {
		return 0
	}
	ctx, cancel := context.WithTimeout(ctx, q.timeout())
	defer cancel()
	sess := olt.NewBudget(olt.ReadOnlySession{Inner: raw, Allowed: src.Driver.Allowed}, queryCommandsEach*oltquery.PerSession, queryMaxBytes)
	for {
		if ctx.Err() != nil {
			return ran
		}
		e, err := q.Store.Claim(cloudID, session) // CLAIMED is on disk before anything is sent
		if err != nil {
			return ran
		}
		ran++
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
		if err := q.Store.Complete(e.JobID, typed); err != nil {
			_, _ = q.Store.AbortBatch(cloudID, "olt_busy")
			return ran
		}
	}
}
