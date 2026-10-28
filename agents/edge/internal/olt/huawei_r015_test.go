package olt

import (
	"context"
	"errors"
	"io"
	"net"
	"os"
	"reflect"
	"regexp"
	"strings"
	"sync"
	"testing"
	"time"

	"golang.org/x/crypto/ssh"
)

const r015Dir = "testdata/huawei_ma5608t/MA5600V800R015C00/"

func r015Text(t *testing.T, name string) string {
	t.Helper()
	b, err := os.ReadFile(r015Dir + name)
	if err != nil {
		t.Fatal(err)
	}
	return stripCtl(eraseMarkers(string(b)))
}

var pon14 = r015Port{path: "0/0/14", f: "0", s: "0", p: "14"}

func TestR015RealCaptureParsesAndIsProvenComplete(t *testing.T) {
	onus, pon := parseR015Port(pon14, r015Text(t, "ont_info_14_all_paged.txt"), r015Text(t, "ont_optical_info_14_all.txt"))
	if len(onus) != 12 || !pon.Verified || pon.Status != "up" || pon.Path != "0/0/14" {
		t.Fatalf("onus=%d pon=%+v", len(onus), pon)
	}
	on := 0
	for _, u := range onus {
		switch u.Status {
		case "online":
			on++
			if u.RxDBm == nil {
				t.Errorf("online ONU %s lost its Rx reading", u.Serial)
			}
		case "offline":
			if u.RxDBm != nil {
				t.Errorf("offline ONU %s must not carry a reading", u.Serial)
			}
		default:
			t.Errorf("unexpected status %q", u.Status)
		}
		if !regexp.MustCompile(`^[0-9A-F]{16}$`).MatchString(u.Serial) || u.PonPath != "0/0/14" {
			t.Errorf("bad ONU %+v", u)
		}
	}
	if on != 3 {
		t.Fatalf("online=%d want 3", on)
	}
	if onus[7].Status != "online" || *onus[7].RxDBm != -13.28 {
		t.Fatalf("ONT-ID 7 = %+v", onus[7])
	}
}

func TestR015IncompleteOrInconsistentListingIsNeverVerified(t *testing.T) {
	info, opt := r015Text(t, "ont_info_14_all_paged.txt"), r015Text(t, "ont_optical_info_14_all.txt")
	row3 := regexp.MustCompile(`(?m)^ *0/ 0/14 +3 .*\n`)
	for name, mut := range map[string]string{
		"a row is missing (truncated listing)":       row3.ReplaceAllString(info, ""),
		"footer missing":                             regexp.MustCompile(`(?m)^ *In port.*\n`).ReplaceAllString(info, ""),
		"footer total differs":                       strings.Replace(info, "total of ONTs are: 12", "total of ONTs are: 13", 1),
		"footer online differs":                      strings.Replace(info, "online: 3", "online: 4", 1),
		"footer names another port":                  strings.Replace(info, "In port 0/ 0/14", "In port 0/ 0/13", 1),
		"duplicated ONT-ID":                          strings.Replace(info, " 3  ", " 2  ", 1),
		"unknown run state":                          strings.Replace(info, "offline", "los    ", 1),
		"two footers (payload imitating the footer)": info + "\n  In port 0/ 0/14, the total of ONTs are: 12, online: 3\n",
	} {
		_, pon := parseR015Port(pon14, mut, opt)
		if pon.Verified {
			t.Errorf("%s: must not be verified", name)
		}
	}
	// a row from another port inside this listing is rejected, not silently attributed
	other := strings.Replace(info, "0/ 0/14   5", "0/ 0/13   5", 1)
	if onus, pon := parseR015Port(pon14, other, opt); pon.Verified || len(onus) != 11 {
		t.Errorf("foreign row: verified=%v onus=%d", pon.Verified, len(onus))
	}
}

