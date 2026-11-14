package olt

import (
	"context"
	"errors"
	"os"
	"reflect"
	"regexp"
	"strings"
	"testing"
	"time"
)

// Fixtures: real read-only captures of two MA5800-X2 (R022C11 and R024C11) taken on 2026-11-14 in the privileged (enable) view, SANITIZED:
// serials are synthetic (vendor prefix + counter), descriptions are CLIENTE_EXEMPLO, the host name is MA5800-EXEMPLO. They are stored the way the
// device sent them (command echo, "{ <cr>||<K> }:", pager prompts with their erase sequences); the tests run them through the same
// eraseMarkers/tidy the interactive shell applies, so the driver sees what it sees on the wire.
const ma58Dir = "testdata/huawei_ma5800_r02x/"

func ma58Raw(t *testing.T, name string) string {
	t.Helper()
	b, err := os.ReadFile(ma58Dir + name)
	if err != nil {
		t.Fatal(err)
	}
	return string(b)
}

// ma58Wire is what the shell hands the driver for `cmd`: pager prompts the device erased are gone, the echo and the trailing prompt are dropped.
func ma58Wire(t *testing.T, name, cmd, prompt string) string {
	t.Helper()
	return tidy(eraseMarkers(ma58Raw(t, name)), cmd, prompt)
}

const (
	ma58User = "MA5800-EXEMPLO>"
	ma58Priv = "MA5800-EXEMPLO#"
)

var ma58Zone = time.FixedZone("olt", -3*3600)

// ma58Session answers by command, records what reaches the "device" and can fail a command.
type ma58Session struct {
	out   map[string]string
	sent  []string
	fails map[string]error
}

func (m *ma58Session) Run(_ context.Context, cmd string) (string, error) {
	m.sent = append(m.sent, cmd)
	if err := m.fails[cmd]; err != nil {
		return "", err
	}
	o, ok := m.out[cmd]
	if !ok {
		return "", errors.New("ma58 fake: no output for " + cmd)
	}
	return o, nil
}

func ma58Device(t *testing.T) *ma58Session {
	return &ma58Session{out: map[string]string{
		"display version":                  ma58Wire(t, "display_version_user_r024c11.txt", "display version", ma58User),
		"enable":                           ma58Wire(t, "enable_ok.txt", "enable", ma58Priv),
		"display ont info summary 0/1/0":   ma58Wire(t, "ont_info_summary_0_1_0_paged.txt", "display ont info summary 0/1/0", ma58Priv),
		"display ont info 0 1 0 all":       ma58Wire(t, "ont_info_0_1_0_all_paged.txt", "display ont info 0 1 0 all", ma58Priv),
		"display ont info summary 0/1/1":   ma58Wire(t, "ont_info_summary_0_1_1_paged.txt", "display ont info summary 0/1/1", ma58Priv),
		"quit":                             "",
		"display ont info summary 0/2/0":   ma58Wire(t, "ont_info_summary_board_missing.txt", "display ont info summary 0/1/0", ma58Priv),
		"display ont info 0 2 0 all":       "",
		"display ont info summary 0/17/15": ma58Wire(t, "ont_info_summary_board_missing.txt", "display ont info summary 0/1/0", ma58Priv),
	}, fails: map[string]error{}}
}

func ma58Snap(t *testing.T, raw Session, zone *time.Location, ports ...string) (Snapshot, error) {
	t.Helper()
	d := HuaweiMA58{Zone: zone}
	return d.Snapshot(context.Background(), ReadOnlySession{Inner: raw, Allowed: d.Allowed}, ports)
}

