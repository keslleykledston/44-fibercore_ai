package main

import (
	"bytes"
	"encoding/base64"
	"io"
	"log/slog"
	"os"
	"path/filepath"
	"strings"
	"testing"

	"github.com/keslleykledston/44-fibercore_ai/agents/edge/internal/config"
	"github.com/keslleykledston/44-fibercore_ai/agents/edge/internal/credfile"
	"github.com/keslleykledston/44-fibercore_ai/agents/edge/internal/gateway"
	"github.com/keslleykledston/44-fibercore_ai/agents/edge/internal/managedolts"
)

var tHostKey = "SHA256:" + base64.RawStdEncoding.EncodeToString(bytes.Repeat([]byte{7}, 32))

const (
	tSecretUser = "usuario-secreto"
	tSecretPass = "senha-secreta-123"
	tSecretComm = "comunidade-secreta"
)

type mfx struct {
	t   *testing.T
	cfg string
	st  *managedolts.Store
}

func newMfx(t *testing.T, cidrs string) *mfx {
	t.Helper()
	dir := privDir(t)
	state := filepath.Join(dir, "managed")
	extra := `,"job_public_key":"` + pubKey + `","olt_secrets":{"seal_key_file":"` + filepath.Join(dir, "keys", "seal.json") + `"},` +
		`"managed_olts":{"state_dir":"` + state + `","allowed_cidrs":[` + cidrs + `],"max_olts":8}`
	f := &mfx{t: t, cfg: writeCfg(t, dir, extra), st: &managedolts.Store{Dir: state}}
	if err := f.st.Init(); err != nil {
		t.Fatal(err)
	}
	return f
}

func (f *mfx) add(name, addr string, n int) managedolts.Entry {
	f.t.Helper()
	e := managedolts.Entry{Name: name, Vendor: "huawei", Address: addr, Port: 22, Protocol: "ssh", Transport: "cli", SNMPPort: 161, HostKeySHA256: tHostKey, SSHMode: "exec",
		CloudID: "5a1f3c52-0b6e-4f0e-9a52-00000000000" + string(rune('0'+n))}
	if _, err := f.st.Upsert(e); err != nil {
		f.t.Fatal(err)
	}
	if err := credfile.Merge(f.st.CredsPath(name), credfile.Creds{Username: tSecretUser, Password: tSecretPass, SNMPCommunity: tSecretComm}); err != nil {
		f.t.Fatal(err)
	}
	return e
}

func (f *mfx) run(fn func(out, errb *bytes.Buffer) int) (int, string, string) {
	var out, errb bytes.Buffer
	c := fn(&out, &errb)
	return c, out.String(), errb.String()
}

func (f *mfx) list() (int, string, string) {
	return f.run(func(o, e *bytes.Buffer) int { return runManagedList([]string{"-config", f.cfg}, o, e) })
}

func (f *mfx) trust(name, typed string) (int, string, string) {
	return f.run(func(o, e *bytes.Buffer) int {
		return runManagedTrust([]string{"-config", f.cfg, name}, strings.NewReader(typed), o, e)
	})
}

func noSecrets(t *testing.T, what string, outs ...string) {
	t.Helper()
	for _, o := range outs {
		for _, s := range []string{tSecretUser, tSecretPass, tSecretComm} {
			if strings.Contains(o, s) {
				t.Fatalf("%s printed a credential: %q", what, s)
			}
		}
	}
}

func TestManagedListShowsStateAndProposedFingerprintAndNeverACredential(t *testing.T) {
	f := newMfx(t, `"10.20.0.0/16"`)
	code, out, errb := f.list()
	if code != 0 || !strings.Contains(out, "no managed OLTs") {
		t.Fatalf("%d %q %q", code, out, errb)
	}
	f.add("OLT-A", "10.20.1.5", 1)
	f.add("OLT-B", "10.30.1.5", 2) // outside the policy
	if err := f.st.Trust("OLT-A", mustEntry(t, f.st, "OLT-A").Digest()); err != nil {
		t.Fatal(err)
	}
	code, out, errb = f.list()
	if code != 0 {
		t.Fatalf("%d %q", code, errb)
	}
	for _, want := range []string{"OLT-A", "10.20.1.5:22", "huawei", "trusted", tHostKey, "OLT-B", "10.30.1.5:22", "awaiting_local_trust", "address_not_allowed"} {
		if !strings.Contains(out, want) {
			t.Errorf("missing %q in:\n%s", want, out)
		}
	}
	noSecrets(t, "managed-list", out, errb)
}