func TestR015AllowlistIsExactAndSeparateFromGenericHuawei(t *testing.T) {
	r, g := HuaweiR015{}, Huawei{}
	for _, c := range []string{"enable", "config", "quit", "interface gpon 0/0", "display board 0", "display ont info 14 all", "display ont optical-info 14 all", "display version"} {
		if !r.Allowed(c) {
			t.Errorf("R015 must allow %q", c)
		}
	}
	for _, c := range []string{"undo ont add 14 1", "interface gpon 0/0 ; reboot", "interface gpon 0/0/1", "display ont info 14", "ont reset 14 1", "save",
		"commit", "scroll", "screen-length 0 temporary", "display current-configuration", "quit all", "enable 15", "config terminal", "display ont info 14 all extra"} {
		if r.Allowed(c) {
			t.Errorf("R015 must deny %q", c)
		}
	}
	for _, c := range []string{"enable", "config", "quit", "interface gpon 0/0", "display ont info 14 all"} {
		if g.Allowed(c) {
			t.Errorf("generic Huawei must deny CLI-mode command %q", c)
		}
	}
}

func TestProfilesRefuseTheWrongFamily(t *testing.T) {
	ma56 := stubSession{r015Text(t, "display_version.txt")}
	if _, err := (Huawei{}).Snapshot(context.Background(), ma56, []string{"0/0/14"}); err == nil || !strings.Contains(err.Error(), "huawei_ma56_r015") {
		t.Fatalf("generic driver must refuse an MA5600 and name the profile: %v", err)
	}
	ma58 := stubSession{"  VERSION : R018\n  PRODUCT : MA5800-X7\n"}
	if _, err := (HuaweiR015{}).Snapshot(context.Background(), ma58, []string{"0/0/14"}); err == nil {
		t.Fatal("the R015 profile must refuse a non-MA5600")
	}
}

type recSession struct {
	out  string
	sent *[]string
}

func (r recSession) Run(_ context.Context, cmd string) (string, error) {
	*r.sent = append(*r.sent, cmd)
	return r.out, nil
}

func TestR015ProfileRefusesOtherMA56ReleasesBeforeAnyModeCommand(t *testing.T) {
	var sent []string
	other := recSession{"  VERSION : MA5600V800R018C00\n  PRODUCT : MA5608T\n", &sent} // same model, different release
	if _, err := (HuaweiR015{}).Snapshot(context.Background(), other, []string{"0/0/14"}); err == nil || !strings.Contains(err.Error(), "R015") {
		t.Fatalf("another MA56 release must be refused: %v", err)
	}
	if !reflect.DeepEqual(sent, []string{"display version"}) {
		t.Fatalf("only display version may be sent to an unvalidated release, sent %v", sent)
	}
}

func TestR015FlowThroughRealShellWithPagerSpace(t *testing.T) {
	srv := startShellSSH(t, false)
	cfg := shellCfg(srv, false)
	cfg.PagerSpace = true
	s, err := DialSSH(context.Background(), cfg)
	if err != nil {
		t.Fatal(err)
	}
	defer s.Close()
	ro := ReadOnlySession{Inner: s, Allowed: HuaweiR015{}.Allowed}
	snap, err := HuaweiR015{}.Snapshot(context.Background(), ro, []string{"0/0/14"})
	if err != nil {
		t.Fatal(err)
	}
	if len(snap.ONUs) != 12 || len(snap.PONs) != 1 || !snap.PONs[0].Verified {
		t.Fatalf("snap: %d onus, pons=%+v", len(snap.ONUs), snap.PONs)
	}
	if snap.Identity.Model != "MA5608T" || snap.Identity.Firmware != "MA5600V800R015C00" {
		t.Fatalf("identity: %+v", snap.Identity)
	}
	srv.mu.Lock()
	defer srv.mu.Unlock()
	want := []string{"display version", "enable", "config", "interface gpon 0/0", "display ont info 14 all", "display ont optical-info 14 all", "quit"}
	if !reflect.DeepEqual(srv.cmds, want) {
		t.Fatalf("commands on the wire:\n got %v\nwant %v", srv.cmds, want)
	}
	if srv.spaces != 1 || srv.stray != 0 {
		t.Fatalf("pager keys: spaces=%d stray=%d (exactly one Space, nothing else)", srv.spaces, srv.stray)
	}
}

