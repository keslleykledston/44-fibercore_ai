package managedcollect

import (
	"bytes"
	"context"
	"encoding/base64"
	"errors"
	"fmt"
	"log/slog"
	"os"
	"path/filepath"
	"strings"
	"sync"
	"testing"

	"github.com/keslleykledston/44-fibercore_ai/agents/edge/internal/allowlist"
	"github.com/keslleykledston/44-fibercore_ai/agents/edge/internal/collector"
	"github.com/keslleykledston/44-fibercore_ai/agents/edge/internal/credfile"
	"github.com/keslleykledston/44-fibercore_ai/agents/edge/internal/managedolts"
	"github.com/keslleykledston/44-fibercore_ai/agents/edge/internal/olt"
)

var hostKey = "SHA256:" + base64.RawStdEncoding.EncodeToString(bytes.Repeat([]byte{7}, 32))

const (
	secUser = "admin-gerenciada"
	secPass = "S3nha-gerenciada!"
	secComm = "comunidade-ro"
)

type fileSession struct{}

func (fileSession) Run(_ context.Context, cmd string) (string, error) {
	m := map[string]string{
		"display version": "display_version.txt", "display ont info summary 0/1/0": "ont_info_summary_0_1_0.txt",
		"display ont optical-info 0/1/0 all": "ont_optical_0_1_0.txt",
	}
	n, ok := m[cmd]
	if !ok {
		return "", errors.New("unexpected " + cmd)
	}
	b, err := os.ReadFile(filepath.Join("..", "olt", "testdata", "huawei_ma5800", "R018", n))
	return string(b), err
}

type lockedBuf struct {
	mu sync.Mutex
	b  bytes.Buffer
}

func (l *lockedBuf) Write(p []byte) (int, error) {
	l.mu.Lock()
	defer l.mu.Unlock()
	return l.b.Write(p)
}
func (l *lockedBuf) String() string { l.mu.Lock(); defer l.mu.Unlock(); return l.b.String() }

type fx struct {
	t       *testing.T
	st      *managedolts.Store
	b       *Builder
	col     *collector.OLT
	logs    *lockedBuf
	opened  []olt.SSHConfig
	snmp    []olt.SNMPConfig
	cloudID int
}

func newFx(t *testing.T, mutPolicy func(*managedolts.Config)) *fx {
	t.Helper()
	f := &fx{t: t, logs: &lockedBuf{}}
	f.st = &managedolts.Store{Dir: filepath.Join(t.TempDir(), "state")}
	if err := f.st.Init(); err != nil {
		t.Fatal(err)
	}
	cfg := managedolts.Config{AllowedCIDRs: []string{"10.20.0.0/16"}, MaxOLTs: 6, PonPorts: []string{"0/1/0"}, AllowedPorts: []int{22, 161}}
	if mutPolicy != nil {
		mutPolicy(&cfg)
	}
	pol, err := managedolts.NewPolicy(cfg)
	if err != nil {
		t.Fatal(err)
	}
	al, _ := allowlist.New([]string{"10.0.0.9:22"})
	f.b = &Builder{Store: f.st, Policy: pol, Allow: al, Static: []Static{{Name: "ESTATICA", DeviceKey: "10.0.0.9"}}, Log: slog.New(slog.NewJSONHandler(f.logs, nil))}
	f.b.OpenSSH = func(_ context.Context, c olt.SSHConfig) (olt.Session, func(), error) {
		f.opened = append(f.opened, c)
		return fileSession{}, func() {}, nil
	}
	f.b.OpenSNMP = func(_ context.Context, c olt.SNMPConfig) (olt.SNMPReader, func(), error) {
		f.snmp = append(f.snmp, c)
		return nil, nil, errors.New("test: no snmp agent")
	}
	f.col = &collector.OLT{EdgeID: "e1", Extra: f.b.Sources}
	return f
}

func (f *fx) entry(name, addr string) managedolts.Entry {
	f.cloudID++
	return managedolts.Entry{Name: name, Vendor: "huawei", Address: addr, Port: 22, Protocol: "ssh", Transport: "cli", SNMPPort: 161, HostKeySHA256: hostKey, SSHMode: "exec",
		CloudID: fmt.Sprintf("5a1f3c52-0b6e-4f0e-9a52-%012d", f.cloudID)}
}

func (f *fx) add(e managedolts.Entry) {
	f.t.Helper()
	if _, err := f.st.Upsert(e); err != nil {
		f.t.Fatal(err)
	}
}

