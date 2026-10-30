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

func TestRefreshTasksNeedsNBIAndSignedJobsAndIsOffByDefault(t *testing.T) {
	const nbi = `,"nbi_url":"http://10.0.0.5:7557","allowlist":["10.0.0.5:7557"]`
	const jobs = `,"jobs_enabled":true,"job_public_key":"A6EHv/POEL4dcN0Y50vAmWfk1jCbpQ1fHdyGZBJVMbg="`
	if c, err := Load(write(t, 0o600, good(nbi+jobs)), "v"); err != nil || c.RefreshTasks {
		t.Fatalf("must be off unless asked: %+v %v", c, err)
	}
	if c, err := Load(write(t, 0o600, good(nbi+jobs+`,"refresh_tasks":true`)), "v"); err != nil || !c.RefreshTasks {
		t.Fatalf("%+v %v", c, err)
	}
	for name, extra := range map[string]string{
		"without jobs": nbi + `,"refresh_tasks":true`,
		"without nbi":  jobs + `,"refresh_tasks":true`,
	} {
		if _, err := Load(write(t, 0o600, good(extra)), "v"); err == nil {
			t.Errorf("%s: active reads must only exist behind signed jobs and an NBI", name)
		}
	}
	if got := RefreshGuardFile("/var/lib/edge/queue.db"); got != "/var/lib/edge/refresh-guard.json" {
		t.Fatalf("%s", got)
	}
}

func TestBenchConfigValidation(t *testing.T) {
	base := `,"nbi_url":"http://127.0.0.1:7557","jobs_enabled":true,"job_public_key":"k","allowed_operations":["collect","reboot_cpe"]`
	dev := `{"oui":"00259E","product_class":"EG8145V5","serial":"48575443E2247AA5"}`
	ok := base + `,"bench":{"bench_writes_enabled":true,"devices":[` + dev + `]}`
	if _, err := Load(write(t, 0o600, good(ok)), "v"); err != nil {
		t.Fatalf("valid bench config: %v", err)
	}
	bad := map[string]string{
		"no devices":    base + `,"bench":{"bench_writes_enabled":true,"devices":[]}`,
		"duplicate":     base + `,"bench":{"bench_writes_enabled":true,"devices":[` + dev + `,` + dev + `]}`,
		"empty serial":  base + `,"bench":{"bench_writes_enabled":true,"devices":[{"oui":"00259E","product_class":"EG8145V5","serial":""}]}`,
		"op not listed": strings.Replace(ok, `,"reboot_cpe"`, ``, 1),
		"no jobs":       strings.Replace(ok, `"jobs_enabled":true`, `"jobs_enabled":false`, 1),
		"too many":      base + `,"bench":{"bench_writes_enabled":true,"devices":[` + strings.Repeat(dev[:len(dev)-3]+`1"},`, 0) + `]}`,
	}
	delete(bad, "too many")
	for name, extra := range bad {
		if _, err := Load(write(t, 0o600, good(extra)), "v"); err == nil {
			t.Errorf("%s: must be refused", name)
		}
	}
	// disabled bench section needs nothing
	if _, err := Load(write(t, 0o600, good(`,"bench":{"bench_writes_enabled":false,"devices":[]}`)), "v"); err != nil {
		t.Fatalf("disabled: %v", err)
	}
}

func TestBenchPacingConfig(t *testing.T) {
	base := `,"nbi_url":"http://127.0.0.1:7557","jobs_enabled":true,"job_public_key":"k","allowed_operations":["collect","reboot_cpe"]`
	dev := `{"oui":"00259E","product_class":"EG8145V5","serial":"48575443E2247AA5"}`
	mk := func(pace string) string {
		return base + `,"bench":{"bench_writes_enabled":true,` + pace + `"devices":[` + dev + `]}`
	}
	c, err := Load(write(t, 0o600, good(mk(""))), "v")
	if err != nil {
		t.Fatal(err)
	}
	if m, n := c.Bench.BenchPacing(); m != 30*time.Minute || n != 2 {
		t.Fatalf("defaults %v %d", m, n)
	}
	c, err = Load(write(t, 0o600, good(mk(`"min_interval_seconds":60,"max_per_hour":10,`))), "v")
	if err != nil {
		t.Fatal(err)
	}
	if m, n := c.Bench.BenchPacing(); m != time.Minute || n != 10 {
		t.Fatalf("lowered %v %d", m, n)
	}
	for _, bad := range []string{`"min_interval_seconds":59,`, `"min_interval_seconds":1801,`, `"min_interval_seconds":-1,`, `"max_per_hour":21,`, `"max_per_hour":-1,`} {
		if _, err := Load(write(t, 0o600, good(mk(bad))), "v"); err == nil {
			t.Errorf("%s: must be refused", bad)
		}
	}
}

