package jobs

import (
	"context"
	"crypto/ed25519"
	"crypto/rand"
	"errors"
	"strings"
	"testing"
	"time"
)

func benchBase() map[string]any {
	return map[string]any{
		"schema_version": "1.0", "job_id": "11111111-1111-4111-8111-111111111111", "tenant_id": "22222222-2222-4222-8222-222222222222",
		"edge_id": "33333333-3333-4333-8333-333333333333", "target_id": "44444444-4444-4444-8444-444444444444", "operation": "reboot_cpe",
		"target_ref": "00259E-EG8145V5-48575443E2247AA5", "idempotency_key": "bench-key-0001",
		"issued_at": "2026-10-28T10:04:00Z", "expires_at": "2026-10-28T10:06:00Z", "nonce": "abcdef0123456789abcdef0123456789",
		"intent_sha256": strings.Repeat("a", 64), "policy_version": "p", "approval_ids": []string{"x"},
		"authorization_id": "55555555-5555-4555-8555-555555555555", "authorization_ends_at": "2026-10-28T10:30:00Z", "owner_epoch": 2,
	}
}

func TestBenchEnvelopeRules(t *testing.T) {
	pub, priv, _ := ed25519.GenerateKey(rand.Reader)
	mk := func(enabled bool) *Verifier {
		v := verifier(pub, inWindow)
		v.Allowed["reboot_cpe"] = true
		v.BenchEnabled = enabled
		return v
	}
	ctx := context.Background()
	if _, err := mk(true).Verify(ctx, signedEnv(t, priv, benchBase(), func(map[string]any) {})); err != nil {
		t.Fatalf("a complete bench envelope must verify: %v", err)
	}
	if _, err := mk(false).Verify(ctx, signedEnv(t, priv, benchBase(), func(map[string]any) {})); !errors.Is(err, ErrOperation) {
		t.Fatalf("bench disabled locally must refuse whatever the Cloud signs: %v", err)
	}
	bad := map[string]func(map[string]any){
		"no target_ref":            func(m map[string]any) { delete(m, "target_ref") },
		"no authorization":         func(m map[string]any) { delete(m, "authorization_id") },
		"authorization not uuid":   func(m map[string]any) { m["authorization_id"] = "abc" },
		"no epoch":                 func(m map[string]any) { delete(m, "owner_epoch") },
		"epoch 0":                  func(m map[string]any) { m["owner_epoch"] = 0 },
		"no window":                func(m map[string]any) { delete(m, "authorization_ends_at") },
		"window closed":            func(m map[string]any) { m["authorization_ends_at"] = "2026-10-28T10:04:30Z" },
		"envelope outlives window": func(m map[string]any) { m["authorization_ends_at"] = "2026-10-28T10:05:30Z" },
		"envelope too long": func(m map[string]any) {
			m["issued_at"] = "2026-10-28T10:00:00Z"
			m["expires_at"] = "2026-10-28T10:10:00Z"
		},
	}
	for name, mut := range bad {
		if _, err := mk(true).Verify(ctx, signedEnv(t, priv, benchBase(), mut)); err == nil {
			t.Errorf("%s: must be refused", name)
		}
	}
	// the new fields never ride on other operations
	for _, op := range []string{"collect", "refresh"} {
		_, err := mk(true).Verify(ctx, signedEnv(t, priv, benchBase(), func(m map[string]any) { m["operation"] = op }))
		if !errors.Is(err, ErrFormat) {
			t.Errorf("%s with authorization fields: %v", op, err)
		}
	}
	// tampering with the epoch breaks the signature
	raw1 := signedEnv(t, priv, benchBase(), func(map[string]any) {})
	tampered := []byte(strings.Replace(string(raw1), `"owner_epoch":2`, `"owner_epoch":9`, 1))
	if _, err := mk(true).Verify(ctx, tampered); !errors.Is(err, ErrSignature) {
		t.Fatalf("tampered epoch: %v", err)
	}
	_ = time.Second
}

func TestBenchSetIsDisjointFromReadOnly(t *testing.T) {
	for op := range BenchWriteOps {
		if ReadOnlyOps[op] {
			t.Fatalf("%s in both sets", op)
		}
	}
	want := []string{"reboot_cpe", "set_wifi_ssid", "onu_reset", "onu_deactivate"}
	if len(BenchWriteOps) != len(want) {
		t.Fatalf("only the H2/H3/H4 operations are compiled in: %v", BenchWriteOps)
	}
	for _, op := range want {
		if !BenchWriteOps[op] {
			t.Fatalf("%s missing: %v", op, BenchWriteOps)
		}
	}
}

func TestBenchSSIDParamsAreSignedAndShaped(t *testing.T) {
	pub, priv, _ := ed25519.GenerateKey(rand.Reader)
	v := verifier(pub, inWindow)
	v.Allowed["set_wifi_ssid"], v.Allowed["reboot_cpe"], v.BenchEnabled = true, true, true
	ctx := context.Background()
	ok := func(m map[string]any) {
		m["operation"] = "set_wifi_ssid"
		m["params"] = map[string]any{"ssid": "BANCADA-H3"}
	}
	if _, err := v.Verify(ctx, signedEnv(t, priv, benchBase(), ok)); err != nil {
		t.Fatalf("a complete ssid envelope must verify: %v", err)
	}
	bad := map[string]func(map[string]any){
		"no params":    func(m map[string]any) { m["operation"] = "set_wifi_ssid" },
		"empty params": func(m map[string]any) { m["operation"] = "set_wifi_ssid"; m["params"] = map[string]any{} },
		"customer ssid": func(m map[string]any) {
			m["operation"] = "set_wifi_ssid"
			m["params"] = map[string]any{"ssid": "CLIENTE-1"}
		},
		"lower case": func(m map[string]any) {
			m["operation"] = "set_wifi_ssid"
			m["params"] = map[string]any{"ssid": "bancada-h3"}
		},
		"trailing nl": func(m map[string]any) {
			m["operation"] = "set_wifi_ssid"
			m["params"] = map[string]any{"ssid": "BANCADA-H3\n"}
		},
		"too long": func(m map[string]any) {
			m["operation"] = "set_wifi_ssid"
			m["params"] = map[string]any{"ssid": "BANCADA-" + strings.Repeat("A", 17)}
		},
		"extra param":    func(m map[string]any) { ok(m); m["params"] = map[string]any{"ssid": "BANCADA-H3", "psk": "x"} },
		"reboot w/ ssid": func(m map[string]any) { m["params"] = map[string]any{"ssid": "BANCADA-H3"} },
	}
	for name, mut := range bad {
		if _, err := v.Verify(ctx, signedEnv(t, priv, benchBase(), mut)); err == nil {
			t.Errorf("%s: must be refused", name)
		}
	}
	for _, op := range []string{"collect", "refresh"} {
		_, err := v.Verify(ctx, signedEnv(t, priv, benchBase(), func(m map[string]any) {
			delete(m, "authorization_id")
			delete(m, "authorization_ends_at")
			delete(m, "owner_epoch")
			m["operation"] = op
			m["params"] = map[string]any{"ssid": "BANCADA-H3"}
		}))
		if err == nil {
			t.Errorf("%s must not carry params", op)
		}
	}
	raw1 := signedEnv(t, priv, benchBase(), ok)
	if _, err := v.Verify(ctx, []byte(strings.Replace(string(raw1), "BANCADA-H3", "BANCADA-H4", 1))); !errors.Is(err, ErrSignature) {
		t.Fatalf("tampered ssid: %v", err)
	}
}