func mustEntry(t *testing.T, st *managedolts.Store, name string) managedolts.Entry {
	t.Helper()
	it, ok, err := st.Get(name)
	if err != nil || !ok {
		t.Fatal(err, ok)
	}
	return it.Entry
}

func TestManagedTrustRequiresTheFingerprintToBeRetypedAndRefusesAMismatch(t *testing.T) {
	f := newMfx(t, `"10.20.0.0/16"`)
	f.add("OLT-A", "10.20.1.5", 1)
	for name, typed := range map[string]string{
		"empty":        "\n",
		"nothing":      "",
		"wrong":        "SHA256:" + strings.Repeat("A", 43) + "\n",
		"lower case":   strings.ToLower(tHostKey) + "\n",
		"without hash": strings.TrimPrefix(tHostKey, "SHA256:") + "\n",
		"truncated":    tHostKey[:len(tHostKey)-1] + "\n",
		"extra":        tHostKey + "x\n",
		"yes":          "yes\n",
	} {
		code, out, errb := f.trust("OLT-A", typed)
		if code != 1 || !strings.Contains(errb, "nothing was trusted") && !strings.Contains(errb, "no input") {
			t.Errorf("%s: code=%d err=%q", name, code, errb)
		}
		noSecrets(t, name, out, errb)
		if mustItem(t, f.st, "OLT-A").Trusted {
			t.Fatalf("%s: trusted after a mismatch", name)
		}
	}
	if _, err := os.Stat(filepath.Join(f.st.Dir, managedolts.TrustFile)); err == nil {
		t.Fatal("no trust file may be written by a refusal")
	}
	// it shows what is being trusted (name, ip:port, vendor, proposed fingerprint) before asking
	code, out, errb := f.trust("OLT-A", tHostKey+"\n")
	if code != 0 {
		t.Fatalf("%d %q", code, errb)
	}
	for _, want := range []string{"OLT-A", "10.20.1.5:22", "huawei", tHostKey, "trusted"} {
		if !strings.Contains(out, want) {
			t.Errorf("missing %q in:\n%s", want, out)
		}
	}
	noSecrets(t, "managed-trust", out, errb)
	if !mustItem(t, f.st, "OLT-A").Trusted {
		t.Fatal("not trusted after a correct retype")
	}
	// a retyped value without the final newline (end of input) is accepted, and a second run says there is nothing to do
	if code, out, _ := f.trust("OLT-A", ""); code != 0 || !strings.Contains(out, "already trusted") {
		t.Fatalf("%d %q", code, out)
	}
}

func mustItem(t *testing.T, st *managedolts.Store, name string) managedolts.Item {
	t.Helper()
	it, ok, err := st.Get(name)
	if err != nil || !ok {
		t.Fatal(err, ok)
	}
	return it
}

func TestManagedTrustAcceptsTheLastLineWithoutANewlineAndFlagsAfterTheName(t *testing.T) {
	f := newMfx(t, `"10.20.0.0/16"`)
	f.add("OLT-A", "10.20.1.5", 1)
	var out, errb bytes.Buffer
	if c := runManagedTrust([]string{"OLT-A", "-config", f.cfg}, strings.NewReader(tHostKey), &out, &errb); c != 0 {
		t.Fatalf("%d %q", c, errb.String())
	}
	if !mustItem(t, f.st, "OLT-A").Trusted {
		t.Fatal("not trusted")
	}
}

func TestManagedTrustRefusesUnknownNamesAndOLTsOutsideThePolicy(t *testing.T) {
	f := newMfx(t, `"10.20.0.0/16"`)
	f.add("FORA", "10.30.1.5", 1)
	if code, _, errb := f.trust("NAO-EXISTE", tHostKey+"\n"); code != 1 || !strings.Contains(errb, "no managed OLT") {
		t.Fatalf("%d %q", code, errb)
	}
	code, _, errb := f.trust("FORA", tHostKey+"\n")
	if code != 1 || !strings.Contains(errb, "local policy") || mustItem(t, f.st, "FORA").Trusted {
		t.Fatalf("an OLT outside the policy must not be trusted: %d %q", code, errb)
	}
	var out, e2 bytes.Buffer
	if c := runManagedTrust([]string{"-config", f.cfg}, strings.NewReader(""), &out, &e2); c != 2 {
		t.Fatalf("no name: %d", c)
	}
	if c := runManagedTrust([]string{"-config", f.cfg, "a", "b"}, strings.NewReader(""), &out, &e2); c != 2 {
		t.Fatalf("two names: %d", c)
	}
}

