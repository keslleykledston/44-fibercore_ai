package bench

import (
	"context"
	"crypto/ed25519"
	"crypto/rand"
	"encoding/base64"
	"encoding/json"
	"errors"
	"path/filepath"
	"testing"
	"time"

	"github.com/keslleykledston/44-fibercore_ai/agents/edge/internal/collector"
	"github.com/keslleykledston/44-fibercore_ai/agents/edge/internal/jobs"
	"github.com/keslleykledston/44-fibercore_ai/agents/edge/internal/nbi"
	"github.com/keslleykledston/44-fibercore_ai/agents/edge/internal/olt"
)

const (
	benchRef = "00259E-EG8145V5-48575443E2247AA5"
	prodRef  = "00259E-EG8145V5-48575443AAAAAAAA"
	authID   = "11111111-1111-4111-8111-111111111111"
)

type fakeACS struct {
	idErr, rebootErr error
	out              nbi.BenchOutcome
	identityCalls    int
	rebootCalls      []string
	ssidCalls        []string
	ssidOut          nbi.SSIDOutcome
	ssidErr          error
}

func (f *fakeACS) SetBenchSSID(_ context.Context, d nbi.BenchDevice, ssid string, _ func(string) bool, _ time.Time, _ string, _ func() time.Time) (nbi.SSIDOutcome, error) {
	f.ssidCalls = append(f.ssidCalls, d.DeviceID+"="+ssid)
	return f.ssidOut, f.ssidErr
}
func (f *fakeACS) BenchIdentity(_ context.Context, d nbi.BenchDevice, _ time.Time) error {
	f.identityCalls++
	return f.idErr
}
func (f *fakeACS) RebootBench(_ context.Context, d nbi.BenchDevice, _ time.Time, _, _ time.Duration, _ func() time.Time) (nbi.BenchOutcome, error) {
	f.rebootCalls = append(f.rebootCalls, d.DeviceID)
	return f.out, f.rebootErr
}

type okGuard struct{ err error }

func (g okGuard) Reserve(string) error { return g.err }

type env struct {
	r    *Runner
	acs  *fakeACS
	priv ed25519.PrivateKey
	now  time.Time
	cl   *jobs.Claims
}

func setup(t *testing.T) *env {
	pub, priv, _ := ed25519.GenerateKey(rand.Reader)
	e := &env{acs: &fakeACS{out: nbi.BenchOutcome{Attempted: true, Accepted: true, PostcheckOK: true}}, priv: priv,
		now: time.Date(2026, 10, 30, 12, 0, 0, 0, time.UTC)}
	cl, err := jobs.OpenClaims(filepath.Join(t.TempDir(), "claims.json"))
	if err != nil {
		t.Fatal(err)
	}
	e.cl = cl
	h := &jobs.LeaseHolder{Pub: pub, EdgeID: "edge-1", TenantID: "ten-1", Now: func() time.Time { return e.now }}
	e.r = &Runner{Devices: map[string]nbi.BenchDevice{benchRef: {DeviceID: benchRef, OUI: "00259E", ProductClass: "EG8145V5", Serial: "48575443E2247AA5"}},
		Lease: h, Claims: cl, Guard: okGuard{}, ACS: e.acs, Now: func() time.Time { return e.now }}
	return e
}

func (e *env) lease(t *testing.T, targets ...jobs.LeaseTarget) {
	m := map[string]any{"schema": "bench-lease/1", "tenant_id": "ten-1", "edge_id": "edge-1", "issued_at": e.now.Format(time.RFC3339),
		"expires_at": e.now.Add(jobs.LeaseTTL).Format(time.RFC3339), "targets": targets}
	raw, _ := json.Marshal(m)
	canon, _ := jobs.Canonical(raw)
	m["signature"] = base64.StdEncoding.EncodeToString(ed25519.Sign(e.priv, canon))
	out, _ := json.Marshal(m)
	if err := e.r.Lease.Accept(base64.StdEncoding.EncodeToString(out)); err != nil {
		t.Fatal(err)
	}
}

