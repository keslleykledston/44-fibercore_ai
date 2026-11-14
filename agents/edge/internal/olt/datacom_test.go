package olt

import (
	"context"
	"errors"
	"os"
	"path/filepath"
	"strings"
	"testing"
)

func dmRead(t *testing.T, name string) string {
	t.Helper()
	b, err := os.ReadFile(filepath.Join("testdata", "datacom_dmos", name))
	if err != nil {
		t.Fatal(err)
	}
	return string(b)
}

// dmSession answers from a map of command -> output and records what reaches the "device".
type dmSession struct {
	out  map[string]string
	sent []string
}

func (s *dmSession) Run(_ context.Context, cmd string) (string, error) {
	s.sent = append(s.sent, cmd)
	o, ok := s.out[cmd]
	if !ok {
		return "", errors.New("dmSession: no output for " + cmd)
	}
	return o, nil
}

func dmFixture(t *testing.T) *dmSession {
	return &dmSession{out: map[string]string{
		"show platform":                dmRead(t, "show_platform_dm4615_8.2.txt"),
		"show interface gpon | nomore": dmRead(t, "show_interface_gpon_all.txt"),
		dmOnuCmd("1/1/1"):              dmRead(t, "onu_list_pon1.txt"),
		dmOnuCmd("1/1/2"):              dmRead(t, "onu_list_pon2.txt"),
		dmOnuCmd("1/1/3"):              dmRead(t, "onu_list_pon3.txt"),
		dmOnuCmd("1/1/5"):              dmRead(t, "onu_list_pon5.txt"),
	}}
}

func TestDatacomPlatformGolden(t *testing.T) {
	for file, want := range map[string]Identity{
		"show_platform_dm4612_7.2.txt":    {Vendor: "datacom", Model: "DM4612", Firmware: "7.2.0-013-1-g1b8f1c9398"},
		"show_platform_dm4612_9.6.txt":    {Vendor: "datacom", Model: "DM4612", Firmware: "9.6.0-198-1-g0410437943"},
		"show_platform_dm4615_8.2.txt":    {Vendor: "datacom", Model: "DM4615", Firmware: "8.2.2-003-1-g2df4ad7b5a"},
		"show_platform_dm4610hw2_5.8.txt": {Vendor: "datacom", Model: "DM4610 HW2", Firmware: "5.8.0-065-1-g9b140cc569"},
	} {
		got, err := parseDatacomPlatform(dmRead(t, file))
		if err != nil || got != want {
			t.Errorf("%s: got %+v err %v want %+v", file, got, err, want)
		}
		lvl, err := Lookup(got)
		if err != nil || lvl != LevelIdentified {
			t.Errorf("%s: registry level %q err %v (must be identified, never observed)", file, lvl, err)
		}
	}
}

func TestDatacomPlatformFailsClosed(t *testing.T) {
	for name, out := range map[string]string{
		"syntax error": dmRead(t, "syntax_error.txt"),
		"empty":        "",
		"no active":    "Chassis/Slot  Product model  Role  Status  Firmware version\n1  DM4612  -  -  Not available\n",
	} {
		if _, err := parseDatacomPlatform(out); err == nil {
			t.Errorf("%s: want error", name)
		}
	}
}

func TestDatacomONUListGolden(t *testing.T) {
	onus, err := parseDatacomONUs(dmRead(t, "onu_list_pon2.txt"), "1/1/2")
	if err != nil || len(onus) != 11 {
		t.Fatalf("pon2: %d onus err %v", len(onus), err)
	}
	if onus[0].Status != "online" || onus[1].Status != "offline" || onus[1].Serial != "DACM00001014" || onus[1].OntID != 1 || !onus[1].HasOntID || onus[1].PonPath != "1/1/2" {
		t.Errorf("pon2 rows wrong: %+v %+v", onus[0], onus[1])
	}
	for _, u := range onus {
		if u.RxDBm != nil || u.LastDownAt != nil {
			t.Errorf("v1 must not invent optical/last-down data: %+v", u)
		}
	}
	// skipped IDs are normal (an ONU was removed): 2 -> 4 must not be an error
	onus, err = parseDatacomONUs(dmRead(t, "onu_list_pon3.txt"), "1/1/3")
	if err != nil || len(onus) != 15 || onus[3].OntID != 4 {
		t.Fatalf("pon3: %d err %v", len(onus), err)
	}
	onus, err = parseDatacomONUs(dmRead(t, "onu_list_pon1.txt"), "1/1/1")
	if err != nil || len(onus) != 20 {
		t.Fatalf("pon1: %d err %v", len(onus), err)
	}
}

