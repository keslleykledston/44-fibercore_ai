package oltsecrets

import (
	"bytes"
	"crypto/ed25519"
	"encoding/base64"
	"encoding/json"
	"fmt"
	"os"
	"path/filepath"
	"strconv"
	"strings"
	"testing"
	"time"

	"github.com/keslleykledston/44-fibercore_ai/agents/edge/internal/config"
	"github.com/keslleykledston/44-fibercore_ai/agents/edge/internal/credfile"
	"github.com/keslleykledston/44-fibercore_ai/agents/edge/internal/managedolts"
)

const (
	mName    = "OLT-GERENCIADA-01"
	mCloudID = "5a1f3c52-0b6e-4f0e-9a52-0a6f6a0c1111"
	mDelivID = "44444444-4444-4444-8444-444444444441"
	mDeliv2  = "44444444-4444-4444-8444-444444444442"
	mDeliv3  = "44444444-4444-4444-8444-444444444443"
)

func did(n int) string { return fmt.Sprintf("44444444-4444-4444-8444-%012d", n) }
func cid(n int) string { return fmt.Sprintf("5a1f3c52-0b6e-4f0e-9a52-%012d", n) }

var mHostKey = "SHA256:" + base64.RawStdEncoding.EncodeToString(bytes.Repeat([]byte{7}, 32))
var mHostKey2 = "SHA256:" + base64.RawStdEncoding.EncodeToString(bytes.Repeat([]byte{9}, 32))

func connBody(over map[string]any) string {
	m := map[string]any{
		"kind": "olt_connection", "action": "set", "address": "10.20.1.5", "port": 22, "protocol": "ssh", "vendor": "huawei", "transport": "cli",
		"snmp_port": 161, "host_key_sha256": mHostKey, "legacy_ssh": false, "ssh_mode": "exec", "cloud_id": mCloudID,
	}
	for k, v := range over {
		if v == nil {
			delete(m, k)
			continue
		}
		m[k] = v
	}
	b, _ := json.Marshal(m)
	return string(b)
}

// menv is the Edge fixture of the managed OLTs: the usual env plus a state directory, a policy and the static OLTs of the base fixture.
type menv struct {
	*env
	st      *managedolts.Store
	dir     string
	removed []string
}

func newManagedEnv(t *testing.T, mut func(*managedolts.Config)) *menv {
	t.Helper()
	e := newEnv(t)
	m := &menv{env: e, dir: privDir(t)}
	m.st = &managedolts.Store{Dir: m.dir, Now: func() time.Time { return e.now }}
	if err := m.st.Init(); err != nil {
		t.Fatal(err)
	}
	cfg := managedolts.Config{StateDir: m.dir, AllowedCIDRs: []string{"10.20.0.0/16"}, MaxOLTs: 5}
	if mut != nil {
		mut(&cfg)
	}
	pol, err := managedolts.NewPolicy(cfg)
	if err != nil {
		t.Fatal(err)
	}
	e.proc.Managed = &Managed{Policy: pol, Store: m.st, OnRemoved: func(id string) { m.removed = append(m.removed, id) },
		Static: []StaticOLT{{Name: tOLT, DeviceKey: "10.0.0.9", CloudID: "77777777-7777-4777-8777-777777777771"}, {Name: tOLT2, DeviceKey: "10.0.0.8"}, {Name: tSNMPOLT, DeviceKey: "10.0.0.7"}}}
	return m
}

func (m *menv) set(id string, over map[string]any) *deliveryResult {
	return m.send(id, mName, connBody(over))
}

type deliveryResult struct {
	Result
}

func (m *menv) send(id, olt, body string) *deliveryResult {
	m.t.Helper()
	return &deliveryResult{m.process(m.build(spec{id: id, olt: olt, kind: config.KindOLTConnection, plaintext: body}))}
}

func (m *menv) wantSet(id string, over map[string]any, code string) {
	m.t.Helper()
	r := m.set(id, over)
	if r.Outcome != OutcomeApplied || r.Code != code {
		m.t.Fatalf("want applied/%q, got %+v", code, r.Result)
	}
}

func (m *menv) wantRefused(id string, over map[string]any, code string) {
	m.t.Helper()
	if r := m.set(id, over); r.Outcome != OutcomeFailed || r.Code != code {
		m.t.Fatalf("want failed/%s for %v, got %+v", code, over, r.Result)
	}
}

func (m *menv) item() managedolts.Item {
	m.t.Helper()
	it, ok, err := m.st.Get(mName)
	if err != nil || !ok {
		m.t.Fatalf("not in the registry: %v %v", ok, err)
	}
	return it
}

func (m *menv) trust() {
	m.t.Helper()
	if err := m.st.Trust(mName, m.item().Entry.Digest()); err != nil {
		m.t.Fatal(err)
	}
}

func (m *menv) registryEmpty() bool {
	l, err := m.st.List()
	return err == nil && len(l) == 0
}

// --- the happy path and the states ----------------------------------------------------------------------------------------------------------------------------------