func envelope(ref string) *jobs.Envelope {
	return &jobs.Envelope{JobID: "job-1", Operation: "reboot_cpe", TargetRef: ref, AuthorizationID: authID, OwnerEpoch: 2,
		ExpiresAt: "2026-10-30T12:02:00Z", AuthorizationEndsAt: "2026-10-30T12:10:00Z"}
}

func TestRunHappy(t *testing.T) {
	e := setup(t)
	e.lease(t, jobs.LeaseTarget{TargetRef: benchRef, OwnerEpoch: 2})
	res := e.r.Run(context.Background(), envelope(benchRef))
	if res.State != "succeeded" || !res.Postcheck {
		t.Fatalf("%+v", res)
	}
	if len(e.acs.rebootCalls) != 1 || e.acs.rebootCalls[0] != benchRef {
		t.Fatalf("calls %v", e.acs.rebootCalls)
	}
	if e.cl.State(authID) != jobs.ClaimDone {
		t.Fatalf("claim %q", e.cl.State(authID))
	}
	// the same authorization can never run twice
	e.r.Guard = okGuard{}
	if res := e.r.Run(context.Background(), envelope(benchRef)); res.State != "failed" || len(e.acs.rebootCalls) != 1 {
		t.Fatalf("second run must be refused: %+v calls=%v", res, e.acs.rebootCalls)
	}
}

func TestRunRefusesAndSendsNothing(t *testing.T) {
	cases := map[string]func(*env) *jobs.Envelope{
		"production device not on the list": func(e *env) *jobs.Envelope {
			e.lease(t, jobs.LeaseTarget{TargetRef: prodRef, OwnerEpoch: 2})
			return envelope(prodRef)
		},
		"no lease": func(e *env) *jobs.Envelope { return envelope(benchRef) },
		"wrong epoch": func(e *env) *jobs.Envelope {
			e.lease(t, jobs.LeaseTarget{TargetRef: benchRef, OwnerEpoch: 3})
			return envelope(benchRef)
		},
		"lease for another target": func(e *env) *jobs.Envelope {
			e.lease(t, jobs.LeaseTarget{TargetRef: prodRef, OwnerEpoch: 2})
			return envelope(benchRef)
		},
		"identity mismatch": func(e *env) *jobs.Envelope {
			e.lease(t, jobs.LeaseTarget{TargetRef: benchRef, OwnerEpoch: 2})
			e.acs.idErr = nbi.ErrBenchIdentity
			return envelope(benchRef)
		},
		"offline": func(e *env) *jobs.Envelope {
			e.lease(t, jobs.LeaseTarget{TargetRef: benchRef, OwnerEpoch: 2})
			e.acs.idErr = nbi.ErrBenchOffline
			return envelope(benchRef)
		},
		"pacing": func(e *env) *jobs.Envelope {
			e.lease(t, jobs.LeaseTarget{TargetRef: benchRef, OwnerEpoch: 2})
			e.r.Guard = okGuard{err: nbi.ErrRefreshTooSoon}
			return envelope(benchRef)
		},
		"other operation": func(e *env) *jobs.Envelope {
			e.lease(t, jobs.LeaseTarget{TargetRef: benchRef, OwnerEpoch: 2})
			x := envelope(benchRef)
			x.Operation = "factory_reset"
			return x
		},
	}
	for name, mk := range cases {
		e := setup(t)
		env := mk(e)
		res := e.r.Run(context.Background(), env)
		if res.State != "failed" {
			t.Errorf("%s: %+v", name, res)
		}
		if len(e.acs.rebootCalls) != 0 {
			t.Errorf("%s: a command was sent: %v", name, e.acs.rebootCalls)
		}
	}
}

