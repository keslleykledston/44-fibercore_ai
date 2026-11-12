package oltsecrets

import (
	"context"
	"errors"
	"log/slog"
	"sync"
	"time"

	"github.com/keslleykledston/44-fibercore_ai/agents/edge/internal/gateway"
)

// Cloud is the part of the gateway the worker uses (the real *gateway.Client, or a fake in tests).
type Cloud interface {
	PublishSealKey(ctx context.Context, publicKey string) (gateway.Outcome, int, error)
	NextSecretDelivery(ctx context.Context) (*gateway.SecretDelivery, error)
	SecretDeliveryResult(ctx context.Context, id, leaseToken, outcome, code string) (gateway.Outcome, int, error)
	SecretsWaitUntil() time.Time
}

const (
	// MinGap: Tick does nothing if called again sooner (the agent calls it on a timer AND right after a heartbeat).
	MinGap = 10 * time.Second
	// RepublishEvery: the public key is sent at the start and then now and then (idempotent in the Cloud); a refusal is not retried sooner than RefusedBackoff.
	RepublishEvery = 6 * time.Hour
	RefusedBackoff = 5 * time.Minute
	// PerTick bounds the deliveries handled in one round (a stuck one cannot make the round endless).
	PerTick = 5
)

// Worker is the delivery loop. It never touches an OLT and holds no lock the collection uses: it only talks to the Cloud and writes the credentials file, which
// the collection reads atomically at the start of its next session.
type Worker struct {
	Cloud Cloud
	Proc  *Processor
	Log   *slog.Logger
	Now   func() time.Time
	// State (ADR-0046), when set, reports the trust state of the managed OLTs to the Cloud at the end of every round (on a change, and now and then).
	State *StateReporter

	mu          sync.Mutex
	lastTick    time.Time
	published   bool      // the key reached the Cloud at least once in this process
	nextPublish time.Time // when to send it again (idempotent), or to retry a refusal
}

func (w *Worker) now() time.Time {
	if w.Now != nil {
		return w.Now()
	}
	return time.Now()
}

// Tick runs one round: publish the key when due, then take deliveries one by one until the Cloud has none. Everything that can go wrong is transient for the NEXT round and
// is never counted against a delivery.
func (w *Worker) Tick(ctx context.Context) {
	w.mu.Lock()
	defer w.mu.Unlock()
	now := w.now()
	if !w.lastTick.IsZero() && now.Sub(w.lastTick) < MinGap {
		return
	}
	w.lastTick = now
	if w.Log == nil {
		w.Log = slog.New(slog.NewJSONHandler(discard{}, nil))
	}
	w.round(ctx, now)
	if w.State != nil {
		w.State.Tick(ctx)
	}
}

// round is the delivery part of a Tick: publish the key when due, then take deliveries.
func (w *Worker) round(ctx context.Context, now time.Time) {
	if time.Now().Before(w.Cloud.SecretsWaitUntil()) { // the Cloud asked this Edge to wait (intake budget or this channel's own): no call is made (the gateway keeps these windows on the wall clock)
		return
	}
	if now.Before(w.nextPublish) && !w.published { // a refused first publication waits before it is asked again
		return
	}
	if !w.published || !now.Before(w.nextPublish) {
		out, status, err := w.Cloud.PublishSealKey(ctx, w.Proc.Key.PublicB64())
		switch out {
		case gateway.Delivered:
			w.published, w.nextPublish = true, now.Add(RepublishEvery)
			w.Log.Info("olt secrets: seal key published", "key_id", w.Proc.Key.KeyID())
		case gateway.Rejected:
			w.nextPublish = now.Add(RefusedBackoff)
			w.Log.Warn("olt secrets: the Cloud refused the seal key (feature off for this provider?); trying again later", "status", status)
			if !w.published {
				return
			}
		default:
			w.Log.Warn("olt secrets: seal key not published; trying again next round", "status", status, "err", err)
			if !w.published { // the Cloud cannot have a delivery for a key it never saw
				return
			}
		}
	}
	for i := 0; i < PerTick; i++ {
		d, err := w.Cloud.NextSecretDelivery(ctx)
		if err != nil {
			if !errors.Is(err, gateway.ErrSecretsThrottled) {
				w.Log.Warn("olt secrets: could not ask for a delivery; trying again next round", "err", err)
			}
			return
		}
		if d == nil {
			return
		}
		res, perr := w.Proc.Process(d)
		if perr != nil { // only a simulated crash: nothing is reported, the Cloud will hand the delivery out again
			return
		}
		out, status, rerr := w.Cloud.SecretDeliveryResult(ctx, d.ID, d.LeaseToken, res.Outcome, res.Code)
		switch {
		case errors.Is(rerr, gateway.ErrStaleLease):
			// a late result of an attempt the Cloud already replaced: nothing changed there; ask again (the redelivery lands in step 3 and answers applied)
			w.Log.Info("olt secrets: result of an old attempt (stale lease); asking again", "delivery_id", safeLog(d.ID))
			continue
		case out == gateway.Delivered:
			w.Log.Info("olt secrets: result reported", "delivery_id", safeLog(d.ID), "outcome", res.Outcome, "code", res.Code)
		case out == gateway.Throttled:
			return
		case out == gateway.Rejected:
			w.Log.Warn("olt secrets: the Cloud refused the result", "delivery_id", safeLog(d.ID), "status", status)
			return
		default:
			// network or 5xx: the delivery stays applied here; the next round gets it again and reports again (step 3), nothing is written twice
			w.Log.Warn("olt secrets: result not delivered; the next round reports it again", "delivery_id", safeLog(d.ID), "status", status, "err", rerr)
			return
		}
	}
}