func TestMA58RealCaptureSnapshotIsProvenCompleteWithCausesAndSerials(t *testing.T) {
	dev := ma58Device(t)
	snap, err := ma58Snap(t, dev, ma58Zone, "0/1/0")
	if err != nil {
		t.Fatal(err)
	}
	if snap.Identity != (Identity{Vendor: "huawei", Model: "MA5800-X2", Firmware: "MA5800V100R024C11"}) {
		t.Fatalf("identity=%+v", snap.Identity)
	}
	if len(snap.PONs) != 1 || snap.PONs[0] != (PON{Path: "0/1/0", Status: "up", Verified: true}) || len(snap.ONUs) != 57 {
		t.Fatalf("pons=%+v onus=%d", snap.PONs, len(snap.ONUs))
	}
	by := map[int]ONU{}
	online, seen := 0, map[string]bool{}
	for _, u := range snap.ONUs {
		by[u.OntID] = u
		if u.Status == "online" {
			online++
		}
		if !regexp.MustCompile(`^[0-9A-F]{16}$`).MatchString(u.Serial) || seen[u.Serial] || u.PonPath != "0/1/0" || !u.HasOntID || u.RxDBm != nil {
			t.Errorf("bad ONU %+v", u)
		}
		seen[u.Serial] = true
		if u.Status == "online" && u.LastDownAt != nil {
			t.Errorf("an online ONU has no last down time: %+v", u)
		}
	}
	if online != 56 {
		t.Fatalf("online=%d want 56", online)
	}
	if _, ok := by[50]; ok { // the OLT itself has no ONT-ID 50 on this port: 57 ONTs are 0..57 minus 50
		t.Fatal("ONT-ID 50 does not exist on this PON")
	}
	// offline + dying-gasp, with the OLT's own down time converted from the OLT clock (-03:00) to UTC
	u5 := by[5]
	if u5.Status != "dying_gasp" || u5.LastDownAt == nil || !u5.LastDownAt.Equal(time.Date(2026, 11, 3, 9, 50, 25, 0, time.UTC)) {
		t.Fatalf("ONT 5 = %+v", u5)
	}
	// the down cause of an ONLINE ONU is history, not state: it stays online (LOSi/LOBi on ONT 3, dying-gasp on ONT 0, "-" on ONT 7)
	for _, id := range []int{0, 3, 7} {
		if by[id].Status != "online" {
			t.Errorf("ONT %d must be online, got %q", id, by[id].Status)
		}
	}
	// joined by ONT-ID: the serial of ONT 0 is the (synthetic) 4 vendor characters + 8 hex digits of the `info ... all` listing, as 16 hex digits
	if !strings.HasPrefix(by[0].Serial, "49544253") { // "ITBS"
		t.Fatalf("ONT 0 serial %s", by[0].Serial)
	}
	want := []string{"display version", "enable", "display ont info summary 0/1/0", "display ont info 0 1 0 all"}
	if !reflect.DeepEqual(dev.sent, want) {
		t.Fatalf("commands:\n got %v\nwant %v", dev.sent, want)
	}
}

func TestMA58LastDownIsNeverGuessedWithoutTheClockZone(t *testing.T) {
	snap, err := ma58Snap(t, ma58Device(t), nil, "0/1/0")
	if err != nil {
		t.Fatal(err)
	}
	for _, u := range snap.ONUs {
		if u.LastDownAt != nil {
			t.Fatalf("no zone configured: %+v must not carry a last down time", u)
		}
	}
	if !snap.PONs[0].Verified || len(snap.ONUs) != 57 {
		t.Fatalf("status and causes are still reported: %+v", snap.PONs)
	}
}

