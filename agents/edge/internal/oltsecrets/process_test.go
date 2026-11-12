package oltsecrets

import (
	"crypto/ed25519"
	"encoding/json"
	"errors"
	"os"
	"path/filepath"
	"strings"
	"testing"
	"time"

	"github.com/keslleykledston/44-fibercore_ai/agents/edge/internal/config"
	"github.com/keslleykledston/44-fibercore_ai/agents/edge/internal/credfile"
	"github.com/keslleykledston/44-fibercore_ai/agents/edge/internal/gateway"
)

func TestHappyPathWritesTheCredentialsFileAndRecordsTheDelivery(t *testing.T) {
	e := newEnv(t)
	e.wantApplied(e.build(spec{}))
	c, found, err := credfile.Read(e.credPath)
	if err != nil || !found || c.Username != tUser || c.Password != tPass || c.SNMPCommunity != "" {
		t.Fatalf("c=%+v found=%v err=%v", c, found, err)
	}
	if fi, _ := os.Stat(e.credPath); fi.Mode().Perm() != 0o600 {
		t.Fatalf("mode %v", fi.Mode().Perm())
	}
	if applied, _, err := e.store.Check(tDelivery, tOLT, config.KindSSHLogin, e.exp); err != nil || !applied {
		t.Fatalf("not recorded: %v %v", applied, err)
	}
}

func TestKindsMergeAndEachOnlyTouchesItsFields(t *testing.T) {
	e := newEnv(t)
	e.wantApplied(e.build(spec{}))
	e.wantApplied(e.build(spec{kind: config.KindSNMPCommunity, id: "33333333-3333-4333-8333-333333333334"}))
	c, _, err := credfile.Read(e.credPath)
	if err != nil || c.Username != tUser || c.Password != tPass || c.SNMPCommunity != tCommunity {
		t.Fatalf("merge lost a field: %+v %v", c, err)
	}
	// a new login replaces username+password together and keeps the community
	e.wantApplied(e.build(spec{id: "33333333-3333-4333-8333-333333333335", plaintext: `{"kind":"ssh_login","username":"novo","password":"outra"}`}))
	c, _, _ = credfile.Read(e.credPath)
	if c.Username != "novo" || c.Password != "outra" || c.SNMPCommunity != tCommunity {
		t.Fatalf("%+v", c)
	}
}

func TestACommunityForAnOLTThatNeverUsesOneAndALoginForAnSNMPOLTAreRefused(t *testing.T) {
	e := newEnv(t)
	e.wantFail(e.build(spec{olt: tOLT2, kind: config.KindSNMPCommunity}), CodeTargetNotConfigured)
	e.wantFail(e.build(spec{olt: tSNMPOLT, kind: config.KindSSHLogin}), CodeTargetNotConfigured)
	e.wantApplied(e.build(spec{olt: tSNMPOLT, kind: config.KindSNMPCommunity}))
	if e.fileExists(e.cred2) {
		t.Fatal("a refused delivery must not create a file")
	}
}

func TestOLTNotConfiguredOrWithoutCredentialsFile(t *testing.T) {
	e := newEnv(t)
	e.wantFail(e.build(spec{olt: "OLT-DESCONHECIDA"}), CodeTargetNotConfigured)
	delete(e.proc.Targets, tOLT2) // an OLT without credentials_file is simply not a target
	e.wantFail(e.build(spec{olt: tOLT2}), CodeTargetNotConfigured)
}

// --- tampering: every one of these must leave NO file behind -------------------------------------------------------------------------------------------------------

func (e *env) assertNothingWritten() {
	e.t.Helper()
	for _, p := range []string{e.credPath, e.cred2, e.credSNMP} {
		if e.fileExists(p) {
			e.t.Fatalf("a refused delivery wrote %s", p)
		}
	}
	if e.fileExists(e.store.Path) {
		e.t.Fatal("a refused delivery was recorded as applied")
	}
}

func TestTamperedCiphertextIsRefusedWhetherOrNotTheCloudResigns(t *testing.T) {
	e := newEnv(t)
	d := e.build(spec{})
	blob, _ := b64.DecodeString(d.Sealed)
	blob[len(blob)-3] ^= 0x01
	// not re-signed: the signature no longer matches the blob (checked first)
	bad := *d
	bad.Sealed = b64.EncodeToString(blob)
	e.wantFail(&bad, CodeBadSignature)
	// re-signed by a Cloud that does not notice: the AEAD tag catches it
	resigned := e.sign(spec{}.fill(e), blob)
	e.wantFail(resigned, CodeDecryptFailed)
	e.assertNothingWritten()
}