func intoGpon(t *testing.T, s *SSHSession) {
	t.Helper()
	for _, c := range []string{"enable", "config", "interface gpon 0/0"} {
		if _, err := s.Run(context.Background(), c); err != nil {
			t.Fatalf("%s: %v", c, err)
		}
	}
}

func TestPagerWithoutOptInFailsClosedAndSendsNoKey(t *testing.T) {
	srv := startShellSSH(t, false)
	s, err := DialSSH(context.Background(), shellCfg(srv, false)) // PagerSpace off
	if err != nil {
		t.Fatal(err)
	}
	defer s.Close()
	intoGpon(t, s)
	if _, err := s.Run(context.Background(), "display ont info 14 all"); !errors.Is(err, ErrPaginated) {
		t.Fatalf("want ErrPaginated, got %v", err)
	}
	srv.mu.Lock()
	defer srv.mu.Unlock()
	if srv.spaces != 0 || srv.stray != 0 {
		t.Fatalf("no key may be sent without the opt-in: spaces=%d stray=%d", srv.spaces, srv.stray)
	}
}

func TestPagerPageLimitAndUnerasedPagerFailClosed(t *testing.T) {
	srv := startShellSSH(t, false)
	cfg := shellCfg(srv, false)
	cfg.PagerSpace = true
	s, err := DialSSH(context.Background(), cfg)
	if err != nil {
		t.Fatal(err)
	}
	if _, err := s.Run(context.Background(), "display endless"); !errors.Is(err, ErrPaginated) {
		t.Fatalf("endless pager: want ErrPaginated, got %v", err)
	}
	s.Close()
	srv.mu.Lock()
	if srv.spaces != defaultMaxPages || srv.stray != 0 {
		t.Fatalf("spaces=%d stray=%d, want exactly %d Spaces", srv.spaces, srv.stray, defaultMaxPages)
	}
	srv.mu.Unlock()

	s2, err := DialSSH(context.Background(), cfg)
	if err != nil {
		t.Fatal(err)
	}
	defer s2.Close()
	if _, err := s2.Run(context.Background(), "display noerase"); !errors.Is(err, ErrPaginated) {
		t.Fatalf("a pager the device did not erase must fail closed, got %v", err)
	}
}

func TestEraseMarkersOnlyRemovesWhatTheDeviceErased(t *testing.T) {
	m := "---- More ( Press 'Q' to break ) ----"
	n := "\x1b[37D"
	if got := eraseMarkers("a\n" + m + n + strings.Repeat(" ", 37) + n + "b"); got != "a\nb" {
		t.Fatalf("got %q", got)
	}
	for name, in := range map[string]string{
		"no erase":          "a\n" + m + "b",
		"wrong distance":    "a\n" + m + "\x1b[10D" + strings.Repeat(" ", 10) + "\x1b[10D" + "b",
		"wrong blank count": "a\n" + m + n + strings.Repeat(" ", 5) + n + "b",
	} {
		if got := eraseMarkers(in); got != in {
			t.Errorf("%s: must be left untouched (and fail closed later), got %q", name, got)
		}
	}
}

func TestR015LargeRealPonsParseAndAreProvenComplete(t *testing.T) {
	for _, c := range []struct {
		file, path   string
		rows, online int
	}{
		{"ont_info_5_all_paged.txt", "0/0/5", 60, 26},    // 5 pager pages
		{"ont_info_12_all.txt", "0/0/12", 6, 5},          // fits one screen, no pager
		{"ont_info_s1_4_all_paged.txt", "0/1/4", 53, 36}, // second board, 4 pager pages
	} {
		f := strings.Split(c.path, "/")
		onus, pon := parseR015Port(r015Port{path: c.path, f: f[0], s: f[1], p: f[2]}, r015Text(t, c.file), "")
		on := 0
		for _, u := range onus {
			if u.Status == "online" {
				on++
			}
		}
		if len(onus) != c.rows || on != c.online || !pon.Verified {
			t.Errorf("%s: rows=%d online=%d verified=%v, want %d/%d verified", c.file, len(onus), on, pon.Verified, c.rows, c.online)
		}
		if Paginated(r015Text(t, c.file)) {
			t.Errorf("%s: pager text survived the erase", c.file)
		}
	}
}