func TestManagedSetIsStoredAndAwaitsLocalTrust(t *testing.T) {
	m := newManagedEnv(t, nil)
	m.wantSet(mDelivID, nil, CodeAwaitingLocalTrust)
	it := m.item()
	if it.Trusted || it.State() != "awaiting_local_trust" {
		t.Fatalf("a delivery must never trust: %+v", it)
	}
	if it.Entry.Address != "10.20.1.5" || it.Entry.Port != 22 || it.Entry.Vendor != "huawei" || it.Entry.CloudID != mCloudID || it.Entry.SSHMode != "exec" || it.Entry.HostKeySHA256 != mHostKey {
		t.Fatalf("%+v", it.Entry)
	}
	for _, f := range []string{filepath.Join(m.dir, managedolts.RegistryFile)} {
		if fi, err := os.Stat(f); err != nil || fi.Mode().Perm() != 0o600 {
			t.Fatalf("%s: %v %v", f, fi, err)
		}
	}
	if m.fileExists(filepath.Join(m.dir, managedolts.TrustFile)) {
		t.Fatal("no trust file may exist before the local trust")
	}
	if applied, _, _ := m.store.Check(mDelivID, mName, config.KindOLTConnection, m.exp); !applied {
		t.Fatal("not recorded in the applied store")
	}
}

func TestManagedOptionalFieldsDefaultAndNullIsAbsent(t *testing.T) {
	m := newManagedEnv(t, nil)
	m.wantSet(mDelivID, map[string]any{"snmp_port": nil, "legacy_ssh": nil, "ssh_mode": nil}, CodeAwaitingLocalTrust)
	e := m.item().Entry
	if e.SNMPPort != 161 || e.LegacySSH || e.SSHMode != "exec" {
		t.Fatalf("%+v", e)
	}
	m.wantSet(mDeliv2, map[string]any{"snmp_port": json.RawMessage("null"), "ssh_mode": "shell"}, CodeAwaitingLocalTrust)
	if m.item().Entry.SSHMode != "shell" {
		t.Fatal("ssh_mode shell not stored")
	}
}

func TestManagedSetWithTheSameContentIsANoOpAndKeepsTheTrust(t *testing.T) {
	m := newManagedEnv(t, nil)
	m.wantSet(mDelivID, nil, CodeAwaitingLocalTrust)
	m.trust()
	regBefore := m.readFile(filepath.Join(m.dir, managedolts.RegistryFile))
	m.wantSet(mDeliv2, nil, "") // a new delivery with the same content: applied, already trusted => no code
	if !m.item().Trusted {
		t.Fatal("the same content must not clear the trust")
	}
	if m.readFile(filepath.Join(m.dir, managedolts.RegistryFile)) != regBefore {
		t.Fatal("the registry was rewritten by a no-op")
	}
}

// --- local policy ---------------------------------------------------------------------------------------------------------------------------------------------------

func TestManagedPolicyRefusals(t *testing.T) {
	m := newManagedEnv(t, func(c *managedolts.Config) {
		c.AllowedCIDRs = []string{"10.20.0.0/16", "127.0.0.0/8", "169.254.0.0/16", "224.0.0.0/8", "0.0.0.0/8"} // special addresses stay refused even inside an allowed CIDR
	})
	cases := []struct {
		name string
		over map[string]any
		code string
	}{
		{"outside the cidr", map[string]any{"address": "10.99.0.1"}, CodeAddressNotAllowed},
		{"public address", map[string]any{"address": "8.8.8.8"}, CodeAddressNotAllowed},
		{"loopback", map[string]any{"address": "127.0.0.1"}, CodeAddressNotAllowed},
		{"link-local (metadata)", map[string]any{"address": "169.254.169.254"}, CodeAddressNotAllowed},
		{"multicast", map[string]any{"address": "224.0.0.5"}, CodeAddressNotAllowed},
		{"unspecified", map[string]any{"address": "0.0.0.0"}, CodeAddressNotAllowed},
		{"this network", map[string]any{"address": "0.1.2.3"}, CodeAddressNotAllowed},
		{"ipv6 loopback", map[string]any{"address": "::1"}, CodeAddressNotAllowed},
		{"ipv6 outside", map[string]any{"address": "fd00::1"}, CodeAddressNotAllowed},
		{"port not allowed", map[string]any{"port": 2222}, CodePortNotAllowed},
		{"legacy not allowed", map[string]any{"legacy_ssh": true}, CodeLegacyNotAllowed},
		{"vendor not supported", map[string]any{"vendor": "mikrotik"}, CodeVendorNotSupported},
		{"zte over snmp is not supported", map[string]any{"vendor": "zte", "transport": "snmp", "snmp_port": 22}, CodeVendorNotSupported},
		{"telnet", map[string]any{"protocol": "telnet", "port": 23}, CodeProtocolNotSupported},
		{"telnet without a host key", map[string]any{"protocol": "telnet", "port": 23, "host_key_sha256": nil}, CodeProtocolNotSupported},
		{"protocol in capitals", map[string]any{"protocol": "SSH"}, CodeProtocolNotSupported},
		{"snmp port is the one dialled", map[string]any{"transport": "snmp", "snmp_port": 161}, CodePortNotAllowed},
	}
	for i, c := range cases {
		m.wantRefused(did(100+i), c.over, c.code)
	}
	if !m.registryEmpty() {
		t.Fatal("a refused delivery must leave nothing in the registry")
	}
}

