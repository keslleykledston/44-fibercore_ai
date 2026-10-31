package bench

import (
	"context"
	"errors"
	"strings"
	"testing"

	"github.com/keslleykledston/44-fibercore_ai/agents/edge/internal/jobs"
	"github.com/keslleykledston/44-fibercore_ai/agents/edge/internal/nbi"
	"github.com/keslleykledston/44-fibercore_ai/agents/edge/internal/speed"
)

const wan181 = "Device.IP.Interface.1"

func i64(v int64) *int64 { return &v }

func speedSetup(t *testing.T) *env {
	e := setup(t)
	cat, err := speed.New(speed.Config{Enabled: true, CoreCIDRs: []string{"10.20.0.0/16"}, Endpoints: []speed.EndpointConfig{{ID: "core-sp-1", Kind: "CORE", Host: "10.20.5.9", Port: 8080}}})
	if err != nil {
		t.Fatal(err)
	}
	e.r.Speed, e.r.WANInterface = cat, map[string]string{benchRef: wan181}
	e.acs.speedOut = nbi.SpeedOutcome{Attempted: true, Counters: &nbi.SpeedCounters{State: "Completed", BOM: "2026-10-30T12:00:01Z", EOM: "2026-10-30T12:00:09Z",
		TestBytesReceived: i64(10_000_000), TotalBytesReceived: i64(10_001_234), TotalBytesSent: i64(10_000_000)}}
	e.lease(t, jobs.LeaseTarget{TargetRef: benchRef, OwnerEpoch: 2})
	return e
}

func speedEnvelope(op, target, profile string) *jobs.Envelope {
	en := envelope(benchRef)
	en.Operation = op
	en.Params = jobs.Params{"target": target, "profile": profile}
	return en
}

func TestSpeedDownloadReportsOnlyTheClosedShape(t *testing.T) {
	e := speedSetup(t)
	res := e.r.Run(context.Background(), speedEnvelope("speed_test_download", "core-sp-1", "10mb"))
	if res.State != "succeeded" || !res.Postcheck || res.Detail != "speed_done" {
		t.Fatalf("%+v", res)
	}
	want := map[string]any{"direction": "download", "target": "core-sp-1", "profile": "10mb", "state": "Completed", "bom": "2026-10-30T12:00:01Z", "eom": "2026-10-30T12:00:09Z",
		"test_bytes_received": int64(10_000_000), "total_bytes_received": int64(10_001_234), "total_bytes_sent": int64(10_000_000)}
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
	if len(e.acs.speedCalls) != 1 {
		t.Fatalf("calls %v", e.acs.speedCalls)
	}
	c := e.acs.speedCalls[0]
	if c.Direction != "download" || c.Root != "tr181" || c.Interface != wan181 || c.URL != "http://10.20.5.9:8080/dl/10mb" || c.FileLength != 0 {
		t.Fatalf("%+v", c)
	}
	if e.cl.State(authID) != jobs.ClaimDone {
		t.Fatalf("claim %q", e.cl.State(authID))
	}
	if len(e.acs.rebootCalls) != 0 || len(e.acs.ssidCalls) != 0 {
		t.Fatal("a speed test must not reboot or change the SSID")
	}
}

func TestSpeedUploadAsksForTheProfileLengthAndReportsIt(t *testing.T) {
	e := speedSetup(t)
	res := e.r.Run(context.Background(), speedEnvelope("speed_test_upload", "core-sp-1", "50mb"))
	if res.State != "succeeded" || res.Data["test_file_length"] != int64(50_000_000) || res.Data["direction"] != "upload" {
		t.Fatalf("%+v", res)
	}
	c := e.acs.speedCalls[0]
	if c.Direction != "upload" || c.URL != "http://10.20.5.9:8080/ul/50mb" || c.FileLength != 50_000_000 {
		t.Fatalf("%+v", c)
	}
}

func TestSpeedAbsentCountersAreLeftOutNeverInvented(t *testing.T) {
	e := speedSetup(t)
	e.acs.speedOut = nbi.SpeedOutcome{Attempted: true, Counters: &nbi.SpeedCounters{State: "Error_InitConnectionFailed"}}
	res := e.r.Run(context.Background(), speedEnvelope("speed_test_download", "core-sp-1", "10mb"))
	if res.State != "succeeded" {
		t.Fatalf("a device-reported error is a clear result: %+v", res)
	}
	for _, k := range []string{"bom", "eom", "test_bytes_received", "total_bytes_received", "test_bytes_sent", "total_bytes_sent", "test_file_length"} {
		if _, ok := res.Data[k]; ok {
			t.Errorf("%q must be absent", k)
		}
	}
	if res.Data["state"] != "Error_InitConnectionFailed" {
		t.Fatalf("%v", res.Data)
	}
}