func TestR015MultiPageRealPonsThroughRealShell(t *testing.T) {
	srv := startShellSSH(t, false)
	cfg := shellCfg(srv, false)
	cfg.PagerSpace = true
	s, err := DialSSH(context.Background(), cfg)
	if err != nil {
		t.Fatal(err)
	}
	defer s.Close()
	ro := ReadOnlySession{Inner: s, Allowed: HuaweiR015{}.Allowed}
	snap, err := HuaweiR015{}.Snapshot(context.Background(), ro, []string{"0/0/5", "0/0/12"})
	if err != nil {
		t.Fatal(err)
	}
	if len(snap.ONUs) != 66 || len(snap.PONs) != 2 || !snap.PONs[0].Verified || !snap.PONs[1].Verified {
		t.Fatalf("onus=%d pons=%+v", len(snap.ONUs), snap.PONs)
	}
	b, _ := os.ReadFile(r015Dir + "ont_info_5_all_paged.txt")
	want := strings.Count(string(b), "More (")
	srv.mu.Lock()
	defer srv.mu.Unlock()
	if want != 5 || srv.spaces != want || srv.stray != 0 {
		t.Fatalf("pager pages in capture=%d, Spaces sent=%d, stray keys=%d", want, srv.spaces, srv.stray)
	}
}

// The simulated device must behave like the real one at the pager, otherwise "no stray key" assertions prove nothing:
// only Space advances; Q breaks the listing and the footer never arrives.
func TestSimulatedPagerOnlyAdvancesOnSpaceAndQBreaksTheListing(t *testing.T) {
	read := func(key string) string {
		srv := startShellSSH(t, false)
		conn, err := ssh.Dial("tcp", srv.addr, &ssh.ClientConfig{User: "u", Auth: []ssh.AuthMethod{ssh.Password("pw")},
			HostKeyCallback: func(_ string, _ net.Addr, k ssh.PublicKey) error {
				if ssh.FingerprintSHA256(k) != srv.fp {
					return errors.New("host key")
				}
				return nil
			}})
		if err != nil {
			t.Fatal(err)
		}
		defer conn.Close()
		sess, _ := conn.NewSession()
		_ = sess.RequestPty("vt100", 512, 200, ssh.TerminalModes{})
		in, _ := sess.StdinPipe()
		out, _ := sess.StdoutPipe()
		_ = sess.Shell()
		var mu sync.Mutex
		var got strings.Builder
		go func() {
			b := make([]byte, 4096)
			for {
				n, err := out.Read(b)
				mu.Lock()
				got.Write(b[:n])
				mu.Unlock()
				if err != nil {
					return
				}
			}
		}()
		snap := func() string { mu.Lock(); defer mu.Unlock(); return got.String() }
		wait := func(sub string) {
			for i := 0; i < 100 && !strings.Contains(snap(), sub); i++ {
				time.Sleep(50 * time.Millisecond)
			}
		}
		wait("OLT-TEST-1>")
		for _, c := range []string{"enable", "config", "interface gpon 0/0"} {
			io.WriteString(in, c+"\r")
			time.Sleep(200 * time.Millisecond)
		}
		io.WriteString(in, "display ont info 5 all\r")
		wait("More (")
		io.WriteString(in, key)
		time.Sleep(800 * time.Millisecond)
		return snap()
	}
	if got := read("q"); strings.Contains(got, "In port") {
		t.Fatal("a Q at the pager must break the listing: the footer must not arrive")
	}
	if got := read(" "); strings.Count(got, "More (") < 2 {
		t.Fatal("Space must advance to the next page")
	}
}