func TestRunLeaseLapsesDuringIdentityRead(t *testing.T) {
	e := setup(t)
	e.lease(t, jobs.LeaseTarget{TargetRef: benchRef, OwnerEpoch: 2})
	e.r.ACS = &laps{fakeACS: e.acs, advance: func() { e.now = e.now.Add(jobs.LeaseTTL) }}
	if res := e.r.Run(context.Background(), envelope(benchRef)); res.State != "failed" || len(e.acs.rebootCalls) != 0 {
		t.Fatalf("%+v %v", res, e.acs.rebootCalls)
	}
	if e.cl.State(authID) != "" {
		t.Fatal("authorization must not be spent when the gate refused")
	}
}

type laps struct {
	*fakeACS
	advance func()
}

func (l *laps) BenchIdentity(ctx context.Context, d nbi.BenchDevice, n time.Time) error {
	l.advance()
	return l.fakeACS.BenchIdentity(ctx, d, n)
}

func TestRunRefusesAnExpiredEnvelopeOrWindowAndSpendsNothing(t *testing.T) {
	for name, mut := range map[string]func(*jobs.Envelope){
		"envelope expired":  func(x *jobs.Envelope) { x.ExpiresAt = "2026-10-30T11:59:59Z" },
		"window ended":      func(x *jobs.Envelope) { x.AuthorizationEndsAt = "2026-10-30T12:00:00Z" },
		"unreadable expiry": func(x *jobs.Envelope) { x.ExpiresAt = "soon" },
	} {
		e := setup(t)
		e.lease(t, jobs.LeaseTarget{TargetRef: benchRef, OwnerEpoch: 2})
		x := envelope(benchRef)
		mut(x)
		if res := e.r.Run(context.Background(), x); res.State != "failed" || len(e.acs.rebootCalls) != 0 || e.cl.State(authID) != "" {
			t.Errorf("%s: %+v calls=%v claim=%q", name, res, e.acs.rebootCalls, e.cl.State(authID))
		}
	}
	// the envelope runs out WHILE the identity is being read: neither the pacing slot nor the authorization is spent
	e := setup(t)
	e.lease(t, jobs.LeaseTarget{TargetRef: benchRef, OwnerEpoch: 2})
	e.r.ACS = &laps{fakeACS: e.acs, advance: func() { e.now = e.now.Add(3 * time.Minute) }}
	e.r.Lease.Now = func() time.Time { return e.now.Add(-3 * time.Minute) } // keep the lease alive: only the envelope is expired
	if res := e.r.Run(context.Background(), envelope(benchRef)); res.State != "failed" || len(e.acs.rebootCalls) != 0 || e.cl.State(authID) != "" {
		t.Fatalf("%+v calls=%v claim=%q", res, e.acs.rebootCalls, e.cl.State(authID))
	}
}

func TestRunOutcomes(t *testing.T) {
	cases := []struct {
		name  string
		out   nbi.BenchOutcome
		err   error
		state string
		post  bool
		claim string
	}{
		{"delivered, did not come back", nbi.BenchOutcome{Attempted: true, Accepted: true}, nil, "succeeded", false, jobs.ClaimUnknown},
		{"ambiguous", nbi.BenchOutcome{Attempted: true}, errors.New("ambiguous"), "failed", false, jobs.ClaimUnknown},
		{"before send", nbi.BenchOutcome{}, nbi.ErrBenchPending, "failed", false, jobs.ClaimFailed},
		{"queued and removed", nbi.BenchOutcome{Attempted: true}, nbi.ErrBenchIdentity, "failed", false, jobs.ClaimUnknown},
	}
	for _, c := range cases {
		e := setup(t)
		e.lease(t, jobs.LeaseTarget{TargetRef: benchRef, OwnerEpoch: 2})
		e.acs.out, e.acs.rebootErr = c.out, c.err
		res := e.r.Run(context.Background(), envelope(benchRef))
		if res.State != c.state || res.Postcheck != c.post || e.cl.State(authID) != c.claim {
			t.Errorf("%s: %+v claim=%q", c.name, res, e.cl.State(authID))
		}
		if len(e.acs.rebootCalls) != 1 {
			t.Errorf("%s: calls=%v", c.name, e.acs.rebootCalls)
		}
	}
}

