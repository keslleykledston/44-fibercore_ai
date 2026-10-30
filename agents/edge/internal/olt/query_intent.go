package olt

import (
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"errors"
	"fmt"
	"regexp"
	"strconv"
	"strings"
)

// The intent of an `olt_query` job (ADR-0029 item 2): what the Cloud signs and the Edge executes. It is CLOSED per query: exactly the integer
// fields of the query's scope, plus the OLT identity and the catalog version. A field too many or too few is refused, never ignored.

var (
	ErrIntentFields  = errors.New("olt query intent: fields do not match the query's scope")
	ErrIntentCatalog = errors.New("olt query intent: made against another catalog version")
	ErrIntentOLT     = errors.New("olt query intent: olt_ref is not a valid OLT identity")
)

func (s Scope) name() string {
	switch s {
	case ScopeSlot:
		return "slot"
	case ScopePON:
		return "pon"
	case ScopeONU:
		return "onu"
	}
	return "global"
}

// CatalogVersion is the hash both sides must hold (the Cloud computes the same string from its own copy of the catalog; a test pins the two together).
func CatalogVersion() string {
	lines := make([]string, 0, len(queryCatalog))
	for _, q := range queryCatalog {
		v := 0
		if q.Validated {
			v = 1
		}
		lines = append(lines, fmt.Sprintf("%s|%s|%d", q.ID, q.Scope.name(), v))
	}
	sum := sha256.Sum256([]byte(strings.Join(lines, "\n")))
	return hex.EncodeToString(sum[:])
}

var uuidRe = regexp.MustCompile(`^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$`)

// Intent is a validated `olt_query` intent.
type Intent struct {
	Query  Query
	Params Params
	OLTRef string
}

// ParseIntent validates the signed params object of an `olt_query` envelope. Numbers must be decimal integers (json.Number): "1.0", "1e2", strings and
// booleans are refused.
func ParseIntent(raw map[string]any) (Intent, error) {
	id, ok := raw["query_id"].(string)
	if !ok {
		return Intent{}, ErrUnknownQuery
	}
	q, ok := QueryByID(id)
	if !ok {
		return Intent{}, ErrUnknownQuery
	}
	ref, ok := raw["olt_ref"].(string)
	if !ok || !uuidRe.MatchString(ref) {
		return Intent{}, ErrIntentOLT
	}
	if v, ok := raw["catalog_version"].(string); !ok || v != CatalogVersion() {
		return Intent{}, ErrIntentCatalog
	}
	want := map[string]bool{"query_id": true, "olt_ref": true, "catalog_version": true}
	switch q.Scope {
	case ScopeSlot:
		want["slot"] = true
	case ScopePON:
		want["slot"], want["port"] = true, true
	case ScopeONU:
		want["slot"], want["port"], want["ont"] = true, true, true
	}
	if len(raw) != len(want) {
		return Intent{}, ErrIntentFields
	}
	for k := range raw {
		if !want[k] {
			return Intent{}, ErrIntentFields
		}
	}
	var p Params
	for field, dst := range map[string]*int{"slot": &p.Slot, "port": &p.Port, "ont": &p.ONT} {
		if !want[field] {
			continue
		}
		n, ok := raw[field].(json.Number)
		if !ok {
			return Intent{}, ErrBadQueryParams
		}
		v, err := strconv.Atoi(n.String())
		if err != nil || strconv.Itoa(v) != n.String() {
			return Intent{}, ErrBadQueryParams
		}
		*dst = v
	}
	if _, err := q.Render(p); err != nil { // the same bounds the command rendering enforces
		return Intent{}, err
	}
	return Intent{Query: q, Params: p, OLTRef: ref}, nil
}