func TestMA58SummaryOfAnOfflinePonCarriesLOSiAndDyingGasp(t *testing.T) {
	rows, clean := parseMA58Summary(ma58Wire(t, "ont_info_summary_0_1_1_paged.txt", "display ont info summary 0/1/1", ma58Priv))
	if !clean || len(rows) != 50 {
		t.Fatalf("rows=%d clean=%v", len(rows), clean)
	}
	by := map[int]ma58Ont{}
	for _, r := range rows {
		by[r.id] = r
	}
	if r := by[47]; r.online || ma58Cause(r.cause) != "dying_gasp" || r.downAt != "13/11/2026 19:58:45" {
		t.Fatalf("ONT 47 = %+v", r)
	}
	if r := by[7]; !r.online || ma58Cause(r.cause) != "los" { // history only: reported online
		t.Fatalf("ONT 7 = %+v", r)
	}
	// LOSi/LOBi on an OFFLINE ONU is `los`; a cause this profile does not know (LOAi) stays plain offline
	for cause, want := range map[string]string{"LOSi/LOBi": "los", "LOBi": "los", "dying-gasp": "dying_gasp", "LOAi": "", "-": "", "power-off": ""} {
		if got := ma58Cause(cause); got != want {
			t.Errorf("cause %q -> %q want %q", cause, got, want)
		}
	}
	sum := ma58Wire(t, "ont_info_summary_0_1_0_paged.txt", "display ont info summary 0/1/0", ma58Priv)
	all := ma58Wire(t, "ont_info_0_1_0_all_paged.txt", "display ont info 0 1 0 all", ma58Priv)
	offlineLOS := strings.Replace(sum, "03/11/2026 06:50:25 dying-gasp", "03/11/2026 06:50:25 LOSi/LOBi ", 1)
	onus, pon := parseMA58Port("0/1/0", offlineLOS, all, ma58Zone)
	if !pon.Verified {
		t.Fatalf("pon=%+v", pon)
	}
	for _, u := range onus {
		if u.OntID == 5 && u.Status != "los" {
			t.Fatalf("offline + LOSi/LOBi must be los: %+v", u)
		}
	}
	// an offline ONT whose DownTime is "-" has no last down time (nothing is invented)
	noTime := strings.Replace(sum, "03/11/2026 03:05:23 03/11/2026 06:50:25 dying-gasp", "03/11/2026 03:05:23 -                   -         ", 1)
	onus, _ = parseMA58Port("0/1/0", noTime, all, ma58Zone)
	for _, u := range onus {
		if u.OntID == 5 && (u.LastDownAt != nil || u.Status != "offline") {
			t.Fatalf("offline without a time or cause: %+v", u)
		}
	}
}

func TestMA58PonWithoutABoardIsAFailureNotAnEmptyPon(t *testing.T) {
	dev := ma58Device(t)
	_, err := ma58Snap(t, dev, ma58Zone, "0/2/0")
	if err == nil || !strings.Contains(err.Error(), "does not exist") || !strings.Contains(err.Error(), "rejected") {
		t.Fatalf("a PON on a missing board must fail the collection with the device's own words: %v", err)
	}
	// the listing of that PON is never asked for after the refusal, and the session did not run on
	if !reflect.DeepEqual(dev.sent, []string{"display version", "enable", "display ont info summary 0/2/0"}) {
		t.Fatalf("sent %v", dev.sent)
	}
	// parsing the refusal text can never yield a (verified) PON
	onus, pon := parseMA58Port("0/1/0", ma58Wire(t, "ont_info_summary_board_missing.txt", "display ont info summary 0/1/0", ma58Priv), "", ma58Zone)
	if len(onus) != 0 || pon.Verified || pon.Status != "unknown" {
		t.Fatalf("onus=%d pon=%+v", len(onus), pon)
	}
}

