package config

import (
	"strings"
	"testing"

	"github.com/keslleykledston/44-fibercore_ai/agents/edge/internal/managedolts"
)

func managedCfg(section string) string {
	return secretsCfg(`,"managed_olts":` + section)
}

const okManaged = `{"state_dir":"/var/lib/fibercore-edge/managed","allowed_cidrs":["10.20.0.0/16"],"max_olts":16}`

func TestManagedOLTsAbsentMeansTheFeatureIsOff(t *testing.T) {
	cfg, err := Load(write(t, 0o600, secretsCfg("")), "v")
	if err != nil || cfg.ManagedOLTs != nil {
		t.Fatalf("absent section must stay off: %v %+v", err, cfg.ManagedOLTs)
	}
}

func TestManagedOLTsValidSection(t *testing.T) {
	cfg, err := Load(write(t, 0o600, managedCfg(`{"state_dir":"/var/lib/fibercore-edge/managed","allowed_cidrs":["10.20.0.0/16","fd00:1234::/32"],"allowed_ports":[22,2222],"max_olts":8,"allow_legacy_ssh":true,"allowed_vendors":["huawei"],"pon_ports":["0/1/0"]}`)), "v")
	if err != nil {
		t.Fatal(err)
	}
	p, err := managedolts.NewPolicy(*cfg.ManagedOLTs)
	if err != nil || len(p.CIDRs) != 2 || !p.Ports[2222] || !p.Legacy || p.Vendors["zte"] || p.Max != 8 {
		t.Fatalf("policy %+v %v", p, err)
	}
}

func TestManagedOLTsDefaultsToPort22AndEverySupportedVendor(t *testing.T) {
	cfg, err := Load(write(t, 0o600, managedCfg(okManaged)), "v")
	if err != nil {
		t.Fatal(err)
	}
	p, _ := managedolts.NewPolicy(*cfg.ManagedOLTs)
	if len(p.Ports) != 1 || !p.Ports[22] || !p.Vendors["huawei"] || !p.Vendors["zte"] || p.Legacy {
		t.Fatalf("%+v", p)
	}
}

func TestManagedOLTsRefusesWideOrMissingCIDRs(t *testing.T) {
	for name, cidrs := range map[string]string{
		"missing":          ``,
		"empty list":       `"allowed_cidrs":[],`,
		"v4 everything":    `"allowed_cidrs":["0.0.0.0/0"],`,
		"v6 everything":    `"allowed_cidrs":["::/0"],`,
		"wider than /8":    `"allowed_cidrs":["10.0.0.0/7"],`,
		"v6 wider than 32": `"allowed_cidrs":["fd00::/31"],`,
		"mapped v6":        `"allowed_cidrs":["::ffff:0.0.0.0/96"],`,
		"not a cidr":       `"allowed_cidrs":["10.0.0.1"],`,
		"host name":        `"allowed_cidrs":["olt.example.com/24"],`,
		"one bad of two":   `"allowed_cidrs":["10.0.0.0/8","0.0.0.0/0"],`,
	} {
		body := `{"state_dir":"/var/lib/fibercore-edge/managed",` + cidrs + `"max_olts":16}`
		if _, err := Load(write(t, 0o600, managedCfg(body)), "v"); err == nil {
			t.Errorf("%s: expected an error", name)
		}
	}
	// the limits themselves are fine
	for _, c := range []string{"10.0.0.0/8", "fd00::/32", "192.168.1.7/32"} {
		if _, err := Load(write(t, 0o600, managedCfg(`{"state_dir":"/var/lib/fibercore-edge/managed","allowed_cidrs":["`+c+`"],"max_olts":4}`)), "v"); err != nil {
			t.Errorf("%s must be accepted: %v", c, err)
		}
	}
}

func TestManagedOLTsOtherRules(t *testing.T) {
	cases := map[string]string{
		"no state_dir":       `{"allowed_cidrs":["10.0.0.0/16"],"max_olts":4}`,
		"relative state_dir": `{"state_dir":"managed","allowed_cidrs":["10.0.0.0/16"],"max_olts":4}`,
		"unclean state_dir":  `{"state_dir":"/var/lib/x/../y","allowed_cidrs":["10.0.0.0/16"],"max_olts":4}`,
		"root state_dir":     `{"state_dir":"/","allowed_cidrs":["10.0.0.0/16"],"max_olts":4}`,
		"no max_olts":        `{"state_dir":"/var/lib/m","allowed_cidrs":["10.0.0.0/16"]}`,
		"max over 64":        `{"state_dir":"/var/lib/m","allowed_cidrs":["10.0.0.0/16"],"max_olts":65}`,
		"port 0":             `{"state_dir":"/var/lib/m","allowed_cidrs":["10.0.0.0/16"],"max_olts":4,"allowed_ports":[0]}`,
		"port 70000":         `{"state_dir":"/var/lib/m","allowed_cidrs":["10.0.0.0/16"],"max_olts":4,"allowed_ports":[70000]}`,
		"unknown vendor":     `{"state_dir":"/var/lib/m","allowed_cidrs":["10.0.0.0/16"],"max_olts":4,"allowed_vendors":["acme"]}`,
		"bad pon":            `{"state_dir":"/var/lib/m","allowed_cidrs":["10.0.0.0/16"],"max_olts":4,"pon_ports":["x"]}`,
		"unknown field":      `{"state_dir":"/var/lib/m","allowed_cidrs":["10.0.0.0/16"],"max_olts":4,"x":1}`,
	}
	for name, body := range cases {
		if _, err := Load(write(t, 0o600, managedCfg(body)), "v"); err == nil {
			t.Errorf("%s: expected an error", name)
		}
	}
}

func TestManagedOLTsNeedsTheSecretsChannel(t *testing.T) {
	_, err := Load(write(t, 0o600, good(`,"managed_olts":`+okManaged)), "v")
	if err == nil || !strings.Contains(err.Error(), "olt_secrets") {
		t.Fatalf("err=%v", err)
	}
}

func TestManagedStateDirIsExclusive(t *testing.T) {
	body := `{"state_dir":"/var/lib/fibercore-edge/keys","allowed_cidrs":["10.20.0.0/16"],"max_olts":16}` // the seal key lives in /var/lib/fibercore-edge/keys
	if _, err := Load(write(t, 0o600, managedCfg(body)), "v"); err == nil || !strings.Contains(err.Error(), "state_dir") {
		t.Fatalf("a state_dir that holds the seal key must be refused: %v", err)
	}
	cfg := `,"allowlist":["10.0.0.9:22"],"olts":[` + oltJSON(`,"credentials_file":"/var/lib/fibercore-edge/managed/creds/x.json"`) + `]`
	if _, err := Load(write(t, 0o600, secretsCfg(cfg+`,"managed_olts":`+okManaged)), "v"); err == nil || !strings.Contains(err.Error(), "state_dir") {
		t.Fatalf("a static credentials_file inside state_dir must be refused: %v", err)
	}
}