func TestEveryFieldOfTheAADIsBound(t *testing.T) {
	e := newEnv(t)
	// The browser sealed with ONE value different from what the (honest) Cloud signs and sends: only the AEAD can notice, and it must.
	for name, s := range map[string]spec{
		"tenant": {sealTenant: "99999999-9999-4999-8999-999999999999"},
		"edge":   {sealEdge: "99999999-9999-4999-8999-999999999999"},
		"olt":    {sealOLT: tOLT2},
		"kind":   {sealKind: config.KindSNMPCommunity, plaintext: `{"kind":"ssh_login","username":"u","password":"p"}`},
		"id":     {sealID: "99999999-9999-4999-8999-999999999999"},
		"key_id": {sealKeyID: "0000000000000000"},
		"exp":    {sealExp: 1893456001},
	} {
		d := e.build(s)
		if r := e.process(d); r.Outcome != OutcomeFailed || r.Code != CodeDecryptFailed {
			t.Errorf("AAD %s: %+v", name, r)
		}
	}
	e.assertNothingWritten()
}

func TestEveryDeliveredFieldIsCoveredByTheSignature(t *testing.T) {
	e := newEnv(t)
	good := e.build(spec{})
	mut := map[string]func(d *gateway.SecretDelivery){
		"olt_name": func(d *gateway.SecretDelivery) { d.OLTName = tOLT2 },
		"kind":     func(d *gateway.SecretDelivery) { d.Kind = config.KindSNMPCommunity },
		"id":       func(d *gateway.SecretDelivery) { d.ID = "33333333-3333-4333-8333-333333333399" },
		"key_id":   func(d *gateway.SecretDelivery) { d.KeyID = "0123456789abcdef" },
		"expires":  func(d *gateway.SecretDelivery) { d.ExpiresAt = json.RawMessage("1893456001") },
	}
	for name, f := range mut {
		c := *good
		f(&c)
		if r := e.process(&c); r.Outcome != OutcomeFailed || r.Code != CodeBadSignature {
			t.Errorf("%s: %+v", name, r)
		}
	}
	e.assertNothingWritten()
}

func TestSignatureMissingInvalidOrFromAnotherKey(t *testing.T) {
	e := newEnv(t)
	good := e.build(spec{})
	for name, f := range map[string]func(d *gateway.SecretDelivery){
		"missing": func(d *gateway.SecretDelivery) { d.Signature = "" },
		"garbage": func(d *gateway.SecretDelivery) { d.Signature = "AAAA" },
		"padded":  func(d *gateway.SecretDelivery) { d.Signature += "==" },
		"standard": func(d *gateway.SecretDelivery) {
			d.Signature = strings.NewReplacer("-", "+", "_", "/").Replace(d.Signature) + "="
		},
		"flipped": func(d *gateway.SecretDelivery) {
			s, _ := b64.DecodeString(d.Signature)
			s[0] ^= 1
			d.Signature = b64.EncodeToString(s)
		},
		"other-signer": func(d *gateway.SecretDelivery) {
			_, other, _ := ed25519.GenerateKey(nil)
			blob, _ := b64.DecodeString(d.Sealed)
			d.Signature = b64.EncodeToString(ed25519.Sign(other, SignedMessage(AAD(tTenant, tEdge, tOLT, config.KindSSHLogin, tDelivery, e.key.KeyID(), e.exp), blob)))
		},
	} {
		c := *good
		f(&c)
		if r := e.process(&c); r.Outcome != OutcomeFailed || r.Code != CodeBadSignature {
			t.Errorf("%s: %+v", name, r)
		}
	}
	e.proc.Pub = nil // a missing pinned key must fail closed, not panic
	e.wantFail(good, CodeBadSignature)
	e.assertNothingWritten()
}