func TestMA58IncompleteOrInconsistentListingIsNeverVerified(t *testing.T) {
	sum := ma58Wire(t, "ont_info_summary_0_1_0_paged.txt", "display ont info summary 0/1/0", ma58Priv)
	all := ma58Wire(t, "ont_info_0_1_0_all_paged.txt", "display ont info 0 1 0 all", ma58Priv)
	row := func(s, id string) string {
		return regexp.MustCompile(`(?m)^ *`+id+` +(online|offline) .*\n`).ReplaceAllString(s, "")
	}
	infoRow := func(s, id string) string {
		return regexp.MustCompile(`(?m)^ *0/ 1/0 +`+id+` +[0-9A-Z]{12} .*\n`).ReplaceAllString(s, "")
	}
	type tc struct{ sum, all string }
	for name, c := range map[string]tc{
		"a summary row is missing (count diverges)":      {row(sum, "20"), all},
		"summary footer missing":                         {regexp.MustCompile(`(?m)^ *In port.*\n`).ReplaceAllString(sum, ""), all},
		"declared total differs":                         {strings.Replace(sum, "total of ONTs are: 57", "total of ONTs are: 58", 1), all},
		"declared online differs":                        {strings.Replace(sum, "online: 56", "online: 57", 1), all},
		"footer names another port":                      {strings.Replace(sum, "In port 0/1/0", "In port 0/1/1", 1), all},
		"two footers (payload imitating the footer)":     {sum + "\n  In port 0/1/0, the total of ONTs are: 57, online: 56\n", all},
		"duplicated ONT-ID":                              {strings.Replace(sum, "\n  21   online", "\n  20   online", 1), all},
		"unknown run state":                              {strings.Replace(sum, "online  09/11/2026 21:02:08", "los     09/11/2026 21:02:08", 1), all},
		"malformed row inside the table":                 {strings.Replace(sum, "  4    online  09/11/2026 19:56:57 09/11/2026 17:25:55 dying-gasp", "  4    online  09/11/2026 19:56:57", 1), all},
		"table never closed (output cut)":                {sum[:strings.Index(sum, "  30   online")], all},
		"serial missing for an ONT-ID":                   {sum, infoRow(all, "9")},
		"serial listing has an ONT-ID the summary lacks": {sum, strings.Replace(all, "0/ 1/0    57 ", "0/ 1/0    99 ", 1)},
		"serial listing for another port":                {sum, strings.Replace(all, "0/ 1/0     3 ", "0/ 1/1     3 ", 1)},
		"no serial listing at all":                       {sum, ""},
	} {
		if _, pon := parseMA58Port("0/1/0", c.sum, c.all, ma58Zone); pon.Verified {
			t.Errorf("%s: must not be verified", name)
		}
	}
	if _, pon := parseMA58Port("0/1/0", sum, all, ma58Zone); !pon.Verified {
		t.Fatal("control: the untouched capture must verify")
	}
	// duplicated serial: two ONT-IDs with the same serial cannot be two ONUs
	dup := regexp.MustCompile(`(?m)^( *0/ 1/0 +1 )([0-9A-Z]{12})`).ReplaceAllString(all, "${1}"+regexp.MustCompile(`(?m)^ *0/ 1/0 +0 ([0-9A-Z]{12})`).FindStringSubmatch(all)[1])
	if _, pon := parseMA58Port("0/1/0", sum, dup, ma58Zone); pon.Verified {
		t.Error("duplicated serial must not be verified")
	}
}

func TestMA58PagedOutputStillCarryingThePagerFailsClosed(t *testing.T) {
	// the raw capture still has the pager prompts (what a transport that does not answer the pager would hand over)
	dev := ma58Device(t)
	dev.out["display ont info summary 0/1/0"] = ma58Raw(t, "ont_info_summary_0_1_0_paged.txt")
	_, err := ma58Snap(t, dev, ma58Zone, "0/1/0")
	if !errors.Is(err, ErrPaginated) {
		t.Fatalf("truncated (paged) listing must fail closed: %v", err)
	}
	if reflect.DeepEqual(dev.sent[len(dev.sent)-1], "display ont info 0 1 0 all") {
		t.Fatalf("nothing may follow a truncated listing: %v", dev.sent)
	}
	// and when the pager text is not recognisable, the count still refuses a listing that stops early
	sum := ma58Wire(t, "ont_info_summary_0_1_0_paged.txt", "display ont info summary 0/1/0", ma58Priv)
	cut := sum[:strings.Index(sum, "  16   online")]
	if _, pon := parseMA58Port("0/1/0", cut, ma58Wire(t, "ont_info_0_1_0_all_paged.txt", "display ont info 0 1 0 all", ma58Priv), ma58Zone); pon.Verified {
		t.Fatal("a listing cut after 16 of 57 rows must not be verified")
	}
}