func TestManagedAddressMustBeAnIPLiteral(t *testing.T) {
	m := newManagedEnv(t, nil)
	for i, a := range []string{"olt.example.com", "10.20.1.5:22", "10.20.1", "10.20.1.5/24", "fe80::1%eth0", "::ffff:10.20.1.5", "", " 10.20.1.5", "010.020.001.005"} {
		m.wantRefused(did(100+i), map[string]any{"address": a}, CodeInvalidPayload)
	}
	m.wantRefused(mDeliv2, map[string]any{"address": "10.020.1.5"}, CodeInvalidPayload) // leading zeros are not canonical
}

func TestManagedAllowedPortsAndVendorsFollowThePolicy(t *testing.T) {
	m := newManagedEnv(t, func(c *managedolts.Config) {
		c.AllowedPorts = []int{22, 161}
		c.AllowedVendors = []string{"huawei"}
		c.AllowLegacySSH = true
	})
	m.wantRefused(mDelivID, map[string]any{"vendor": "zte"}, CodeVendorNotAllowed)
	m.wantSet(mDeliv2, map[string]any{"transport": "snmp", "snmp_port": 161}, CodeAwaitingLocalTrust)
	m.wantSet(mDeliv3, map[string]any{"legacy_ssh": true, "port": 22}, CodeAwaitingLocalTrust)
	if !m.item().Entry.LegacySSH {
		t.Fatal("legacy allowed by the policy must be stored")
	}
}

func TestManagedMaximumCountsTheStaticOLTs(t *testing.T) {
	m := newManagedEnv(t, nil) // max 5, 3 static => 2 managed
	other := func(i int, name string) {
		m.t.Helper()
		id := did(100 + i)
		cloud := cid(100 + i)
		r := m.send(id, name, connBody(map[string]any{"address": "10.20.2." + strconv.Itoa(1+i), "cloud_id": cloud}))
		if r.Outcome != OutcomeApplied {
			m.t.Fatalf("%s: %+v", name, r.Result)
		}
	}
	other(0, "NOVA-1")
	other(1, "NOVA-2")
	r := m.send(mDelivID, "NOVA-3", connBody(map[string]any{"address": "10.20.2.9", "cloud_id": mCloudID}))
	if r.Outcome != OutcomeFailed || r.Code != CodeTooManyOLTs {
		t.Fatalf("%+v", r.Result)
	}
	// updating one that is already there does not need room
	r = m.send(mDeliv2, "NOVA-1", connBody(map[string]any{"address": "10.20.2.1", "cloud_id": cid(100), "ssh_mode": "shell"}))
	if r.Outcome != OutcomeApplied {
		t.Fatalf("%+v", r.Result)
	}
	// removing one frees a place
	m.send(mDeliv3, "NOVA-2", `{"kind":"olt_connection","action":"remove","cloud_id":"`+cid(101)+`"}`)
	r = m.send("44444444-4444-4444-8444-4444444444aa", "NOVA-3", connBody(map[string]any{"address": "10.20.2.9", "cloud_id": mCloudID}))
	if r.Outcome != OutcomeApplied {
		t.Fatalf("a freed place must be usable: %+v", r.Result)
	}
}

func TestManagedNameConflictsStaticWins(t *testing.T) {
	m := newManagedEnv(t, nil)
	for i, name := range []string{tOLT, tOLT2, tSNMPOLT} {
		r := m.send(did(100+i), name, connBody(nil))
		if r.Outcome != OutcomeFailed || r.Code != CodeNameConflict {
			t.Fatalf("%s: %+v", name, r.Result)
		}
		// not even a remove touches a static OLT
		r = m.send(did(200+i), name, `{"kind":"olt_connection","action":"remove","cloud_id":"`+mCloudID+`"}`)
		if r.Outcome != OutcomeFailed || r.Code != CodeNameConflict {
			t.Fatalf("remove %s: %+v", name, r.Result)
		}
	}
	// the same physical device or Cloud id as a static OLT, or as another managed one, is a conflict too
	m.wantRefused(mDeliv2, map[string]any{"address": "10.0.0.9"}, CodeAddressNotAllowed) // outside the CIDR first
	m2 := newManagedEnv(t, func(c *managedolts.Config) { c.AllowedCIDRs = []string{"10.0.0.0/8"} })
	m2.wantRefused(mDeliv2, map[string]any{"address": "10.0.0.9"}, CodeNameConflict)
	m2.wantRefused(mDeliv3, map[string]any{"cloud_id": "77777777-7777-4777-8777-777777777771"}, CodeNameConflict)
	m2.wantSet(mDelivID, nil, CodeAwaitingLocalTrust)
	if r := m2.send("44444444-4444-4444-8444-4444444444bb", "OUTRA", connBody(nil)); r.Code != CodeNameConflict {
		t.Fatalf("another managed OLT with the same device: %+v", r.Result)
	}
}

