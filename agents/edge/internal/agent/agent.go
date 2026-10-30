// Package agent runs the Edge loops: heartbeat, collection into the durable queue, and ordered delivery.
package agent

import (
	"context"
	"encoding/json"
	"errors"
	"log/slog"
	"sync/atomic"
	"time"

	"github.com/keslleykledston/44-fibercore_ai/agents/edge/internal/bench"
	"github.com/keslleykledston/44-fibercore_ai/agents/edge/internal/collector"
	"github.com/keslleykledston/44-fibercore_ai/agents/edge/internal/gateway"
	"github.com/keslleykledston/44-fibercore_ai/agents/edge/internal/jobs"
	"github.com/keslleykledston/44-fibercore_ai/agents/edge/internal/nbi"
	"github.com/keslleykledston/44-fibercore_ai/agents/edge/internal/olt"
	"github.com/keslleykledston/44-fibercore_ai/agents/edge/internal/oltquery"
	"github.com/keslleykledston/44-fibercore_ai/agents/edge/internal/queue"
)

// RefreshFunc performs the authorised active read of ONE device (ADR-SD-002 item 4) and returns a counts-only detail.
type RefreshFunc func(ctx context.Context, deviceRef string) (detail string, err error)

type Agent struct {
	EdgeID, TenantID, Version string
	GW                        *gateway.Client
	Q                         *queue.Queue
	Collectors                []collector.Collector
	Jobs                      *jobs.Verifier  // nil => job polling disabled
	Refresher                 RefreshFunc     // nil => refresh jobs that name a device fail closed
	Queries                   *oltquery.Store // nil => olt_query jobs are refused (ADR-0029); the queries run in the OLT collector's own session
	Bench                     *bench.Runner   // nil => bench writes are refused (ADR-0030); its Lease is fed from every poll answer
	JobPollEvery              time.Duration
	HeartbeatEvery            time.Duration
	CollectEvery              time.Duration
	Log                       *slog.Logger
}

// CollectOnce runs every collector and persists results BEFORE any network delivery (store-and-forward).
// A failing collector is logged and never blocks the others. Returns an error when the round was incomplete
// (collector or persistence failure) so the caller can retry sooner than the regular interval.
func (a *Agent) CollectOnce(ctx context.Context) error {
	var errs []error
	for _, c := range a.Collectors {
		items, err := c.Collect(ctx)
		complete := err == nil // a partial result is still persisted, but never supersedes the previous complete round
		if err != nil {
			a.Log.Warn("collector failed (partial results are kept)", "collector", c.Name(), "items", len(items), "err", err)
			errs = append(errs, err)
		}
		round := time.Now().UnixNano()
		keys := map[string]struct{}{}
		for i, it := range items {
			if err := a.Q.Enqueue(ctx, it.Kind, it.Key, round, it.Payload); err != nil {
				a.Log.Error("enqueue failed; round incomplete", "collector", c.Name(), "unsaved_items", len(items)-i, "err", err)
				errs = append(errs, err)
				complete = false
				break // remaining items of this collector stay un-persisted => round marked incomplete
			}
			keys[it.Key] = struct{}{}
		}
		if complete { // only a fully persisted round may supersede the previous one
			for k := range keys {
				if k == "" {
					continue
				}
				if err := a.Q.PruneSuperseded(ctx, k, round); err != nil {
					a.Log.Warn("prune superseded failed", "key", k, "err", err)
				}
			}
		}
	}
	if d := a.Q.Dropped; d > 0 {
		a.Log.Warn("queue backpressure dropped oldest snapshots", "total_dropped", d)
	}
	a.reportQueries(ctx) // queries that ran in this round's session
	return errors.Join(errs...)
}

// Flush delivers queued items oldest-first. It stops at the first transient failure to preserve order.
func (a *Agent) Flush(ctx context.Context) {
	for {
		items, err := a.Q.Next(ctx, 20)
		if err != nil || len(items) == 0 {
			return
		}
		for _, it := range items {
			out, derr := a.GW.Deliver(ctx, it.Kind, it.Payload)
			switch out {
			case gateway.Delivered:
				// If the ack fails the item is redelivered; snapshots are idempotent in the Cloud
				// (upsert guarded by observed_at), so a duplicate is harmless.
				if err := a.Q.Ack(ctx, it.ID); err != nil {
					a.Log.Error("ack failed; item will be redelivered (idempotent)", "id", it.ID, "err", err)
					return
				}
			case gateway.Rejected:
				a.Log.Error("payload rejected by cloud; dead-lettering", "id", it.ID, "err", derr)
				if err := a.Q.Dead(ctx, it, derr.Error()); err != nil {
					a.Log.Error("dead-letter failed; stopping flush to retry later", "id", it.ID, "err", err)
					return
				}
			default:
				dead, _ := a.Q.Retry(ctx, it, errString(derr))
				a.Log.Warn("delivery deferred", "id", it.ID, "err", derr, "dead_lettered", dead)
				if !dead {
					return
				}
			}
		}
	}
}