func TestMA58EnableIsTheFirstStepAfterIdentificationAndTheSessionEndsWithQuit(t *testing.T) {
	dev := ma58Device(t)
	if _, err := ma58Snap(t, dev, ma58Zone, "0/1/0", "0/1/1"); err == nil {
		t.Fatal("0/1/1 has no serial listing in the fake device: the collection must fail, not guess")
	}
	dev = ma58Device(t)
	dev.out["display ont info 0 1 1 all"] = ma58Wire(t, "ont_info_0_1_0_all_paged.txt", "display ont info 0 1 0 all", ma58Priv)
	snap, err := ma58Snap(t, dev, ma58Zone, "0/1/0", "0/1/1")
	if err != nil {
		t.Fatal(err)
	}
	if len(snap.PONs) != 2 || snap.PONs[1].Verified { // the serial listing of ANOTHER port can never verify this PON
		t.Fatalf("pons=%+v", snap.PONs)
	}
	want := []string{"display version", "enable", "display ont info summary 0/1/0", "display ont info 0 1 0 all", "display ont info summary 0/1/1", "display ont info 0 1 1 all"}
	if !reflect.DeepEqual(dev.sent, want) {
		t.Fatalf("commands:\n got %v\nwant %v", dev.sent, want)
	}
	n := 0
	for i, c := range dev.sent {
		if c == "enable" {
			n++
			if i != 1 {
				t.Errorf("enable must come right after display version, at %d", i)
			}
		}
		if c == "quit" {
			t.Errorf("the MA5800 asks a (y/n) question on quit and the shell never answers: no quit at %d", i)
		}
		if !(HuaweiMA58{}).Allowed(c) || !SafeCommand(c) {
			t.Errorf("sent a command outside the allowlist: %q", c)
		}
		for _, bad := range []string{"config", "undo", "reboot", "reset", "diagnose", "system-view", "save", "commit", "shutdown", "delete", "add", "set", "interface", "write"} {
			if strings.Contains(strings.ToLower(c), bad) {
				t.Errorf("write-looking command %q", c)
			}
		}
	}
	if n != 1 {
		t.Fatalf("enable sent %d times", n)
	}
}

func TestMA58QuitIsNeverSentNorAllowed(t *testing.T) {
	// real MA5800: `quit` asks "Are you sure to log out? (y/n)[n]:" and the shell never answers, leaving the prompt pending for the next command of the session
	if (HuaweiMA58{}).Allowed("quit") {
		t.Fatal("quit must not be in the allowlist")
	}
}

func TestMA58EnableDeniedStopsEverythingAfterIt(t *testing.T) {
	for name, out := range map[string]string{
		"device rejects the command":          "  % Unknown command, the error locates at '^'\n",
		"explicit failure":                    "  Failure: The user has no right to execute this command\n",
		"still on the user prompt":            "MA5800-EXEMPLO>\n",
		"unexpected banner after enable":      "  Warning: something the profile does not understand\n\nMA5800-EXEMPLO#\n",
		"privilege prompt next to a user one": "MA5800-EXEMPLO#\nMA5800-EXEMPLO>\n",
		"asks for a password (not accepted)":  "  Password:\n",
		"authentication failed":               "  Authentication failed\n",
	} {
		dev := ma58Device(t)
		dev.out["enable"] = out
		_, err := ma58Snap(t, dev, ma58Zone, "0/1/0")
		if err == nil {
			t.Errorf("%s: must fail", name)
			continue
		}
		if !reflect.DeepEqual(dev.sent, []string{"display version", "enable"}) {
			t.Errorf("%s: only display version + enable may have been sent, got %v", name, dev.sent)
		}
	}
	// the elevation answering with an error from the transport (e.g. the shell failing closed on a question) is the same
	dev := ma58Device(t)
	dev.fails["enable"] = errors.New("interactive question")
	if _, err := ma58Snap(t, dev, ma58Zone, "0/1/0"); err == nil || !reflect.DeepEqual(dev.sent, []string{"display version", "enable"}) {
		t.Fatalf("err=%v sent=%v", err, dev.sent)
	}
	// and the real success answer passes
	if !ma58EnableOK(ma58Wire(t, "enable_ok.txt", "enable", ma58Priv)) || !ma58EnableOK("") || !ma58EnableOK(ma58Raw(t, "enable_ok.txt")) {
		t.Fatal("the captured enable answer must be accepted")
	}
}