func (f *fx) trust(name string) {
	f.t.Helper()
	it, ok, err := f.st.Get(name)
	if err != nil || !ok {
		f.t.Fatal(err, ok)
	}
	if err := f.st.Trust(name, it.Entry.Digest()); err != nil {
		f.t.Fatal(err)
	}
}

func (f *fx) creds(name string) {
	f.t.Helper()
	if err := f.st.EnsureCredsDir(); err != nil {
		f.t.Fatal(err)
	}
	if err := credfile.Merge(f.st.CredsPath(name), credfile.Creds{Username: secUser, Password: secPass, SNMPCommunity: secComm}); err != nil {
		f.t.Fatal(err)
	}
}

func (f *fx) names() []string {
	var out []string
	for _, s := range f.b.Sources() {
		out = append(out, s.Name)
	}
	return out
}

func (f *fx) collect() ([]collector.Item, error) { return f.col.Collect(context.Background()) }

func TestOnlyTrustedOLTsAreCollectedAndTheRegistryIsReReadEveryRound(t *testing.T) {
	f := newFx(t, nil)
	if items, err := f.collect(); err != nil || len(items) != 0 {
		t.Fatalf("an empty registry collects nothing: %v %v", items, err)
	}
	e := f.entry("OLT-A", "10.20.1.5")
	f.add(e)
	f.creds("OLT-A")
	// awaiting the local trust: nothing is opened, nothing is read
	if items, err := f.collect(); err != nil || len(items) != 0 || len(f.opened) != 0 {
		t.Fatalf("an untrusted OLT must not be touched: %v %v opened=%d", items, err, len(f.opened))
	}
	// the operator trusts it: the SAME collector (no restart) collects it in the next round, with the delivered credentials and the pinned key
	f.trust("OLT-A")
	items, err := f.collect()
	if err != nil || len(items) != 1 || items[0].Kind != "olt_snapshot" || items[0].Key != "olt:OLT-A" {
		t.Fatalf("items=%v err=%v", items, err)
	}
	if len(f.opened) != 1 {
		t.Fatalf("opened %d", len(f.opened))
	}
	c := f.opened[0]
	if c.Addr != "10.20.1.5:22" || c.User != secUser || c.Password != secPass || c.HostKeySHA256 != hostKey || c.Shell || c.Legacy || c.Dial == nil {
		t.Fatalf("%+v", c)
	}
	// a second OLT appears while the Edge runs
	e2 := f.entry("OLT-B", "10.20.1.6")
	f.add(e2)
	f.creds("OLT-B")
	f.trust("OLT-B")
	if got := f.names(); len(got) != 2 || got[0] != "OLT-A" || got[1] != "OLT-B" {
		t.Fatalf("%v", got)
	}
	// and one is removed: gone in the next round
	if _, err := f.st.Remove("OLT-A", ""); err != nil {
		t.Fatal(err)
	}
	if got := f.names(); len(got) != 1 || got[0] != "OLT-B" {
		t.Fatalf("%v", got)
	}
	if strings.Contains(f.logs.String(), secPass) || strings.Contains(f.logs.String(), secUser) {
		t.Fatal("a credential reached the log")
	}
}

func TestTheSnapshotCarriesTheManagedNameAndTheCloudID(t *testing.T) {
	f := newFx(t, nil)
	e := f.entry("OLT-A", "10.20.1.5")
	f.add(e)
	f.creds("OLT-A")
	f.trust("OLT-A")
	src := f.b.Sources()
	if len(src) != 1 || src[0].CloudID != e.CloudID || src[0].Name != "OLT-A" || len(src[0].Ports) != 1 {
		t.Fatalf("%+v", src)
	}
}

