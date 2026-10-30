// Package jobs verifies Cloud job envelopes. The Edge executes NOTHING unless the envelope is signed by the pinned
// Cloud key, bound to this edge+tenant, unexpired, unreplayed, and its operation is both in the local allowlist and in
// the compile-time read-only set. Write operations cannot be enabled by configuration alone.
package jobs

import (
	"bytes"
	"context"
	"crypto/ed25519"
	"encoding/base64"
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"errors"
	"fmt"
	"regexp"
	"time"
)

// ReadOnlyOps is the compile-time ceiling: a config file can narrow it, never widen it.
var ReadOnlyOps = map[string]bool{"collect": true, "refresh": true}

// BenchWriteOps (ADR-0030) is a SEPARATE compile-time set: the only writes this Edge can ever run, and only on the configured bench devices,
// with a single-use prior authorization, a durable claim, a valid lease and the device confirmed against the ACS. ReadOnlyOps never grows.
var BenchWriteOps = map[string]bool{"reboot_cpe": true, "set_wifi_ssid": true, "onu_reset": true, "onu_deactivate": true}

// QueryOps (ADR-0029) is a THIRD compile-time set: read-only queries of the OLT's CLI. It runs only when the local switch is on and a checker for the
// intent is wired in; whatever the Cloud signs, an unknown or unwired query operation is refused here. ReadOnlyOps and BenchWriteOps never grow.
var QueryOps = map[string]bool{"olt_query": true}

// QueryEnvelopeTTL bounds how long an olt_query envelope may live (the Cloud's job window is 15 minutes).
const QueryEnvelopeTTL = 20 * time.Minute

// BenchSSIDRe is the ONLY SSID the bench may ever set (ADR-0030 H3). Checked here, again at the Cloud and again right before the task is sent.
var BenchSSIDRe = regexp.MustCompile(`^BANCADA-[A-Z0-9]{1,16}$`)

// BenchEnvelopeTTL bounds how long a bench envelope may live (the Cloud issues it for at most this long).
const BenchEnvelopeTTL = 2 * time.Minute

var (
	ErrSignature = errors.New("invalid signature")
	ErrExpired   = errors.New("envelope expired or not yet valid")
	ErrBinding   = errors.New("envelope bound to another edge/tenant")
	ErrOperation = errors.New("operation not permitted on this edge")
	ErrReplay    = errors.New("nonce already seen")
	ErrFormat    = errors.New("malformed envelope")
)

var targetRefRe = regexp.MustCompile(`^[A-Za-z0-9._%-]{3,200}$`)
var authIDRe = regexp.MustCompile(`^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$`)

const (
	maxLifetime = time.Hour
	clockSkew   = 2 * time.Minute
)

type Envelope struct {
	SchemaVersion  string   `json:"schema_version"`
	JobID          string   `json:"job_id"`
	TenantID       string   `json:"tenant_id"`
	EdgeID         string   `json:"edge_id"`
	TargetID       string   `json:"target_id"`
	TargetRef      string   `json:"target_ref,omitempty"` // refresh and bench writes: the ACS device id the Cloud signed for this job
	Operation      string   `json:"operation"`
	IdempotencyKey string   `json:"idempotency_key"`
	IssuedAt       string   `json:"issued_at"`
	ExpiresAt      string   `json:"expires_at"`
	Nonce          string   `json:"nonce"`
	IntentSHA256   string   `json:"intent_sha256"`
	PolicyVersion  string   `json:"policy_version"`
	ApprovalIDs    []string `json:"approval_ids"`
	// Bench writes only (ADR-0030); all covered by the signature, all absent on every other operation.
	AuthorizationID     string `json:"authorization_id,omitempty"`
	AuthorizationEndsAt string `json:"authorization_ends_at,omitempty"`
	OwnerEpoch          int    `json:"owner_epoch,omitempty"`
	// Parameters covered by the signature: bench set_wifi_ssid (one string) and olt_query (the closed intent, integers as json.Number); absent everywhere else.
	Params    Params `json:"params,omitempty"`
	Signature string `json:"signature"`
}

// Params are the signed parameters of an envelope. Values keep their JSON type (strings, json.Number) so each operation's checker can be strict.
type Params map[string]any