func TestSignedForAnotherTenantOrEdgeIsNotValidHere(t *testing.T) {
	e := newEnv(t)
	d := e.build(spec{})
	blob, _ := b64.DecodeString(d.Sealed)
	for name, aad := range map[string][]byte{
		"tenant": AAD("99999999-9999-4999-8999-999999999999", tEdge, tOLT, config.KindSSHLogin, tDelivery, e.key.KeyID(), e.exp),
		"edge":   AAD(tTenant, "99999999-9999-4999-8999-999999999999", tOLT, config.KindSSHLogin, tDelivery, e.key.KeyID(), e.exp),
	} {
		c := *d
		c.Signature = b64.EncodeToString(ed25519.Sign(e.signPriv, SignedMessage(aad, blob)))
		if r := e.process(&c); r.Code != CodeBadSignature {
			t.Errorf("%s: %+v", name, r)
		}
	}
	// an identity echoed by the Cloud that disagrees with ours
	c := *d
	c.TenantID = "99999999-9999-4999-8999-999999999999"
	e.wantFail(&c, CodeAADMismatch)
	c = *d
	c.EdgeID = "99999999-9999-4999-8999-999999999999"
	e.wantFail(&c, CodeAADMismatch)
	c = *d
	c.AAD = "fibercore-seal-v1\nsomething else"
	e.wantFail(&c, CodeAADMismatch)
	c = *d
	c.TenantID, c.EdgeID, c.AAD = tTenant, tEdge, string(AAD(tTenant, tEdge, tOLT, config.KindSSHLogin, tDelivery, e.key.KeyID(), e.exp))
	e.wantApplied(&c) // the same identity, echoed, is fine
}

func TestKeyIDOfAnotherKey(t *testing.T) {
	e := newEnv(t)
	e.wantFail(e.build(spec{keyID: "0123456789abcdef"}), CodeBadKeyID)
	e.assertNothingWritten()
}

func TestValidityWindowAndTolerances(t *testing.T) {
	e := newEnv(t)
	at := func(off time.Duration) int64 { return e.now.Add(off).Unix() }
	e.wantFail(e.build(spec{exp: at(-3 * time.Minute)}), CodeExpired)
	e.wantFail(e.build(spec{exp: at(-24 * time.Hour)}), CodeExpired)
	e.wantFail(e.build(spec{exp: at(66 * time.Minute)}), CodeInvalidPayload) // too far ahead: the Cloud never issues it
	e.wantFail(e.build(spec{exp: at(24 * time.Hour)}), CodeInvalidPayload)
	e.assertNothingWritten()
	e.wantApplied(e.build(spec{exp: at(-time.Minute), id: "33333333-3333-4333-8333-333333333341"}))     // inside the 2 min tolerance
	e.wantApplied(e.build(spec{exp: at(64 * time.Minute), id: "33333333-3333-4333-8333-333333333342"})) // inside 65 min
}

func TestReplayOfAnAppliedDeliveryDoesNotWriteAgain(t *testing.T) {
	e := newEnv(t)
	d := e.build(spec{})
	e.wantApplied(d)
	// from here ANY write of this delivery would fail: the replay must not try
	if err := os.Chmod(e.credDir, 0o500); err != nil {
		t.Fatal(err)
	}
	defer os.Chmod(e.credDir, 0o700)
	e.wantApplied(d)
	e.wantApplied(d)
	// ... and the content stays what it was, even if an operator edited another field since
	_ = os.Chmod(e.credDir, 0o700)
	if err := credfile.Merge(e.credPath, credfile.Creds{SNMPCommunity: "operador"}); err != nil {
		t.Fatal(err)
	}
	e.wantApplied(d)
	c, _, _ := credfile.Read(e.credPath)
	if c.SNMPCommunity != "operador" {
		t.Fatalf("a replay rewrote the file: %+v", c)
	}
}

func TestStaleDeliveryIsARollbackAndIsRefused(t *testing.T) {
	e := newEnv(t)
	newer := e.build(spec{id: "33333333-3333-4333-8333-333333333351", exp: e.exp, plaintext: `{"kind":"ssh_login","username":"novo","password":"novo-pw"}`})
	older := e.build(spec{id: "33333333-3333-4333-8333-333333333352", exp: e.exp - 300, plaintext: `{"kind":"ssh_login","username":"velho","password":"velho-pw"}`})
	e.wantApplied(newer)
	e.wantFail(older, CodeStale)
	c, _, _ := credfile.Read(e.credPath)
	if c.Username != "novo" {
		t.Fatalf("rolled back: %+v", c)
	}
	// the same expires_at is not older; another kind or another OLT has its own history
	e.wantApplied(e.build(spec{id: "33333333-3333-4333-8333-333333333353", exp: e.exp, plaintext: `{"kind":"ssh_login","username":"igual","password":"igual-pw"}`}))
	e.wantApplied(e.build(spec{id: "33333333-3333-4333-8333-333333333354", exp: e.exp - 300, olt: tOLT2}))
	e.wantApplied(e.build(spec{id: "33333333-3333-4333-8333-333333333355", exp: e.exp - 300, kind: config.KindSNMPCommunity}))
}