func TestOnlyTheExactIPAndPortOfEachTrustedOLTIsDialable(t *testing.T) {
	f := newFx(t, nil)
	f.add(f.entry("OLT-A", "10.20.1.5"))
	f.creds("OLT-A")
	f.trust("OLT-A")
	e := f.entry("OLT-SNMP", "10.20.1.6")
	e.Transport = "snmp"
	f.add(e)
	f.creds("OLT-SNMP")
	f.trust("OLT-SNMP")
	f.add(f.entry("OLT-NOVA", "10.20.1.7")) // not trusted: not dialable
	f.col.Collect(context.Background())
	if len(f.opened) != 1 || len(f.snmp) != 1 {
		t.Fatalf("ssh=%d snmp=%d", len(f.opened), len(f.snmp))
	}
	ssh, snmp := f.opened[0], f.snmp[0]
	if snmp.Addr != "10.20.1.6:161" || snmp.Community != secComm {
		t.Fatalf("%+v", snmp)
	}
	for _, hp := range []string{"10.20.1.6:161", "10.20.1.5:22", "10.0.0.9:22"} { // the SNMP one, the ssh one, and the static allowlist
		if !snmp.Allowed(hp) {
			t.Errorf("%s must be dialable", hp)
		}
	}
	for _, hp := range []string{"10.20.1.6:22", "10.20.1.5:161", "10.20.1.7:22", "10.20.1.8:22", "10.20.1.5:2222", "8.8.8.8:22", "10.0.0.9:2222", "127.0.0.1:22", "[::1]:22"} {
		if snmp.Allowed(hp) {
			t.Errorf("%s must NOT be dialable", hp)
		}
	}
	for _, hp := range []string{"10.20.1.7:22", "10.20.1.5:2222", "8.8.8.8:22", "10.20.1.6:22", "169.254.169.254:80", "olt.example.com:22"} { // the real dialer: refused before any resolution or connection
		if _, err := ssh.Dial(context.Background(), "tcp", hp); !errors.Is(err, allowlist.ErrDenied) {
			t.Errorf("%s: %v", hp, err)
		}
	}
}

func TestAHandEditedRegistryOrATamperedTrustCollectsNothing(t *testing.T) {
	f := newFx(t, nil)
	e := f.entry("OLT-A", "10.20.1.5")
	f.add(e)
	f.creds("OLT-A")
	f.trust("OLT-A")
	// edit the address of the trusted entry by hand
	reg := filepath.Join(f.st.Dir, managedolts.RegistryFile)
	b, _ := os.ReadFile(reg)
	if err := os.WriteFile(reg, bytes.Replace(b, []byte("10.20.1.5"), []byte("10.20.1.99"), 1), 0o600); err != nil {
		t.Fatal(err)
	}
	if got := f.names(); len(got) != 0 {
		t.Fatalf("a hand-edited address must not be collected: %v", got)
	}
	f.collect()
	if len(f.opened) != 0 {
		t.Fatal("a session was opened")
	}
	// a hand-added, perfectly valid entry is not trusted either
	os.WriteFile(reg, b, 0o600)
	x := f.entry("MANUAL", "10.20.7.7")
	f.add(x)
	f.creds("MANUAL")
	if got := f.names(); len(got) != 1 || got[0] != "OLT-A" {
		t.Fatalf("%v", got)
	}
}

func TestTheTrustIsCheckedAgainWhenTheSessionOpens(t *testing.T) {
	f := newFx(t, nil)
	e := f.entry("OLT-A", "10.20.1.5")
	f.add(e)
	f.creds("OLT-A")
	f.trust("OLT-A")
	src := f.b.Sources()
	if len(src) != 1 {
		t.Fatal("setup")
	}
	// the Cloud changes the host key (trust is cleared) after the round started: the open must refuse
	e.HostKeySHA256 = "SHA256:" + base64.RawStdEncoding.EncodeToString(bytes.Repeat([]byte{9}, 32))
	f.add(e)
	if _, _, err := src[0].Open(context.Background()); !errors.Is(err, ErrNotTrusted) || len(f.opened) != 0 {
		t.Fatalf("err=%v opened=%d", err, len(f.opened))
	}
	// a removed OLT likewise
	f.add(f.entry("OLT-B", "10.20.1.6"))
	f.creds("OLT-B")
	f.trust("OLT-B")
	srcB := f.b.Sources()
	f.st.Remove("OLT-B", "")
	for _, s := range srcB {
		if s.Name == "OLT-B" {
			if _, _, err := s.Open(context.Background()); !errors.Is(err, ErrNotTrusted) {
				t.Fatalf("err=%v", err)
			}
		}
	}
}