// String returns the value of k when it is a string, else "".
func (p Params) String(k string) string { s, _ := p[k].(string); return s }

// NonceStore remembers nonces until they expire (persisted: a restart must not reopen the replay window).
type NonceStore interface {
	// Remember returns false if the nonce was already present.
	Remember(ctx context.Context, nonce string, until time.Time) (bool, error)
}

// Canonical reproduces the Cloud's signing bytes: object without "signature", keys sorted, compact, no HTML escaping.
func Canonical(raw []byte) ([]byte, error) {
	var m map[string]any
	dec := json.NewDecoder(bytes.NewReader(raw))
	dec.UseNumber()
	if err := dec.Decode(&m); err != nil {
		return nil, fmt.Errorf("%w: %v", ErrFormat, err)
	}
	delete(m, "signature")
	var buf bytes.Buffer
	enc := json.NewEncoder(&buf)
	enc.SetEscapeHTML(false)
	if err := enc.Encode(m); err != nil { // encoding/json sorts map keys
		return nil, err
	}
	return bytes.TrimRight(buf.Bytes(), "\n"), nil
}

type Verifier struct {
	Pub      ed25519.PublicKey
	EdgeID   string
	TenantID string
	Allowed  map[string]bool // local allowlist (subset of ReadOnlyOps, plus BenchWriteOps when BenchEnabled)
	// BenchEnabled is the local `bench_writes_enabled` switch (ADR-0030 item 3): without it a bench operation is refused here, whatever the Cloud signs.
	BenchEnabled bool
	// QueryEnabled is the local `olt_query_enabled` switch (ADR-0029) and QueryCheck validates the closed intent against the Edge's own catalog and
	// OLT identity. Without both, an olt_query envelope is refused here, whatever the Cloud signs.
	QueryEnabled bool
	QueryCheck   func(params map[string]any, targetID string) error
	Nonces       NonceStore
	Now          func() time.Time
}

func ParsePublicKey(b64 string) (ed25519.PublicKey, error) {
	b, err := base64.StdEncoding.DecodeString(b64)
	if err != nil || len(b) != ed25519.PublicKeySize {
		return nil, errors.New("job_public_key must be a base64 Ed25519 public key (32 bytes)")
	}
	return ed25519.PublicKey(b), nil
}

