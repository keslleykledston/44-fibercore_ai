package bench

import (
	"context"
	"errors"
	"testing"

	"github.com/keslleykledston/44-fibercore_ai/agents/edge/internal/jobs"
	"github.com/keslleykledston/44-fibercore_ai/agents/edge/internal/nbi"
	"github.com/keslleykledston/44-fibercore_ai/agents/edge/internal/ping"
)

func pingSetup(t *testing.T) *env {
	e := setup(t)
	cat, err := ping.New(ping.Config{Enabled: true, CoreCIDRs: []string{"10.20.0.0/16"}, Targets: []ping.TargetConfig{{ID: "core-lab", Kind: "CORE", Host: "10.20.5.9"}, {ID: "dns-publico", Kind: "INTERNET", Host: "9.9.9.9"}}})
	if err != nil {
		t.Fatal(err)
	}
	e.r.Ping, e.r.WANInterface = cat, map[string]string{benchRef: wan181}
	e.acs.pingOut = nbi.PingOutcome{Attempted: true, Counters: &nbi.PingCounters{State: "Completed", Success: i64(5), Failure: i64(0), AvgMS: i64(12), MinMS: i64(9), MaxMS: i64(21)}}
	e.lease(t, jobs.LeaseTarget{TargetRef: benchRef, OwnerEpoch: 2})
	return e
}

func pingEnvelope(target string) *jobs.Envelope {
	en := envelope(benchRef)
	en.Operation = "ping_test"
	en.Params = jobs.Params{"target": target}
	return en
}

func TestPingReportsOnlyTheClosedShapeAndTheEdgeFixesTheTestShape(t *testing.T) {
	e := pingSetup(t)
	res := e.r.Run(context.Background(), pingEnvelope("dns-publico"))
	if res.State != "succeeded" || !res.Postcheck || res.Detail != "ping_done" {
		t.Fatalf("%+v", res)
	}
	want := map[string]any{"target": "dns-publico", "state": "Completed", "success": int64(5), "failure": int64(0), "avg_ms": int64(12), "min_ms": int64(9), "max_ms": int64(21)}
	for k, v := range want {
		if res.Data[k] != v {
			t.Errorf("%s = %v, want %v", k, res.Data[k], v)
		}
	}
	for k := range res.Data {
		if _, ok := want[k]; !ok && k != "polling_ms" {
			t.Errorf("unexpected key %q in the report", k)
		}
	}
	if len(e.acs.pingCalls) != 1 {
		t.Fatalf("calls %v", e.acs.pingCalls)
	}
	c := e.acs.pingCalls[0]
	if c.Root != "tr181" || c.Interface != wan181 || c.Host != "9.9.9.9" || c.Repetitions != 5 || c.TimeoutMS != 1000 {
		t.Fatalf("the request is the Edge's own: %+v", c)
	}
	if e.cl.State(authID) != jobs.ClaimDone {
		t.Fatalf("claim %q", e.cl.State(authID))
	}
	if len(e.acs.rebootCalls) != 0 || len(e.acs.ssidCalls) != 0 || len(e.acs.speedCalls) != 0 {
		t.Fatal("a ping test must not reboot, change the SSID or run a throughput test")
	}
}

func TestPingAbsentLeavesAreLeftOutNeverInvented(t *testing.T) {
	e := pingSetup(t)
	e.acs.pingOut = nbi.PingOutcome{Attempted: true, Counters: &nbi.PingCounters{State: "Error_CannotResolveHostName"}}
	res := e.r.Run(context.Background(), pingEnvelope("core-lab"))
	if res.State != "succeeded" || res.Data["state"] != "Error_CannotResolveHostName" {
		t.Fatalf("a device-reported error is a clear result: %+v", res)
	}
	for _, k := range []string{"success", "failure", "avg_ms", "min_ms", "max_ms"} {
		if _, ok := res.Data[k]; ok {
			t.Errorf("%q must be absent", k)
		}
	}
}