func TestThePolicyIsAppliedAtEveryRoundNotOnlyWhenTheDeliveryArrived(t *testing.T) {
	f := newFx(t, nil)
	f.add(f.entry("OLT-A", "10.20.1.5"))
	f.creds("OLT-A")
	f.trust("OLT-A")
	if len(f.names()) != 1 {
		t.Fatal("setup")
	}
	// the administrator narrows the policy later: the OLT is out
	for name, mut := range map[string]func(*managedolts.Config){
		"cidr":   func(c *managedolts.Config) { c.AllowedCIDRs = []string{"10.30.0.0/16"} },
		"port":   func(c *managedolts.Config) { c.AllowedPorts = []int{2222} },
		"vendor": func(c *managedolts.Config) { c.AllowedVendors = []string{"zte"} },
	} {
		cfg := managedolts.Config{AllowedCIDRs: []string{"10.20.0.0/16"}, MaxOLTs: 6, PonPorts: []string{"0/1/0"}}
		mut(&cfg)
		pol, err := managedolts.NewPolicy(cfg)
		if err != nil {
			t.Fatal(err)
		}
		f.b.Policy = pol
		if got := f.names(); len(got) != 0 {
			t.Errorf("%s: %v", name, got)
		}
	}
}

func TestSkipsAndCaps(t *testing.T) {
	f := newFx(t, func(c *managedolts.Config) { c.MaxOLTs = 3 }) // 1 static => 2 managed
	for i, n := range []string{"M1", "M2", "M3"} {
		f.add(f.entry(n, fmt.Sprintf("10.20.1.%d", 10+i)))
		f.creds(n)
		f.trust(n)
	}
	if got := f.names(); len(got) != 2 {
		t.Fatalf("the maximum counts the static OLTs: %v", got)
	}
	// a managed OLT on the static device or with the static name is never collected
	f2 := newFx(t, func(c *managedolts.Config) { c.AllowedCIDRs = []string{"10.0.0.0/8"} })
	f2.add(f2.entry("DOBRA", "10.0.0.9"))
	f2.trust("DOBRA")
	f2.add(f2.entry("ESTATICA", "10.20.1.50"))
	f2.trust("ESTATICA")
	if got := f2.names(); len(got) != 0 {
		t.Fatalf("%v", got)
	}
	// no pon_ports: trusted but not collected, and it says so
	f3 := newFx(t, func(c *managedolts.Config) { c.PonPorts = nil })
	f3.add(f3.entry("SEM-PON", "10.20.1.5"))
	f3.trust("SEM-PON")
	if got := f3.names(); len(got) != 0 || !strings.Contains(f3.logs.String(), "pon_ports") {
		t.Fatalf("%v %s", got, f3.logs.String())
	}
}

func TestMissingOrLooseCredentialsFailTheSessionBeforeAnyConnection(t *testing.T) {
	f := newFx(t, nil)
	f.add(f.entry("OLT-A", "10.20.1.5"))
	f.trust("OLT-A")
	_, err := f.collect()
	if err == nil || len(f.opened) != 0 {
		t.Fatalf("no credentials delivered yet: err=%v opened=%d", err, len(f.opened))
	}
	f.creds("OLT-A")
	os.Chmod(f.st.CredsPath("OLT-A"), 0o644)
	if src := f.b.Sources(); len(src) != 1 {
		t.Fatal("setup")
	} else if _, _, err := src[0].Open(context.Background()); err == nil || len(f.opened) != 0 || strings.Contains(err.Error(), secPass) {
		t.Fatalf("a loose credentials file must fail closed: %v", err)
	}
}

func TestAnUnreadableRegistryCollectsNothingAndWarnsOnce(t *testing.T) {
	f := newFx(t, nil)
	f.add(f.entry("OLT-A", "10.20.1.5"))
	f.trust("OLT-A")
	os.Chmod(filepath.Join(f.st.Dir, managedolts.RegistryFile), 0o644)
	for i := 0; i < 3; i++ {
		if got := f.names(); len(got) != 0 {
			t.Fatalf("%v", got)
		}
	}
	if n := strings.Count(f.logs.String(), "registry cannot be used"); n != 1 {
		t.Fatalf("warned %d times", n)
	}
}

func TestSSHModeAndLegacyReachTheSession(t *testing.T) {
	f := newFx(t, func(c *managedolts.Config) { c.AllowLegacySSH = true })
	e := f.entry("OLT-A", "10.20.1.5")
	e.SSHMode, e.LegacySSH = "shell", true
	f.add(e)
	f.creds("OLT-A")
	f.trust("OLT-A")
	src := f.b.Sources()
	if _, _, err := src[0].Open(context.Background()); err != nil {
		t.Fatal(err)
	}
	if c := f.opened[0]; !c.Shell || !c.Legacy {
		t.Fatalf("%+v", c)
	}
}
