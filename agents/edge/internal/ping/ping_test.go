package ping

import "testing"

func okCfg() Config {
	return Config{Enabled: true, CoreCIDRs: []string{"10.20.0.0/16"}, Targets: []TargetConfig{
		{ID: "core-lab", Kind: "CORE", Host: "10.20.5.9"}, {ID: "dns-publico", Kind: "INTERNET", Host: "9.9.9.9"}}}
}

func TestCatalogAcceptsCoreInsidePrefixesAndPublicInternetAndNothingElse(t *testing.T) {
	c, err := New(okCfg())
	if err != nil {
		t.Fatal(err)
	}
	if tg, ok := c.Target("core-lab"); !ok || tg.Addr.String() != "10.20.5.9" || tg.Kind != "CORE" {
		t.Fatalf("%+v %v", tg, ok)
	}
	if c.Check("dns-publico") != nil || c.Check("nao-existe") != ErrUnknownTarget {
		t.Fatal("Check must accept only listed ids")
	}
	if got := c.All(); len(got) != 2 || got[0].ID != "core-lab" {
		t.Fatalf("stable order: %+v", got)
	}
}

func TestCatalogRefusesEveryUnsafeOrMalformedEntry(t *testing.T) {
	cases := map[string]func(*Config){
		"empty":                  func(c *Config) { c.Targets = nil },
		"too many":               func(c *Config) { c.Targets = make([]TargetConfig, 9) },
		"bad id":                 func(c *Config) { c.Targets[0].ID = "Core Lab" },
		"duplicate":              func(c *Config) { c.Targets[1].ID = "core-lab" },
		"kind":                   func(c *Config) { c.Targets[0].Kind = "EDGE" },
		"a name, not a literal":  func(c *Config) { c.Targets[1].Host = "dns.example.test" },
		"loopback":               func(c *Config) { c.Targets[1].Host = "127.0.0.1" },
		"metadata/link-local":    func(c *Config) { c.Targets[1].Host = "169.254.169.254" },
		"multicast":              func(c *Config) { c.Targets[1].Host = "224.0.0.1" },
		"internet but private":   func(c *Config) { c.Targets[1].Host = "192.168.1.1" },
		"internet but cgnat":     func(c *Config) { c.Targets[1].Host = "100.64.0.1" },
		"core outside prefixes":  func(c *Config) { c.Targets[0].Host = "10.99.0.1" },
		"prefix not canonical":   func(c *Config) { c.CoreCIDRs = []string{"10.20.5.9/16"} },
		"prefix too broad":       func(c *Config) { c.CoreCIDRs = []string{"0.0.0.0/0"} },
		"prefix covers metadata": func(c *Config) { c.CoreCIDRs = []string{"169.254.0.0/16"} },
		"ipv4-mapped ipv6":       func(c *Config) { c.Targets[1].Host = "::ffff:9.9.9.9" },
	}
	for name, mutate := range cases {
		c := okCfg()
		mutate(&c)
		if _, err := New(c); err == nil {
			t.Errorf("%s: must be refused", name)
		}
	}
}

func TestTheTestShapeIsFixedByTheEdge(t *testing.T) {
	if Repetitions != 5 || TimeoutMS != 1000 {
		t.Fatalf("ADR-0030 amendment Q1 fixes 5 repetitions and a 1000 ms timeout, got %d / %d", Repetitions, TimeoutMS)
	}
}