func TestManagedDisabledWithoutTheSection(t *testing.T) {
	e := newEnv(t) // no Managed
	r := e.process(e.build(spec{olt: mName, kind: config.KindOLTConnection, plaintext: connBody(nil)}))
	if r.Outcome != OutcomeFailed || r.Code != CodeManagedDisabled {
		t.Fatalf("%+v", r)
	}
	e.assertNothingWritten()
}

func TestManagedInvalidPayloads(t *testing.T) {
	m := newManagedEnv(t, nil)
	bad := map[string]string{
		"extra field":               connBody(map[string]any{"password": "x"}),
		"extra field on remove":     `{"kind":"olt_connection","action":"remove","cloud_id":"` + mCloudID + `","address":"10.20.1.5"}`,
		"remove without cloud_id":   `{"kind":"olt_connection","action":"remove"}`,
		"unknown action":            connBody(map[string]any{"action": "update"}),
		"wrong kind":                connBody(map[string]any{"kind": "ssh_login"}),
		"missing address":           connBody(map[string]any{"address": nil}),
		"missing host key":          connBody(map[string]any{"host_key_sha256": nil}),
		"missing vendor":            connBody(map[string]any{"vendor": nil}),
		"missing transport":         connBody(map[string]any{"transport": nil}),
		"missing cloud_id":          connBody(map[string]any{"cloud_id": nil}),
		"missing protocol":          connBody(map[string]any{"protocol": nil}),
		"port as a string":          connBody(map[string]any{"port": "22"}),
		"port as a fraction":        connBody(map[string]any{"port": 22.5}),
		"port 0":                    connBody(map[string]any{"port": 0}),
		"port 65536":                connBody(map[string]any{"port": 65536}),
		"snmp_port 0":               connBody(map[string]any{"snmp_port": 0}),
		"transport unknown":         connBody(map[string]any{"transport": "netconf"}),
		"ssh_mode unknown":          connBody(map[string]any{"ssh_mode": "telnet"}),
		"legacy as a string":        connBody(map[string]any{"legacy_ssh": "false"}),
		"fingerprint md5":           connBody(map[string]any{"host_key_sha256": "MD5:aa:bb"}),
		"fingerprint no prefix":     connBody(map[string]any{"host_key_sha256": strings.TrimPrefix(mHostKey, "SHA256:")}),
		"fingerprint short":         connBody(map[string]any{"host_key_sha256": mHostKey[:len(mHostKey)-1]}),
		"fingerprint padded":        connBody(map[string]any{"host_key_sha256": mHostKey + "="}),
		"fingerprint non canonical": connBody(map[string]any{"host_key_sha256": mHostKey[:len(mHostKey)-1] + "B"}),
		"cloud_id not a uuid":       connBody(map[string]any{"cloud_id": "OLT-1"}),
		"vendor with a space":       connBody(map[string]any{"vendor": "hua wei"}),
		"not json":                  `olt_connection`,
		"json array":                `[]`,
		"trailing data":             connBody(nil) + `{}`,
	}
	i := 0
	for name, body := range bad {
		i++
		r := m.send(did(400+i), mName, body)
		if r.Outcome != OutcomeFailed || r.Code != CodeInvalidPayload {
			t.Errorf("%s: want invalid_payload, got %+v", name, r.Result)
		}
	}
	if !m.registryEmpty() {
		t.Fatal("nothing may be stored")
	}
	// "fingerprint non canonical": the last base64 character carries 4 bits only; B in that place has extra bits set
}

// --- forged, replayed, wrong AAD, bad signature (the olt_connection kind) --------------------------------------------------------------------------------------------------

