package managedolts

import (
	"bytes"
	"encoding/base64"
	"fmt"
	"os"
	"path/filepath"
	"strings"
	"sync"
	"testing"
)

var hk = "SHA256:" + base64.RawStdEncoding.EncodeToString(bytes.Repeat([]byte{7}, 32))

func entry(name string) Entry {
	return Entry{Name: name, Vendor: "huawei", Address: "10.20.1.5", Port: 22, Protocol: "ssh", Transport: "cli", SNMPPort: 161, HostKeySHA256: hk, SSHMode: "exec",
		CloudID: "5a1f3c52-0b6e-4f0e-9a52-0a6f6a0c1111"}
}

func newStore(t *testing.T) *Store {
	t.Helper()
	d := filepath.Join(t.TempDir(), "state")
	s := &Store{Dir: d}
	if err := s.Init(); err != nil {
		t.Fatal(err)
	}
	return s
}

func TestCheckCIDR(t *testing.T) {
	for _, ok := range []string{"10.0.0.0/8", "10.20.0.0/16", "192.168.1.1/32", "fd00::/32", "2001:db8::/48"} {
		if _, err := CheckCIDR(ok); err != nil {
			t.Errorf("%s: %v", ok, err)
		}
	}
	for _, bad := range []string{"0.0.0.0/0", "::/0", "10.0.0.0/7", "0.0.0.0/1", "fd00::/31", "::ffff:10.0.0.0/104", "10.0.0.1", "x/8", "", "10.0.0.0/33", "fe80::1%eth0/64"} {
		if _, err := CheckCIDR(bad); err == nil {
			t.Errorf("%q must be refused", bad)
		}
	}
	if p, _ := CheckCIDR("10.20.1.5/16"); p.String() != "10.20.0.0/16" {
		t.Fatalf("masked form: %v", p)
	}
}

func TestSpecialAddresses(t *testing.T) {
	for _, s := range []string{"127.0.0.1", "127.8.8.8", "::1", "0.0.0.0", "::", "224.0.0.1", "ff02::1", "169.254.1.1", "fe80::1", "255.255.255.255", "0.1.2.3", "ff01::1"} {
		a, ok := ParseLiteral(s)
		if !ok || !SpecialAddress(a) {
			t.Errorf("%s must be special", s)
		}
	}
	for _, s := range []string{"10.20.1.5", "192.168.0.1", "fd00::5", "8.8.8.8"} {
		if a, ok := ParseLiteral(s); !ok || SpecialAddress(a) {
			t.Errorf("%s must be ordinary", s)
		}
	}
}

func TestPolicyCheckOrderAndCodes(t *testing.T) {
	p, err := NewPolicy(Config{AllowedCIDRs: []string{"10.20.0.0/16"}, MaxOLTs: 4, AllowedVendors: []string{"huawei"}})
	if err != nil {
		t.Fatal(err)
	}
	e := entry("A")
	if c := p.Check(e); c != "" {
		t.Fatal(c)
	}
	for name, mut := range map[string]struct {
		f    func(*Entry)
		code string
	}{
		"vendor":  {func(e *Entry) { e.Vendor = "acme" }, CodeVendorNotSupported},
		"allowed": {func(e *Entry) { e.Vendor = "zte" }, CodeVendorNotAllowed},
		"legacy":  {func(e *Entry) { e.LegacySSH = true }, CodeLegacyNotAllowed},
		"address": {func(e *Entry) { e.Address = "10.21.0.1" }, CodeAddressNotAllowed},
		"port":    {func(e *Entry) { e.Port = 23 }, CodePortNotAllowed},
		"snmp":    {func(e *Entry) { e.Transport = "snmp"; e.SNMPPort = 161 }, CodePortNotAllowed},
	} {
		x := entry("A")
		mut.f(&x)
		if c := p.Check(x); c != mut.code {
			t.Errorf("%s: got %q want %q", name, c, mut.code)
		}
	}
}

func TestNewPolicyReportsEveryProblem(t *testing.T) {
	_, err := NewPolicy(Config{AllowedCIDRs: []string{"0.0.0.0/0", "bad"}, AllowedPorts: []int{0}, MaxOLTs: 0, AllowedVendors: []string{"x"}, PonPorts: []string{"1"}})
	if err == nil {
		t.Fatal("expected errors")
	}
	for _, want := range []string{"allowed_cidrs", "allowed_ports", "max_olts", "allowed_vendors", "pon_ports"} {
		if !strings.Contains(err.Error(), want) {
			t.Errorf("missing %s in %v", want, err)
		}
	}
}

