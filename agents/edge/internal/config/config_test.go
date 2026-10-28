package config

import (
	"os"
	"path/filepath"
	"strings"
	"testing"
)

const goodUUID = "0b8d5a0e-1111-4222-8333-444455556666"

func write(t *testing.T, mode os.FileMode, body string) string {
	p := filepath.Join(t.TempDir(), "c.json")
	if err := os.WriteFile(p, []byte(body), mode); err != nil {
		t.Fatal(err)
	}
	_ = os.Chmod(p, mode)
	return p
}

func good(extra string) string {
	return `{"gateway_url":"https://gw.example.com","edge_id":"` + goodUUID + `","tenant_id":"` + goodUUID + `","client_id":"` + goodUUID +
		`","secret_file":"/s","queue_path":"/q","connector_id":"c"` + extra + `}`
}

func TestLoadOK(t *testing.T) {
	c, err := Load(write(t, 0o600, good(`,"allowlist":["10.0.0.5:7557"]`)), "v")
	if err != nil || c.HeartbeatSeconds != 30 || c.CollectSeconds != 300 {
		t.Fatalf("c=%+v err=%v", c, err)
	}
}

func TestRejects(t *testing.T) {
	cases := map[string]string{
		"perms":      "perm",
		"http":       strings.Replace(good(""), "https://gw.example.com", "http://gw.example.com", 1),
		"http-lo-no": strings.Replace(good(""), "https://gw.example.com", "http://127.0.0.1:8000", 1),
		"bad-uuid":   strings.Replace(good(""), goodUUID, "nope", 1),
		"unknown":    good(`,"nbi_url_from_cloud":"x"`),
		"fast":       good(`,"heartbeat_seconds":1`),
	}
	for name, body := range cases {
		mode := os.FileMode(0o600)
		if name == "perms" {
			mode, body = 0o644, good("")
		}
		if _, err := Load(write(t, mode, body), "v"); err == nil {
			t.Errorf("%s: expected error", name)
		}
	}
}

func TestInsecureOnlyForLoopbackWithFlag(t *testing.T) {
	body := strings.Replace(good(`,"allow_insecure_dev":true`), "https://gw.example.com", "http://127.0.0.1:18420", 1)
	if _, err := Load(write(t, 0o600, body), "v"); err != nil {
		t.Fatal(err)
	}
	body = strings.Replace(good(`,"allow_insecure_dev":true`), "https://gw.example.com", "http://10.0.0.9:80", 1)
	if _, err := Load(write(t, 0o600, body), "v"); err == nil {
		t.Fatal("flag must not allow non-loopback http")
	}
}

func TestReadSecretEnforcesMode(t *testing.T) {
	p := write(t, 0o644, "secret\n")
	if _, err := ReadSecret(p); err == nil {
		t.Fatal("0644 secret must be refused")
	}
	p = write(t, 0o600, "secret\n")
	if s, err := ReadSecret(p); err != nil || s != "secret" {
		t.Fatalf("s=%q err=%v", s, err)
	}
}