func TestManagedForgedDeliveriesAreRefused(t *testing.T) {
	m := newManagedEnv(t, nil)
	good := m.build(spec{id: mDelivID, olt: mName, kind: config.KindOLTConnection, plaintext: connBody(nil)})

	// signature of another key
	other := ed25519.NewKeyFromSeed(bytes.Repeat([]byte{1}, 32))
	blob, _ := b64.DecodeString(good.Sealed)
	aad := AAD(tTenant, tEdge, mName, config.KindOLTConnection, mDelivID, good.KeyID, m.exp)
	forged := *good
	forged.Signature = b64.EncodeToString(ed25519.Sign(other, SignedMessage(aad, blob)))
	m.wantFail(&forged, CodeBadSignature)

	// no signature at all
	unsigned := *good
	unsigned.Signature = ""
	m.wantFail(&unsigned, CodeBadSignature)

	// a delivery signed for another OLT name, replayed under this one
	swapped := *good
	swapped.OLTName = "OUTRA-OLT"
	m.wantFail(&swapped, CodeBadSignature)

	// signed for another kind: an ssh_login envelope cannot be turned into a connection
	asKind := *good
	asKind.Kind = config.KindSSHLogin
	m.wantFail(&asKind, CodeBadSignature)

	// AAD: the browser sealed for another OLT / delivery id / expiry than what the (honest) Cloud signs: the AEAD notices
	for name, s := range map[string]spec{
		"olt":  {sealOLT: "OUTRA-OLT"},
		"id":   {sealID: "99999999-9999-4999-8999-999999999999"},
		"exp":  {sealExp: m.exp + 1},
		"kind": {sealKind: config.KindSSHLogin},
	} {
		s.id, s.olt, s.kind, s.plaintext = mDelivID, mName, config.KindOLTConnection, connBody(nil)
		if r := m.process(m.build(s)); r.Outcome != OutcomeFailed || r.Code != CodeDecryptFailed {
			t.Errorf("AAD %s: %+v", name, r)
		}
	}
	// tampered ciphertext, re-signed by a careless Cloud: the tag catches it
	blob[len(blob)-2] ^= 1
	m.wantFail(m.sign(spec{id: mDelivID, olt: mName, kind: config.KindOLTConnection, keyID: good.KeyID, exp: m.exp}, blob), CodeDecryptFailed)
	// another key id, an expired delivery
	m.wantFail(m.build(spec{id: mDelivID, olt: mName, kind: config.KindOLTConnection, plaintext: connBody(nil), keyID: "0000000000000000"}), CodeBadKeyID)
	m.wantFail(m.build(spec{id: mDelivID, olt: mName, kind: config.KindOLTConnection, plaintext: connBody(nil), exp: m.now.Unix() - 3600}), CodeExpired)

	if !m.registryEmpty() || m.fileExists(m.store.Path) {
		t.Fatal("a forged delivery must leave nothing behind")
	}
	// the genuine one still works
	if r := m.process(good); r.Outcome != OutcomeApplied {
		t.Fatalf("%+v", r)
	}
}

func TestManagedReplayAndRollback(t *testing.T) {
	m := newManagedEnv(t, nil)
	d := m.build(spec{id: mDelivID, olt: mName, kind: config.KindOLTConnection, plaintext: connBody(nil)})
	if r := m.process(d); r.Code != CodeAwaitingLocalTrust {
		t.Fatalf("%+v", r)
	}
	m.trust()
	// the very same delivery again (replay or a lost result): applied, never written again, and the trust is left alone
	reg := m.readFile(filepath.Join(m.dir, managedolts.RegistryFile))
	if r := m.process(d); r.Outcome != OutcomeApplied || r.Code != "" {
		t.Fatalf("a replay of a trusted one: %+v", r)
	}
	if m.readFile(filepath.Join(m.dir, managedolts.RegistryFile)) != reg || !m.item().Trusted {
		t.Fatal("a replay changed state")
	}
	// a newer set changes the host key; an OLDER delivery (earlier expiry) cannot bring the old one back
	newer := m.build(spec{id: mDeliv2, olt: mName, kind: config.KindOLTConnection, exp: m.exp + 60, plaintext: connBody(map[string]any{"host_key_sha256": mHostKey2})})
	if r := m.process(newer); r.Code != CodeAwaitingLocalTrust {
		t.Fatalf("%+v", r)
	}
	older := m.build(spec{id: mDeliv3, olt: mName, kind: config.KindOLTConnection, exp: m.exp, plaintext: connBody(nil)})
	m.wantFail(older, CodeStale)
	if m.item().Entry.HostKeySHA256 != mHostKey2 {
		t.Fatal("the stale delivery changed the registry")
	}
}

// --- a fall between the registry and the applied store -----------------------------------------------------------------------------------------------------------------

func TestManagedCrashBetweenRegistryAndStoreIsIdempotent(t *testing.T) {
	m := newManagedEnv(t, nil)
	d := m.build(spec{id: mDelivID, olt: mName, kind: config.KindOLTConnection, plaintext: connBody(nil)})
	m.proc.AfterWrite = func() error { return ErrAborted }
	if _, err := m.proc.Process(d); err != ErrAborted {
		t.Fatalf("err=%v", err)
	}
	if applied, _, _ := m.store.Check(mDelivID, mName, config.KindOLTConnection, m.exp); applied {
		t.Fatal("the store must not know it yet")
	}
	if m.item().Trusted { // the registry was written, still awaiting
		t.Fatal("trusted after a crash?")
	}
	reg := m.readFile(filepath.Join(m.dir, managedolts.RegistryFile))
	m.proc.AfterWrite = nil
	if r := m.process(d); r.Outcome != OutcomeApplied || r.Code != CodeAwaitingLocalTrust { // the redelivery writes the SAME content
		t.Fatalf("%+v", r)
	}
	if m.readFile(filepath.Join(m.dir, managedolts.RegistryFile)) != reg {
		t.Fatal("the redelivery changed the registry")
	}
	// and a fall between the store and the result: the redelivery lands in step 3
	m.proc.AfterRecord = func() error { return ErrAborted }
	d2 := m.build(spec{id: mDeliv2, olt: mName, kind: config.KindOLTConnection, plaintext: connBody(map[string]any{"ssh_mode": "shell"})})
	if _, err := m.proc.Process(d2); err != ErrAborted {
		t.Fatalf("err=%v", err)
	}
	m.proc.AfterRecord = nil
	if r := m.process(d2); r.Outcome != OutcomeApplied || r.Code != CodeAwaitingLocalTrust || m.item().Entry.SSHMode != "shell" {
		t.Fatalf("%+v", r)
	}
}

