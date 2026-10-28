package olt

import (
	"context"
	"errors"
	"os"
	"reflect"
	"regexp"
	"strings"
	"testing"
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
