package jobs

import (
	"context"
	"crypto/ed25519"
	"crypto/rand"
	"encoding/base64"
	"encoding/json"
	"errors"
	"testing"
	"time"
)

const (
	qOLT = "8f14e45f-ceea-467a-9a36-4a1b5c3d2e10"
	// computed by the Cloud (apps/api/app/api/jobs.py _intent_hash) for exactly the params below
	qHash = "e3ccc5caef226c81094daf5c66f85399c06ea2f241ca35c39c044549dbde8fe0"
	qCat  = "959fdad3e4dc820399aec98bc2a232e35a714136043353424c12a5f67c36e62c"
)

func queryBase() map[string]any {
	m := benchBase()
	for _, k := range []string{"target_ref", "authorization_id", "authorization_ends_at", "owner_epoch"} {
		delete(m, k)
	}
	m["operation"], m["target_id"], m["intent_sha256"] = "olt_query", qOLT, qHash
	m["issued_at"], m["expires_at"] = "2026-10-28T10:04:00Z", "2026-10-28T10:19:00Z"
	m["owner_epoch"] = 3
	m["params"] = map[string]any{"query_id": "pon.ont.info", "olt_ref": qOLT, "catalog_version": qCat, "slot": 1, "port": 0}
	return m
}

func TestIntentHashMatchesTheCloud(t *testing.T) {
	h, err := IntentHash("olt_query", "olt", qOLT, Params{"query_id": "pon.ont.info", "olt_ref": qOLT, "catalog_version": qCat, "slot": jsonNum("1"), "port": jsonNum("0")})
	if err != nil || h != qHash {
		t.Fatalf("hash %s (%v), the Cloud computes %s", h, err, qHash)
	}
}

func TestQueryEnvelopeRules(t *testing.T) {
	pub, priv, _ := ed25519.GenerateKey(rand.Reader)
	var seen map[string]any
	mk := func(enabled, wired bool) *Verifier {
		v := verifier(pub, inWindow)
		v.Allowed["olt_query"] = true
		v.QueryEnabled = enabled
		if wired {
			v.QueryCheck = func(p map[string]any, target string) error { seen = p; return nil }
		}
		return v
	}
	ctx := context.Background()
	env, err := mk(true, true).Verify(ctx, signedEnv(t, priv, queryBase(), func(map[string]any) {}))
	if err != nil {
		t.Fatalf("a complete query envelope must verify: %v", err)
	}
	if env.Params.String("query_id") != "pon.ont.info" || seen["slot"] == nil {
		t.Fatalf("the checker must see the signed params: %v", seen)
	}
	for name, v := range map[string]*Verifier{"switch off": mk(false, true), "no checker wired": mk(true, false)} {
		if _, err := v.Verify(ctx, signedEnv(t, priv, queryBase(), func(map[string]any) {})); !errors.Is(err, ErrOperation) {
			t.Errorf("%s must refuse whatever the Cloud signs: %v", name, err)
		}
	}
	notAllowed := mk(true, true)
	delete(notAllowed.Allowed, "olt_query")
	if _, err := notAllowed.Verify(ctx, signedEnv(t, priv, queryBase(), func(map[string]any) {})); !errors.Is(err, ErrOperation) {
		t.Errorf("not in allowed_operations: %v", err)
	}
	bad := map[string]func(map[string]any){
		"params swapped under the same hash": func(m map[string]any) { m["params"].(map[string]any)["slot"] = 2 },
		"query swapped":                      func(m map[string]any) { m["params"].(map[string]any)["query_id"] = "olt.board" },
		"extra param":                        func(m map[string]any) { m["params"].(map[string]any)["x"] = 1 },
		"no params":                          func(m map[string]any) { delete(m, "params") },
		"another target under the same hash": func(m map[string]any) { m["target_id"] = "44444444-4444-4444-8444-444444444444" },
		"target_ref":                         func(m map[string]any) { m["target_ref"] = "00259E-EG8145V5-48575443E2247AA5" },
		"authorization fields":               func(m map[string]any) { m["authorization_id"] = "55555555-5555-4555-8555-555555555555" },
		"no epoch":                           func(m map[string]any) { delete(m, "owner_epoch") },
		"epoch 0":                            func(m map[string]any) { m["owner_epoch"] = 0 },
		"envelope too long": func(m map[string]any) {
			m["issued_at"], m["expires_at"] = "2026-10-28T10:00:00Z", "2026-10-28T10:30:00Z"
		},
	}
	for name, mut := range bad {
		if _, err := mk(true, true).Verify(ctx, signedEnv(t, priv, queryBase(), mut)); err == nil {
			t.Errorf("%s: must be refused", name)
		}
	}
	rejecting := mk(true, true)
	rejecting.QueryCheck = func(map[string]any, string) error { return errors.New("not my OLT") }
	if _, err := rejecting.Verify(ctx, signedEnv(t, priv, queryBase(), func(map[string]any) {})); !errors.Is(err, ErrFormat) {
		t.Errorf("the checker's refusal must refuse the envelope: %v", err)
	}
}

func TestQuerySetIsDisjointFromTheOthers(t *testing.T) {
	for op := range QueryOps {
		if ReadOnlyOps[op] || BenchWriteOps[op] {
			t.Fatalf("%s in more than one compile-time set", op)
		}
	}
	if len(QueryOps) != 1 || !QueryOps["olt_query"] {
		t.Fatalf("only olt_query is compiled in: %v", QueryOps)
	}
}