func TestManagedCrashAfterTheRegistryChangeNeverLeavesTheOldTrustActive(t *testing.T) {
	m := newManagedEnv(t, nil)
	m.wantSet(mDelivID, nil, CodeAwaitingLocalTrust)
	m.trust()
	// the new address reaches the registry, the process dies before anything else: the old trust digest no longer matches
	m.proc.AfterWrite = func() error { return ErrAborted }
	d := m.build(spec{id: mDeliv2, olt: mName, kind: config.KindOLTConnection, plaintext: connBody(map[string]any{"address": "10.20.9.9"})})
	if _, err := m.proc.Process(d); err != ErrAborted {
		t.Fatalf("err=%v", err)
	}
	if m.item().Trusted {
		t.Fatal("a changed address must never stay trusted")
	}
}

// --- the trust --------------------------------------------------------------------------------------------------------------------------------------------------------

func TestManagedAnyConnectionFieldChangeZeroesTheTrust(t *testing.T) {
	changes := map[string]map[string]any{
		"address":         {"address": "10.20.1.6"},
		"port":            {"port": 2222},
		"transport":       {"transport": "snmp", "snmp_port": 22},
		"host_key_sha256": {"host_key_sha256": mHostKey2},
		"snmp_port":       {"snmp_port": 162},
		"ssh_mode":        {"ssh_mode": "shell"},
		"legacy_ssh":      {"legacy_ssh": true},
		"vendor":          {"vendor": "zte"}, // picks the driver, i.e. the commands that run (Codex r1)
	}
	i := 0
	for field, over := range changes {
		i++
		m := newManagedEnv(t, func(c *managedolts.Config) { c.AllowedPorts = []int{22, 2222, 162}; c.AllowLegacySSH = true })
		m.wantSet(mDelivID, nil, CodeAwaitingLocalTrust)
		m.trust()
		if !m.item().Trusted {
			t.Fatalf("%s: setup", field)
		}
		m.wantSet(mDeliv2, over, CodeAwaitingLocalTrust)
		if m.item().Trusted {
			t.Errorf("%s: the trust survived a change", field)
		}
		// going back to the old value does NOT bring the old trust back
		m.wantSet(mDeliv3, nil, CodeAwaitingLocalTrust)
		if m.item().Trusted {
			t.Errorf("%s: the trust came back with the old value", field)
		}
		if m.fileExists(filepath.Join(m.dir, managedolts.TrustFile)) && strings.Contains(m.readFile(filepath.Join(m.dir, managedolts.TrustFile)), mName) {
			t.Errorf("%s: the trust entry was not dropped", field)
		}
	}
	// the Cloud id alone never changes where the Edge connects nor what it runs
	m := newManagedEnv(t, nil)
	m.wantSet(mDelivID, nil, CodeAwaitingLocalTrust)
	m.trust()
	m.wantSet(mDeliv2, map[string]any{"cloud_id": "5a1f3c52-0b6e-4f0e-9a52-0a6f6a0c2222"}, "")
	if !m.item().Trusted {
		t.Fatal("vendor/cloud_id must not clear the trust")
	}
}

