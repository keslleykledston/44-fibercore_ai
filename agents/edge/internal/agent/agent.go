// Package agent runs the Edge loops: heartbeat, collection into the durable queue, and ordered delivery.
package agent

import (
	"context"
	"encoding/json"
	"errors"
	"log/slog"
	"sync/atomic"
	"time"

	"github.com/keslleykledston/44-fibercore_ai/agents/edge/internal/collector"
	"github.com/keslleykledston/44-fibercore_ai/agents/edge/internal/gateway"
	"github.com/keslleykledston/44-fibercore_ai/agents/edge/internal/jobs"
	"github.com/keslleykledston/44-fibercore_ai/agents/edge/internal/nbi"
	"github.com/keslleykledston/44-fibercore_ai/agents/edge/internal/queue"
)

// RefreshFunc performs the authorised active read of ONE device (ADR-SD-002 item 4) and returns a counts-only detail.
type RefreshFunc func(ctx context.Context, deviceRef string) (detail string, err error)

type Agent struct {
	EdgeID, TenantID, Version string
	GW                        *gateway.Client
	Q                         *queue.Queue
	Collectors                []collector.Collector
	Jobs                      *jobs.Verifier // nil => job polling disabled
	Refresher                 RefreshFunc    // nil => refresh jobs that name a device fail closed
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
	raw, err := a.GW.NextJob(ctx)
	if err != nil {
		a.Log.Warn("job poll failed", "err", err)
		return
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
	// Outcomes go through the durable queue (ordered after the data they refer to, retried until the Cloud acknowledges;
	// the Cloud treats repeats of the same outcome as no-ops). A lost response can no longer strand a job.
	a.reportJob(ctx, env.JobID, "accepted", "", false)
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
