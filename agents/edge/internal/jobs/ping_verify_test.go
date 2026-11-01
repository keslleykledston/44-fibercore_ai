package jobs

import (
	"context"
	"crypto/ed25519"
	"crypto/rand"
	"errors"
	"testing"
)

func TestPingEnvelopeRules(t *testing.T) {
	pub, priv, _ := ed25519.GenerateKey(rand.Reader)
	ctx := context.Background()
	good := map[string]any{"target": "core-lab"}
	mk := func(benchOn, pingOn bool, check func(target string) error) *Verifier {
		v := verifier(pub, inWindow)
		v.Allowed["ping_test"] = true
		v.BenchEnabled, v.PingEnabled, v.PingCheck = benchOn, pingOn, check
		return v
	}
	known := func(target string) error {
		if target != "core-lab" {
			return errors.New("unknown destination")
		}
		return nil
	}
	if _, err := mk(true, true, known).Verify(ctx, signedEnv(t, priv, benchBase(), speedEnv("ping_test", good))); err != nil {
		t.Fatalf("a complete ping envelope must verify: %v", err)
	}
	// each local switch is required, whatever the Cloud signs
	for name, v := range map[string]*Verifier{"bench off": mk(false, true, known), "ping off": mk(true, false, known), "no checker": mk(true, true, nil)} {
		if _, err := v.Verify(ctx, signedEnv(t, priv, benchBase(), speedEnv("ping_test", good))); !errors.Is(err, ErrOperation) {
			t.Errorf("%s: %v", name, err)
		}
	}
	v := mk(true, true, known)
	delete(v.Allowed, "ping_test")
	if _, err := v.Verify(ctx, signedEnv(t, priv, benchBase(), speedEnv("ping_test", good))); !errors.Is(err, ErrOperation) {
		t.Errorf("not in the allowlist: %v", err)
	}
	// the speed switches do not open a ping test, and the ping switches do not open a speed test
	only := verifier(pub, inWindow)
	only.Allowed["ping_test"], only.BenchEnabled, only.SpeedEnabled, only.SpeedCheck = true, true, true, func(string, string) error { return nil }
	if _, err := only.Verify(ctx, signedEnv(t, priv, benchBase(), speedEnv("ping_test", good))); !errors.Is(err, ErrOperation) {
		t.Errorf("speed switches must not open a ping test: %v", err)
	}
	bad := map[string]func(map[string]any){
		"unknown destination":  speedEnv("ping_test", map[string]any{"target": "other"}),
		"an address as target": speedEnv("ping_test", map[string]any{"target": "9.9.9.9"}),
		"extra parameter":      speedEnv("ping_test", map[string]any{"target": "core-lab", "count": 50}),
		"no parameters":        speedEnv("ping_test", map[string]any{}),
		"number not a name":    speedEnv("ping_test", map[string]any{"target": 3}),
		"no target_ref":        func(m map[string]any) { speedEnv("ping_test", good)(m); delete(m, "target_ref") },
		"no authorization":     func(m map[string]any) { speedEnv("ping_test", good)(m); delete(m, "authorization_id") },
		"hash of other params": func(m map[string]any) {
			speedEnv("ping_test", good)(m)
			m["params"] = map[string]any{"target": "other"}
		},
		"hash of another op": func(m map[string]any) { speedEnv("ping_test", good)(m); m["operation"] = "reboot_cpe" },
	}
	for name, mut := range bad {
		if _, err := mk(true, true, known).Verify(ctx, signedEnv(t, priv, benchBase(), mut)); err == nil {
			t.Errorf("%s: must be refused", name)
		}
	}
}