func TestSpeedRefusalsHappenBeforeAnythingIsSpent(t *testing.T) {
	cases := map[string]struct {
		mut    func(*env)
		env    *jobs.Envelope
		detail string
	}{
		"module off":       {func(e *env) { e.r.Speed = nil }, speedEnvelope("speed_test_download", "core-sp-1", "10mb"), "speed_disabled"},
		"unknown endpoint": {func(e *env) {}, speedEnvelope("speed_test_download", "other-node", "10mb"), "endpoint_unknown"},
		"unknown profile":  {func(e *env) {}, speedEnvelope("speed_test_download", "core-sp-1", "1gb"), "endpoint_unknown"},
		"no wan reference": {func(e *env) { e.r.WANInterface = nil }, speedEnvelope("speed_test_download", "core-sp-1", "10mb"), "wan_reference_missing"},
		"bad wan reference": {func(e *env) { e.r.WANInterface = map[string]string{benchRef: "Device.IP.Interface.1; x"} },
			speedEnvelope("speed_test_download", "core-sp-1", "10mb"), "wan_reference_missing"},
		"identity": {func(e *env) { e.acs.idErr = nbi.ErrBenchIdentity }, speedEnvelope("speed_test_download", "core-sp-1", "10mb"), "identity_not_confirmed"},
		"offline":  {func(e *env) { e.acs.idErr = nbi.ErrBenchOffline }, speedEnvelope("speed_test_download", "core-sp-1", "10mb"), "device_offline"},
		"pacing":   {func(e *env) { e.r.Guard = okGuard{err: nbi.ErrRefreshTooSoon} }, speedEnvelope("speed_test_download", "core-sp-1", "10mb"), "pacing"},
	}
	for name, c := range cases {
		e := speedSetup(t)
		c.mut(e)
		res := e.r.Run(context.Background(), c.env)
		if res.State != "failed" || res.Detail != c.detail || res.Data != nil {
			t.Errorf("%s: %+v (want detail %q)", name, res, c.detail)
		}
		if len(e.acs.speedCalls) != 0 {
			t.Errorf("%s: the ACS was asked to run a test", name)
		}
		if st := e.cl.State(authID); st != "" {
			t.Errorf("%s: the authorization was spent (%q)", name, st)
		}
	}
}

func TestSpeedOnADeviceOutsideTheBenchListIsRefused(t *testing.T) {
	e := speedSetup(t)
	e.lease(t, jobs.LeaseTarget{TargetRef: prodRef, OwnerEpoch: 2})
	en := speedEnvelope("speed_test_download", "core-sp-1", "10mb")
	en.TargetRef = prodRef
	res := e.r.Run(context.Background(), en)
	if res.State != "failed" || res.Detail != "not_bench_device" || len(e.acs.speedCalls) != 0 {
		t.Fatalf("%+v", res)
	}
}

func TestSpeedUncertainOutcomesAreFailedAndSpendTheAuthorizationAsUnknown(t *testing.T) {
	for name, c := range map[string]struct {
		out    nbi.SpeedOutcome
		err    error
		detail string
		claim  string
	}{
		"timeout":   {nbi.SpeedOutcome{Attempted: true}, nbi.ErrSpeedTimeout, "timeout", jobs.ClaimUnknown},
		"ambiguous": {nbi.SpeedOutcome{Attempted: true}, errors.New("ambiguous speed request"), "outcome_unknown", jobs.ClaimUnknown},
		"uncleaned": {nbi.SpeedOutcome{Attempted: true}, nbi.ErrBenchUncleaned, "outcome_unknown", jobs.ClaimUnknown},
	} {
		e := speedSetup(t)
		e.acs.speedOut, e.acs.speedErr = c.out, c.err
		res := e.r.Run(context.Background(), speedEnvelope("speed_test_download", "core-sp-1", "10mb"))
		if res.State != "failed" || res.Detail != c.detail || res.Data != nil || res.Postcheck {
			t.Errorf("%s: %+v", name, res)
		}
		if e.cl.State(authID) != c.claim {
			t.Errorf("%s: claim %q", name, e.cl.State(authID))
		}
		if len(e.acs.speedCalls) != 1 {
			t.Errorf("%s: the request must never be repeated", name)
		}
	}
	// refused before anything was sent: a clean failure, the authorization is marked failed (not unknown)
	e := speedSetup(t)
	e.acs.speedOut, e.acs.speedErr = nbi.SpeedOutcome{Attempted: true}, nbi.ErrSpeedUnsupported
	res := e.r.Run(context.Background(), speedEnvelope("speed_test_download", "core-sp-1", "10mb"))
	if res.State != "failed" || res.Detail != "outcome_unknown" {
		t.Fatalf("an Attempted outcome with an unclassified error stays unknown: %+v", res)
	}
	e = speedSetup(t)
	e.acs.speedOut, e.acs.speedErr = nbi.SpeedOutcome{}, nbi.ErrSpeedUnsupported
	res = e.r.Run(context.Background(), speedEnvelope("speed_test_download", "core-sp-1", "10mb"))
	if res.State != "failed" || res.Detail != "speed_not_started" || e.cl.State(authID) != jobs.ClaimFailed {
		t.Fatalf("%+v claim %q", res, e.cl.State(authID))
	}
}

func TestSpeedAnAuthorizationServesOneTestOnly(t *testing.T) {
	e := speedSetup(t)
	if res := e.r.Run(context.Background(), speedEnvelope("speed_test_download", "core-sp-1", "10mb")); res.State != "succeeded" {
		t.Fatalf("%+v", res)
	}
	res := e.r.Run(context.Background(), speedEnvelope("speed_test_download", "core-sp-1", "10mb"))
	if res.State != "failed" || res.Detail != "authorization_used" || len(e.acs.speedCalls) != 1 {
		t.Fatalf("second run must be refused: %+v calls=%d", res, len(e.acs.speedCalls))
	}
}

func TestEverySpeedDetailIsAShortCode(t *testing.T) {
	for _, d := range []string{"anything with spaces", "Upper", "10.1.2.3 failed", "", strings.Repeat("a", 41), "http://x"} {
		if got := speedDetail(d); got != "refused" {
			t.Errorf("%q -> %q", d, got)
		}
	}
	if speedDetail("timeout") != "timeout" || speedDetail("no valid Cloud lease for this target") != "no_lease" {
		t.Error("known details map to codes")
	}
}