func TestInvalidPlaintextIsRefused(t *testing.T) {
	e := newEnv(t)
	long := func(n int) string { return strings.Repeat("a", n) }
	for name, pt := range map[string]string{
		"not json":      `nope`,
		"empty user":    `{"kind":"ssh_login","username":"","password":"x"}`,
		"empty pass":    `{"kind":"ssh_login","username":"u","password":""}`,
		"missing pass":  `{"kind":"ssh_login","username":"u"}`,
		"user too long": `{"kind":"ssh_login","username":"` + long(65) + `","password":"x"}`,
		"pass too long": `{"kind":"ssh_login","username":"u","password":"` + long(129) + `"}`,
		"newline":       `{"kind":"ssh_login","username":"u\n","password":"x"}`,
		"cr":            `{"kind":"ssh_login","username":"u","password":"x\r"}`,
		"nul":           `{"kind":"ssh_login","username":"u","password":"x\u0000y"}`,
		"unknown field": `{"kind":"ssh_login","username":"u","password":"x","extra":1}`,
		"wrong kind":    `{"kind":"snmp_community","community":"c"}`,
		"mixed":         `{"kind":"ssh_login","username":"u","password":"x","community":"c"}`,
		"trailing":      `{"kind":"ssh_login","username":"u","password":"x"} {}`,
	} {
		e.wantFail(e.build(spec{plaintext: pt}), CodeInvalidPayload)
		_ = name
	}
	for _, pt := range []string{`{"kind":"snmp_community","community":""}`, `{"kind":"snmp_community","community":"` + long(65) + `"}`, `{"kind":"snmp_community","community":"a\nb"}`, `{"kind":"snmp_community"}`} {
		e.wantFail(e.build(spec{kind: config.KindSNMPCommunity, plaintext: pt}), CodeInvalidPayload)
	}
	// the limits themselves are fine
	e.wantApplied(e.build(spec{plaintext: `{"kind":"ssh_login","username":"` + long(64) + `","password":"` + long(128) + `"}`}))
	e.assertNothingWrittenExcept(e.credPath)
}

func (e *env) assertNothingWrittenExcept(keep string) {
	e.t.Helper()
	for _, p := range []string{e.cred2, e.credSNMP} {
		if p != keep && e.fileExists(p) {
			e.t.Fatalf("wrote %s", p)
		}
	}
}

func TestMalformedEnvelopeFields(t *testing.T) {
	e := newEnv(t)
	good := e.build(spec{})
	for name, f := range map[string]func(d *gateway.SecretDelivery){
		"id":         func(d *gateway.SecretDelivery) { d.ID = "x" },
		"no lease":   func(d *gateway.SecretDelivery) { d.LeaseToken = "" },
		"no olt":     func(d *gateway.SecretDelivery) { d.OLTName = "" },
		"kind":       func(d *gateway.SecretDelivery) { d.Kind = "other" },
		"key_id":     func(d *gateway.SecretDelivery) { d.KeyID = "ZZ" },
		"exp null":   func(d *gateway.SecretDelivery) { d.ExpiresAt = json.RawMessage("null") },
		"exp float":  func(d *gateway.SecretDelivery) { d.ExpiresAt = json.RawMessage("1893456000.5") },
		"exp text":   func(d *gateway.SecretDelivery) { d.ExpiresAt = json.RawMessage(`"tomorrow"`) },
		"no blob":    func(d *gateway.SecretDelivery) { d.Sealed = "" },
		"blob junk":  func(d *gateway.SecretDelivery) { d.Sealed = "!!!!" },
		"blob huge":  func(d *gateway.SecretDelivery) { d.Sealed = strings.Repeat("A", 4*MaxBlobBytes+4) },
		"blob >2048": func(d *gateway.SecretDelivery) { d.Sealed = b64.EncodeToString(make([]byte, MaxBlobBytes+1)) },
	} {
		c := *good
		f(&c)
		if r := e.process(&c); r.Outcome != OutcomeFailed || r.Code != CodeInvalidPayload {
			t.Errorf("%s: %+v", name, r)
		}
	}
}

