package jobs

import (
	"context"
	"crypto/ed25519"
	"crypto/rand"
	"errors"
	"testing"
)

func speedEnv(op string, params map[string]any) func(map[string]any) {
	return func(m map[string]any) {
		m["operation"] = op
		m["params"] = params
		h, _ := IntentHash(op, "cpe", m["target_id"].(string), Params(params))
		m["intent_sha256"] = h
	}
}

func TestSpeedEnvelopeRules(t *testing.T) {
	pub, priv, _ := ed25519.GenerateKey(rand.Reader)
	ctx := context.Background()
	good := map[string]any{"target": "core-sp-1", "profile": "10mb"}
	mk := func(benchOn, speedOn bool, check func(target, profile string) error) *Verifier {
		v := verifier(pub, inWindow)
		v.Allowed["speed_test_download"], v.Allowed["speed_test_upload"] = true, true
		v.BenchEnabled, v.SpeedEnabled, v.SpeedCheck = benchOn, speedOn, check
		return v
	}
	known := func(target, profile string) error {
		if target != "core-sp-1" || (profile != "10mb" && profile != "50mb" && profile != "200mb") {
			return errors.New("unknown endpoint or profile")
		}
		return nil
	}
	for _, op := range []string{"speed_test_download", "speed_test_upload"} {
		if _, err := mk(true, true, known).Verify(ctx, signedEnv(t, priv, benchBase(), speedEnv(op, good))); err != nil {
			t.Fatalf("%s: a complete speed envelope must verify: %v", op, err)
		}
	}
	// each local switch is required, whatever the Cloud signs
	for name, v := range map[string]*Verifier{"bench off": mk(false, true, known), "speed off": mk(true, false, known), "no checker": mk(true, true, nil)} {
		if _, err := v.Verify(ctx, signedEnv(t, priv, benchBase(), speedEnv("speed_test_download", good))); !errors.Is(err, ErrOperation) {
			t.Errorf("%s: %v", name, err)
		}
	}
	// the operation is also gated by the local allowlist
	v := mk(true, true, known)
	delete(v.Allowed, "speed_test_download")
	if _, err := v.Verify(ctx, signedEnv(t, priv, benchBase(), speedEnv("speed_test_download", good))); !errors.Is(err, ErrOperation) {
		t.Errorf("not in the allowlist: %v", err)
	}
	bad := map[string]func(map[string]any){
		"unknown endpoint":    speedEnv("speed_test_download", map[string]any{"target": "other-node", "profile": "10mb"}),
		"unknown profile":     speedEnv("speed_test_download", map[string]any{"target": "core-sp-1", "profile": "1gb"}),
		"a url as the target": speedEnv("speed_test_download", map[string]any{"target": "http://10.0.0.1/f", "profile": "10mb"}),
		"missing profile":     speedEnv("speed_test_download", map[string]any{"target": "core-sp-1"}),
		"extra parameter":     speedEnv("speed_test_download", map[string]any{"target": "core-sp-1", "profile": "10mb", "url": "http://x"}),
		"no parameters":       speedEnv("speed_test_download", map[string]any{}),
		"numbers not names":   speedEnv("speed_test_download", map[string]any{"target": 3, "profile": 10}),
		"no target_ref":       func(m map[string]any) { speedEnv("speed_test_download", good)(m); delete(m, "target_ref") },
		"no authorization":    func(m map[string]any) { speedEnv("speed_test_download", good)(m); delete(m, "authorization_id") },
		"hash of other params": func(m map[string]any) {
			speedEnv("speed_test_download", good)(m)
			m["params"] = map[string]any{"target": "core-sp-1", "profile": "50mb"}
		},
		"hash of another op": func(m map[string]any) { speedEnv("speed_test_download", good)(m); m["operation"] = "speed_test_upload" },
	}
	for name, mut := range bad {
		if _, err := mk(true, true, known).Verify(ctx, signedEnv(t, priv, benchBase(), mut)); err == nil {
			t.Errorf("%s: must be refused", name)
		}
	}
	// other bench operations are unchanged: they still take no parameters and do not need the speed switches
	r := mk(true, false, nil)
	r.Allowed["reboot_cpe"] = true
	if _, err := r.Verify(ctx, signedEnv(t, priv, benchBase(), func(map[string]any) {})); err != nil {
		t.Errorf("reboot must not depend on the speed section: %v", err)
	}
}

func TestSpeedOperationsAreBenchWritesAndNeverReadOnly(t *testing.T) {
	for _, op := range []string{"speed_test_download", "speed_test_upload"} {
		if !BenchWriteOps[op] || !SpeedOps[op] || ReadOnlyOps[op] || QueryOps[op] {
			t.Errorf("%s must be a bench write only", op)
		}
	}
	if len(ReadOnlyOps) != 2 {
		t.Error("the read-only ceiling must not grow")
	}
}