func TestDigestCoversExactlyTheConnectionFields(t *testing.T) {
	base := entry("A")
	d := base.Digest()
	changes := map[string]func(*Entry){
		"name": func(e *Entry) { e.Name = "B" }, "address": func(e *Entry) { e.Address = "10.20.1.6" }, "port": func(e *Entry) { e.Port = 2222 },
		"transport": func(e *Entry) { e.Transport = "snmp" }, "host key": func(e *Entry) { e.HostKeySHA256 = "SHA256:" + strings.Repeat("A", 43) },
		"snmp_port": func(e *Entry) { e.SNMPPort = 162 }, "ssh_mode": func(e *Entry) { e.SSHMode = "shell" }, "legacy": func(e *Entry) { e.LegacySSH = true },
		"vendor": func(e *Entry) { e.Vendor = "zte" }, // the vendor picks the driver, i.e. the commands that run (Codex r1)
	}
	for name, f := range changes {
		x := base
		f(&x)
		if x.Digest() == d {
			t.Errorf("%s must change the digest", name)
		}
	}
	for name, f := range map[string]func(*Entry){"cloud_id": func(e *Entry) { e.CloudID = "5a1f3c52-0b6e-4f0e-9a52-0a6f6a0c2222" }} {
		x := base
		f(&x)
		if x.Digest() != d {
			t.Errorf("%s must NOT change the digest", name)
		}
	}
	// length prefixes: no value can slide into its neighbour
	a, b := base, base
	a.Name, a.Address = "ab", "10.20.1.5"
	b.Name, b.Address = "a", "b10.20.1.5"
	if a.Digest() == b.Digest() {
		t.Fatal("fields must not be ambiguous")
	}
}

func TestEntryValidateAndNames(t *testing.T) {
	if err := entry("OLT Centro Ação").Validate(); err != nil {
		t.Fatal(err)
	}
	for _, n := range []string{"", " x", "x ", "a\nb", "a\x1b[31mb", "a‮b", "a\x00", strings.Repeat("x", 129), "\xff"} {
		if entry(n).Validate() == nil {
			t.Errorf("%q must be refused", n)
		}
	}
	x := entry("A")
	x.Address = "010.20.1.5"
	if x.Validate() == nil {
		t.Fatal("non canonical address")
	}
	x = entry("A")
	x.Address = "::ffff:10.20.1.5"
	if x.Validate() == nil {
		t.Fatal("mapped address")
	}
	x = entry("A")
	x.Protocol = "telnet"
	if x.Validate() == nil {
		t.Fatal("telnet entry")
	}
}

func TestHostKeyFormat(t *testing.T) {
	if !ValidHostKey(hk) {
		t.Fatal("valid")
	}
	for _, bad := range []string{"", "SHA256:", "SHA256:abc", hk + "=", hk[:len(hk)-1], "sha256:" + hk[7:], "MD5:" + hk[7:], hk[:len(hk)-1] + "B", "SHA256:" + strings.Repeat("!", 43)} {
		if ValidHostKey(bad) {
			t.Errorf("%q must be refused", bad)
		}
	}
}

func TestStoreInitIsPrivateAndRefusesLooseDirectories(t *testing.T) {
	s := newStore(t)
	for _, d := range []string{s.Dir, filepath.Join(s.Dir, "creds")} {
		if fi, err := os.Stat(d); err != nil || fi.Mode().Perm() != 0o700 {
			t.Fatalf("%s: %v %v", d, fi, err)
		}
	}
	loose := filepath.Join(t.TempDir(), "loose")
	if err := os.Mkdir(loose, 0o755); err != nil {
		t.Fatal(err)
	}
	os.Chmod(loose, 0o755)
	if err := (&Store{Dir: loose}).Init(); err == nil {
		t.Fatal("a state directory open to group/others must be refused")
	}
	if err := (&Store{Dir: "relative"}).Init(); err == nil {
		t.Fatal("a relative state directory must be refused")
	}
	// a state directory that is a symlink to somewhere else is a directory we own only if the target is: still 0700 required
}

func TestUpsertListRemoveRoundTripAndFileModes(t *testing.T) {
	s := newStore(t)
	if l, err := s.List(); err != nil || len(l) != 0 {
		t.Fatalf("%v %v", l, err)
	}
	r, err := s.Upsert(entry("B"))
	if err != nil || !r.Created || !r.Changed || r.TrustCleared {
		t.Fatalf("%+v %v", r, err)
	}
	if _, err := s.Upsert(entry("A")); err != nil {
		t.Fatal(err)
	}
	l, _ := s.List()
	if len(l) != 2 || l[0].Entry.Name != "A" || l[1].Entry.Name != "B" || l[0].Trusted {
		t.Fatalf("%+v", l)
	}
	if fi, _ := os.Stat(filepath.Join(s.Dir, RegistryFile)); fi.Mode().Perm() != 0o600 {
		t.Fatalf("mode %v", fi.Mode().Perm())
	}
	if r, _ := s.Upsert(entry("A")); r.Changed || r.Created {
		t.Fatalf("an identical upsert is a no-op: %+v", r)
	}
	if err := s.Trust("A", entry("A").Digest()); err != nil {
		t.Fatal(err)
	}
	if fi, _ := os.Stat(filepath.Join(s.Dir, TrustFile)); fi.Mode().Perm() != 0o600 {
		t.Fatalf("trust mode %v", fi.Mode().Perm())
	}
	it, ok, _ := s.Get("A")
	if !ok || !it.Trusted || it.State() != StateTrusted {
		t.Fatalf("%+v", it)
	}
	id, err := s.Remove("A", "")
	if err != nil || id != entry("A").CloudID {
		t.Fatalf("%q %v", id, err)
	}
	if id, err := s.Remove("A", ""); err != nil || id != "" {
		t.Fatalf("a second remove is a no-op: %q %v", id, err)
	}
	if l, _ := s.List(); len(l) != 1 {
		t.Fatalf("%+v", l)
	}
}