func ssidEnvelope(ref string) *jobs.Envelope {
	x := envelope(ref)
	x.Operation, x.Params = "set_wifi_ssid", jobs.Params{"ssid": "BANCADA-H3"}
	return x
}

func TestRunSSIDOutcomesAndGates(t *testing.T) {
	good := nbi.SSIDOutcome{Attempted: true, Applied: true, Verified: true, Restored: true, Detail: "ok"}
	cases := []struct {
		name  string
		out   nbi.SSIDOutcome
		err   error
		state string
		post  bool
		claim string
	}{
		{"changed, read back, restored", good, nil, "succeeded", true, jobs.ClaimDone},
		{"restored but change unproven", nbi.SSIDOutcome{Attempted: true, Applied: true, Restored: true}, nil, "failed", false, jobs.ClaimUnknown},
		{"restore not confirmed", nbi.SSIDOutcome{Attempted: true, Applied: true, Verified: true}, nbi.ErrBenchRestore, "failed", false, jobs.ClaimUnknown},
		{"not delivered", nbi.SSIDOutcome{Attempted: true}, nbi.ErrBenchIdentity, "failed", false, jobs.ClaimUnknown},
		{"before any send", nbi.SSIDOutcome{}, nbi.ErrBenchPending, "failed", false, jobs.ClaimFailed},
	}
	for _, c := range cases {
		e := setup(t)
		e.lease(t, jobs.LeaseTarget{TargetRef: benchRef, OwnerEpoch: 2})
		e.acs.ssidOut, e.acs.ssidErr = c.out, c.err
		res := e.r.Run(context.Background(), ssidEnvelope(benchRef))
		if res.State != c.state || res.Postcheck != c.post || e.cl.State(authID) != c.claim {
			t.Errorf("%s: %+v claim=%q", c.name, res, e.cl.State(authID))
		}
		if len(e.acs.ssidCalls) != 1 || e.acs.ssidCalls[0] != benchRef+"=BANCADA-H3" || len(e.acs.rebootCalls) != 0 {
			t.Errorf("%s: calls %v %v", c.name, e.acs.ssidCalls, e.acs.rebootCalls)
		}
	}
}

func TestSSIDGatesAreTheSameAsTheRebootOnes(t *testing.T) {
	e := setup(t)
	if res := e.r.Run(context.Background(), ssidEnvelope(benchRef)); res.State != "failed" || len(e.acs.ssidCalls) != 0 {
		t.Fatalf("no lease: %+v", res)
	}
	e.lease(t, jobs.LeaseTarget{TargetRef: prodRef, OwnerEpoch: 2})
	if res := e.r.Run(context.Background(), ssidEnvelope(prodRef)); res.State != "failed" || len(e.acs.ssidCalls) != 0 {
		t.Fatalf("production device: %+v", res)
	}
	e = setup(t)
	e.lease(t, jobs.LeaseTarget{TargetRef: benchRef, OwnerEpoch: 2})
	e.acs.idErr = nbi.ErrBenchIdentity
	if res := e.r.Run(context.Background(), ssidEnvelope(benchRef)); res.State != "failed" || len(e.acs.ssidCalls) != 0 || e.cl.State(authID) != "" {
		t.Fatalf("identity: %+v", res)
	}
}

// ---- H4: OLT maneuvers ----

func oltEnv(op string) *jobs.Envelope {
	x := envelope(benchRef)
	x.Operation = op
	return x
}

