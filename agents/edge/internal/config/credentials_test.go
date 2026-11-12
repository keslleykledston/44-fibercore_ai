package config

import (
	"os"
	"path/filepath"
	"strings"
	"testing"
)

const goodKey = "KayDvQ3+uJw0aLSMrrx7a5oYPCgK2TLtczJkZ4mZ0BE=" // 32 bytes, std base64 (the format of job_public_key)

func secretsCfg(extra string) string {
	return good(`,"job_public_key":"` + goodKey + `","olt_secrets":{"seal_key_file":"/var/lib/fibercore-edge/keys/seal.json"}` + extra)
}

func oltJSON(extra string) string {
	return `{"name":"A","vendor":"huawei","address":"10.0.0.9:22","host_key_sha256":"SHA256:abc","pon_ports":["0/1/0"]` + extra + `}`
}

func TestOldConfigsLoadExactlyAsBefore(t *testing.T) {
	cfg, err := Load(write(t, 0o600, good(`,"allowlist":["10.0.0.9:22"],"olts":[`+oltJSON(`,"username":"ro","secret_file":"/s"`)+`]`)), "v")
	if err != nil {
		t.Fatal(err)
	}
	if cfg.OLTSecrets != nil || cfg.OLTs[0].CredentialsFile != "" || cfg.OLTs[0].AcceptsKind(KindSSHLogin) {
		t.Fatal("the feature must be entirely off without the section")
	}
}

func TestSharedStaticSecretFilesStillLoad(t *testing.T) {
	// two OLTs sharing ONE password file and the service secret_file being the same too: legitimate in old configs
	two := `,"allowlist":["10.0.0.9:22","10.0.0.8:22"],"olts":[` +
		oltJSON(`,"username":"ro","secret_file":"/s"`) + `,` +
		strings.Replace(strings.Replace(oltJSON(`,"username":"ro","secret_file":"/s"`), `"A"`, `"B"`, 1), "10.0.0.9", "10.0.0.8", 1) + `]`
	if _, err := Load(write(t, 0o600, good(two)), "v"); err != nil {
		t.Fatalf("old shared secret files must keep loading: %v", err)
	}
}

func TestCredentialsFileRequiresTheSection(t *testing.T) {
	_, err := Load(write(t, 0o600, good(`,"allowlist":["10.0.0.9:22"],"olts":[`+oltJSON(`,"credentials_file":"/var/lib/fibercore-edge/cred/a.json"`)+`]`)), "v")
	if err == nil || !strings.Contains(err.Error(), "olt_secrets") {
		t.Fatalf("err=%v", err)
	}
}

func TestSectionNeedsKeyFileAndPinnedSigningKey(t *testing.T) {
	cases := map[string]string{
		"no seal key file":   good(`,"job_public_key":"` + goodKey + `","olt_secrets":{}`),
		"relative key file":  good(`,"job_public_key":"` + goodKey + `","olt_secrets":{"seal_key_file":"seal.json"}`),
		"no job_public_key":  good(`,"olt_secrets":{"seal_key_file":"/k/seal.json"}`),
		"short job key":      good(`,"job_public_key":"AAAA","olt_secrets":{"seal_key_file":"/k/seal.json"}`),
		"poll too fast":      good(`,"job_public_key":"` + goodKey + `","olt_secrets":{"seal_key_file":"/k/seal.json","poll_seconds":5}`),
		"poll too slow":      good(`,"job_public_key":"` + goodKey + `","olt_secrets":{"seal_key_file":"/k/seal.json","poll_seconds":900}`),
		"relative applied":   good(`,"job_public_key":"` + goodKey + `","olt_secrets":{"seal_key_file":"/k/seal.json","applied_file":"a.json"}`),
		"unknown field":      good(`,"job_public_key":"` + goodKey + `","olt_secrets":{"seal_key_file":"/k/seal.json","x":1}`),
		"key file = secret":  good(`,"job_public_key":"` + goodKey + `","olt_secrets":{"seal_key_file":"/s"}`),
		"applied = key file": good(`,"job_public_key":"` + goodKey + `","olt_secrets":{"seal_key_file":"/k/seal.json","applied_file":"/k/seal.json"}`),
	}
	for name, body := range cases {
		if _, err := Load(write(t, 0o600, body), "v"); err == nil {
			t.Errorf("%s: expected an error", name)
		}
	}
	if cfg, err := Load(write(t, 0o600, secretsCfg(`,"allowlist":[]`)), "v"); err != nil || cfg.OLTSecrets.Poll().Seconds() != 30 {
		t.Fatalf("a section alone is valid (OLTs may be enabled later): %v", err)
	}
}

