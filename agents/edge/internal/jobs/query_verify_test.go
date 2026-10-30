package jobs

import (
	"context"
	"crypto/ed25519"
	"crypto/rand"
	"encoding/json"
	"errors"
	"testing"
)

const (
	qOLT = "8f14e45f-ceea-467a-9a36-4a1b5c3d2e10"
	// computed by the Cloud (apps/api/app/api/jobs.py _intent_hash) for exactly the params below
	qHash = "775f8c74e86cbbd5112a6c798605ab0654c31a748b05fae20024e74e3393adde"
	qCat  = "1e1e5b3010c3788d6d86ae858c3d7bc976fc40a56916342d131b42acd5723b84"
)

func queryBase() map[string]any {
	m := benchBase()
	for _, k := range []string{"target_ref", "authorization_id", "authorization_ends_at", "owner_epoch"} {
		delete(m, k)
	}
	m["operation"], m["target_id"], m["intent_sha256"] = "olt_query", qOLT, qHash
	m["issued_at"], m["expires_at"] = "2026-10-28T10:04:00Z", "2026-10-28T10:19:00Z"
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
		"epoch":                              func(m map[string]any) { m["owner_epoch"] = 1 },
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