func TestDatacomEmptyPONIsComplete(t *testing.T) {
	onus, err := parseDatacomONUs(dmRead(t, "onu_list_pon5.txt"), "1/1/5")
	if err != nil || onus == nil || len(onus) != 0 {
		t.Fatalf("no entries must be a complete empty PON: %v %v", onus, err)
	}
}

func TestDatacomNeverReadsBrokenOutputAsCompletePON(t *testing.T) {
	good := dmRead(t, "onu_list_pon2.txt")
	lines := strings.Split(strings.TrimRight(good, "\n"), "\n")
	last := lines[len(lines)-1]
	head := strings.Join(lines[:len(lines)-1], "\n") + "\n"
	for name, out := range map[string]string{
		"syntax error":        dmRead(t, "syntax_error.txt"),
		"empty":               "",
		"blank":               "\n\n",
		"pager":               good + "--More--\n",
		"pager vrp style":     good + "---- More ( Press 'Q' to break ) ----\n",
		"no header":           strings.Join(lines[2:], "\n") + "\n",
		"header only":         strings.Join(lines[:2], "\n") + "\n",
		"truncated last row":  head + last[:18],
		"cut mid serial":      head + last[:30],
		"foreign pon row":     strings.Replace(good, "1/1/2     12 ", "1/1/3     12 ", 1),
		"repeated id":         good + lines[2] + "\n",
		"id out of range":     good + "1/1/2     128      HWTC00009999    Up           None\n",
		"no entries + noise":  "% No entries found.\nextra\n",
		"no entries + header": strings.Join(lines[:2], "\n") + "\n% No entries found.\n",
		"unknown prompt":      "Error: command failed\n",
	} {
		if onus, err := parseDatacomONUs(out, "1/1/2"); err == nil {
			t.Errorf("%s: parsed as complete PON with %d onus", name, len(onus))
		}
	}
	if _, err := parseDatacomONUs(good+"--More--\n", "1/1/2"); !errors.Is(err, ErrPaginated) {
		t.Errorf("pager must surface ErrPaginated, got %v", err)
	}
}

func TestDatacomSnapshotGolden(t *testing.T) {
	raw := dmFixture(t)
	d := Datacom{}
	snap, err := d.Snapshot(context.Background(), ReadOnlySession{Inner: raw, Allowed: d.Allowed}, []string{"1/1/1", "1/1/2", "1/1/3", "1/1/5"})
	if err != nil {
		t.Fatal(err)
	}
	if snap.Identity.Model != "DM4615" || len(snap.PONs) != 4 || len(snap.ONUs) != 20+11+15 {
		t.Fatalf("snap identity=%+v pons=%d onus=%d", snap.Identity, len(snap.PONs), len(snap.ONUs))
	}
	for _, p := range snap.PONs {
		if p.Status != "up" || !p.Verified {
			t.Errorf("pon %+v", p)
		}
	}
	var off, on int
	for _, u := range snap.ONUs {
		switch u.Status {
		case "offline":
			off++
		case "online":
			on++
		}
	}
	if off+on != len(snap.ONUs) || off < 2 {
		t.Errorf("online=%d offline=%d of %d", on, off, len(snap.ONUs))
	}
	for _, c := range raw.sent {
		if !d.Allowed(c) || !SafeCommand(c) {
			t.Errorf("sent non-allowlisted command %q", c)
		}
	}
}

func TestDatacomSnapshotDiscoversPONsFromInterfaceListing(t *testing.T) {
	raw := dmFixture(t)
	for _, n := range []string{"4", "6", "7", "8"} { // not captured; the CLI's own "no entries" keeps this test about discovery
		raw.out[dmOnuCmd("1/1/"+n)] = "% No entries found.\n"
	}
	d := Datacom{}
	snap, err := d.Snapshot(context.Background(), ReadOnlySession{Inner: raw, Allowed: d.Allowed}, nil)
	if err != nil {
		t.Fatal(err)
	}
	if len(snap.PONs) != 8 || snap.PONs[0].Path != "1/1/1" || snap.PONs[7].Path != "1/1/8" {
		t.Fatalf("pons=%+v", snap.PONs)
	}
}

