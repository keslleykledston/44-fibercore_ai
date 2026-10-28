// Package agent runs the Edge loops: heartbeat, collection into the durable queue, and ordered delivery.
package agent

import (
	"context"
	"errors"
	"log/slog"
	"time"

	"github.com/keslleykledston/44-fibercore_ai/agents/edge/internal/collector"
	"github.com/keslleykledston/44-fibercore_ai/agents/edge/internal/gateway"
	"github.com/keslleykledston/44-fibercore_ai/agents/edge/internal/queue"
)

type Agent struct {
	EdgeID, TenantID, Version string
	GW                        *gateway.Client
	Q                         *queue.Queue
	Collectors                []collector.Collector
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

func errString(err error) string {
	if err == nil {
		return ""
	}
	return err.Error()
}

func (a *Agent) Run(ctx context.Context) {
	hb := time.NewTicker(a.HeartbeatEvery)
	col := time.NewTicker(a.CollectEvery)
	defer hb.Stop()
	defer col.Stop()
	retry := time.NewTimer(time.Hour)
	retry.Stop()
	defer retry.Stop()
	collect := func() {
		if err := a.CollectOnce(ctx); err != nil {
			retry.Reset(30 * time.Second) // incomplete round: try again soon instead of waiting a full interval
		}
		a.Flush(ctx)
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
		case <-retry.C:
			collect()
		}
	}
}