func TestMA58OnlyTheCapturedReleasesGetEnableAndTheOntCommands(t *testing.T) {
	for name, ver := range map[string]string{
		"older MA5800 (R018, synthetic fixtures only)": "  VERSION : R018\n  PRODUCT : MA5800-X7\n",
		"another MA5800 release":                       "  VERSION : MA5800V100R023C10\n  PRODUCT : MA5800-X2\n",
		"an MA5600 on a MA5800 profile":                "  VERSION : MA5600V800R015C00\n  PRODUCT : MA5608T\n",
		"a different vendor model":                     "  VERSION : MA5800V100R022C11\n  PRODUCT : MA5683T\n",
	} {
		var sent []string
		_, err := (HuaweiMA58{}).Snapshot(context.Background(), recSession{ver, &sent}, []string{"0/1/0"})
		if err == nil {
			t.Errorf("%s: must be refused", name)
		}
		if !reflect.DeepEqual(sent, []string{"display version"}) {
			t.Errorf("%s: only display version may reach an unvalidated device, sent %v", name, sent)
		}
	}
	// the generic Huawei driver refuses these releases and names the profile (it would send optical-info and never enable)
	r022 := stubSession{ma58Wire(t, "display_version_user_r022c11.txt", "display version", ma58User)}
	if _, err := (Huawei{}).Snapshot(context.Background(), r022, []string{"0/1/0"}); err == nil || !strings.Contains(err.Error(), "huawei_ma58_r02x") {
		t.Fatalf("generic driver must refuse MA5800 R02x and name the profile: %v", err)
	}
	// ...and the R015 profile refuses them too
	if _, err := (HuaweiR015{}).Snapshot(context.Background(), r022, []string{"0/0/14"}); err == nil {
		t.Fatal("the R015 profile must refuse an MA5800")
	}
	// R022 is accepted by the profile
	id, err := (HuaweiMA58{}).Identify(context.Background(), r022)
	if err != nil || !isMA58R02x(id) || id.Firmware != "MA5800V100R022C11" || id.Model != "MA5800-X2" {
		t.Fatalf("id=%+v err=%v", id, err)
	}
}

func TestMA58AllowlistIsExactAndReadOnly(t *testing.T) {
	d := HuaweiMA58{}
	for _, ok := range []string{
		"display version", "enable", "display ont autofind all", "display ont info summary 0/1/0", "display ont info summary 0/21/15", "display ont info 0 1 0 all",
		"display ont info 0 17 15 all", "display ont info summary 0/0/0",
	} {
		if !d.Allowed(ok) {
			t.Errorf("%q must be allowed", ok)
		}
	}
	raw := &fixtureSession{dir: "x", files: map[string]string{}}
	ro := ReadOnlySession{Inner: raw, Allowed: d.Allowed}
	for _, bad := range []string{
		"config", "system-view", "diagnose", "undo ont add 0 1", "reset", "reboot", "save", "quit config", "enable password", "enable 15", "disable", "return",
		"interface gpon 0/1", "display ont info summary 1/1/0", "display ont info summary 0/22/0", "display ont info summary 0/1/16", "display ont info summary 0/01/0",
		"display ont info summary 0/1/0 extra", "display ont info 0 1 0 all; reboot", "display ont info 0 1 0 all | include x", "display ont info 1 1 0 all",
		"display ont info 0 22 0 all", "display ont info 0 1 16 all", "display ont info 0/1/0 all", "display ont optical-info 0/1/0 all", "display ont autofind", "display ont autofind all x", "display ont autofind 0/1/0",
		"display board 0", "display ont info summary 0/1/x", " enable", "enable ", "Enable", "display version\nreboot", "enable;config", "", strings.Repeat("a", 200),
	} {
		if _, err := ro.Run(context.Background(), bad); !errors.Is(err, ErrCommandDenied) {
			t.Errorf("%q must be denied, got %v", bad, err)
		}
	}
	if len(raw.sent) != 0 {
		t.Fatalf("denied commands reached the device: %v", raw.sent)
	}
}

func TestMA58InvalidPonPortRejectedBeforeAnyCommand(t *testing.T) {
	for _, p := range []string{"0/1/0; reboot", "1/1/0", "0/22/0", "0/1/16", "0/01/0", "0/1", "x", ""} {
		dev := ma58Device(t)
		if _, err := ma58Snap(t, dev, ma58Zone, p); err == nil {
			t.Errorf("port %q must be rejected", p)
		}
		if len(dev.sent) != 0 {
			t.Errorf("port %q: a bad port must not even touch the device, sent %v", p, dev.sent)
		}
	}
	// a good port followed by a bad one is also refused before the first command
	dev := ma58Device(t)
	if _, err := ma58Snap(t, dev, ma58Zone, "0/1/0", "0/1/99"); err == nil || len(dev.sent) != 0 {
		t.Fatalf("err=%v sent=%v", err, dev.sent)
	}
	// no ports: identification only, and no elevation
	dev = ma58Device(t)
	snap, err := ma58Snap(t, dev, ma58Zone)
	if err != nil || len(snap.PONs) != 0 || !reflect.DeepEqual(dev.sent, []string{"display version"}) {
		t.Fatalf("err=%v snap=%+v sent=%v", err, snap, dev.sent)
	}
}

