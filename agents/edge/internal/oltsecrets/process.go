package oltsecrets

import (
	"bytes"
	"crypto/ed25519"
	"encoding/json"
	"errors"
	"log/slog"
	"regexp"
	"strings"
	"sync"
	"time"

	"github.com/keslleykledston/44-fibercore_ai/agents/edge/internal/config"
	"github.com/keslleykledston/44-fibercore_ai/agents/edge/internal/credfile"
	"github.com/keslleykledston/44-fibercore_ai/agents/edge/internal/gateway"
)

// Failure codes of ADR-0045 (the closed list the Cloud accepts).
const (
	CodeBadKeyID            = "bad_key_id"
	CodeExpired             = "expired"
	CodeAADMismatch         = "aad_mismatch"
	CodeBadSignature        = "bad_signature"
	CodeDecryptFailed       = "decrypt_failed"
	CodeInvalidPayload      = "invalid_payload"
	CodeStale               = "stale"
	CodeTargetNotConfigured = "target_not_configured"
	CodeWriteFailed         = "write_failed"
	CodeStateUnreadable     = "state_unreadable"
)

// Clock tolerances (ADR-0045): an expires_at in the past is accepted up to 2 minutes (clock drift); one more than 65 minutes ahead is refused (the Cloud only issues <= 60).
const (
	PastTolerance = 2 * time.Minute
	MaxAhead      = 65 * time.Minute
)

const (
	OutcomeApplied = "applied"
	OutcomeFailed  = "failed"
)

// Result is what is reported to the Cloud for one attempt.
type Result struct {
	Outcome string // applied | failed
	Code    string // failure code; empty when applied
}

// ErrAborted is returned by a test hook to simulate the process dying at that point: nothing is reported.
var ErrAborted = errors.New("aborted (simulated crash)")

// Target is one OLT of THIS Edge's configuration that accepted remote credentials (it has a credentials_file).
type Target struct {
	Name string
	Path string
	// Accepts says which kinds this OLT entry would ever use (config.OLTConfig.AcceptsKind).
	Accepts func(kind string) bool
}

// Processor applies ONE delivery in the exact order of ADR-0045:
//
//	(1) verify signature, key_id, AAD (own tenant/edge/OLT), validity   (2) open and validate the JSON   (3) already applied => do not write, answer applied
//	(4) write the credentials file (atomic)   (5) record the delivery id in the applied store (atomic)   (6) the caller reports the result.
//
// A crash between (4) and (5) makes the redelivery write the SAME content again (idempotent); between (5) and (6) the redelivery lands in (3) and answers applied.
type Processor struct {
	TenantID, EdgeID string
	Key              *Key
	Pub              ed25519.PublicKey // the Cloud's pinned key (job_public_key)
	Targets          map[string]Target
	Store            *AppliedStore
	Now              func() time.Time
	Log              *slog.Logger

	// Test hooks (nil in production): called after step 4 / step 5; an error aborts the processing as if the process had died there.
	AfterWrite  func() error
	AfterRecord func() error

	mu sync.Mutex
}

func (p *Processor) now() time.Time {
	if p.Now != nil {
		return p.Now()
	}
	return time.Now()
}

func (p *Processor) logf() *slog.Logger {
	if p.Log != nil {
		return p.Log
	}
	return slog.New(slog.NewJSONHandler(discard{}, nil))
}

type discard struct{}

func (discard) Write(b []byte) (int, error) { return len(b), nil }

var (
	uuidRe  = regexp.MustCompile(`^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$`)
	keyIDRe = regexp.MustCompile(`^[0-9a-f]{16}$`)
)

func fail(code string) Result { return Result{Outcome: OutcomeFailed, Code: code} }

// parseExpires accepts unix seconds (a JSON number) or an RFC 3339 string with WHOLE seconds (the browser chooses an integer: a fraction cannot be the AAD it sealed).
func parseExpires(raw json.RawMessage) (int64, bool) {
	raw = bytes.TrimSpace(raw)
	if len(raw) == 0 || string(raw) == "null" {
		return 0, false
	}
	if raw[0] == '"' {
		var s string
		if json.Unmarshal(raw, &s) != nil {
			return 0, false
		}
		t, err := time.Parse(time.RFC3339Nano, s)
		if err != nil || t.Nanosecond() != 0 {
			return 0, false
		}
		return t.Unix(), true
	}
	var n json.Number
	dec := json.NewDecoder(bytes.NewReader(raw))
	dec.UseNumber()
	if dec.Decode(&n) != nil {
		return 0, false
	}
	v, err := n.Int64() // a fraction or exponent is not an integer second
	if err != nil || v <= 0 {
		return 0, false
	}
	return v, true
}