func TestDatacomSnapshotFailsClosed(t *testing.T) {
	d := Datacom{}
	// a PON that errors aborts the snapshot: no partial inventory presented as complete
	raw := dmFixture(t)
	raw.out[dmOnuCmd("1/1/2")] = dmRead(t, "onu_list_pon2.txt") + "--More--\n"
	_, err := d.Snapshot(context.Background(), ReadOnlySession{Inner: raw, Allowed: d.Allowed}, []string{"1/1/1", "1/1/2"})
	if !errors.Is(err, ErrPaginated) {
		t.Errorf("paged pon: %v", err)
	}
	raw = dmFixture(t)
	raw.out["show interface gpon | nomore"] = dmRead(t, "syntax_error.txt")
	if _, err = d.Snapshot(context.Background(), ReadOnlySession{Inner: raw, Allowed: d.Allowed}, nil); err == nil {
		t.Error("refused interface listing must fail")
	}
	raw = dmFixture(t)
	if _, err = d.Snapshot(context.Background(), ReadOnlySession{Inner: raw, Allowed: d.Allowed}, []string{"1/1/99"}); err == nil {
		t.Error("port 99 must be refused before any ONU command")
	}
	for _, p := range []string{"1/1/0", "1/1/25", "1/2/1", "1/1/1 ; x", "../1", ""} {
		if ValidDatacomPort(p) {
			t.Errorf("port %q accepted", p)
		}
	}
}

func TestDatacomAllowlistIsExact(t *testing.T) {
	d := Datacom{}
	for _, c := range []string{
		"show platform", "show interface gpon | nomore", "show interface gpon 1/1/1 onu | nomore", "show interface gpon 1/1/24 onu | nomore",
	} {
		if !d.Allowed(c) || !SafeCommand(c) {
			t.Errorf("must allow %q", c)
		}
	}
	for _, c := range []string{
		"show running-config", "show running-config | nomore", "show platform | nomore", "show interface gpon", "show interface gpon onu | nomore",
		"show interface gpon 1/1/1 onu", "show interface gpon 1/1/1 onu | grep x", "show interface gpon 1/1/1 onu | nomore | nomore",
		"show interface gpon 1/1/1 onu | nomore | grep x", "show interface gpon 1/1/1 onu | nomore;", "show interface gpon 1/1/1 onu |nomore",
		"show interface gpon 1/1/99 onu | nomore", "show interface gpon 1/1/0 onu | nomore", "show interface gpon 1/1/25 onu | nomore",
		"show interface gpon 1/2/1 onu | nomore", "show interface gpon 1/1/1  onu | nomore",
		"show interface gpon 1/1/1 onu detail | nomore", "show interface gpon 1/1/1 onu 1 optical-info | nomore",
		"config", "dot1x", "interface gpon 1/1/1", "onu 1 shutdown", "commit", "write memory", "reload", "request system restart",
		"no interface gpon 1/1/1", "show platform\n", " show platform", "show platform ", "SHOW PLATFORM", "",
	} {
		if d.Allowed(c) && SafeCommand(c) {
			t.Errorf("must deny %q", c)
		}
	}
	// through the session wrapper nothing outside the list reaches the device
	raw := dmFixture(t)
	rs := ReadOnlySession{Inner: raw, Allowed: d.Allowed}
	for _, c := range []string{"show running-config", "show interface gpon 1/1/1 onu | grep x", "show interface gpon 1/1/99 onu | nomore", "configure", "show platform | nomore | nomore"} {
		if _, err := rs.Run(context.Background(), c); !errors.Is(err, ErrCommandDenied) {
			t.Errorf("%q: want ErrCommandDenied, got %v", c, err)
		}
	}
	if len(raw.sent) != 0 {
		t.Errorf("denied commands reached the device: %v", raw.sent)
	}
}

func TestSafeCommandPagerSuffixOnly(t *testing.T) {
	for c, want := range map[string]bool{
		"show x | nomore":          true,
		"show x | nomore | nomore": false,
		"show x | grep y":          false,
		"show x | nomore ":         false,
		"show x |nomore":           false,
		"show x | nomoreX":         false,
		"| nomore":                 false,
		" | nomore":                false,
		"show | nomore x":          false,
		"show x ; | nomore":        false,
	} {
		if got := SafeCommand(c); got != want {
			t.Errorf("SafeCommand(%q)=%v want %v", c, got, want)
		}
	}
	// other drivers' allowlists never match the suffix, so the relaxation does not widen them
	for _, c := range []string{"display version | nomore", "show version | nomore"} {
		if (Huawei{}).Allowed(c) || (ZTE{}).Allowed(c) {
			t.Errorf("huawei/zte must not allow %q", c)
		}
	}
}