func TestExpiresAtAsRFC3339WholeSecondsIsAccepted(t *testing.T) {
	e := newEnv(t)
	d := e.build(spec{})
	d.ExpiresAt = json.RawMessage(`"` + time.Unix(e.exp, 0).UTC().Format(time.RFC3339) + `"`)
	e.wantApplied(d)
}

// --- crashes between the steps (4), (5), (6) --------------------------------------------------------------------------------------------------------------------------

func TestCrashAfterTheCredentialsWriteIsRepairedByTheRedelivery(t *testing.T) {
	e := newEnv(t)
	d := e.build(spec{})
	e.proc.AfterWrite = func() error { return ErrAborted } // the process dies between (4) and (5)
	if _, err := e.proc.Process(d); !errors.Is(err, ErrAborted) {
		t.Fatalf("err=%v", err)
	}
	if applied, _, _ := e.store.Check(tDelivery, tOLT, config.KindSSHLogin, e.exp); applied {
		t.Fatal("not recorded yet: the redelivery has to run the steps again")
	}
	before := e.readFile(e.credPath)
	e.proc.AfterWrite = nil
	e.wantApplied(d) // the Cloud handed it out again
	if e.readFile(e.credPath) != before {
		t.Fatal("the rewrite must be the SAME content (idempotent)")
	}
	if applied, _, _ := e.store.Check(tDelivery, tOLT, config.KindSSHLogin, e.exp); !applied {
		t.Fatal("now recorded")
	}
}

func TestCrashAfterTheRecordMakesTheRedeliveryAnswerAppliedWithoutWriting(t *testing.T) {
	e := newEnv(t)
	d := e.build(spec{})
	e.proc.AfterRecord = func() error { return ErrAborted } // dies between (5) and (6): nothing was reported
	if _, err := e.proc.Process(d); !errors.Is(err, ErrAborted) {
		t.Fatalf("err=%v", err)
	}
	e.proc.AfterRecord = nil
	if err := os.Chmod(e.credDir, 0o500); err != nil { // a write would now fail
		t.Fatal(err)
	}
	defer os.Chmod(e.credDir, 0o700)
	e.wantApplied(d)
}

func TestARestartLosesNothing(t *testing.T) {
	e := newEnv(t)
	d := e.build(spec{})
	e.wantApplied(d)
	// a brand new Processor and store over the same files (the Edge restarted)
	p2 := &Processor{TenantID: e.proc.TenantID, EdgeID: e.proc.EdgeID, Key: e.proc.Key, Pub: e.proc.Pub, Targets: e.proc.Targets, Now: e.proc.Now,
		Store: &AppliedStore{Path: e.store.Path, Now: e.store.Now}}
	if err := os.Chmod(e.credDir, 0o500); err != nil {
		t.Fatal(err)
	}
	defer os.Chmod(e.credDir, 0o700)
	r, err := p2.Process(d)
	if err != nil || r.Outcome != OutcomeApplied {
		t.Fatalf("%+v %v", r, err)
	}
}

// --- the stores ------------------------------------------------------------------------------------------------------------------------------------------------------

func TestMissingStoreIsEmptyAndCorruptOneIsMovedAside(t *testing.T) {
	e := newEnv(t)
	e.wantApplied(e.build(spec{})) // store absent: empty, works
	if err := os.WriteFile(e.store.Path, []byte("{not json"), 0o600); err != nil {
		t.Fatal(err)
	}
	e.wantApplied(e.build(spec{id: "33333333-3333-4333-8333-333333333361"}))
	ents, _ := filepath.Glob(e.store.Path + ".corrupt-*")
	if len(ents) != 1 {
		t.Fatalf("the corrupt store must be kept aside: %v", ents)
	}
	if !strings.Contains(e.logs.String(), "corrupt") {
		t.Fatal("a warning is expected")
	}
	// the new store is valid again
	if applied, _, err := e.store.Check("33333333-3333-4333-8333-333333333361", tOLT, config.KindSSHLogin, e.exp); err != nil || !applied {
		t.Fatalf("%v %v", applied, err)
	}
}

