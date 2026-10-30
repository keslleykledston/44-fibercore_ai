// Package bench runs the Edge half of the bench homologation gate (ADR-0030). A bench write executes only when ALL of these hold, checked here
// in this order and each one failing closed: the device is on the local closed list; a Cloud lease valid right now names it with the envelope's
// owner epoch; the ACS shows exactly that device (OUI/class/serial) recently online; the pacing slot is reserved on disk; and the single-use
// authorization is durably claimed. Only then is the command sent, once, never retried.
package bench

import (
	"context"
	"errors"
	"log/slog"
	"sync/atomic"
	"time"

	"github.com/keslleykledston/44-fibercore_ai/agents/edge/internal/jobs"
	"github.com/keslleykledston/44-fibercore_ai/agents/edge/internal/nbi"
)

type ACS interface {
	BenchIdentity(ctx context.Context, d nbi.BenchDevice, now time.Time) error
	SetBenchSSID(ctx context.Context, d nbi.BenchDevice, ssid string, valid func(string) bool, notAfter time.Time, restoreFile string, now func() time.Time) (nbi.SSIDOutcome, error)
	RebootBench(ctx context.Context, d nbi.BenchDevice, notAfter time.Time, wait, poll time.Duration, now func() time.Time) (nbi.BenchOutcome, error)
}

type Guard interface{ Reserve(deviceID string) error }

type Result struct {
	State     string // accepted-final states for the Cloud: "succeeded" | "failed"
	Detail    string // short category only: never a device id, serial or raw error
	Postcheck bool
}

type Runner struct {
	Devices     map[string]nbi.BenchDevice // by ACS device id: the local closed list
	Lease       *jobs.LeaseHolder
	Claims      *jobs.Claims
	Guard       Guard
	ACS         ACS
	RestoreFile string        // H3: where the original SSID is kept (local only) until the restore is confirmed
	Wait        time.Duration // how long to wait for the CPE to boot again
	Poll        time.Duration
	Now         func() time.Time
	Log         *slog.Logger

	busy atomic.Bool
}

func (r *Runner) now() time.Time {
	if r.Now != nil {
		return r.Now()
	}
	return time.Now()
}

func fail(detail string) Result { return Result{State: "failed", Detail: detail} }

// Run executes one verified bench envelope. At most one runs at a time on this Edge.
func (r *Runner) Run(ctx context.Context, env *jobs.Envelope) Result {
	if !jobs.BenchWriteOps[env.Operation] || (env.Operation != "reboot_cpe" && env.Operation != "set_wifi_ssid") {
		return fail("operation not supported on the bench")
	}
	if !r.busy.CompareAndSwap(false, true) {
		return fail("another bench operation is running")
	}
	defer r.busy.Store(false)
	notAfter, err := deadline(env)
	if err != nil || !r.now().Before(notAfter) {
		return fail("envelope or authorization window already over")
	}
	dev, ok := r.Devices[env.TargetRef]
	if !ok {
		return fail("target is not on the local bench list")
	}
	if err := r.Lease.Check(env.TargetRef, env.OwnerEpoch); err != nil {
		return fail("no valid Cloud lease for this target")
	}
	if err := r.ACS.BenchIdentity(ctx, dev, r.now()); err != nil {
		if errors.Is(err, nbi.ErrBenchOffline) {
			return fail("device not recently online")
		}
		return fail("device identity not confirmed")
	}
	// re-check the lease after the (network) identity read: it may have lapsed or moved while we waited
	if err := r.Lease.Check(env.TargetRef, env.OwnerEpoch); err != nil {
		return fail("no valid Cloud lease for this target")
	}
	if !r.now().Before(notAfter) { // identity read took too long: do not spend the pacing slot nor the authorization
		return fail("envelope or authorization window already over")
	}
	if err := r.Guard.Reserve(env.TargetRef); err != nil {
		return fail("pacing: too soon or state unavailable")
	}
	if err := r.Claims.Claim(env.AuthorizationID, env.JobID, env.TargetRef, env.OwnerEpoch); err != nil {
		if errors.Is(err, jobs.ErrClaimTaken) {
			return fail("authorization already used on this edge")
		}
		if errors.Is(err, jobs.ErrStaleEpoch) {
			return fail("owner epoch is older than one already seen")
		}
		return fail("claim state unavailable")
	}
	// From here the authorization is spent.
	if env.Operation == "set_wifi_ssid" {
		return r.setSSID(ctx, env, dev, notAfter)
	}
	out, err := r.ACS.RebootBench(ctx, dev, notAfter, r.Wait, r.Poll, r.now)
	switch {
	case err == nil && out.Accepted && out.PostcheckOK:
		r.finish(env, jobs.ClaimDone)
		return Result{State: "succeeded", Detail: "reboot delivered and the device came back", Postcheck: true}
	case err == nil && out.Accepted:
		r.finish(env, jobs.ClaimUnknown)
		return Result{State: "succeeded", Detail: "reboot delivered; return of the device not confirmed"}
	case !out.Attempted || nbi.IsNotDelivered(err):
		r.finish(env, jobs.ClaimFailed)
		return fail("reboot not sent or not delivered")
	default:
		r.finish(env, jobs.ClaimUnknown)
		return Result{State: "failed", Detail: "outcome unknown; operator check required"}
	}
}

// setSSID is H3: the value was validated at the envelope; the ACS layer validates it again and restores the original before it reports.
func (r *Runner) setSSID(ctx context.Context, env *jobs.Envelope, dev nbi.BenchDevice, notAfter time.Time) Result {
	out, err := r.ACS.SetBenchSSID(ctx, dev, env.Params["ssid"], jobs.BenchSSIDRe.MatchString, notAfter, r.RestoreFile, r.now)
	switch {
	case err == nil && out.Applied && out.Verified && out.Restored:
		r.finish(env, jobs.ClaimDone)
		return Result{State: "succeeded", Detail: out.Detail, Postcheck: true}
	case err == nil && out.Restored: // the original is back, but the change was not proven (acknowledged without read-back, or unanswered)
		r.finish(env, jobs.ClaimUnknown)
		return Result{State: "failed", Detail: out.Detail}
	case !out.Attempted || nbi.IsNotDelivered(err):
		r.finish(env, jobs.ClaimFailed)
		return fail("ssid not sent or not delivered")
	case errors.Is(err, nbi.ErrBenchRestore):
		r.finish(env, jobs.ClaimUnknown)
		return Result{State: "failed", Detail: "restore of the original SSID not confirmed; operator must restore it"}
	default:
		r.finish(env, jobs.ClaimUnknown)
		return Result{State: "failed", Detail: "outcome unknown; operator check required"}
	}
}

// deadline is the last instant a command may be sent: the earlier of the envelope's expiry and the end of the authorization window.
func deadline(env *jobs.Envelope) (time.Time, error) {
	exp, e1 := time.Parse(time.RFC3339, env.ExpiresAt)
	end, e2 := time.Parse(time.RFC3339, env.AuthorizationEndsAt)
	if e1 != nil || e2 != nil {
		return time.Time{}, errors.New("unreadable validity")
	}
	if end.Before(exp) {
		return end, nil
	}
	return exp, nil
}

func (r *Runner) finish(env *jobs.Envelope, state string) {
	if err := r.Claims.Finish(env.AuthorizationID, state); err != nil && r.Log != nil {
		r.Log.Error("could not persist the final claim state (it reads back as UNKNOWN)", "job_id", env.JobID)
	}
}