// Process runs steps (1) to (5). The returned Result is what step (6) must report; an error means "report nothing" (simulated crash only).
func (p *Processor) Process(d *gateway.SecretDelivery) (Result, error) {
	p.mu.Lock()
	defer p.mu.Unlock()
	log := p.logf().With("delivery_id", safeLog(d.ID), "olt", safeLog(d.OLTName), "kind", safeLog(d.Kind))

	// Structure first: nothing here is trusted, it only decides whether the signed bytes can even be rebuilt.
	exp, expOK := parseExpires(d.ExpiresAt)
	if !uuidRe.MatchString(d.ID) || d.LeaseToken == "" || d.OLTName == "" || len(d.OLTName) > 128 ||
		(d.Kind != config.KindSSHLogin && d.Kind != config.KindSNMPCommunity) || !keyIDRe.MatchString(d.KeyID) || !expOK ||
		d.Sealed == "" || len(d.Sealed) > 4*MaxBlobBytes {
		log.Warn("olt secret delivery refused", "code", CodeInvalidPayload, "step", "structure")
		return fail(CodeInvalidPayload), nil
	}
	blob, err := decodeBlob(d.Sealed)
	if err != nil || len(blob) > MaxBlobBytes {
		log.Warn("olt secret delivery refused", "code", CodeInvalidPayload, "step", "blob")
		return fail(CodeInvalidPayload), nil
	}
	aad := AAD(p.TenantID, p.EdgeID, d.OLTName, d.Kind, d.ID, d.KeyID, exp)

	// (1) signature, key_id, AAD, validity
	sig, serr := b64.DecodeString(d.Signature)
	if len(p.Pub) != ed25519.PublicKeySize || d.Signature == "" || serr != nil || len(sig) != ed25519.SignatureSize || !ed25519.Verify(p.Pub, SignedMessage(aad, blob), sig) {
		log.Warn("olt secret delivery refused", "code", CodeBadSignature)
		return fail(CodeBadSignature), nil
	}
	if d.KeyID != p.Key.KeyID() {
		log.Warn("olt secret delivery refused", "code", CodeBadKeyID)
		return fail(CodeBadKeyID), nil
	}
	// The wire form carries no tenant or edge: they come from this Edge's own configuration and are inside the signed AAD. If the Cloud echoes an identity or the whole
	// AAD anyway, it must agree with ours.
	if (d.TenantID != "" && !strings.EqualFold(d.TenantID, p.TenantID)) || (d.EdgeID != "" && !strings.EqualFold(d.EdgeID, p.EdgeID)) || (d.AAD != "" && d.AAD != string(aad)) {
		log.Warn("olt secret delivery refused", "code", CodeAADMismatch)
		return fail(CodeAADMismatch), nil
	}
	now := p.now()
	switch {
	case time.Unix(exp, 0).Add(PastTolerance).Before(now):
		log.Warn("olt secret delivery refused", "code", CodeExpired)
		return fail(CodeExpired), nil
	case time.Unix(exp, 0).After(now.Add(MaxAhead)):
		log.Warn("olt secret delivery refused", "code", CodeInvalidPayload, "step", "validity too far ahead")
		return fail(CodeInvalidPayload), nil
	}
	tgt, ok := p.Targets[d.OLTName]
	if !ok || tgt.Path == "" || (tgt.Accepts != nil && !tgt.Accepts(d.Kind)) {
		log.Warn("olt secret delivery refused", "code", CodeTargetNotConfigured)
		return fail(CodeTargetNotConfigured), nil
	}

	// (2) open and validate
	pt, err := p.Key.Open(blob, aad)
	if err != nil {
		log.Warn("olt secret delivery refused", "code", CodeDecryptFailed)
		return fail(CodeDecryptFailed), nil
	}
	defer credfile.Zero(pt)
	set, perr := parsePlaintext(pt, d.Kind)
	if perr != nil {
		log.Warn("olt secret delivery refused", "code", CodeInvalidPayload, "step", "plaintext")
		return fail(CodeInvalidPayload), nil
	}

	// (3) already applied => never write again, answer applied; a rollback is refused
	done, stale, err := p.Store.Check(strings.ToLower(d.ID), d.OLTName, d.Kind, exp)
	if err != nil {
		log.Error("olt secret delivery not applied: the applied-delivery store is unreadable", "code", CodeStateUnreadable, "err", err)
		return fail(CodeStateUnreadable), nil
	}
	if done {
		log.Info("olt secret delivery was already applied; reporting applied without writing again")
		return Result{Outcome: OutcomeApplied}, nil
	}
	if stale {
		log.Warn("olt secret delivery refused", "code", CodeStale)
		return fail(CodeStale), nil
	}

	// (4) credentials file (atomic, locked, merged)
	if err := credfile.Merge(tgt.Path, set); err != nil {
		log.Error("olt secret delivery not applied: the credentials file could not be written", "code", CodeWriteFailed, "err", err)
		return fail(CodeWriteFailed), nil
	}
	if p.AfterWrite != nil {
		if err := p.AfterWrite(); err != nil {
			return Result{}, err
		}
	}

	// (5) applied store (atomic)
	if err := p.Store.Record(strings.ToLower(d.ID), d.OLTName, d.Kind, exp); err != nil {
		// the credentials ARE in the file, but the Edge cannot remember it: report the failure honestly so the operator looks; a new delivery rewrites the same values
		log.Error("olt secret delivery written but NOT recorded: the applied-delivery store cannot be written", "code", CodeStateUnreadable, "err", err)
		return fail(CodeStateUnreadable), nil
	}
	if p.AfterRecord != nil {
		if err := p.AfterRecord(); err != nil {
			return Result{}, err
		}
	}
	log.Info("olt secret delivery applied")
	return Result{Outcome: OutcomeApplied}, nil
}