func TestRunOLTOutcomesAndTheOrderOfTheGates(t *testing.T) {
	cases := []struct {
		name    string
		out     olt.ManeuverOutcome
		err     error
		claim   bool // does the fake driver call beforeSend (i.e. the identity passed)?
		state   string
		post    bool
		claimSt string
	}{
		{"done", olt.ManeuverOutcome{Sent: true, Done: true, Detail: "ok"}, nil, true, "succeeded", true, jobs.ClaimDone},
		{"no return", olt.ManeuverOutcome{Sent: true}, olt.ErrBenchOLTNoReturn, true, "failed", false, jobs.ClaimUnknown},
		{"stuck", olt.ManeuverOutcome{Sent: true}, olt.ErrBenchOLTStuck, true, "failed", false, jobs.ClaimUnknown},
		{"refused", olt.ManeuverOutcome{}, olt.ErrBenchOLTRefused, true, "failed", false, jobs.ClaimFailed},
		{"identity", olt.ManeuverOutcome{}, olt.ErrBenchOLTIdentity, false, "failed", false, ""},
		{"guard", olt.ManeuverOutcome{}, collector.ErrOLTNotDue, false, "failed", false, ""},
	}
	for _, op := range []string{"onu_reset", "onu_deactivate"} {
		for _, c := range cases {
			e := setup(t)
			e.lease(t, jobs.LeaseTarget{TargetRef: benchRef, OwnerEpoch: 2})
			var gotOp string
			e.r.OLT = func(_ context.Context, o string, _ time.Time, before func() error) (olt.ManeuverOutcome, error) {
				gotOp = o
				if c.claim {
					if err := before(); err != nil {
						return olt.ManeuverOutcome{}, err
					}
				}
				return c.out, c.err
			}
			res := e.r.Run(context.Background(), oltEnv(op))
			if res.State != c.state || res.Postcheck != c.post || e.cl.State(authID) != c.claimSt || gotOp != op {
				t.Errorf("%s/%s: %+v claim=%q op=%q", op, c.name, res, e.cl.State(authID), gotOp)
			}
			if len(e.acs.rebootCalls)+len(e.acs.ssidCalls) != 0 || e.acs.identityCalls != 0 {
				t.Errorf("%s/%s: the TR-069 side must not be touched", op, c.name)
			}
		}
	}
}

func TestRunOLTNeedsLeaseAndExecutorAndSpendsNothingWithoutThem(t *testing.T) {
	e := setup(t)
	called := false
	e.r.OLT = func(context.Context, string, time.Time, func() error) (olt.ManeuverOutcome, error) {
		called = true
		return olt.ManeuverOutcome{}, nil
	}
	if res := e.r.Run(context.Background(), oltEnv("onu_reset")); res.State != "failed" || called {
		t.Fatalf("no lease: %+v", res)
	}
	e.lease(t, jobs.LeaseTarget{TargetRef: prodRef, OwnerEpoch: 2})
	if res := e.r.Run(context.Background(), oltEnv("onu_reset")); res.State != "failed" || called {
		t.Fatalf("lease for another device: %+v", res)
	}
	e = setup(t)
	e.lease(t, jobs.LeaseTarget{TargetRef: benchRef, OwnerEpoch: 2})
	if res := e.r.Run(context.Background(), oltEnv("onu_reset")); res.State != "failed" || e.cl.State(authID) != "" {
		t.Fatalf("no executor configured: %+v", res)
	}
}

func TestRunOLTPacingAndClaimAreSpentOnlyAfterTheIdentity(t *testing.T) {
	e := setup(t)
	e.lease(t, jobs.LeaseTarget{TargetRef: benchRef, OwnerEpoch: 2})
	e.r.Guard = okGuard{err: nbi.ErrRefreshTooSoon}
	sent := false
	e.r.OLT = func(_ context.Context, _ string, _ time.Time, before func() error) (olt.ManeuverOutcome, error) {
		if err := before(); err != nil {
			return olt.ManeuverOutcome{}, err
		}
		sent = true
		return olt.ManeuverOutcome{Sent: true, Done: true}, nil
	}
	if res := e.r.Run(context.Background(), oltEnv("onu_reset")); res.State != "failed" || sent || e.cl.State(authID) != "" {
		t.Fatalf("pacing: %+v sent=%v", res, sent)
	}
}