// changing reads the retyped value only AFTER the Cloud changed the OLT: what was shown is not what is there anymore.
type changing struct {
	f    *mfx
	done bool
	r    io.Reader
}

func (c *changing) Read(p []byte) (int, error) {
	if !c.done {
		c.done = true
		e := mustEntry(c.f.t, c.f.st, "OLT-A")
		e.Address = "10.20.9.9"
		if _, err := c.f.st.Upsert(e); err != nil {
			c.f.t.Fatal(err)
		}
	}
	return c.r.Read(p)
}

func TestManagedTrustRefusesWhatChangedWhileTheOperatorWasConfirming(t *testing.T) {
	f := newMfx(t, `"10.20.0.0/16"`)
	f.add("OLT-A", "10.20.1.5", 1)
	var out, errb bytes.Buffer
	c := runManagedTrust([]string{"-config", f.cfg, "OLT-A"}, &changing{f: f, r: strings.NewReader(tHostKey + "\n")}, &out, &errb)
	if c != 1 || !strings.Contains(errb.String(), "changed in the Cloud") || mustItem(t, f.st, "OLT-A").Trusted {
		t.Fatalf("%d %q", c, errb.String())
	}
}

func TestManagedCommandsNeedTheSectionAndAValidConfig(t *testing.T) {
	dir := privDir(t)
	cfg := writeCfg(t, dir, `,"job_public_key":"`+pubKey+`","olt_secrets":{"seal_key_file":"`+filepath.Join(dir, "k", "seal.json")+`"}`)
	var out, errb bytes.Buffer
	if c := runManagedList([]string{"-config", cfg}, &out, &errb); c != 2 || !strings.Contains(errb.String(), "managed_olts") {
		t.Fatalf("%d %q", c, errb.String())
	}
	errb.Reset()
	if c := runManagedTrust([]string{"-config", cfg, "X"}, strings.NewReader(""), &out, &errb); c != 2 || !strings.Contains(errb.String(), "managed_olts") {
		t.Fatalf("%d %q", c, errb.String())
	}
	errb.Reset()
	if c := runManagedList([]string{"-config", filepath.Join(dir, "nope.json")}, &out, &errb); c != 2 {
		t.Fatalf("%d", c)
	}
}

func TestManagedListFailsClosedOnAnUnreadableRegistry(t *testing.T) {
	f := newMfx(t, `"10.20.0.0/16"`)
	f.add("OLT-A", "10.20.1.5", 1)
	os.Chmod(filepath.Join(f.st.Dir, managedolts.RegistryFile), 0o644)
	code, out, errb := f.list()
	if code != 1 || strings.Contains(out, "OLT-A") || !strings.Contains(errb, "unreadable") {
		t.Fatalf("%d %q %q", code, out, errb)
	}
}

func TestSetupSecretsWiresTheManagedOLTsOrRefusesALooseStateDir(t *testing.T) {
	f := newMfx(t, `"10.20.0.0/16"`)
	loaded, err := config.Load(f.cfg, "v")
	if err != nil {
		t.Fatal(err)
	}
	w, err := setupSecrets(loaded, gateway.New("https://gw.example.com", "c", "s", nil), slog.New(slog.NewTextHandler(io.Discard, nil)))
	if err != nil || w == nil || w.State == nil || w.Proc.Managed == nil || w.Proc.Managed.Policy == nil || w.Proc.Managed.Store.Dir != f.st.Dir {
		t.Fatalf("%+v %v", w, err)
	}
	// a state directory open to others: the Edge refuses to start (the same stance as for the seal key)
	if err := os.Chmod(f.st.Dir, 0o755); err != nil {
		t.Fatal(err)
	}
	if _, err := setupSecrets(loaded, gateway.New("https://gw.example.com", "c", "s", nil), slog.New(slog.NewTextHandler(io.Discard, nil))); err == nil {
		t.Fatal("a loose state_dir must refuse to start")
	}
	// without the section nothing managed is wired
	dir := privDir(t)
	plain := writeCfg(t, dir, `,"job_public_key":"`+pubKey+`","olt_secrets":{"seal_key_file":"`+filepath.Join(dir, "k", "seal.json")+`"}`)
	l2, _ := config.Load(plain, "v")
	w2, err := setupSecrets(l2, gateway.New("https://gw.example.com", "c", "s", nil), slog.New(slog.NewTextHandler(io.Discard, nil)))
	if err != nil || w2.State != nil || w2.Proc.Managed != nil {
		t.Fatalf("%+v %v", w2, err)
	}
}