func TestCredentialsFileRelaxesTheStaticSourcesButNotTheRest(t *testing.T) {
	ok := func(olt string) error {
		_, err := Load(write(t, 0o600, secretsCfg(`,"allowlist":["10.0.0.9:22","10.0.0.9:161"],"olts":[`+olt+`]`)), "v")
		return err
	}
	cred := `,"credentials_file":"/var/lib/fibercore-edge/cred/a.json"`
	// CLI: no username, no secret_file at all
	if err := ok(oltJSON(cred)); err != nil {
		t.Fatalf("login only from the credentials file: %v", err)
	}
	// without the credentials file the old rule stands
	if err := ok(oltJSON(`,"username":"ro"`)); err == nil {
		t.Fatal("username without secret_file and without credentials_file must still be refused")
	}
	// SNMP transport: community only from the file
	snmp := `{"name":"S","vendor":"huawei","transport":"snmp","snmp_address":"10.0.0.9:161","pon_ports":["0/1/0"]`
	if err := ok(snmp + cred + `}`); err != nil {
		t.Fatalf("snmp community only from the credentials file: %v", err)
	}
	if err := ok(snmp + `}`); err == nil {
		t.Fatal("snmp without any community source must be refused")
	}
	// last_down: community from the credentials file of the same OLT
	withLD := strings.Replace(oltJSON(`,"profile":"huawei_ma56_r015"`+cred), `"pon_ports":["0/1/0"]`, `"pon_ports":["0/0/14"],"last_down":{"snmp_address":"10.0.0.9:161"}`, 1)
	if err := ok(withLD); err != nil {
		t.Fatalf("last_down community from the credentials file: %v", err)
	}
	noCred := strings.Replace(oltJSON(`,"profile":"huawei_ma56_r015","username":"ro","secret_file":"/s"`), `"pon_ports":["0/1/0"]`, `"pon_ports":["0/0/14"],"last_down":{"snmp_address":"10.0.0.9:161"}`, 1)
	if err := ok(noCred); err == nil {
		t.Fatal("last_down without a community source must be refused")
	}
	// host key and the rest are NOT relaxed
	if err := ok(strings.Replace(oltJSON(cred), `"host_key_sha256":"SHA256:abc"`, `"host_key_sha256":""`, 1)); err == nil {
		t.Fatal("the pinned host key stays mandatory")
	}
	// relative / duplicated credentials files
	if err := ok(oltJSON(`,"credentials_file":"cred/a.json"`)); err == nil {
		t.Fatal("relative credentials_file")
	}
	if err := ok(oltJSON(`,"credentials_file":"/s"`)); err == nil {
		t.Fatal("credentials_file equal to a static secret file")
	}
	second := strings.Replace(strings.Replace(oltJSON(cred), `"A"`, `"B"`, 1), "10.0.0.9:22", "10.0.0.8:22", 1)
	if _, err := Load(write(t, 0o600, secretsCfg(`,"allowlist":["10.0.0.9:22","10.0.0.8:22"],"olts":[`+oltJSON(cred)+`,`+second+`]`)), "v"); err == nil {
		t.Fatal("two OLTs must not share one credentials file")
	}
}

func TestAcceptsKind(t *testing.T) {
	cli := OLTConfig{CredentialsFile: "/c"}
	cliLD := OLTConfig{CredentialsFile: "/c", LastDown: &LastDownConfig{}}
	snmp := OLTConfig{CredentialsFile: "/c", Transport: "snmp"}
	none := OLTConfig{}
	for _, tc := range []struct {
		o    OLTConfig
		kind string
		want bool
	}{
		{cli, KindSSHLogin, true}, {cli, KindSNMPCommunity, false}, {cliLD, KindSNMPCommunity, true}, {cliLD, KindSSHLogin, true},
		{snmp, KindSNMPCommunity, true}, {snmp, KindSSHLogin, false}, {none, KindSSHLogin, false}, {none, KindSNMPCommunity, false}, {cli, "other", false},
	} {
		if got := tc.o.AcceptsKind(tc.kind); got != tc.want {
			t.Errorf("%+v %s: got %v", tc.o, tc.kind, got)
		}
	}
}

// --- precedence at the start of a session -----------------------------------------------------------------------------------------------------------------------------

func privTemp(t *testing.T) string {
	d := filepath.Join(t.TempDir(), "d")
	if err := os.Mkdir(d, 0o700); err != nil {
		t.Fatal(err)
	}
	return d
}

func put(t *testing.T, p, body string, mode os.FileMode) {
	t.Helper()
	if err := os.WriteFile(p, []byte(body), mode); err != nil {
		t.Fatal(err)
	}
	_ = os.Chmod(p, mode)
}