func TestManagedHandEditedRegistryActivatesNothing(t *testing.T) {
	m := newManagedEnv(t, nil)
	m.wantSet(mDelivID, nil, CodeAwaitingLocalTrust)
	reg := filepath.Join(m.dir, managedolts.RegistryFile)
	var f struct {
		V    int                 `json:"v"`
		OLTs []managedolts.Entry `json:"olts"`
	}
	if err := json.Unmarshal([]byte(m.readFile(reg)), &f); err != nil {
		t.Fatal(err)
	}
	// 1. adding a perfectly valid entry by hand: listed, never trusted
	extra := f.OLTs[0]
	extra.Name, extra.Address, extra.CloudID = "MANUAL", "10.20.7.7", "5a1f3c52-0b6e-4f0e-9a52-0a6f6a0c3333"
	f.OLTs = append(f.OLTs, extra)
	b, _ := json.Marshal(f)
	if err := os.WriteFile(reg, b, 0o600); err != nil {
		t.Fatal(err)
	}
	l, err := m.st.List()
	if err != nil || len(l) != 2 || l[0].Trusted || l[1].Trusted {
		t.Fatalf("%+v %v", l, err)
	}
	// 2. a trusted entry whose address is edited by hand is no longer trusted
	m.trust()
	f.OLTs[0].Address = "10.20.1.99"
	b, _ = json.Marshal(f)
	os.WriteFile(reg, b, 0o600)
	if m.item().Trusted {
		t.Fatal("a hand-edited address must not stay trusted")
	}
	// 3. so is an edit of the host key, the port, the transport...
	f.OLTs[0].Address = "10.20.1.5"
	f.OLTs[0].HostKeySHA256 = mHostKey2
	b, _ = json.Marshal(f)
	os.WriteFile(reg, b, 0o600)
	if m.item().Trusted {
		t.Fatal("a hand-edited host key must not stay trusted")
	}
	// 4. putting everything back, the OLT is the one that was trusted again (the digest is the whole truth)
	f.OLTs[0].HostKeySHA256 = mHostKey
	b, _ = json.Marshal(f)
	os.WriteFile(reg, b, 0o600)
	if !m.item().Trusted {
		t.Fatal("the original, trusted content is trusted")
	}
	// 5. a hand-written trust digest for another entry does not trust this one
	tr := filepath.Join(m.dir, managedolts.TrustFile)
	os.WriteFile(tr, []byte(`{"v":1,"trusted":[{"name":"MANUAL","digest":"`+strings.Repeat("0", 64)+`","at":1}]}`), 0o600)
	l, _ = m.st.List()
	if l[0].Trusted || l[1].Trusted {
		t.Fatalf("%+v", l)
	}
	// 6. a loose or invalid file is refused (fail closed), never half-read
	os.Chmod(reg, 0o644)
	if _, err := m.st.List(); err == nil {
		t.Fatal("a registry readable by others must be refused")
	}
	os.Chmod(reg, 0o600)
	os.WriteFile(reg, []byte(`{"v":1,"olts":[{"name":"X"}]}`), 0o600)
	if _, err := m.st.List(); err == nil {
		t.Fatal("an invalid entry must refuse the whole registry")
	}
}

// --- remove -----------------------------------------------------------------------------------------------------------------------------------------------------------

func TestManagedRemoveDeletesRegistryTrustAndCredentials(t *testing.T) {
	m := newManagedEnv(t, nil)
	m.wantSet(mDelivID, nil, CodeAwaitingLocalTrust)
	m.trust()
	if r := m.process(m.build(spec{id: mDeliv2, olt: mName})); r.Outcome != OutcomeApplied { // ssh_login into the automatic file
		t.Fatalf("%+v", r)
	}
	creds := m.st.CredsPath(mName)
	if !m.fileExists(creds) {
		t.Fatal("setup: no credentials file")
	}
	rm := `{"kind":"olt_connection","action":"remove","cloud_id":"` + mCloudID + `"}`
	r := m.send(mDeliv3, mName, rm)
	if r.Outcome != OutcomeApplied || r.Code != "" {
		t.Fatalf("%+v", r.Result)
	}
	if !m.registryEmpty() || m.fileExists(creds) || m.fileExists(creds+".lock") {
		t.Fatal("registry and credentials must be gone")
	}
	if tr := m.readFile(filepath.Join(m.dir, managedolts.TrustFile)); strings.Contains(tr, mName) {
		t.Fatalf("trust not dropped: %s", tr)
	}
	if len(m.removed) != 1 || m.removed[0] != mCloudID {
		t.Fatalf("OnRemoved: %v", m.removed)
	}
	// a remove of something that is not there is applied (idempotent), and a set after a remove starts from nothing: untrusted, no old credentials
	if r := m.send("44444444-4444-4444-8444-4444444444cc", mName, rm); r.Outcome != OutcomeApplied {
		t.Fatalf("%+v", r.Result)
	}
	m.wantSet("44444444-4444-4444-8444-4444444444dd", nil, CodeAwaitingLocalTrust)
	if m.item().Trusted || m.fileExists(creds) {
		t.Fatal("a re-added OLT must start untrusted and without credentials")
	}
}

func TestManagedRemoveIsFinishedByARedeliveryAfterACrash(t *testing.T) {
	m := newManagedEnv(t, nil)
	m.wantSet(mDelivID, nil, CodeAwaitingLocalTrust)
	m.process(m.build(spec{id: mDeliv2, olt: mName}))
	rm := m.build(spec{id: mDeliv3, olt: mName, kind: config.KindOLTConnection, plaintext: `{"kind":"olt_connection","action":"remove","cloud_id":"` + mCloudID + `"}`})
	m.proc.AfterWrite = func() error { return ErrAborted }
	if _, err := m.proc.Process(rm); err != ErrAborted {
		t.Fatal(err)
	}
	m.proc.AfterWrite = nil
	if r := m.process(rm); r.Outcome != OutcomeApplied || r.Code != "" || !m.registryEmpty() {
		t.Fatalf("%+v", r)
	}
}

// --- credentials for a managed OLT ------------------------------------------------------------------------------------------------------------------------------------

