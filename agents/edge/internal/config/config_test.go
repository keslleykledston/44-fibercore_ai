package config

import (
	"os"
	"path/filepath"
	"strings"
	"testing"
	"time"
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

func TestOLTConfigValidation(t *testing.T) {
	olt := func(addr, pin, port, vendor string) string {
		return `,"allowlist":["10.0.0.9:22"],"olts":[{"name":"A","vendor":"` + vendor + `","address":"` + addr + `","username":"ro","secret_file":"/s","host_key_sha256":"` + pin + `","pon_ports":["` + port + `"]}]`
	}
	if _, err := Load(write(t, 0o600, good(olt("10.0.0.9:22", "SHA256:abc", "0/1/0", "huawei"))), "v"); err != nil {
		t.Fatalf("valid olt rejected: %v", err)
	}
	for name, body := range map[string]string{
		"not-in-allowlist": olt("10.0.0.10:22", "SHA256:abc", "0/1/0", "huawei"),
		"no-pin":           olt("10.0.0.9:22", "", "0/1/0", "huawei"),
		"bad-port":         olt("10.0.0.9:22", "SHA256:abc", "0/1/0; reboot", "huawei"),
		"bad-vendor":       olt("10.0.0.9:22", "SHA256:abc", "0/1/0", "cisco"),
	} {
		if _, err := Load(write(t, 0o600, good(body)), "v"); err == nil {
			t.Errorf("%s: expected error", name)
		}
	}
}

func TestOLTSSHModeAndLegacyOptIn(t *testing.T) {
	olt := func(extra string) string {
		return `,"allowlist":["10.0.0.9:22"],"olts":[{"name":"A","vendor":"huawei","address":"10.0.0.9:22","username":"ro","secret_file":"/s","host_key_sha256":"SHA256:abc","pon_ports":["0/1/0"]` + extra + `}]`
	}
	for _, extra := range []string{``, `,"ssh_mode":"exec"`, `,"ssh_mode":"shell","legacy_ssh":true`} {
		cfg, err := Load(write(t, 0o600, good(olt(extra))), "v")
		if err != nil {
			t.Fatalf("%q rejected: %v", extra, err)
		}
		if extra == `,"ssh_mode":"shell","legacy_ssh":true` && (cfg.OLTs[0].SSHMode != "shell" || !cfg.OLTs[0].LegacySSH) {
			t.Fatalf("fields not loaded: %+v", cfg.OLTs[0])
		}
	}
	if cfg, _ := Load(write(t, 0o600, good(olt(``))), "v"); cfg.OLTs[0].LegacySSH {
		t.Fatal("legacy SSH must be off unless explicitly enabled")
	}
	for _, extra := range []string{`,"ssh_mode":"telnet"`, `,"ssh_mode":"SHELL"`} {
		if _, err := Load(write(t, 0o600, good(olt(extra))), "v"); err == nil {
			t.Errorf("%q must be rejected", extra)
		}
	}
}

func TestOLTProfileAndPagerSpaceValidation(t *testing.T) {
	olt := func(vendor, extra string) string {
		return `,"allowlist":["10.0.0.9:22"],"olts":[{"name":"A","vendor":"` + vendor + `","address":"10.0.0.9:22","username":"ro","secret_file":"/s","host_key_sha256":"SHA256:abc","pon_ports":["0/0/14"]` + extra + `}]`
	}
	ok := `,"ssh_mode":"shell","ssh_pager_space":true,"legacy_ssh":true,"profile":"huawei_ma56_r015"`
	cfg, err := Load(write(t, 0o600, good(olt("huawei", ok))), "v")
	if err != nil {
		t.Fatalf("valid R015 config rejected: %v", err)
	}
	if o := cfg.OLTs[0]; o.Profile != "huawei_ma56_r015" || !o.SSHPagerSpace {
		t.Fatalf("fields not loaded: %+v", o)
	}
	for name, body := range map[string]string{
		"unknown profile":       olt("huawei", `,"profile":"huawei_ma56_r016"`),
		"profile on zte":        olt("zte", `,"profile":"huawei_ma56_r015"`),
		"pager space w/o shell": olt("huawei", `,"ssh_pager_space":true`),
		"pager space on exec":   olt("huawei", `,"ssh_mode":"exec","ssh_pager_space":true`),
	} {
		if _, err := Load(write(t, 0o600, good(body)), "v"); err == nil {
			t.Errorf("%s: must be rejected", name)
		}
	}
	if cfg, _ := Load(write(t, 0o600, good(olt("huawei", ""))), "v"); cfg.OLTs[0].SSHPagerSpace || cfg.OLTs[0].Profile != "" {
		t.Fatal("pager key and profile must be off unless explicitly enabled")
	}
}

func TestTwoOLTNamesCannotShareOneSNMPAgent(t *testing.T) {
	both := func(a, b string) string {
		mk := func(name, addr string) string {
			return `{"name":"` + name + `","vendor":"huawei","pon_ports":["0/0/14"],"transport":"snmp","snmp_address":"` + addr + `","snmp_community_file":"/c"}`
		}
		return `,"allowlist":["192.0.2.10:161","192.0.2.11:161","[2001:db8::1]:161","[2001:0db8:0:0:0:0:0:1]:161"],"olts":[` + mk("A", a) + `,` + mk("B", b) + `]`
	}
	if _, err := Load(write(t, 0o600, good(both("192.0.2.10:161", "192.0.2.11:161"))), "v"); err != nil {
		t.Fatalf("two different agents must be accepted: %v", err)
	}
	for name, body := range map[string]string{
		"same address":                  both("192.0.2.10:161", "192.0.2.10:161"),
		"same IPv6, different spelling": both("[2001:db8::1]:161", "[2001:0db8:0:0:0:0:0:1]:161"),
	} {
		if _, err := Load(write(t, 0o600, good(body)), "v"); err == nil {
			t.Errorf("%s: two names for one agent must be rejected", name)
		}
	}
}

func TestOLTSNMPTransportValidation(t *testing.T) {
	olt := func(extra string) string {
		return `,"allowlist":["192.0.2.10:161","olt.example:161","192.0.2.10:22"],"olts":[{"name":"A","vendor":"huawei","pon_ports":["0/0/14"]` + extra + `}]`
	}
	ok := `,"transport":"snmp","snmp_address":"192.0.2.10:161","snmp_community_file":"/c","snmp_pace_ms":1000,"snmp_max_requests":300`
	cfg, err := Load(write(t, 0o600, good(olt(ok))), "v")
	if err != nil {
		t.Fatalf("valid snmp OLT rejected: %v", err)
	}
	if o := cfg.OLTs[0]; o.Transport != "snmp" || o.SNMPAddress != "192.0.2.10:161" || o.SNMPMaxRequests != 300 {
		t.Fatalf("fields not loaded: %+v", o)
	}
	for name, extra := range map[string]string{
		"hostname instead of an IP literal": `,"transport":"snmp","snmp_address":"olt.example:161","snmp_community_file":"/c"`,
		"not in the allowlist":              `,"transport":"snmp","snmp_address":"192.0.2.99:161","snmp_community_file":"/c"`,
		"no community file":                 `,"transport":"snmp","snmp_address":"192.0.2.10:161"`,
		"ssh fields mixed in":               `,"transport":"snmp","snmp_address":"192.0.2.10:161","snmp_community_file":"/c","username":"u"`,
		"pace out of range":                 `,"transport":"snmp","snmp_address":"192.0.2.10:161","snmp_community_file":"/c","snmp_pace_ms":99999`,
		"pace below the 1s floor":           `,"transport":"snmp","snmp_address":"192.0.2.10:161","snmp_community_file":"/c","snmp_pace_ms":200`,
		"budget above the cap":              `,"transport":"snmp","snmp_address":"192.0.2.10:161","snmp_community_file":"/c","snmp_max_requests":5000`,
		"unknown transport":                 `,"transport":"telnet","address":"192.0.2.10:22"`,
		"snmp fields without the transport": `,"snmp_address":"192.0.2.10:161","address":"192.0.2.10:22","username":"u","secret_file":"/s","host_key_sha256":"SHA256:abc"`,
	} {
		if _, err := Load(write(t, 0o600, good(olt(extra))), "v"); err == nil {
			t.Errorf("%s: must be rejected", name)
		}
	}
}

func TestOLTPacingDefaultsAndBounds(t *testing.T) {
	olt := func(extra string) string {
		return `,"allowlist":["10.0.0.9:22"],"olts":[{"name":"A","vendor":"huawei","address":"10.0.0.9:22","username":"ro","secret_file":"/s","host_key_sha256":"SHA256:abc","pon_ports":["0/1/0"]` + extra + `}]`
	}
	cfg, err := Load(write(t, 0o600, good(olt(``))), "v")
	if err != nil {
		t.Fatal(err)
	}
	if cfg.OLTs[0].OLTInterval() != 15*time.Minute || cfg.OLTs[0].OLTCooldown() != 0 {
		t.Fatalf("a CLI OLT defaults to one login per 15 minutes: %v / %v", cfg.OLTs[0].OLTInterval(), cfg.OLTs[0].OLTCooldown())
	}
	cfg, err = Load(write(t, 0o600, good(olt(`,"collect_seconds":1800,"cooldown_seconds":600`))), "v")
	if err != nil || cfg.OLTs[0].OLTInterval() != 30*time.Minute || cfg.OLTs[0].OLTCooldown() != 10*time.Minute {
		t.Fatalf("explicit pacing: %v %+v", err, cfg.OLTs[0])
	}
	for _, extra := range []string{`,"collect_seconds":5`, `,"collect_seconds":-1`, `,"collect_seconds":100000`, `,"cooldown_seconds":59`} {
		if _, err := Load(write(t, 0o600, good(olt(extra))), "v"); err == nil {
			t.Errorf("%q must be rejected (a tight loop on a real OLT)", extra)
		}
	}
}

func TestDeviceKeyIsTheHostWhateverTheTransportOrPort(t *testing.T) {
	for in, want := range map[string]string{"192.0.2.10:22": "192.0.2.10", "192.0.2.10:161": "192.0.2.10", "192.0.2.10": "192.0.2.10",
		"[2001:DB8::1]:22": "2001:db8::1", "OLT-A.Example.NET:22": "olt-a.example.net"} {
		if got := DeviceKey(in); got != want {
			t.Errorf("DeviceKey(%q)=%q want %q", in, got, want)
		}
	}
}

func TestOnePhysicalOLTCannotBeConfiguredTwice(t *testing.T) {
	ssh := `{"name":"A","vendor":"huawei","address":"10.0.0.9:22","username":"ro","secret_file":"/s","host_key_sha256":"SHA256:abc","pon_ports":["0/1/0"]}`
	snmp := func(name, addr string) string {
		return `{"name":"` + name + `","vendor":"huawei","transport":"snmp","snmp_address":"` + addr + `","snmp_community_file":"/c","pon_ports":["0/1/0"]}`
	}
	cases := map[string]string{
		"ssh+snmp same host": `,"allowlist":["10.0.0.9:22","10.0.0.9:161"],"olts":[` + ssh + `,` + snmp("B", "10.0.0.9:161") + `]`,
		"two snmp ports":     `,"allowlist":["10.0.0.9:161","10.0.0.9:162"],"olts":[` + snmp("A", "10.0.0.9:161") + `,` + snmp("B", "10.0.0.9:162") + `]`,
	}
	for name, body := range cases {
		if _, err := Load(write(t, 0o600, good(body)), "v"); err == nil || !strings.Contains(err.Error(), "already configured") {
			t.Errorf("%s: want 'already configured', got %v", name, err)
		}
	}
	other := `,"allowlist":["10.0.0.9:22","10.0.0.10:161"],"olts":[` + ssh + `,` + snmp("B", "10.0.0.10:161") + `]`
	if _, err := Load(write(t, 0o600, good(other)), "v"); err != nil {
		t.Fatalf("two different devices are fine: %v", err)
	}
}

func TestAnOLTAddressMustBeAnIPLiteralSoAliasesCannotSplitTheGuard(t *testing.T) {
	body := `,"allowlist":["olt-a.example.net:22"],"olts":[{"name":"A","vendor":"huawei","address":"olt-a.example.net:22","username":"ro","secret_file":"/s","host_key_sha256":"SHA256:abc","pon_ports":["0/1/0"]}]`
	if _, err := Load(write(t, 0o600, good(body)), "v"); err == nil || !strings.Contains(err.Error(), "IP literal") {
		t.Fatalf("a host-name OLT address must be refused: %v", err)
	}
}

func TestLockAndGuardBelongToTheStateDirectoryNotToTheQueueFileName(t *testing.T) {
	l1, g1 := StateFiles("/var/lib/edge/queue.db")
	l2, g2 := StateFiles("/var/lib/edge/other-queue.sqlite")
	l3, _ := StateFiles("/var/lib/edge2/queue.db")
	if l1 != l2 || g1 != g2 || l1 == l3 {
		t.Fatalf("same directory must share lock and guard: %s %s %s %s %s", l1, l2, g1, g2, l3)
	}
}

func TestR015ProfileLimitsPonPortsAtLoadTime(t *testing.T) {
	mk := func(ports, extra string) string {
		return `,"allowlist":["10.0.0.9:22"],"olts":[{"name":"A","vendor":"huawei","address":"10.0.0.9:22","username":"ro","secret_file":"/s","host_key_sha256":"SHA256:abc","pon_ports":[` + ports + `]` + extra + `}]`
	}
	r015 := `,"ssh_mode":"shell","ssh_pager_space":true,"legacy_ssh":true,"profile":"huawei_ma56_r015"`
	for _, ports := range []string{`"0/0/0"`, `"0/17/15"`, `"0/0/14","0/1/15"`} {
		if _, err := Load(write(t, 0o600, good(mk(ports, r015))), "v"); err != nil {
			t.Errorf("%s must load: %v", ports, err)
		}
	}
	for _, ports := range []string{`"1/0/14"`, `"0/18/14"`, `"0/0/16"`, `"0/00/1"`, `"0/0/14","0/18/1"`} {
		if _, err := Load(write(t, 0o600, good(mk(ports, r015))), "v"); err == nil {
			t.Errorf("%s must be refused at load, not fail every collection round", ports)
		}
	}
	if _, err := Load(write(t, 0o600, good(mk(`"1/0/14"`, ""))), "v"); err != nil {
		t.Errorf("limits belong to the R015 profile only: %v", err)
	}
}
