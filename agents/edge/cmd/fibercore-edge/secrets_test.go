package main

import (
	"bytes"
	"io"
	"log/slog"
	"os"
	"path/filepath"
	"strings"
	"testing"

	"github.com/keslleykledston/44-fibercore_ai/agents/edge/internal/config"
	"github.com/keslleykledston/44-fibercore_ai/agents/edge/internal/gateway"
	"github.com/keslleykledston/44-fibercore_ai/agents/edge/internal/oltsecrets"
)

const (
	uid    = "0b8d5a0e-1111-4222-8333-444455556666"
	pubKey = "KayDvQ3+uJw0aLSMrrx7a5oYPCgK2TLtczJkZ4mZ0BE="
)

func writeCfg(t *testing.T, dir, extra string) string {
	t.Helper()
	body := `{"gateway_url":"https://gw.example.com","edge_id":"` + uid + `","tenant_id":"` + uid + `","client_id":"` + uid +
		`","secret_file":"/s","queue_path":"` + filepath.Join(dir, "q.db") + `","connector_id":"c"` + extra + `}`
	p := filepath.Join(dir, "config.json")
	if err := os.WriteFile(p, []byte(body), 0o600); err != nil {
		t.Fatal(err)
	}
	return p
}

func privDir(t *testing.T) string {
	d := filepath.Join(t.TempDir(), "d")
	if err := os.Mkdir(d, 0o700); err != nil {
		t.Fatal(err)
	}
	return d
}

func TestSealFingerprintPrintsTheFingerprintAndNeverTheSecret(t *testing.T) {
	dir := privDir(t)
	keyPath := filepath.Join(dir, "keys", "seal.json")
	cfg := writeCfg(t, dir, `,"job_public_key":"`+pubKey+`","olt_secrets":{"seal_key_file":"`+keyPath+`"}`)
	var out, errb bytes.Buffer
	// before the first start there is no key: the command never creates one
	if code := runSealFingerprint([]string{"-config", cfg}, &out, &errb); code == 0 || out.Len() != 0 {
		t.Fatalf("code=%d out=%q", code, out.String())
	}
	if _, err := os.Stat(keyPath); err == nil {
		t.Fatal("seal-fingerprint must not generate the key")
	}
	// the Edge start generates it
	loaded, err := config.Load(cfg, "v")
	if err != nil {
		t.Fatal(err)
	}
	w, err := setupSecrets(loaded, gateway.New("https://gw.example.com", "c", "s", nil), slog.New(slog.NewTextHandler(io.Discard, nil)))
	if err != nil || w == nil {
		t.Fatalf("%v %v", w, err)
	}
	out.Reset()
	errb.Reset()
	if code := runSealFingerprint([]string{"-config", cfg}, &out, &errb); code != 0 {
		t.Fatalf("code=%d err=%s", code, errb.String())
	}
	k, _ := oltsecrets.LoadKey(keyPath)
	want := "fingerprint: " + k.Fingerprint() + "\nkey_id: " + k.KeyID() + "\npublic_key: " + k.PublicB64() + "\n"
	if out.String() != want {
		t.Fatalf("%q != %q", out.String(), want)
	}
	raw, _ := os.ReadFile(keyPath)
	if strings.Contains(out.String()+errb.String(), strings.TrimSpace(string(raw))) {
		t.Fatal("the key file content must never be printed")
	}
}

func TestSealFingerprintWithoutTheSection(t *testing.T) {
	dir := privDir(t)
	cfg := writeCfg(t, dir, ``)
	var out, errb bytes.Buffer
	if code := runSealFingerprint([]string{"-config", cfg}, &out, &errb); code != 2 || !strings.Contains(errb.String(), "olt_secrets") {
		t.Fatalf("code=%d err=%q", code, errb.String())
	}
}

func TestSetupSecretsIsOffWithoutTheSection(t *testing.T) {
	dir := privDir(t)
	loaded, err := config.Load(writeCfg(t, dir, ``), "v")
	if err != nil {
		t.Fatal(err)
	}
	if w, err := setupSecrets(loaded, nil, slog.New(slog.NewTextHandler(io.Discard, nil))); w != nil || err != nil {
		t.Fatalf("the whole feature is off without the section: %v %v", w, err)
	}
}

func TestSetupSecretsRefusesABrokenKeyInsteadOfMakingANewOne(t *testing.T) {
	dir := privDir(t)
	keyPath := filepath.Join(dir, "seal.json")
	if err := os.WriteFile(keyPath, []byte("garbage"), 0o600); err != nil {
		t.Fatal(err)
	}
	loaded, err := config.Load(writeCfg(t, dir, `,"job_public_key":"`+pubKey+`","olt_secrets":{"seal_key_file":"`+keyPath+`"}`), "v")
	if err != nil {
		t.Fatal(err)
	}
	if _, err := setupSecrets(loaded, nil, slog.New(slog.NewTextHandler(io.Discard, nil))); err == nil {
		t.Fatal("a broken key must stop the start")
	}
	if b, _ := os.ReadFile(keyPath); string(b) != "garbage" {
		t.Fatal("a broken key file must be left alone")
	}
}