func TestUnreadableStoreFailsClosedWithoutWriting(t *testing.T) {
	e := newEnv(t)
	if err := os.WriteFile(e.store.Path, []byte(`{"v":1}`), 0o644); err != nil { // loose permissions: the Edge will not trust it
		t.Fatal(err)
	}
	_ = os.Chmod(e.store.Path, 0o644)
	e.wantFail(e.build(spec{}), CodeStateUnreadable)
	if e.fileExists(e.credPath) {
		t.Fatal("no credential may be written while the store cannot be trusted")
	}
}

func TestStoreWriteFailureAfterTheCredentialsWereWrittenIsReportedHonestly(t *testing.T) {
	e := newEnv(t)
	e.store.Path = filepath.Join(e.credDir, "sub", "applied.json") // parent does not exist and cannot be made: it is a FILE
	if err := os.WriteFile(filepath.Join(e.credDir, "sub"), []byte("x"), 0o600); err != nil {
		t.Fatal(err)
	}
	e.wantFail(e.build(spec{}), CodeStateUnreadable)
}

func TestStoreRetention(t *testing.T) {
	e := newEnv(t)
	base := time.Unix(1_700_000_000, 0)
	e.store.Now = func() time.Time { return base }
	for i := 0; i < MaxApplied+50; i++ {
		id := "00000000-0000-4000-8000-" + pad12(i)
		if err := e.store.Record(id, tOLT, config.KindSSHLogin, int64(i+1)); err != nil {
			t.Fatal(err)
		}
		e.store.Now = func() time.Time { return base.Add(time.Duration(i) * time.Second) }
	}
	f, err := e.store.load()
	if err != nil || len(f.Applied) != MaxApplied {
		t.Fatalf("len=%d err=%v", len(f.Applied), err)
	}
	if ok, _, _ := e.store.Check("00000000-0000-4000-8000-"+pad12(0), tOLT, config.KindSSHLogin, 1<<40); ok {
		t.Fatal("the oldest beyond the cap goes first")
	}
	if ok, _, _ := e.store.Check("00000000-0000-4000-8000-"+pad12(MaxApplied+49), tOLT, config.KindSSHLogin, 1<<40); !ok {
		t.Fatal("the newest is kept")
	}
	// older than 24 h goes even under the cap, and the per-OLT last expires_at stays (anti-rollback outlives the ids)
	e.store.Now = func() time.Time { return base.Add(48 * time.Hour) }
	if err := e.store.Record("00000000-0000-4000-8000-ffffffffffff", tOLT, config.KindSSHLogin, 5); err != nil {
		t.Fatal(err)
	}
	f, _ = e.store.load()
	if len(f.Applied) != 1 {
		t.Fatalf("older than 24h must be dropped: %d", len(f.Applied))
	}
	if _, stale, _ := e.store.Check("11111111-0000-4000-8000-000000000000", tOLT, config.KindSSHLogin, 10); !stale {
		t.Fatal("the last expires_at of the OLT+kind is kept")
	}
}

func pad12(i int) string {
	s := "000000000000"
	n := []byte(s)
	for p := 11; p >= 0 && i > 0; p-- {
		n[p] = "0123456789"[i%10]
		i /= 10
	}
	return string(n)
}

// --- the credentials file ---------------------------------------------------------------------------------------------------------------------------------------------

func TestUnwritableOrBrokenTargetFileIsWriteFailedAndKeepsWhatWasThere(t *testing.T) {
	e := newEnv(t)
	// an existing file that cannot be parsed is NOT overwritten (the merge could not keep what is inside)
	if err := os.WriteFile(e.credPath, []byte(`{"v":1,"password":"antigo-segredo"`), 0o600); err != nil {
		t.Fatal(err)
	}
	e.wantFail(e.build(spec{}), CodeWriteFailed)
	if e.readFile(e.credPath) != `{"v":1,"password":"antigo-segredo"` {
		t.Fatal("a broken file must be left as it was")
	}
	// directory not private
	_ = os.Remove(e.credPath)
	if err := os.Chmod(e.credDir, 0o755); err != nil {
		t.Fatal(err)
	}
	defer os.Chmod(e.credDir, 0o700)
	e.wantFail(e.build(spec{id: "33333333-3333-4333-8333-333333333371"}), CodeWriteFailed)
	if e.fileExists(e.credPath) {
		t.Fatal("nothing may be written into a loose directory")
	}
}

