// Package agent runs the Edge loops: heartbeat, collection into the durable queue, and ordered delivery.
package agent

import (
	"context"
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
// A failing collector is logged and never blocks the others or the Edge.
func (a *Agent) CollectOnce(ctx context.Context) {
	for _, c := range a.Collectors {
		items, err := c.Collect(ctx)
		if err != nil {
			a.Log.Warn("collector failed", "collector", c.Name(), "err", err)
			continue
		}
		for _, it := range items {
			if err := a.Q.Enqueue(ctx, it.Kind, it.Payload); err != nil {
				a.Log.Error("enqueue failed", "err", err)
			}
		}
	}
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
				_ = a.Q.Ack(ctx, it.ID)
			case gateway.Rejected:
				a.Log.Error("payload rejected by cloud; dead-lettered", "id", it.ID, "err", derr)
				_ = a.Q.Dead(ctx, it, derr.Error())
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
	a.CollectOnce(ctx)
	a.Flush(ctx)
	for {
		select {
		case <-ctx.Done():
			return
		case <-hb.C:
			if out, err := a.GW.Heartbeat(ctx, a.EdgeID, a.TenantID, a.Version); out != gateway.Delivered {
				a.Log.Warn("heartbeat failed", "err", err)
			}
		case <-col.C:
			a.CollectOnce(ctx)
			a.Flush(ctx)
		}
	}
}