// Verify checks a raw envelope. Order matters: signature first, so nothing unauthenticated is trusted afterwards.
func (v *Verifier) Verify(ctx context.Context, raw []byte) (*Envelope, error) {
	canon, err := Canonical(raw)
	if err != nil {
		return nil, err
	}
	var env Envelope
	dec := json.NewDecoder(bytes.NewReader(raw))
	dec.DisallowUnknownFields()
	dec.UseNumber()
	if err := dec.Decode(&env); err != nil || env.SchemaVersion != "1.0" {
		return nil, fmt.Errorf("%w: unknown or missing fields", ErrFormat)
	}
	sig, err := base64.StdEncoding.DecodeString(env.Signature)
	if err != nil || !ed25519.Verify(v.Pub, canon, sig) {
		return nil, ErrSignature
	}
	if env.EdgeID != v.EdgeID || env.TenantID != v.TenantID {
		return nil, ErrBinding
	}
	now := v.Now()
	iss, e1 := time.Parse(time.RFC3339, env.IssuedAt)
	exp, e2 := time.Parse(time.RFC3339, env.ExpiresAt)
	if e1 != nil || e2 != nil || !exp.After(now) || iss.After(now.Add(clockSkew)) || exp.Sub(iss) > maxLifetime {
		return nil, ErrExpired
	}
	bench := BenchWriteOps[env.Operation]
	query := QueryOps[env.Operation]
	if !(ReadOnlyOps[env.Operation] || (bench && v.BenchEnabled) || (query && v.QueryEnabled && v.QueryCheck != nil)) || !v.Allowed[env.Operation] {
		return nil, fmt.Errorf("%w: %s", ErrOperation, env.Operation)
	}
	if env.Operation == "refresh" && env.TargetRef != "" && !targetRefRe.MatchString(env.TargetRef) {
		return nil, fmt.Errorf("%w: invalid target_ref", ErrFormat)
	}
	if env.Operation != "refresh" && !bench && env.TargetRef != "" { // (olt_query has no target_ref either)
		return nil, fmt.Errorf("%w: target_ref only exists on refresh and bench writes", ErrFormat)
	}
	if query {
		if env.AuthorizationID != "" || env.AuthorizationEndsAt != "" || env.OwnerEpoch != 0 || exp.Sub(iss) > QueryEnvelopeTTL+time.Second {
			return nil, fmt.Errorf("%w: a query carries no authorization and lives at most %s", ErrFormat, QueryEnvelopeTTL)
		}
		// the signed hash must be the hash of the intent actually carried: an envelope whose params were swapped under a reused hash is refused
		if h, err := IntentHash(env.Operation, "olt", env.TargetID, env.Params); err != nil || h != env.IntentSHA256 {
			return nil, fmt.Errorf("%w: intent hash does not cover the parameters", ErrFormat)
		}
		if err := v.QueryCheck(env.Params, env.TargetID); err != nil {
			return nil, fmt.Errorf("%w: %v", ErrFormat, err)
		}
	} else if bench {
		if err := checkBench(&env, iss, exp, now); err != nil {
			return nil, err
		}
	} else if env.AuthorizationID != "" || env.AuthorizationEndsAt != "" || env.OwnerEpoch != 0 || len(env.Params) != 0 {
		return nil, fmt.Errorf("%w: authorization fields only exist on bench writes", ErrFormat)
	}
	if len(env.Nonce) < 16 {
		return nil, fmt.Errorf("%w: nonce too short", ErrFormat)
	}
	fresh, err := v.Nonces.Remember(ctx, env.Nonce, exp.Add(clockSkew))
	if err != nil {
		return nil, err
	}
	if !fresh {
		return nil, ErrReplay
	}
	return &env, nil
}

// checkBench is the envelope-level half of the bench gate: everything a bench write must carry, bounded in time. The other half (device
// identity against the ACS, durable claim, lease, epoch) runs at execution, immediately before anything is sent.
func checkBench(env *Envelope, iss, exp, now time.Time) error {
	if !targetRefRe.MatchString(env.TargetRef) {
		return fmt.Errorf("%w: a bench write names its target device", ErrFormat)
	}
	if !authIDRe.MatchString(env.AuthorizationID) || env.OwnerEpoch < 1 {
		return fmt.Errorf("%w: a bench write carries its authorization and owner epoch", ErrFormat)
	}
	end, err := time.Parse(time.RFC3339, env.AuthorizationEndsAt)
	if err != nil || !end.After(now) || exp.After(end) {
		return fmt.Errorf("%w: authorization window closed or shorter than the envelope", ErrExpired)
	}
	if exp.Sub(iss) > BenchEnvelopeTTL+time.Second {
		return fmt.Errorf("%w: a bench envelope lives at most %s", ErrExpired, BenchEnvelopeTTL)
	}
	switch env.Operation {
	case "set_wifi_ssid":
		if len(env.Params) != 1 || !BenchSSIDRe.MatchString(env.Params.String("ssid")) {
			return fmt.Errorf("%w: set_wifi_ssid takes exactly one ssid parameter of the bench shape", ErrFormat)
		}
	default:
		if len(env.Params) != 0 {
			return fmt.Errorf("%w: this bench operation takes no parameters", ErrFormat)
		}
	}
	return nil
}

// IntentHash reproduces the Cloud's intent hash: SHA-256 of the compact JSON of {operation, target_type, target_id, params} with sorted keys.
func IntentHash(operation, targetType, targetID string, params Params) (string, error) {
	var buf bytes.Buffer
	enc := json.NewEncoder(&buf)
	enc.SetEscapeHTML(false)
	if err := enc.Encode(map[string]any{"operation": operation, "target_type": targetType, "target_id": targetID, "params": map[string]any(params)}); err != nil {
		return "", err
	}
	sum := sha256.Sum256(bytes.TrimRight(buf.Bytes(), "\n"))
	return hex.EncodeToString(sum[:]), nil
}