// safeLog keeps an unauthenticated field short and printable before it reaches a log line.
func safeLog(s string) string {
	if len(s) > 80 {
		s = s[:80]
	}
	return strings.Map(func(r rune) rune {
		if r < 0x20 || r == 0x7f {
			return '?'
		}
		return r
	}, s)
}

// decodeBlob decodes the sealed field: base64url, padded or not (the signature covers the DECODED bytes, so padding cannot change what is verified).
func decodeBlob(s string) ([]byte, error) {
	s = strings.TrimRight(s, "=")
	return b64.DecodeString(s)
}

var errPayload = errors.New("invalid payload")

type plaintext struct {
	Kind      string  `json:"kind"`
	Username  *string `json:"username"`
	Password  *string `json:"password"`
	Community *string `json:"community"`
}

// parsePlaintext validates the sealed JSON against ADR-0045 and returns the fields to merge. Errors are fixed text: a json error can quote the input.
func parsePlaintext(pt []byte, kind string) (credfile.Creds, error) {
	var p plaintext
	dec := json.NewDecoder(bytes.NewReader(pt))
	dec.DisallowUnknownFields()
	if dec.Decode(&p) != nil || dec.More() || p.Kind != kind {
		return credfile.Creds{}, errPayload
	}
	var c credfile.Creds
	switch kind {
	case config.KindSSHLogin:
		if p.Username == nil || p.Password == nil || p.Community != nil ||
			credfile.ValidateField(*p.Username, credfile.MaxUsername) != nil || credfile.ValidateField(*p.Password, credfile.MaxPassword) != nil {
			return credfile.Creds{}, errPayload
		}
		c.Username, c.Password = *p.Username, *p.Password
	case config.KindSNMPCommunity:
		if p.Community == nil || p.Username != nil || p.Password != nil || credfile.ValidateField(*p.Community, credfile.MaxCommunity) != nil {
			return credfile.Creds{}, errPayload
		}
		c.SNMPCommunity = *p.Community
	default:
		return credfile.Creds{}, errPayload
	}
	return c, nil
}