func jsonNum(s string) json.Number { return json.Number(s) }

func TestTheTwoLeaseFamiliesNeverPassForEachOther(t *testing.T) {
	pub, priv, _ := ed25519.GenerateKey(rand.Reader)
	now := inWindow
	clk := func() time.Time { return inWindow }
	mk := func(schema string) string {
		return base64.StdEncoding.EncodeToString(signedEnv(t, priv, map[string]any{
			"schema": schema, "tenant_id": benchBase()["tenant_id"], "edge_id": benchBase()["edge_id"], "issued_at": now.Format(time.RFC3339),
			"expires_at": now.Add(LeaseTTL).Format(time.RFC3339), "targets": []any{map[string]any{"target_ref": qOLT, "owner_epoch": 3}},
		}, func(map[string]any) {}))
	}
	bench := &LeaseHolder{Pub: pub, EdgeID: benchBase()["edge_id"].(string), TenantID: benchBase()["tenant_id"].(string), Now: clk}
	oltH := &LeaseHolder{Schema: "olt-lease/1", Pub: pub, EdgeID: bench.EdgeID, TenantID: bench.TenantID, Now: clk}
	if err := oltH.Accept(mk("olt-lease/1")); err != nil {
		t.Fatalf("own family: %v", err)
	}
	if e, ok := oltH.Epoch(qOLT); !ok || e != 3 {
		t.Fatalf("epoch %d %v", e, ok)
	}
	if err := oltH.Check(qOLT, 3); err != nil {
		t.Fatal(err)
	}
	if err := oltH.Check(qOLT, 2); !errors.Is(err, ErrLeaseTarget) {
		t.Fatalf("another generation: %v", err)
	}
	if err := bench.Accept(mk("olt-lease/1")); err == nil {
		t.Fatal("an OLT lease must not pass for a bench lease")
	}
	if err := oltH.Accept(mk("bench-lease/1")); err == nil {
		t.Fatal("a bench lease must not pass for an OLT lease")
	}
	if _, ok := oltH.Epoch(qOLT); ok {
		t.Fatal("a rejected lease withdraws the one held")
	}
	if err := oltH.Accept(""); err != nil {
		t.Fatal(err)
	}
}

func TestAnOLTLeaseIsRefusedWhenTheClocksDisagreeBeyondTheSkew(t *testing.T) {
	pub, priv, _ := ed25519.GenerateKey(rand.Reader)
	for name, shift := range map[string]time.Duration{"edge clock behind": -50 * time.Second, "edge clock ahead": 50 * time.Second, "inside the skew": 30 * time.Second} {
		clk := func() time.Time { return inWindow.Add(shift) }
		h := &LeaseHolder{Schema: "olt-lease/1", MaxSkew: 45 * time.Second, Pub: pub, EdgeID: benchBase()["edge_id"].(string), TenantID: benchBase()["tenant_id"].(string), Now: clk}
		raw := base64.StdEncoding.EncodeToString(signedEnv(t, priv, map[string]any{
			"schema": "olt-lease/1", "tenant_id": h.TenantID, "edge_id": h.EdgeID, "issued_at": inWindow.Format(time.RFC3339),
			"expires_at": inWindow.Add(LeaseTTL).Format(time.RFC3339), "targets": []any{map[string]any{"target_ref": qOLT, "owner_epoch": 1}},
		}, func(map[string]any) {}))
		err := h.Accept(raw)
		if (name == "inside the skew") != (err == nil) {
			t.Errorf("%s: %v", name, err)
		}
	}
}

func TestGrantIsOneAtomicAnswerForEpochAndTime(t *testing.T) {
	pub, priv, _ := ed25519.GenerateKey(rand.Reader)
	clk := func() time.Time { return inWindow }
	h := &LeaseHolder{Schema: "olt-lease/1", Pub: pub, EdgeID: benchBase()["edge_id"].(string), TenantID: benchBase()["tenant_id"].(string), Now: clk}
	lease := func(epoch int) string {
		return base64.StdEncoding.EncodeToString(signedEnv(t, priv, map[string]any{
			"schema": "olt-lease/1", "tenant_id": h.TenantID, "edge_id": h.EdgeID, "issued_at": inWindow.Format(time.RFC3339),
			"expires_at": inWindow.Add(LeaseTTL).Format(time.RFC3339), "targets": []any{map[string]any{"target_ref": qOLT, "owner_epoch": epoch}},
		}, func(map[string]any) {}))
	}
	if _, err := h.Grant(qOLT, 1); !errors.Is(err, ErrNoLease) {
		t.Fatalf("no lease: %v", err)
	}
	if err := h.Accept(lease(1)); err != nil {
		t.Fatal(err)
	}
	left, err := h.Grant(qOLT, 1)
	if err != nil || left <= 0 || left > LeaseTTL {
		t.Fatalf("%v %v", left, err)
	}
	if _, err := h.Grant(qOLT, 2); !errors.Is(err, ErrLeaseTarget) {
		t.Fatalf("another generation: %v", err)
	}
	if err := h.Accept(lease(2)); err != nil { // the renewal changed the generation
		t.Fatal(err)
	}
	if _, err := h.Grant(qOLT, 1); !errors.Is(err, ErrLeaseTarget) {
		t.Fatalf("the old epoch no longer gets a deadline: %v", err)
	}
}