// PollJob fetches at most one job, verifies it and executes it. Unverifiable envelopes are dropped and logged: nothing
// unauthenticated is ever acted upon, nor trusted enough to report on.
func (a *Agent) PollJob(ctx context.Context) {
	if a.Jobs == nil {
		return
	}
	a.reportQueries(ctx) // outcomes of queries that ran in a collection session, or that expired or lost their outcome, travel as they become known
	raw, lease, err := a.GW.NextJob(ctx)
	if err != nil {
		a.Log.Warn("job poll failed", "err", err) // the lease already held simply runs out on its own
		return
	}
	if a.Bench != nil {
		if lerr := a.Bench.Lease.Accept(lease); lerr != nil {
			a.Log.Warn("bench lease rejected; bench writes unavailable until a valid one arrives", "err", lerr)
		}
	}
	if raw == nil {
		return
	}
	env, err := a.Jobs.Verify(ctx, raw)
	if err != nil {
		a.Log.Error("job envelope rejected", "err", err)
		return
	}
	a.Log.Info("job accepted", "job_id", env.JobID, "operation", env.Operation)
	if jobs.QueryOps[env.Operation] {
		a.reportJob(ctx, env.JobID, "accepted", "", false)
		a.queueQuery(ctx, env)
		return
	}
	// Outcomes go through the durable queue (ordered after the data they refer to, retried until the Cloud acknowledges;
	// the Cloud treats repeats of the same outcome as no-ops). A lost response can no longer strand a job.
	a.reportJob(ctx, env.JobID, "accepted", "", false)
	if jobs.BenchWriteOps[env.Operation] {
		a.runBench(ctx, env)
		return
	}
	// A refresh that names a device asks the ACS to read it first (rate-limited, allowlisted). Without a configured Refresher it fails closed.
	refreshDetail := ""
	if env.Operation == "refresh" && env.TargetRef != "" {
		if a.Refresher == nil {
			a.reportJob(ctx, env.JobID, "failed", "active refresh is not enabled on this edge", false)
			a.Flush(ctx)
			return
		}
		d, rerr := a.Refresher(ctx, env.TargetRef)
		if rerr != nil {
			a.Log.Warn("refresh failed", "job_id", env.JobID, "err", rerr)
			a.reportJob(ctx, env.JobID, "failed", "refresh not performed: "+refreshReason(rerr), false)
			a.Flush(ctx)
			return
		}
		refreshDetail = d
	}
	// collect/refresh are the only operations that pass Verify: a fresh read-only round, then delivery.
	cerr := a.CollectOnce(ctx)
	a.Flush(ctx)
	pending, _, qerr := a.Q.Counts(ctx)
	ok := cerr == nil && qerr == nil && pending == 0 // post-check: round complete AND everything delivered
	state, detail := "succeeded", "collection round delivered"
	if refreshDetail != "" {
		detail = refreshDetail + "; " + detail
	}
	if !ok {
		state, detail = "failed", "collection incomplete or delivery pending"
	}
	a.reportJob(ctx, env.JobID, state, detail, ok)
	a.Flush(ctx)
}

// runBench hands a verified bench write to the runner OFF the poll loop (the CPE takes minutes to boot again; heartbeats must not stop).
// The runner refuses a second operation while one runs. Without a runner the job fails closed.
func (a *Agent) runBench(ctx context.Context, env *jobs.Envelope) {
	if a.Bench == nil {
		a.reportJob(ctx, env.JobID, "failed", "bench writes are not enabled on this edge", false)
		a.Flush(ctx)
		return
	}
	go func() {
		res := a.Bench.Run(ctx, env)
		a.Log.Info("bench job finished", "job_id", env.JobID, "state", res.State, "detail", res.Detail)
		a.reportJob(ctx, env.JobID, res.State, res.Detail, res.Postcheck)
		a.Flush(ctx)
	}()
}

func (a *Agent) reportJob(ctx context.Context, jobID, state, detail string, postcheck bool) {
	b, _ := json.Marshal(map[string]any{"job_id": jobID, "state": state, "detail": detail, "postcheck_ok": postcheck})
	if err := a.Q.Enqueue(ctx, "job_result", "", 0, b); err != nil {
		a.Log.Error("could not persist job result", "job_id", jobID, "err", err)
	}
}

func (a *Agent) pollEvery() time.Duration {
	if a.Jobs == nil || a.JobPollEvery <= 0 {
		return time.Hour * 24 * 365 // effectively never
	}
	return a.JobPollEvery
}

func errString(err error) string {
	if err == nil {
		return ""
	}
	return err.Error()
}