func TestManagedCredentialsAreStoredEvenBeforeTheTrustAndNeedARegistryEntry(t *testing.T) {
	m := newManagedEnv(t, nil)
	// no registry entry, no static credentials_file: target_not_configured
	m.wantFail(m.build(spec{id: mDelivID, olt: mName}), CodeTargetNotConfigured)
	m.wantFail(m.build(spec{id: mDelivID, olt: mName, kind: config.KindSNMPCommunity}), CodeTargetNotConfigured)
	if m.fileExists(m.st.CredsPath(mName)) {
		t.Fatal("nothing may be written for an unknown OLT")
	}
	m.wantSet(mDeliv2, nil, CodeAwaitingLocalTrust)
	// awaiting trust: the login is stored (never used before the trust), and the result is a plain applied
	m.wantApplied(m.build(spec{id: mDeliv3, olt: mName}))
	c, found, err := credfile.Read(m.st.CredsPath(mName))
	if err != nil || !found || c.Username != tUser || c.Password != tPass {
		t.Fatalf("%+v %v %v", c, found, err)
	}
	if fi, _ := os.Stat(m.st.CredsPath(mName)); fi.Mode().Perm() != 0o600 {
		t.Fatalf("mode %v", fi.Mode().Perm())
	}
	// an SNMP community for a CLI entry is something it would never use
	m.wantFail(m.build(spec{id: "44444444-4444-4444-8444-4444444444ee", olt: mName, kind: config.KindSNMPCommunity}), CodeTargetNotConfigured)
	// ...and an SNMP entry takes the community, not a login
	m.wantSet("44444444-4444-4444-8444-4444444444ef", map[string]any{"transport": "snmp", "port": 22, "snmp_port": 22}, CodeAwaitingLocalTrust)
	m.wantFail(m.build(spec{id: "44444444-4444-4444-8444-4444444444f0", olt: mName}), CodeTargetNotConfigured)
	m.wantApplied(m.build(spec{id: "44444444-4444-4444-8444-4444444444f1", olt: mName, kind: config.KindSNMPCommunity}))
	// a static OLT without credentials_file does not take credentials from the Cloud either, whatever the registry says
	delete(m.proc.Targets, tOLT2)
	m.wantFail(m.build(spec{id: "44444444-4444-4444-8444-4444444444f2", olt: tOLT2}), CodeTargetNotConfigured)
}

func TestManagedOLTNamesNeverReachAPathAsTheyAre(t *testing.T) {
	m := newManagedEnv(t, func(c *managedolts.Config) { c.MaxOLTs = 64 })
	for i, name := range []string{"../../etc/passwd", "a/b", "OLT Centro Ação", ".hidden", ".fc-tmp-x", strings.Repeat("x", 120), "a.json", "x\\y"} {
		id := did(100 + i)
		cloud := cid(100 + i)
		r := m.send(id, name, connBody(map[string]any{"address": "10.20.3." + strconv.Itoa(1+i), "cloud_id": cloud}))
		if r.Outcome != OutcomeApplied {
			t.Fatalf("%q: %+v", name, r.Result)
		}
		p := m.st.CredsPath(name)
		if filepath.Dir(p) != filepath.Join(m.dir, "creds") || strings.HasPrefix(filepath.Base(p), ".") {
			t.Fatalf("%q -> %s", name, p)
		}
		m.wantApplied(m.build(spec{id: did(300 + i), olt: name}))
		if !m.fileExists(p) {
			t.Fatalf("%q: no credentials file at %s", name, p)
		}
	}
	// ordinary names keep the human name; two distinct odd names never share a file
	if filepath.Base(m.st.CredsPath("OLT-1")) != "OLT-1.json" || m.st.CredsPath("a b") == m.st.CredsPath("a_b") || m.st.CredsPath("a b") == m.st.CredsPath("a  b") {
		t.Fatal("file names")
	}
}

func TestManagedNothingSecretReachesLogsOrResults(t *testing.T) {
	m := newManagedEnv(t, nil)
	m.wantSet(mDelivID, nil, CodeAwaitingLocalTrust)
	m.wantApplied(m.build(spec{id: mDeliv2, olt: mName}))
	m.wantFail(m.build(spec{id: mDeliv3, olt: mName, kind: config.KindSNMPCommunity}), CodeTargetNotConfigured)
	out := m.logs.String()
	for _, secret := range []string{tUser, tPass, tCommunity} {
		if strings.Contains(out, secret) {
			t.Fatalf("a secret reached the log: %q", secret)
		}
	}
}

func TestManagedNamesWithControlCharactersAreRefused(t *testing.T) {
	m := newManagedEnv(t, nil)
	for i, name := range []string{"OLT\nFALSA: trusted", "OLT\x1b[2J", "OLT\u202etrust", " espaco", "tab\t"} {
		r := m.send(did(500+i), name, connBody(nil))
		if r.Outcome != OutcomeFailed || r.Code != CodeInvalidPayload {
			t.Errorf("%q: %+v", name, r.Result)
		}
	}
	if !m.registryEmpty() {
		t.Fatal("nothing may be stored")
	}
}