// --- nothing secret in logs, results or errors ----------------------------------------------------------------------------------------------------------------------

func TestNoSecretReachesLogsOrResults(t *testing.T) {
	e := newEnv(t)
	secrets := []string{tUser, tPass, tCommunity, "antigo-segredo"}
	var results []Result
	run := func(d *gateway.SecretDelivery) { results = append(results, e.process(d)) }
	// success, replay, every refusal path
	d := e.build(spec{})
	run(d)
	run(d)
	run(e.build(spec{kind: config.KindSNMPCommunity, id: "33333333-3333-4333-8333-333333333381"}))
	run(e.build(spec{id: "33333333-3333-4333-8333-333333333382", exp: e.exp - 3600}))
	run(e.build(spec{id: "33333333-3333-4333-8333-333333333383", sealOLT: tOLT2}))
	run(e.build(spec{id: "33333333-3333-4333-8333-333333333384", olt: "OUTRA"}))
	run(e.build(spec{id: "33333333-3333-4333-8333-333333333385", keyID: "0123456789abcdef"}))
	run(e.build(spec{id: "33333333-3333-4333-8333-333333333386", plaintext: `{"kind":"ssh_login","username":"` + tUser + `","password":"` + tPass + `\n"}`}))
	bad := e.build(spec{id: "33333333-3333-4333-8333-333333333387"})
	bad.Signature = "AAAA"
	run(bad)
	// a corrupt target file that CONTAINS a secret, and a corrupt store
	_ = os.WriteFile(e.cred2, []byte(`{"v":1,"password":"antigo-segredo"`), 0o600)
	run(e.build(spec{id: "33333333-3333-4333-8333-333333333388", olt: tOLT2}))
	_ = os.WriteFile(e.store.Path, []byte(`{"antigo-segredo`), 0o600)
	run(e.build(spec{id: "33333333-3333-4333-8333-333333333389"}))
	out := e.logs.String()
	for _, s := range secrets {
		if strings.Contains(out, s) {
			t.Fatalf("a secret reached the log: %q\n%s", s, out)
		}
		for _, r := range results {
			if strings.Contains(r.Code, s) || strings.Contains(r.Outcome, s) {
				t.Fatalf("a secret reached a result: %+v", r)
			}
		}
	}
	if out == "" {
		t.Fatal("the test captured nothing: it proves nothing")
	}
}

func TestNoTemporaryFileIsLeftAndNothingIsReadableByOthers(t *testing.T) {
	e := newEnv(t)
	for i := 0; i < 5; i++ {
		id := "33333333-3333-4333-8333-3333333334" + pad12(i)[10:]
		e.wantApplied(e.build(spec{id: id}))
	}
	ents, _ := os.ReadDir(e.credDir)
	for _, ent := range ents {
		fi, _ := ent.Info()
		if strings.HasPrefix(ent.Name(), ".fc-tmp-") {
			t.Fatalf("temporary file left behind: %s", ent.Name())
		}
		if fi.Mode().Perm()&0o077 != 0 {
			t.Fatalf("%s is readable by others: %v", ent.Name(), fi.Mode())
		}
	}
	// a leftover from a crash is removed by the next write
	left := filepath.Join(e.credDir, ".fc-tmp-deadbeef")
	if err := os.WriteFile(left, []byte("segredo-esquecido"), 0o600); err != nil {
		t.Fatal(err)
	}
	e.wantApplied(e.build(spec{id: "33333333-3333-4333-8333-333333333499"}))
	if e.fileExists(left) {
		t.Fatal("a leftover temporary file must be cleaned")
	}
}

func TestProcessUnderAPermissiveUmaskStillCreates0600(t *testing.T) {
	e := newEnv(t)
	old := setUmask(0)
	defer setUmask(old)
	e.wantApplied(e.build(spec{}))
	for _, p := range []string{e.credPath, e.credPath + ".lock", e.store.Path} {
		fi, err := os.Stat(p)
		if err != nil || fi.Mode().Perm() != 0o600 {
			t.Fatalf("%s: %v %v", p, fi, err)
		}
	}
}
