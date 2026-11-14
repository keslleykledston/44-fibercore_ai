package config

import "testing"

func TestMA58ProfileValidation(t *testing.T) {
	olt := func(vendor, ports, extra string) string {
		return `,"allowlist":["10.0.0.9:22"],"olts":[{"name":"A","vendor":"` + vendor + `","address":"10.0.0.9:22","username":"ro","secret_file":"/s","host_key_sha256":"SHA256:abc","pon_ports":` + ports + extra + `}]`
	}
	shell := `,"ssh_mode":"shell","ssh_pager_space":true,"profile":"huawei_ma58_r02x"`
	cfg, err := Load(write(t, 0o600, good(olt("huawei", `["0/1/0","0/1/1"]`, shell+`,"clock_offset_minutes":-180`))), "v")
	if err != nil {
		t.Fatalf("valid MA5800 config rejected: %v", err)
	}
	if o := cfg.OLTs[0]; o.Profile != "huawei_ma58_r02x" || o.ClockOffsetMinutes == nil || *o.ClockOffsetMinutes != -180 {
		t.Fatalf("fields not loaded: %+v", o)
	}
	if cfg, err := Load(write(t, 0o600, good(olt("huawei", `["0/1/0"]`, shell))), "v"); err != nil || cfg.OLTs[0].ClockOffsetMinutes != nil {
		t.Fatalf("the clock offset is optional and never defaulted: %v", err)
	}
	for name, body := range map[string]string{
		"profile on zte":             olt("zte", `["0/1/0"]`, shell),
		"profile without shell mode": olt("huawei", `["0/1/0"]`, `,"profile":"huawei_ma58_r02x"`),
		"profile on exec mode":       olt("huawei", `["0/1/0"]`, `,"ssh_mode":"exec","profile":"huawei_ma58_r02x"`),
		"frame 1":                    olt("huawei", `["1/1/0"]`, shell),
		"slot out of range":          olt("huawei", `["0/22/0"]`, shell),
		"port out of range":          olt("huawei", `["0/1/16"]`, shell),
		"offset without the profile": olt("huawei", `["0/1/0"]`, `,"ssh_mode":"shell","clock_offset_minutes":-180`),
		"offset below range":         olt("huawei", `["0/1/0"]`, shell+`,"clock_offset_minutes":-721`),
		"offset above range":         olt("huawei", `["0/1/0"]`, shell+`,"clock_offset_minutes":841`),
		"R015 last_down on MA5800":   olt("huawei", `["0/1/0"]`, shell+`,"last_down":{"snmp_address":"10.0.0.9:161"}`),
		"R015 down_times on MA5800":  olt("huawei", `["0/1/0"]`, shell+`,"down_times":{}`),
		"another unknown profile":    olt("huawei", `["0/1/0"]`, `,"ssh_mode":"shell","profile":"huawei_ma58_r03x"`),
	} {
		if _, err := Load(write(t, 0o600, good(body)), "v"); err == nil {
			t.Errorf("%s: must be rejected", name)
		}
	}
}