func (a *Agent) Run(ctx context.Context) {
	poll := time.NewTicker(a.pollEvery())
	defer poll.Stop()
	hb := time.NewTicker(a.HeartbeatEvery)
	col := time.NewTicker(a.CollectEvery)
	defer hb.Stop()
	defer col.Stop()
	retry := time.NewTimer(time.Hour)
	retry.Stop()
	defer retry.Stop()
	// Collection runs OFF the main loop so a slow OLT never delays heartbeats; at most one round at a time.
	var running atomic.Bool
	retryCh := make(chan struct{}, 1)
	collect := func() {
		if !running.CompareAndSwap(false, true) {
			return // previous round still running: skip, do not pile up
		}
		go func() {
			defer running.Store(false)
			cctx, cancel := context.WithTimeout(ctx, 10*time.Minute)
			defer cancel()
			if err := a.CollectOnce(cctx); err != nil {
				select { // incomplete round: schedule a sooner retry
				case retryCh <- struct{}{}:
				default:
				}
			}
			a.Flush(ctx)
		}()
	}
	collect()
	for {
		select {
		case <-ctx.Done():
			return
		case <-hb.C:
			if out, err := a.GW.Heartbeat(ctx, a.EdgeID, a.TenantID, a.Version); out != gateway.Delivered {
				a.Log.Warn("heartbeat failed", "err", err)
			}
		case <-col.C:
			collect()
		case <-poll.C:
			a.PollJob(ctx)
		case <-retryCh:
			retry.Reset(30 * time.Second)
		case <-retry.C:
			collect()
		}
	}
}

// refreshReason is what may travel to the Cloud about a refused/failed refresh: a short category, never device ids or raw errors.
func refreshReason(err error) string {
	switch {
	case errors.Is(err, nbi.ErrRefreshTooSoon):
		return "device refreshed too recently"
	case errors.Is(err, nbi.ErrRefreshBudget):
		return "hourly refresh budget exhausted"
	case errors.Is(err, nbi.ErrRefreshUncleaned):
		return "a pending task may remain on the ACS; operator check required"
	case errors.Is(err, nbi.ErrRefreshPending):
		return "a pending task already exists on the ACS; operator check required"
	case errors.Is(err, nbi.ErrRefreshHeld):
		return "device on hold after an unclean refresh"
	case errors.Is(err, nbi.ErrRefreshNoReserve):
		return "pacing state unavailable"
	case errors.Is(err, nbi.ErrBadDeviceID), errors.Is(err, nbi.ErrNoDataModel):
		return "device unknown or data model unsupported"
	default:
		return "acs request failed"
	}
}

// queueQuery puts a verified olt_query on the durable queue. NOTHING runs here: the query is executed later, inside a CLI session the OLT guard already
// permits, after the collection's own commands (collector.Queries). The Cloud sees `accepted` now and the typed result (or the failure category) later.
func (a *Agent) queueQuery(ctx context.Context, env *jobs.Envelope) {
	if a.Queries == nil {
		a.reportJob(ctx, env.JobID, "failed", "olt queries are not enabled on this edge", false)
		a.Flush(ctx)
		return
	}
	intent, err := olt.ParseIntent(env.Params) // verified once already; the queue only ever holds what the catalog accepts
	exp, terr := time.Parse(time.RFC3339, env.ExpiresAt)
	if err != nil || terr != nil {
		a.reportJob(ctx, env.JobID, "failed", "query_not_accepted", false)
		a.Flush(ctx)
		return
	}
	if err := a.Queries.Enqueue(env.JobID, oltquery.Intent{QueryID: intent.Query.ID, OLTRef: intent.OLTRef, Slot: intent.Params.Slot, Port: intent.Params.Port, ONT: intent.Params.ONT}, exp); err != nil {
		a.Log.Warn("olt query not queued", "job_id", env.JobID, "err", err)
		reason := "queue_error"
		if errors.Is(err, oltquery.ErrQueueFull) {
			reason = "queue_full"
		}
		a.reportJob(ctx, env.JobID, "failed", reason, false)
	}
	a.Flush(ctx) // delivers the acceptance (or the refusal) now
}

// reportQueries hands the finished queries to the durable delivery queue and marks them reported only after that write succeeded. Re-sending is safe (the
// Cloud treats a repeated outcome as a no-op) and never executes anything.
func (a *Agent) reportQueries(ctx context.Context) {
	if a.Queries == nil {
		return
	}
	_, _ = a.Queries.ExpireDue() // waiting queries past their deadline end, and a claim nobody finished becomes UNKNOWN (no restart needed)
	pending, err := a.Queries.PendingReports()
	if err != nil {
		a.Log.Warn("olt query queue unreadable; nothing reported", "err", err)
		return
	}
	for _, e := range pending {
		m := map[string]any{"job_id": e.JobID}
		switch e.State {
		case oltquery.Executed:
			m["state"], m["postcheck_ok"], m["detail"], m["data"] = "succeeded", true, "typed result", json.RawMessage(e.Result)
		case oltquery.Unknown: // it may have reached the OLT: not a failure, not a success, never repeated
			m["state"], m["postcheck_ok"], m["detail"] = "succeeded", false, "outcome unknown after a restart"
		default:
			m["state"], m["postcheck_ok"], m["detail"] = "failed", false, e.Reason
		}
		b, _ := json.Marshal(m)
		if err := a.Q.Enqueue(ctx, "job_result", "", 0, b); err != nil {
			a.Log.Error("could not persist olt query result", "job_id", e.JobID, "err", err)
			return
		}
		if err := a.Queries.MarkReported(e.JobID); err != nil {
			a.Log.Error("could not mark olt query reported", "job_id", e.JobID, "err", err)
			return
		}
	}
	if len(pending) > 0 {
		a.Flush(ctx)
	}
}