func TestPingRefusalsHappenBeforeAnythingIsSpent(t *testing.T) {
	cases := map[string]struct {
		mut    func(*env)
		env    *jobs.Envelope
		detail string
	}{
		"module off":        {func(e *env) { e.r.Ping = nil }, pingEnvelope("core-lab"), "ping_disabled"},
		"unknown target":    {func(e *env) {}, pingEnvelope("outro"), "target_unknown"},
		"no wan reference":  {func(e *env) { e.r.WANInterface = nil }, pingEnvelope("core-lab"), "wan_reference_missing"},
		"bad wan reference": {func(e *env) { e.r.WANInterface = map[string]string{benchRef: "Device.IP.Interface.1; x"} }, pingEnvelope("core-lab"), "wan_reference_missing"},
		"identity":          {func(e *env) { e.acs.idErr = nbi.ErrBenchIdentity }, pingEnvelope("core-lab"), "identity_not_confirmed"},
		"offline":           {func(e *env) { e.acs.idErr = nbi.ErrBenchOffline }, pingEnvelope("core-lab"), "device_offline"},
		"pacing":            {func(e *env) { e.r.Guard = okGuard{err: nbi.ErrRefreshTooSoon} }, pingEnvelope("core-lab"), "pacing"},
	}
	for name, c := range cases {
		e := pingSetup(t)
		c.mut(e)
		res := e.r.Run(context.Background(), c.env)
		if res.State != "failed" || res.Detail != c.detail || res.Data != nil {
			t.Errorf("%s: %+v (want detail %q)", name, res, c.detail)
		}
		if len(e.acs.pingCalls) != 0 {
			t.Errorf("%s: the ACS was asked to run a test", name)
		}
		if st := e.cl.State(authID); st != "" {
			t.Errorf("%s: the authorization was spent (%q)", name, st)
		}
	}
}

func TestPingAServiceWANThatIsNotConnectedHasItsOwnCodeAndTheClaimIsFailedNotUnknown(t *testing.T) {
	e := pingSetup(t)
	e.acs.pingOut, e.acs.pingErr = nbi.PingOutcome{}, nbi.ErrSpeedWANDown
	res := e.r.Run(context.Background(), pingEnvelope("core-lab"))
	if res.State != "failed" || res.Detail != "wan_not_connected" || res.Data != nil || res.Postcheck {
		t.Fatalf("%+v", res)
	}
	if e.cl.State(authID) != jobs.ClaimFailed {
		t.Fatalf("a refusal before any write must not spend the authorization as unknown: %q", e.cl.State(authID))
	}
}

func TestPingUncertainOutcomesAreFailedAndSpendTheAuthorizationAsUnknown(t *testing.T) {
	for name, c := range map[string]struct {
		out    nbi.PingOutcome
		err    error
		detail string
		claim  string
	}{
		"timeout":     {nbi.PingOutcome{Attempted: true}, nbi.ErrPingTimeout, "timeout", jobs.ClaimUnknown},
		"ambiguous":   {nbi.PingOutcome{Attempted: true}, errors.New("ambiguous ping request"), "outcome_unknown", jobs.ClaimUnknown},
		"uncleaned":   {nbi.PingOutcome{Attempted: true}, nbi.ErrBenchUncleaned, "outcome_unknown", jobs.ClaimUnknown},
		"not started": {nbi.PingOutcome{}, errors.New("device unreachable"), "ping_not_started", jobs.ClaimFailed},
	} {
		e := pingSetup(t)
		e.acs.pingOut, e.acs.pingErr = c.out, c.err
		res := e.r.Run(context.Background(), pingEnvelope("core-lab"))
		if res.State != "failed" || res.Detail != c.detail || res.Data != nil || res.Postcheck {
			t.Errorf("%s: %+v", name, res)
		}
		if e.cl.State(authID) != c.claim {
			t.Errorf("%s: claim %q, want %q", name, e.cl.State(authID), c.claim)
		}
	}
}

func TestPingOnADeviceOutsideTheBenchListIsRefused(t *testing.T) {
	e := pingSetup(t)
	e.lease(t, jobs.LeaseTarget{TargetRef: prodRef, OwnerEpoch: 2})
	en := pingEnvelope("core-lab")
	en.TargetRef = prodRef
	res := e.r.Run(context.Background(), en)
	if res.State != "failed" || res.Detail != "not_bench_device" || len(e.acs.pingCalls) != 0 {
		t.Fatalf("%+v", res)
	}
}