func TestMA58DeviceRejectionOfAListingFailsTheCollection(t *testing.T) {
	for _, out := range []string{
		"  % Unknown command, the error locates at '^'\n", "  % Parameter error, the error locates at '^'\n", "  Failure: The ONT does not exist\n",
	} {
		dev := ma58Device(t)
		dev.out["display ont info 0 1 0 all"] = out
		if _, err := ma58Snap(t, dev, ma58Zone, "0/1/0"); err == nil {
			t.Errorf("%q: must fail", out)
		}
	}
}

func TestMA58SerialIsTheCanonicalSixteenHexOfTheOtherHuaweiSources(t *testing.T) {
	for in, want := range map[string]string{
		"ITBS5F453E48":     "495442535F453E48", // 4 vendor characters + 8 hex
		"itbs5f453e48":     "697462735F453E48", // vendor characters are bytes, not case-folded
		"42061D00C970":     "34323036" + "1D00C970",
		"4857544310001a2b": "4857544310001A2B", // already the 8 bytes in hex (MA5600 CLI / SNMP form)
	} {
		if got, ok := ma58Serial(in); !ok || got != want {
			t.Errorf("%q -> %q,%v want %q", in, got, ok, want)
		}
	}
	for _, bad := range []string{"", "ITBS5F453E4", "ITBS5F453E48X", "IT-S5F453E48", "ITBS5F453EZZ", "485754431000A00", "-", "0/1/0"} {
		if got, ok := ma58Serial(bad); ok {
			t.Errorf("%q must be refused, got %q", bad, got)
		}
	}
}

func TestMA58RegistryKeepsTheCapturedReleasesAtIdentified(t *testing.T) {
	for _, fw := range []string{"MA5800V100R022C11", "MA5800V100R024C11"} {
		lvl, err := Lookup(Identity{Vendor: "huawei", Model: "MA5800-X2", Firmware: fw})
		if err != nil || lvl != LevelIdentified {
			t.Fatalf("%s: lvl=%s err=%v", fw, lvl, err)
		}
	}
	for _, fw := range []string{"MA5800V100R023C10", "MA5800V100R021C00", "MA5800V200R022C11", ""} {
		if _, err := Lookup(Identity{Vendor: "huawei", Model: "MA5800-X2", Firmware: fw}); !errors.Is(err, ErrUnsupportedFirmware) {
			t.Errorf("%q must stay unsupported: %v", fw, err)
		}
	}
	found := 0
	for _, h := range Registry {
		if h.Vendor == "huawei" && h.ModelPrefix == "MA5800" && strings.HasPrefix(h.FirmwarePrefix, "MA5800V100R02") {
			found++
			if h.Level != LevelIdentified || !strings.Contains(h.Evidence, "real capture 2026-11-14") || !strings.Contains(h.Evidence, "NOT enough for observed") {
				t.Errorf("registry entry: %+v", h)
			}
		}
	}
	if found != 2 {
		t.Fatalf("expected the R022 and the R024 entries, found %d", found)
	}
}

func TestMA58FixturesAreSanitized(t *testing.T) {
	entries, err := os.ReadDir(ma58Dir)
	if err != nil || len(entries) == 0 {
		t.Fatal(err)
	}
	serial := regexp.MustCompile(`\b[0-9A-Za-z]{4}0000[0-9A-F]{4}\b`)
	token := regexp.MustCompile(`\b[0-9A-Za-z]{12,16}\b`)
	ip := regexp.MustCompile(`\b\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}\b`)
	for _, e := range entries {
		b := ma58Raw(t, e.Name())
		if regexp.MustCompile(`MA5800-X2-\w+`).MatchString(b) || !strings.Contains(b+"MA5800-EXEMPLO", "MA5800-EXEMPLO") {
			t.Errorf("%s: carries a real host name", e.Name())
		}
		if ip.MatchString(b) {
			t.Errorf("%s: carries an IP address", e.Name())
		}
		for _, tk := range token.FindAllString(b, -1) {
			if !serial.MatchString(tk) && !strings.HasPrefix(tk, "MA5800V100R02") && tk != "automatically" { // only synthetic serials and the firmware string may look like a serial
				t.Errorf("%s: token %q is neither a synthetic serial nor the version", e.Name(), tk)
			}
		}
		for _, line := range strings.Split(b, "\n") {
			if m := regexp.MustCompile(`[A-Z]{3,}_[A-Z_]{3,}`).FindString(line); m != "" && m != "CLIENTE_EXEMPLO" {
				t.Errorf("%s: description %q was not sanitized", e.Name(), m)
			}
		}
	}
}