func TestBenchOLTConfig(t *testing.T) {
	dev := `{"oui":"00259E","product_class":"EG8145V5","serial":"48575443E2247AA5"}`
	olts := `,"olts":[{"name":"OLT-A","vendor":"huawei","address":"10.0.0.1:22","username":"u","secret_file":"/s","host_key_sha256":"SHA256:abc","pon_ports":["0/0/14"]}]`
	mk := func(ops, bench string) string {
		return `,"nbi_url":"http://127.0.0.1:7557","jobs_enabled":true,"job_public_key":"k","allowlist":["10.0.0.1:22"],"allowed_operations":[` + ops + `]` + olts +
			`,"bench":{"bench_writes_enabled":true,"devices":[` + dev + `]` + bench + `}`
	}
	goodOLT := `,"olt":{"name":"OLT-A","frame":0,"slot":0,"port":14,"ont_id":10,"gpon_serial":"48575443E2247AA5"}`
	if _, err := Load(write(t, 0o600, good(mk(`"collect","onu_reset"`, goodOLT))), "v"); err != nil {
		t.Fatalf("valid: %v", err)
	}
	bad := map[string]string{
		"ops without olt": mk(`"collect","onu_reset"`, ""),
		"unknown olt":     mk(`"collect","onu_reset"`, strings.Replace(goodOLT, "OLT-A", "OLT-X", 1)),
		"serial mismatch": mk(`"collect","onu_reset"`, strings.Replace(goodOLT, "48575443E2247AA5", "48575443AAAAAAAA", 1)),
		"lower case":      mk(`"collect","onu_reset"`, strings.Replace(goodOLT, "48575443E2247AA5", "48575443e2247aa5", 1)),
		"port 16":         mk(`"collect","onu_reset"`, strings.Replace(goodOLT, `"port":14`, `"port":16`, 1)),
		"ont id 128":      mk(`"collect","onu_reset"`, strings.Replace(goodOLT, `"ont_id":10`, `"ont_id":128`, 1)),
		"gap below floor": mk(`"collect","onu_reset"`, strings.Replace(goodOLT, `}`, `,"min_gap_seconds":30}`, 1)),
		"wait too long":   mk(`"collect","onu_reset"`, strings.Replace(goodOLT, `}`, `,"wait_seconds":601}`, 1)),
	}
	for name, extra := range bad {
		if _, err := Load(write(t, 0o600, good(extra)), "v"); err == nil {
			t.Errorf("%s: must be refused", name)
		}
	}
}

func TestOLTLastDownConfig(t *testing.T) {
	cli := func(extra string) string {
		return `,"allowlist":["10.0.0.9:22","10.0.0.9:161","10.0.0.8:161"],"olts":[{"name":"A","vendor":"huawei","profile":"huawei_ma56_r015","address":"10.0.0.9:22","username":"ro","secret_file":"/s","host_key_sha256":"SHA256:abc","pon_ports":["0/1/0"]` + extra + `}]`
	}
	ld := func(f string) string { return `,"last_down":{` + f + `}` }
	const ok = `"snmp_address":"10.0.0.9:161","snmp_community_file":"/c"`
	cfg, err := Load(write(t, 0o600, good(cli(ld(ok+`,"every_seconds":1800`)))), "v")
	if err != nil || cfg.OLTs[0].LastDown == nil || cfg.OLTs[0].LastDown.Every() != 30*time.Minute {
		t.Fatalf("valid last_down rejected: %v", err)
	}
	if cfg, _ = Load(write(t, 0o600, good(cli(ld(ok)))), "v"); cfg.OLTs[0].LastDown.Every() != time.Hour || cfg.OLTs[0].LastDown.Pace() != 2*time.Second {
		t.Fatal("default must be one hour and a 2 s pace (1 s apart made the real agent go mute)")
	}
	if cfg, _ = Load(write(t, 0o600, good(cli(ld(ok+`,"snmp_pace_ms":3000`)))), "v"); cfg.OLTs[0].LastDown.Pace() != 3*time.Second {
		t.Fatal("an explicit pace must be honoured")
	}
	if cfg, _ = Load(write(t, 0o600, good(cli(ld(ok)))), "v"); cfg.OLTs[0].LastDown.Settle() != 4*time.Minute {
		t.Fatal("default settle must be 4 minutes")
	}
	for name, extra := range map[string]string{
		"settle too short": ld(ok + `,"settle_seconds":10`),
		"settle too long":  ld(ok + `,"settle_seconds":3600`),
		"other device":     ld(`"snmp_address":"10.0.0.8:161","snmp_community_file":"/c"`),
		"not in allowlist": ld(`"snmp_address":"10.0.0.9:162","snmp_community_file":"/c"`),
		"no community":     ld(`"snmp_address":"10.0.0.9:161"`),
		"too frequent":     ld(ok + `,"every_seconds":300`),
		"too fast pace":    ld(ok + `,"snmp_pace_ms":200`),
		"too many reqs":    ld(ok + `,"snmp_max_requests":5000`),
		"host name":        ld(`"snmp_address":"olt.example:161","snmp_community_file":"/c"`),
	} {
		if _, err := Load(write(t, 0o600, good(cli(extra))), "v"); err == nil {
			t.Errorf("%s: expected error", name)
		}
	}
	notR015 := `,"allowlist":["10.0.0.9:22","10.0.0.9:161"],"olts":[{"name":"A","vendor":"huawei","address":"10.0.0.9:22","username":"ro","secret_file":"/s","host_key_sha256":"SHA256:abc","pon_ports":["0/1/0"]` + ld(ok) + `}]`
	if _, err := Load(write(t, 0o600, good(notR015)), "v"); err == nil {
		t.Error("last_down without the validated profile must be refused")
	}
}

