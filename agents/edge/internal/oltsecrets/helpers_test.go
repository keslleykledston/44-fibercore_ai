package oltsecrets

import (
	"bytes"
	"crypto/ecdh"
	"crypto/ed25519"
	"encoding/hex"
	"encoding/json"
	"log/slog"
	"os"
	"path/filepath"
	"strconv"
	"sync"
	"testing"
	"time"

	"github.com/keslleykledston/44-fibercore_ai/agents/edge/internal/config"
	"github.com/keslleykledston/44-fibercore_ai/agents/edge/internal/gateway"
)

const (
	tTenant   = "11111111-1111-4111-8111-111111111111"
	tEdge     = "22222222-2222-4222-8222-222222222222"
	tOLT      = "OLT-CENTRO-01"
	tOLT2     = "OLT-NORTE-02"
	tSNMPOLT  = "OLT-SNMP-03"
	tDelivery = "33333333-3333-4333-8333-333333333333"
	// the secrets of the tests: every log/error/result must be free of them
	tUser      = "admin-olt"
	tPass      = "S3nha!com acentuação-ç"
	tCommunity = "public-ro_01"
)

// lockedBuffer is a log sink that can be read while other goroutines write.
type lockedBuffer struct {
	mu sync.Mutex
	b  bytes.Buffer
}

func (l *lockedBuffer) Write(p []byte) (int, error) {
	l.mu.Lock()
	defer l.mu.Unlock()
	return l.b.Write(p)
}
func (l *lockedBuffer) String() string { l.mu.Lock(); defer l.mu.Unlock(); return l.b.String() }

// privDir is a directory with mode 0700 (t.TempDir() is 0777 &^ umask).
func privDir(t *testing.T) string {
	t.Helper()
	d := filepath.Join(t.TempDir(), "d")
	if err := os.Mkdir(d, 0o700); err != nil {
		t.Fatal(err)
	}
	return d
}

// env is a complete Edge-side fixture: key, the Cloud's signing key, targets, store and a processor with a controlled clock.
type env struct {
	t        *testing.T
	key      *Key
	signPriv ed25519.PrivateKey
	proc     *Processor
	store    *AppliedStore
	logs     *lockedBuffer
	credDir  string
	credPath string // OLT-CENTRO-01 (CLI + last_down)
	cred2    string // OLT-NORTE-02 (CLI)
	credSNMP string // OLT-SNMP-03 (snmp transport)
	now      time.Time
	exp      int64
}

func newEnv(t *testing.T) *env {
	t.Helper()
	e := &env{t: t, logs: &lockedBuffer{}, now: time.Unix(1893456000-600, 0)}
	e.exp = 1893456000
	scalar, _ := hex.DecodeString("1f1f1f1f1f1f1f1f1f1f1f1f1f1f1f1f1f1f1f1f1f1f1f1f1f1f1f1f1f1f1f1f")
	var err error
	if e.key, err = KeyFromScalar(scalar); err != nil {
		t.Fatal(err)
	}
	seed, _ := hex.DecodeString("202122232425262728292a2b2c2d2e2f303132333435363738393a3b3c3d3e3f")
	e.signPriv = ed25519.NewKeyFromSeed(seed)
	e.credDir = privDir(t)
	e.credPath = filepath.Join(e.credDir, "centro.cred.json")
	e.cred2 = filepath.Join(e.credDir, "norte.cred.json")
	e.credSNMP = filepath.Join(e.credDir, "snmp.cred.json")
	oltCLI := config.OLTConfig{Name: tOLT, CredentialsFile: e.credPath, LastDown: &config.LastDownConfig{}}
	oltCLI2 := config.OLTConfig{Name: tOLT2, CredentialsFile: e.cred2}
	oltSNMP := config.OLTConfig{Name: tSNMPOLT, Transport: "snmp", CredentialsFile: e.credSNMP}
	e.store = &AppliedStore{Path: filepath.Join(privDir(t), "applied.json"), Now: func() time.Time { return e.now }}
	log := slog.New(slog.NewJSONHandler(e.logs, &slog.HandlerOptions{Level: slog.LevelDebug}))
	e.store.Log = log
	e.proc = &Processor{
		TenantID: tTenant, EdgeID: tEdge, Key: e.key, Pub: e.signPriv.Public().(ed25519.PublicKey), Store: e.store, Log: log,
		Now: func() time.Time { return e.now },
		Targets: map[string]Target{
			tOLT:     {Name: tOLT, Path: e.credPath, Accepts: oltCLI.AcceptsKind},
			tOLT2:    {Name: tOLT2, Path: e.cred2, Accepts: oltCLI2.AcceptsKind},
			tSNMPOLT: {Name: tSNMPOLT, Path: e.credSNMP, Accepts: oltSNMP.AcceptsKind},
		},
	}
	return e
}