func TestMA58PortWithNoOntIsAnEmptyUnverifiedPonNotAFailure(t *testing.T) {
	dev := ma58Device(t)
	dev.out["display ont info summary 0/1/2"] = "display ont info summary 0/1/2 \r\n{ <cr>||<K> }: \r\n\r\n  Command:\r\n          display ont info summary 0/1/2\r\n  Failure: The ONT does not exist\r\n\r\n" + ma58Priv
	snap, err := ma58Snap(t, dev, ma58Zone, "0/1/0", "0/1/2")
	if err != nil {
		t.Fatalf("an empty port must not fail the collection: %v", err)
	}
	if len(snap.PONs) != 2 || snap.PONs[1].Path != "0/1/2" || snap.PONs[1].Verified || snap.PONs[1].Status != "unknown" {
		t.Fatalf("pons %+v", snap.PONs)
	}
	for _, sent := range dev.sent {
		if sent == "display ont info 0 1 2 all" {
			t.Fatal("the serial listing of an empty port must not be asked for")
		}
	}
	// "This board does not exist" stays a failure
	if _, err := ma58Snap(t, ma58Device(t), ma58Zone, "0/2/0"); err == nil {
		t.Fatal("a missing board must still fail")
	}
}

// Real capture, MA5800 R022C11 and R024C11 (2026-11-14), no ONT waiting: the same empty answer as the MA5600 R015.
func TestMA58AutofindEmptyListIsAnEmptyResult(t *testing.T) {
	dev := &ma58Session{out: map[string]string{"display ont autofind all": ma58Wire(t, "display_ont_autofind_all_empty.txt", "display ont autofind all", ma58Priv)}, fails: map[string]error{}}
	out, err := (HuaweiMA58{}).RunAutofind(context.Background(), dev)
	if err != nil {
		t.Fatal(err)
	}
	raw, err := ParseResult("olt.autofind", out)
	if err != nil || !strings.Contains(string(raw), "[]") {
		t.Fatalf("raw=%s err=%v", raw, err)
	}
	if !reflect.DeepEqual(dev.sent, []string{"display ont autofind all"}) {
		t.Fatalf("sent %v", dev.sent)
	}
}

// The layout WITH entries was not seen on this family: it is only accepted when it is the one verified on the R015 (synthetic reuse), and anything else fails closed.
func TestMA58AutofindWithEntryUsesTheVerifiedLayoutAndRefusesTheRest(t *testing.T) {
	b, err := os.ReadFile(r015Dir + "display_ont_autofind_all.txt")
	if err != nil {
		t.Fatal(err)
	}
	dev := &ma58Session{out: map[string]string{"display ont autofind all": string(b)}, fails: map[string]error{}}
	out, err := (HuaweiMA58{}).RunAutofind(context.Background(), dev)
	if err != nil {
		t.Fatal(err)
	}
	if _, err := ParseResult("olt.autofind", out); err != nil {
		t.Fatal(err)
	}
	dev.out["display ont autofind all"] = "  Command:\n  display ont autofind all\n  Some new layout nobody saw\n"
	out, _ = (HuaweiMA58{}).RunAutofind(context.Background(), dev)
	if _, err := ParseResult("olt.autofind", out); err == nil {
		t.Fatal("an unknown layout must be a bad output")
	}
	dev.out["display ont autofind all"] = "  % Unknown command, the error locates at '^'\n"
	if _, err := (HuaweiMA58{}).RunAutofind(context.Background(), dev); err == nil {
		t.Fatal("a device rejection must be an error")
	}
}
