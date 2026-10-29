// Package jobs verifies Cloud job envelopes. The Edge executes NOTHING unless the envelope is signed by the pinned
// Cloud key, bound to this edge+tenant, unexpired, unreplayed, and its operation is both in the local allowlist and in
// the compile-time read-only set. Write operations cannot be enabled by configuration alone.
package jobs

import (
	"bytes"
	"context"
	"crypto/ed25519"
	"encoding/base64"
	"encoding/json"
	"errors"
	"fmt"
	"regexp"
	"time"
)

// ReadOnlyOps is the compile-time ceiling: a config file can narrow it, never widen it.
var ReadOnlyOps = map[string]bool{"collect": true, "refresh": true}

var (
	ErrSignature = errors.New("invalid signature")
	ErrExpired   = errors.New("envelope expired or not yet valid")
	ErrBinding   = errors.New("envelope bound to another edge/tenant")
	ErrOperation = errors.New("operation not permitted on this edge")
	ErrReplay    = errors.New("nonce already seen")
	ErrFormat    = errors.New("malformed envelope")
)

var targetRefRe = regexp.MustCompile(`^[A-Za-z0-9._%-]{3,200}$`)

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
	TargetRef      string   `json:"target_ref,omitempty"` // refresh only: the ACS device id the Cloud signed for this job
	Operation      string   `json:"operation"`
	IdempotencyKey string   `json:"idempotency_key"`
	IssuedAt       string   `json:"issued_at"`
	ExpiresAt      string   `json:"expires_at"`
	Nonce          string   `json:"nonce"`
	IntentSHA256   string   `json:"intent_sha256"`
	PolicyVersion  string   `json:"policy_version"`
	ApprovalIDs    []string `json:"approval_ids"`
	Signature      string   `json:"signature"`
}

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
	Allowed  map[string]bool // local allowlist (subset of ReadOnlyOps)
	Nonces   NonceStore
	Now      func() time.Time
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
	if !ReadOnlyOps[env.Operation] || !v.Allowed[env.Operation] {
		return nil, fmt.Errorf("%w: %s", ErrOperation, env.Operation)
	}
	if env.Operation == "refresh" && env.TargetRef != "" && !targetRefRe.MatchString(env.TargetRef) {
		return nil, fmt.Errorf("%w: invalid target_ref", ErrFormat)
	}
	if env.Operation != "refresh" && env.TargetRef != "" {
		return nil, fmt.Errorf("%w: target_ref only exists on refresh", ErrFormat)
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