func TestTrustRefusesWhatChangedAfterItWasShown(t *testing.T) {
	s := newStore(t)
	e := entry("A")
	s.Upsert(e)
	shown := e.Digest()
	e.Address = "10.20.1.77" // the Cloud changes it between the display and the confirmation
	s.Upsert(e)
	if err := s.Trust("A", shown); err != ErrChanged {
		t.Fatalf("err=%v", err)
	}
	if it, _, _ := s.Get("A"); it.Trusted {
		t.Fatal("must stay untrusted")
	}
	if err := s.Trust("ZZ", shown); err != ErrNotFound {
		t.Fatalf("err=%v", err)
	}
}

func TestStateFilesAreFailClosed(t *testing.T) {
	s := newStore(t)
	s.Upsert(entry("A"))
	reg := filepath.Join(s.Dir, RegistryFile)
	good, _ := os.ReadFile(reg)
	bad := map[string]func(){
		"loose mode":    func() { os.Chmod(reg, 0o644) },
		"not json":      func() { os.WriteFile(reg, []byte("{"), 0o600) },
		"unknown field": func() { os.WriteFile(reg, []byte(`{"v":1,"olts":[],"x":1}`), 0o600) },
		"version":       func() { os.WriteFile(reg, []byte(`{"v":2,"olts":[]}`), 0o600) },
		"trailing":      func() { os.WriteFile(reg, append(append([]byte{}, good...), []byte(`{}`)...), 0o600) },
		"dup name": func() {
			os.WriteFile(reg, []byte(`{"v":1,"olts":[`+strings.Repeat(string(good[len(`{"v":1,"olts":[`):len(good)-2])+",", 2)+`]}`), 0o600)
		},
		"a link": func() { os.Remove(reg); os.Symlink(filepath.Join(s.Dir, "other"), reg) },
	}
	for name, f := range bad {
		os.Remove(reg)
		os.WriteFile(reg, good, 0o600)
		os.Chmod(reg, 0o600)
		f()
		if _, err := s.List(); err == nil {
			t.Errorf("%s: a registry like this must be refused", name)
		}
	}
	os.Remove(reg)
	os.WriteFile(reg, good, 0o600)
	if _, err := s.List(); err != nil {
		t.Fatal(err)
	}
	tr := filepath.Join(s.Dir, TrustFile)
	for name, body := range map[string]string{"bad digest": `{"v":1,"trusted":[{"name":"A","digest":"zz","at":1}]}`, "version": `{"v":3,"trusted":[]}`, "not json": `x`} {
		os.WriteFile(tr, []byte(body), 0o600)
		if _, err := s.List(); err == nil {
			t.Errorf("trust %s must be refused", name)
		}
	}
	// a loose directory
	os.Remove(tr)
	os.Chmod(s.Dir, 0o755)
	if _, err := s.List(); err == nil {
		t.Fatal("a state directory open to others must be refused")
	}
	os.Chmod(s.Dir, 0o700)
}

func TestConcurrentWritersNeverLoseAnUpdate(t *testing.T) {
	s := newStore(t)
	var wg sync.WaitGroup
	for i := 0; i < 12; i++ {
		wg.Add(1)
		go func(i int) {
			defer wg.Done()
			e := entry(string(rune('A' + i)))
			e.Address = fmt.Sprintf("10.20.%d.1", i)
			e.CloudID = fmt.Sprintf("5a1f3c52-0b6e-4f0e-9a52-%012x", i)
			if _, err := s.Upsert(e); err != nil {
				t.Error(err)
			}
		}(i)
	}
	wg.Wait()
	if l, err := s.List(); err != nil || len(l) != 12 {
		t.Fatalf("%d %v", len(l), err)
	}
}

func TestCredsFileName(t *testing.T) {
	if CredsFileName("OLT-CENTRO-01") != "OLT-CENTRO-01.json" {
		t.Fatal("ordinary name")
	}
	seen := map[string]string{}
	for _, n := range []string{"a b", "a_b", "a  b", "../x", "..", ".", "a/b", "a\\b", "ção", ".hid", "-x", "x~y", strings.Repeat("y", 100), "OLT 1", "OLT_1"} {
		f := CredsFileName(n)
		if strings.ContainsAny(f, `/\`) || strings.HasPrefix(f, ".") || len(f) > 64 || !strings.HasSuffix(f, ".json") {
			t.Errorf("%q -> %q", n, f)
		}
		if prev, dup := seen[f]; dup {
			t.Errorf("%q and %q share %q", n, prev, f)
		}
		seen[f] = n
	}
}