func TestOLTDownTimesConfig(t *testing.T) {
	cli := func(extra string) string {
		return `,"allowlist":["10.0.0.9:22","10.0.0.9:161"],"olts":[{"name":"A","vendor":"huawei","profile":"huawei_ma56_r015","address":"10.0.0.9:22","username":"ro","secret_file":"/s","host_key_sha256":"SHA256:abc","pon_ports":["0/1/0"]` + extra + `}]`
	}
	cfg, err := Load(write(t, 0o600, good(cli(`,"down_times":{}`))), "v")
	if err != nil || cfg.OLTs[0].DownTimes == nil || cfg.OLTs[0].DownTimes.Max() != 15 {
		t.Fatalf("default must be 15 reads per collection: %v", err)
	}
	if cfg, err = Load(write(t, 0o600, good(cli(`,"down_times":{"max_per_round":40}`))), "v"); err != nil || cfg.OLTs[0].DownTimes.Max() != 40 {
		t.Fatalf("explicit value: %v", err)
	}
	for name, extra := range map[string]string{
		"negative":       `,"down_times":{"max_per_round":-1}`,
		"too many":       `,"down_times":{"max_per_round":61}`,
		"with last_down": `,"down_times":{},"last_down":{"snmp_address":"10.0.0.9:161","snmp_community_file":"/c"}`,
	} {
		if _, err := Load(write(t, 0o600, good(cli(extra))), "v"); err == nil {
			t.Errorf("%s: expected error", name)
		}
	}
	notR015 := `,"allowlist":["10.0.0.9:22"],"olts":[{"name":"A","vendor":"huawei","address":"10.0.0.9:22","username":"ro","secret_file":"/s","host_key_sha256":"SHA256:abc","pon_ports":["0/1/0"],"down_times":{}}]`
	if _, err := Load(write(t, 0o600, good(notR015)), "v"); err == nil {
		t.Error("down_times without the validated profile must be refused")
	}
}

func TestOLTQueryConfig(t *testing.T) {
	cid := "8f14e45f-ceea-467a-9a36-4a1b5c3d2e10"
	olt := func(extra string) string {
		return `{"name":"OLT-A","vendor":"huawei","address":"10.0.0.1:22","username":"u","secret_file":"/s","host_key_sha256":"SHA256:abc","pon_ports":["0/0/14"],"profile":"huawei_ma56_r015"` + extra + `}`
	}
	mk := func(enabled bool, ops, olts string) string {
		e := ""
		if enabled {
			e = `,"olt_query_enabled":true`
		}
		return `,"jobs_enabled":true,"job_public_key":"k","allowlist":["10.0.0.1:22"],"allowed_operations":[` + ops + `]` + e + `,"olts":[` + olts + `]`
	}
	if _, err := Load(write(t, 0o600, good(mk(true, `"collect","olt_query"`, olt(`,"cloud_id":"`+cid+`"`)))), "v"); err != nil {
		t.Fatalf("valid: %v", err)
	}
	if _, err := Load(write(t, 0o600, good(mk(false, `"collect"`, olt(`,"cloud_id":"`+cid+`"`)))), "v"); err != nil {
		t.Fatalf("a cloud_id alone enables nothing: %v", err)
	}
	for name, cfg := range map[string]string{
		"no operation listed":  mk(true, `"collect"`, olt(`,"cloud_id":"`+cid+`"`)),
		"no olt with cloud_id": mk(true, `"collect","olt_query"`, olt("")),
		"upper-case id":        mk(true, `"collect","olt_query"`, olt(`,"cloud_id":"`+strings.ToUpper(cid)+`"`)),
		"not a uuid":           mk(true, `"collect","olt_query"`, olt(`,"cloud_id":"OLT-A"`)),
		"cloud_id on a generic profile": mk(true, `"collect","olt_query"`,
			strings.Replace(olt(`,"cloud_id":"`+cid+`"`), `,"profile":"huawei_ma56_r015"`, "", 1)),
		"duplicate id": mk(true, `"collect","olt_query"`, olt(`,"cloud_id":"`+cid+`"`)+","+strings.Replace(strings.Replace(olt(`,"cloud_id":"`+cid+`"`), "OLT-A", "OLT-B", 1), "10.0.0.1:22", "10.0.0.2:22", 1)),
	} {
		if _, err := Load(write(t, 0o600, good(cfg)), "v"); err == nil {
			t.Errorf("%s: must be refused", name)
		}
	}
	if _, err := Load(write(t, 0o600, good(`,"jobs_enabled":false,"olt_query_enabled":true,"allowed_operations":["olt_query"],"olts":[`+olt(`,"cloud_id":"`+cid+`"`)+`],"allowlist":["10.0.0.1:22"]`)), "v"); err == nil {
		t.Error("olt_query_enabled without jobs_enabled must be refused")
	}
}