func TestSSHLoginPrecedenceFieldByField(t *testing.T) {
	dir := privTemp(t)
	secret := filepath.Join(dir, "static.secret")
	put(t, secret, "static-pw\n", 0o600)
	cred := filepath.Join(dir, "cred.json")
	o := OLTConfig{Username: "static-user", SecretFile: secret, CredentialsFile: cred}

	// no credentials file yet: the static configuration only
	if u, p, err := o.SSHLogin(); err != nil || u != "static-user" || p != "static-pw" {
		t.Fatalf("%q %q %v", u, p, err)
	}
	// both fields in the file: the file wins, the static secret is not even needed
	put(t, cred, `{"v":1,"username":"file-user","password":"file-pw"}`, 0o600)
	_ = os.Remove(secret)
	if u, p, err := o.SSHLogin(); err != nil || u != "file-user" || p != "file-pw" {
		t.Fatalf("%q %q %v", u, p, err)
	}
	// only the community in the file: login falls back to the static configuration
	put(t, secret, "static-pw\n", 0o600)
	put(t, cred, `{"v":1,"snmp_community":"c"}`, 0o600)
	if u, p, err := o.SSHLogin(); err != nil || u != "static-user" || p != "static-pw" {
		t.Fatalf("%q %q %v", u, p, err)
	}
	// only a password in the file: the username falls back
	put(t, cred, `{"v":1,"password":"file-pw"}`, 0o600)
	if u, p, err := o.SSHLogin(); err != nil || u != "static-user" || p != "file-pw" {
		t.Fatalf("%q %q %v", u, p, err)
	}
	// no static source at all and an empty file: an error of the session, not a blank login
	bare := OLTConfig{CredentialsFile: cred}
	put(t, cred, `{"v":1,"snmp_community":"c"}`, 0o600)
	if _, _, err := bare.SSHLogin(); err == nil {
		t.Fatal("no login anywhere must be an error")
	}
}

func TestCommunityPrecedence(t *testing.T) {
	dir := privTemp(t)
	static := filepath.Join(dir, "static.snmp")
	put(t, static, "static-community\n", 0o600)
	cred := filepath.Join(dir, "cred.json")
	o := OLTConfig{CredentialsFile: cred}
	if c, err := o.Community(static); err != nil || c != "static-community" {
		t.Fatalf("%q %v", c, err)
	}
	put(t, cred, `{"v":1,"snmp_community":"file-community","username":"u","password":"p"}`, 0o600)
	if c, err := o.Community(static); err != nil || c != "file-community" {
		t.Fatalf("%q %v", c, err)
	}
	put(t, cred, `{"v":1,"username":"u","password":"p"}`, 0o600) // the file has no community: static
	if c, err := o.Community(static); err != nil || c != "static-community" {
		t.Fatalf("%q %v", c, err)
	}
	if _, err := o.Community(""); err == nil {
		t.Fatal("no community anywhere must be an error")
	}
	// without credentials_file it is exactly the old behaviour
	if c, err := (OLTConfig{}).Community(static); err != nil || c != "static-community" {
		t.Fatalf("%q %v", c, err)
	}
	if _, err := (OLTConfig{}).Community(filepath.Join(dir, "missing")); err == nil {
		t.Fatal("a missing static file is still an error")
	}
}

// A credentials file that exists but cannot be trusted is an error of the session: there is NO fallback to the static source.
func TestBrokenCredentialsFileFailsClosedWithoutFallback(t *testing.T) {
	dir := privTemp(t)
	secret := filepath.Join(dir, "static.secret")
	put(t, secret, "static-pw\n", 0o600)
	snmp := filepath.Join(dir, "static.snmp")
	put(t, snmp, "static-community\n", 0o600)
	cred := filepath.Join(dir, "cred.json")
	o := OLTConfig{Username: "u", SecretFile: secret, CredentialsFile: cred}
	for name, mk := range map[string]func(){
		"loose permissions": func() { put(t, cred, `{"v":1,"username":"a","password":"b","snmp_community":"c"}`, 0o644) },
		"invalid json":      func() { put(t, cred, `{"v":1,"password":"SEGREDO-AQUI`, 0o600) },
		"wrong version":     func() { put(t, cred, `{"v":9}`, 0o600) },
		"symlink": func() {
			put(t, filepath.Join(dir, "real.json"), `{"v":1,"password":"b"}`, 0o600)
			_ = os.Remove(cred)
			_ = os.Symlink(filepath.Join(dir, "real.json"), cred)
		},
	} {
		_ = os.RemoveAll(cred)
		mk()
		if u, p, err := o.SSHLogin(); err == nil || p != "" || u != "" {
			t.Errorf("%s: ssh must fail closed: %q %q %v", name, u, p, err)
		} else if strings.Contains(err.Error(), "SEGREDO") {
			t.Errorf("%s: the error carries the secret: %v", name, err)
		}
		if c, err := o.Community(snmp); err == nil || c != "" {
			t.Errorf("%s: snmp must fail closed: %q %v", name, c, err)
		}
	}
	// the directory open to others
	_ = os.RemoveAll(cred)
	put(t, cred, `{"v":1,"username":"a","password":"b"}`, 0o600)
	if err := os.Chmod(dir, 0o755); err != nil {
		t.Fatal(err)
	}
	defer os.Chmod(dir, 0o700)
	if _, _, err := o.SSHLogin(); err == nil {
		t.Error("a loose directory must fail closed")
	}
}

func TestWithoutCredentialsFileTheOldBehaviourIsUntouched(t *testing.T) {
	dir := privTemp(t)
	secret := filepath.Join(dir, "static.secret")
	put(t, secret, "static-pw\n", 0o600)
	o := OLTConfig{Username: "u", SecretFile: secret}
	if u, p, err := o.SSHLogin(); err != nil || u != "u" || p != "static-pw" {
		t.Fatalf("%q %q %v", u, p, err)
	}
	put(t, secret, "static-pw\n", 0o644)
	if _, _, err := o.SSHLogin(); err == nil {
		t.Fatal("a loose static secret is still refused")
	}
}
