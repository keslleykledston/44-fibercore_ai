package jobs

import (
	"context"
	"crypto/ed25519"
	"encoding/base64"
	"encoding/json"
	"os"
	"path/filepath"
	"sync"
	"testing"
	"time"
)

type memNonces struct {
	mu sync.Mutex
	m  map[string]bool
}

func (n *memNonces) Remember(_ context.Context, nonce string, _ time.Time) (bool, error) {
	n.mu.Lock()
	defer n.mu.Unlock()
	if n.m == nil {
		n.m = map[string]bool{}
	}
	if n.m[nonce] {
		return false, nil
	}
	n.m[nonce] = true
	return true, nil
}

type golden struct {
	PublicKey string         `json:"public_key_b64"`
	Envelope  map[string]any `json:"envelope"`
}

func loadGolden(t *testing.T) (golden, ed25519.PublicKey) {
	b, err := os.ReadFile(filepath.Join("..", "..", "..", "..", "tests", "fixtures", "edge", "job_envelope_signed.golden.json"))
	if err != nil {
		t.Fatal(err)
	}
	var g golden
	if err := json.Unmarshal(b, &g); err != nil {
		t.Fatal(err)
	}
	pub, err := ParsePublicKey(g.PublicKey)
	if err != nil {
		t.Fatal(err)
	}
	return g, pub
}

func verifier(pub ed25519.PublicKey, now time.Time) *Verifier {
	return &Verifier{Pub: pub, EdgeID: "33333333-3333-4333-8333-333333333333", TenantID: "22222222-2222-4222-8222-222222222222",
		Allowed: map[string]bool{"collect": true, "refresh": true}, Nonces: &memNonces{}, Now: func() time.Time { return now }}
}

var inWindow = time.Date(2026, 10, 28, 10, 5, 0, 0, time.UTC)

func raw(m map[string]any) []byte { b, _ := json.Marshal(m); return b }

func clone(m map[string]any) map[string]any {
	out := map[string]any{}
	for k, v := range m {
		out[k] = v
	}
	return out
}

// The Python Cloud signs; the Go Edge must accept exactly those bytes (cross-language canonicalisation contract).
func TestPythonSignedEnvelopeVerifies(t *testing.T) {
	g, pub := loadGolden(t)
	env, err := verifier(pub, inWindow).Verify(context.Background(), raw(g.Envelope))
	if err != nil || env.Operation != "collect" {
		t.Fatalf("env=%v err=%v", env, err)
	}
}

func TestTamperingBindingExpiryAndReplayAreRejected(t *testing.T) {
	g, pub := loadGolden(t)
	ctx := context.Background()
	for name, tc := range map[string]struct {
		mutate func(map[string]any)
		now    time.Time
		want   error
	}{
		"operation":   {func(m map[string]any) { m["operation"] = "reboot_cpe" }, inWindow, ErrSignature},
		"target":      {func(m map[string]any) { m["target_id"] = "99999999-9999-4999-8999-999999999999" }, inWindow, ErrSignature},
		"signature":   {func(m map[string]any) { m["signature"] = base64.StdEncoding.EncodeToString(make([]byte, 64)) }, inWindow, ErrSignature},
		"no-sig":      {func(m map[string]any) { delete(m, "signature") }, inWindow, ErrSignature},
		"expired":     {func(m map[string]any) {}, inWindow.Add(time.Hour), ErrExpired},
		"not-yet":     {func(m map[string]any) {}, inWindow.Add(-time.Hour), ErrExpired},
		"extra-field": {func(m map[string]any) { m["shell"] = "id" }, inWindow, ErrFormat},
	} {
		m := clone(g.Envelope)
		tc.mutate(m)
		if _, err := verifier(pub, tc.now).Verify(ctx, raw(m)); err == nil || !errorsIs(err, tc.want) {
			t.Errorf("%s: want %v got %v", name, tc.want, err)
		}
	}
	// replay
	v := verifier(pub, inWindow)
	if _, err := v.Verify(ctx, raw(g.Envelope)); err != nil {
		t.Fatal(err)
	}
	if _, err := v.Verify(ctx, raw(g.Envelope)); !errorsIs(err, ErrReplay) {
		t.Fatalf("replay not rejected: %v", err)
	}
	// wrong edge / tenant binding
	other := verifier(pub, inWindow)
	other.EdgeID = "00000000-0000-4000-8000-000000000000"
	if _, err := other.Verify(ctx, raw(g.Envelope)); !errorsIs(err, ErrBinding) {
		t.Fatalf("binding: %v", err)
	}
	// wrong key
	wrongPub, _, _ := ed25519.GenerateKey(nil)
	if _, err := verifier(wrongPub, inWindow).Verify(ctx, raw(g.Envelope)); !errorsIs(err, ErrSignature) {
		t.Fatalf("wrong key: %v", err)
	}
}

func TestWriteOperationsCannotBeEnabledByConfig(t *testing.T) {
	g, pub := loadGolden(t)
	v := verifier(pub, inWindow)
	v.Allowed["collect"] = false // narrowing works
	if _, err := v.Verify(context.Background(), raw(g.Envelope)); !errorsIs(err, ErrOperation) {
		t.Fatalf("narrowed config must refuse: %v", err)
	}
	for _, op := range []string{"reboot_cpe", "set_wifi_ssid", "provision_onu", "firmware_upgrade"} {
		if ReadOnlyOps[op] {
			t.Fatalf("%s must never be in the compile-time read-only set", op)
		}
	}
}

func errorsIs(err, target error) bool {
	for e := err; e != nil; {
		if e == target {
			return true
		}
		u, ok := e.(interface{ Unwrap() error })
		if !ok {
			return false
		}
		e = u.Unwrap()
	}
	return false
}