// spec describes one delivery the way the Cloud would build it; the zero value is a valid ssh_login for tOLT.
type spec struct {
	id, olt, kind, keyID string
	exp                  int64
	plaintext            string // empty = the right one for the kind
	// what the browser sealed with (AAD) when it differs from what the Cloud signs/sends
	sealTenant, sealEdge, sealOLT, sealKind, sealID, sealKeyID string
	sealExp                                                    int64
}

func (s spec) fill(e *env) spec {
	if s.id == "" {
		s.id = tDelivery
	}
	if s.olt == "" {
		s.olt = tOLT
	}
	if s.kind == "" {
		s.kind = config.KindSSHLogin
	}
	if s.keyID == "" {
		s.keyID = e.key.KeyID()
	}
	if s.exp == 0 {
		s.exp = e.exp
	}
	if s.plaintext == "" {
		if s.kind == config.KindSSHLogin {
			b, _ := json.Marshal(map[string]string{"kind": s.kind, "username": tUser, "password": tPass})
			s.plaintext = string(b)
		} else {
			b, _ := json.Marshal(map[string]string{"kind": s.kind, "community": tCommunity})
			s.plaintext = string(b)
		}
	}
	return s
}

// build makes a delivery: sealed with the (possibly different) seal AAD, signed over the AAD the Edge will rebuild from what is sent.
func (e *env) build(s spec) *gateway.SecretDelivery {
	e.t.Helper()
	s = s.fill(e)
	pick := func(v, d string) string {
		if v != "" {
			return v
		}
		return d
	}
	sealExp := s.sealExp
	if sealExp == 0 {
		sealExp = s.exp
	}
	sealAAD := AAD(pick(s.sealTenant, tTenant), pick(s.sealEdge, tEdge), pick(s.sealOLT, s.olt), pick(s.sealKind, s.kind), pick(s.sealID, s.id), pick(s.sealKeyID, s.keyID), sealExp)
	blob, err := Seal(e.key.PublicPoint(), sealAAD, []byte(s.plaintext))
	if err != nil {
		e.t.Fatal(err)
	}
	return e.sign(s, blob)
}

// sign signs the AAD the Edge rebuilds from s and sends it with blob.
func (e *env) sign(s spec, blob []byte) *gateway.SecretDelivery {
	aad := AAD(tTenant, tEdge, s.olt, s.kind, s.id, s.keyID, s.exp)
	sig := ed25519.Sign(e.signPriv, SignedMessage(aad, blob))
	return &gateway.SecretDelivery{
		ID: s.id, LeaseToken: "lease-1", OLTName: s.olt, Kind: s.kind, KeyID: s.keyID,
		ExpiresAt: json.RawMessage(strconv.FormatInt(s.exp, 10)),
		Sealed:    b64.EncodeToString(blob), Signature: b64.EncodeToString(sig),
	}
}

func (e *env) process(d *gateway.SecretDelivery) Result {
	e.t.Helper()
	r, err := e.proc.Process(d)
	if err != nil {
		e.t.Fatalf("unexpected abort: %v", err)
	}
	return r
}

func (e *env) wantFail(d *gateway.SecretDelivery, code string) {
	e.t.Helper()
	if r := e.process(d); r.Outcome != OutcomeFailed || r.Code != code {
		e.t.Fatalf("want failed/%s, got %+v", code, r)
	}
}

func (e *env) wantApplied(d *gateway.SecretDelivery) {
	e.t.Helper()
	if r := e.process(d); r.Outcome != OutcomeApplied || r.Code != "" {
		e.t.Fatalf("want applied, got %+v", r)
	}
}

func (e *env) fileExists(p string) bool { _, err := os.Lstat(p); return err == nil }

func (e *env) readFile(p string) string {
	b, err := os.ReadFile(p)
	if err != nil {
		e.t.Fatal(err)
	}
	return string(b)
}

func mustEphemeral(t *testing.T, hexScalar string) *ecdh.PrivateKey {
	t.Helper()
	b, err := hex.DecodeString(hexScalar)
	if err != nil {
		t.Fatal(err)
	}
	k, err := ecdh.P256().NewPrivateKey(b)
	if err != nil {
		t.Fatal(err)
	}
	return k
}
