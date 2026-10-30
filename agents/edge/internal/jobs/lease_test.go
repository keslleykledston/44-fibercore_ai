package jobs

import (
	"crypto/ed25519"
	"crypto/rand"
	"encoding/base64"
	"encoding/json"
	"errors"
	"os"
	"path/filepath"
	"testing"
	"time"
)

type leaseEnv struct {
	pub  ed25519.PublicKey
	priv ed25519.PrivateKey
	now  time.Time
	h    *LeaseHolder
}

func newLeaseEnv(t *testing.T) *leaseEnv {
	pub, priv, _ := ed25519.GenerateKey(rand.Reader)
	e := &leaseEnv{pub: pub, priv: priv, now: time.Date(2026, 10, 30, 12, 0, 0, 0, time.UTC)}
	e.h = &LeaseHolder{Pub: pub, EdgeID: "edge-1", TenantID: "ten-1", Now: func() time.Time { return e.now }}
	return e
}

func (e *leaseEnv) header(mut func(map[string]any)) string {
	m := map[string]any{"schema": "bench-lease/1", "tenant_id": "ten-1", "edge_id": "edge-1",
		"issued_at": e.now.Format(time.RFC3339), "expires_at": e.now.Add(LeaseTTL).Format(time.RFC3339),
		"targets": []any{map[string]any{"target_ref": "00259E-EG8145V5-AAAA", "owner_epoch": 3}}}
	if mut != nil {
		mut(m)
	}
	raw, _ := json.Marshal(m)
	canon, _ := Canonical(raw)
	m["signature"] = base64.StdEncoding.EncodeToString(ed25519.Sign(e.priv, canon))
	out, _ := json.Marshal(m)
	return base64.StdEncoding.EncodeToString(out)
}

func TestLeaseHappyAndExpiry(t *testing.T) {
	e := newLeaseEnv(t)
	if err := e.h.Check("00259E-EG8145V5-AAAA", 3); !errors.Is(err, ErrNoLease) {
		t.Fatalf("no lease yet: %v", err)
	}
	if err := e.h.Accept(e.header(nil)); err != nil {
		t.Fatal(err)
	}
	if err := e.h.Check("00259E-EG8145V5-AAAA", 3); err != nil {
		t.Fatal(err)
	}
	if err := e.h.Check("00259E-EG8145V5-AAAA", 2); !errors.Is(err, ErrLeaseTarget) {
		t.Fatalf("other epoch: %v", err)
	}
	if err := e.h.Check("00259E-EG8145V5-BBBB", 3); !errors.Is(err, ErrLeaseTarget) {
		t.Fatalf("other target: %v", err)
	}
	e.now = e.now.Add(LeaseTTL)
	if err := e.h.Check("00259E-EG8145V5-AAAA", 3); !errors.Is(err, ErrNoLease) {
		t.Fatalf("expired lease must not be honoured: %v", err)
	}
}

func TestLeaseWithdrawnAndRejected(t *testing.T) {
	cases := map[string]func(map[string]any){
		"tenant":  func(m map[string]any) { m["tenant_id"] = "other" },
		"edge":    func(m map[string]any) { m["edge_id"] = "other" },
		"expired": func(m map[string]any) { m["expires_at"] = "2026-10-30T11:59:00Z" },
		"toolong": func(m map[string]any) { m["expires_at"] = "2026-10-30T13:00:00Z" },
		"schema":  func(m map[string]any) { m["schema"] = "x" },
		"epoch0": func(m map[string]any) {
			m["targets"] = []any{map[string]any{"target_ref": "00259E-EG8145V5-AAAA", "owner_epoch": 0}}
		},
		"extra": func(m map[string]any) { m["more"] = 1 },
	}
	for name, mut := range cases {
		e := newLeaseEnv(t)
		_ = e.h.Accept(e.header(nil))
		if err := e.h.Accept(e.header(mut)); err == nil {
			t.Errorf("%s: must be rejected", name)
		}
		if err := e.h.Check("00259E-EG8145V5-AAAA", 3); err == nil {
			t.Errorf("%s: a rejected lease must also withdraw the previous one", name)
		}
	}
	e := newLeaseEnv(t)
	_ = e.h.Accept(e.header(nil))
	if err := e.h.Accept(""); err != nil {
		t.Fatal(err)
	}
	if err := e.h.Check("00259E-EG8145V5-AAAA", 3); err == nil {
		t.Fatal("empty header must withdraw the lease")
	}
	// tampered after signing
	h := e.header(nil)
	raw, _ := base64.StdEncoding.DecodeString(h)
	var m map[string]any
	_ = json.Unmarshal(raw, &m)
	m["targets"] = []any{map[string]any{"target_ref": "PROD-DEVICE-0001", "owner_epoch": 3}}
	raw, _ = json.Marshal(m)
	if err := e.h.Accept(base64.StdEncoding.EncodeToString(raw)); err == nil {
		t.Fatal("tampered lease must be rejected")
	}
	// wrong key
	e2 := newLeaseEnv(t)
	if err := e.h.Accept(e2.header(nil)); err == nil {
		t.Fatal("lease signed by another key must be rejected")
	}
}

func TestLeaseOlderIssueIgnored(t *testing.T) {
	e := newLeaseEnv(t)
	_ = e.h.Accept(e.header(nil))
	old := e.header(func(m map[string]any) {
		m["issued_at"] = e.now.Add(-time.Minute).Format(time.RFC3339)
		m["expires_at"] = e.now.Add(LeaseTTL - time.Minute).Format(time.RFC3339)
		m["targets"] = []any{}
	})
	if err := e.h.Accept(old); err != nil {
		t.Fatal(err)
	}
	if err := e.h.Check("00259E-EG8145V5-AAAA", 3); err != nil {
		t.Fatalf("an older lease must not override the newer one: %v", err)
	}
}

func TestPythonSignedLeaseVerifies(t *testing.T) {
	b, err := os.ReadFile(filepath.Join("..", "..", "..", "..", "tests", "fixtures", "edge", "bench_lease_signed.golden.json"))
	if err != nil {
		t.Fatal(err)
	}
	var g struct {
		PublicKey string `json:"public_key_b64"`
		Header    string `json:"header"`
	}
	if err := json.Unmarshal(b, &g); err != nil {
		t.Fatal(err)
	}
	pub, err := ParsePublicKey(g.PublicKey)
	if err != nil {
		t.Fatal(err)
	}
	now := time.Date(2026, 10, 30, 12, 0, 30, 0, time.UTC)
	h := &LeaseHolder{Pub: pub, EdgeID: "33333333-3333-4333-8333-333333333333", TenantID: "22222222-2222-4222-8222-222222222222", Now: func() time.Time { return now }}
	if err := h.Accept(g.Header); err != nil {
		t.Fatalf("the Cloud's signature must verify on the Edge: %v", err)
	}
	if err := h.Check("00259E-EG8145V5-48575443E2247AA5", 2); err != nil {
		t.Fatal(err)
	}
}
