package olt

import (
	"context"
	"errors"
	"strings"
	"testing"
	"time"
)

// scriptSession answers each allowlisted command from a map and records what was asked.
type scriptSession struct {
	answers map[string]string
	asked   []string
	banner  string
}

func (s *scriptSession) Run(ctx context.Context, cmd string) (string, error) {
	s.asked = append(s.asked, cmd)
	out, ok := s.answers[cmd]
	if !ok {
		return "", errors.New("unexpected command " + cmd)
	}
	return out, nil
}
func (s *scriptSession) Banner() string { return s.banner }

func ibSession(t *testing.T) *scriptSession {
	return &scriptSession{
		banner: fixture(t, "banner.txt"),
		answers: map[string]string{
			"card stats":    fixture(t, "card_stats.txt"),
			"olt show port": fixture(t, "olt_show_port.txt"),
			"onu status":    fixture(t, "onu_status.txt"),
		},
	}
}

func TestIntelbrasIdentifyAndLookup(t *testing.T) {
	id, err := Intelbras{}.Identify(context.Background(), ibSession(t))
	if err != nil {
		t.Fatal(err)
	}
	if id.Vendor != "intelbras" || id.Model != "OLT8820PLUS" || id.Firmware != "2.112" {
		t.Fatalf("identity = %+v", id)
	}
	lvl, err := Lookup(id)
	if err != nil || lvl != LevelIdentified {
		t.Fatalf("Lookup = %v, %v; the real capture is NOT enough for observed", lvl, err)
	}
	if _, err := Lookup(Identity{Vendor: "intelbras", Model: "OLT8820PLUS", Firmware: "3.0"}); !errors.Is(err, ErrUnsupportedFirmware) {
		t.Fatalf("other firmware must be unsupported, got %v", err)
	}
}

func TestIntelbrasIdentifyNeedsBannerAndFirmware(t *testing.T) {
	s := ibSession(t)
	s.banner = "Welcome\n"
	if _, err := (Intelbras{}).Identify(context.Background(), s); err == nil {
		t.Fatal("no model in the banner must be an error")
	}
	s = ibSession(t)
	s.answers["card stats"] = "garbage\n"
	if _, err := (Intelbras{}).Identify(context.Background(), s); err == nil {
		t.Fatal("no firmware must be an error")
	}
}

func TestIntelbrasSnapshotGolden(t *testing.T) {
	s := ibSession(t)
	snap, err := Intelbras{}.Snapshot(context.Background(), s, nil)
	if err != nil {
		t.Fatal(err)
	}
	for _, c := range s.asked {
		if !IntelbrasAllowed(c) {
			t.Fatalf("driver asked for %q", c)
		}
	}
	if len(snap.PONs) != 3 {
		t.Fatalf("PONs = %+v", snap.PONs)
	}
	for i, p := range snap.PONs {
		if p.Path != string(rune('1'+i)) || p.Status != "unknown" || !p.Verified {
			t.Errorf("PON %d = %+v (footer counts match the rows: Verified)", i, p)
		}
	}
	if len(snap.ONUs) != 16 {
		t.Fatalf("ONUs = %d, want 13+3+0", len(snap.ONUs))
	}
	by := map[string]ONU{}
	for _, u := range snap.ONUs {
		by[u.PonPath+"/"+u.Serial] = u
	}
	on := by["1/5E000002"] // Active with power: ONU Rx Power is the SECOND dBm column
	if on.Status != "online" || on.RxDBm == nil || *on.RxDBm != -17.72 {
		t.Fatalf("online ONU = %+v", on)
	}
	off := by["1/5E000001"] // Inactive, hint DGI: stays offline, no power
	if off.Status != "offline" || off.RxDBm != nil {
		t.Fatalf("offline ONU = %+v", off)
	}
	if by["2/5E100003"].Status != "offline" || by["2/5E100001"].PonPath != "2" {
		t.Fatalf("PON 2 rows wrong: %+v", by)
	}
}

func TestIntelbrasHintNeverChangesStatus(t *testing.T) {
	blocks, err := parseIntelbrasONUs(fixture(t, "onu_status.txt"))
	if err != nil {
		t.Fatal(err)
	}
	b := blocks["1"]
	if b.hints["1"] != "DGI" || b.hints["3"] != "LOAMI" || len(b.hints) != 2 {
		t.Fatalf("hints = %v", b.hints)
	}
	for _, u := range b.onus {
		if u.Status != "online" && u.Status != "offline" {
			t.Fatalf("status %q: only Active/Inactive decide", u.Status)
		}
	}
}

func TestIntelbrasEmptyGPONAndNoONUs(t *testing.T) {
	blocks, err := parseIntelbrasONUs(fixture(t, "onu_status.txt"))
	if err != nil {
		t.Fatal(err)
	}
	e := blocks["3"]
	if e == nil || !e.footer || e.rows != 0 || e.configured != 0 {
		t.Fatalf("empty GPON 3 = %+v", e)
	}
	// the whole OLT with no ONU at all: still a complete answer when every footer says 0
	s := ibSession(t)
	s.answers["onu status"] = "\nGPON 1\n\nheader\n\nConfigured ONUs: 0, Active ONUs = 0\nOLT total configured = 0\n"
	s.answers["olt show port"] = "GPON Temperature Voltage Tx Bias Current  Tx Power    Rx Power   End Of Life Status\n 1       35 C    3.205 V      14 mA       3.328 dBm  -31.549 dBm         OK        \n"
	snap, err := Intelbras{}.Snapshot(context.Background(), s, nil)
	if err != nil || len(snap.ONUs) != 0 || len(snap.PONs) != 1 || !snap.PONs[0].Verified {
		t.Fatalf("snap=%+v err=%v", snap, err)
	}
}

func TestIntelbrasInvalidOrTruncatedNeverBecomesCompletePON(t *testing.T) {
	// %% Invalid command in any of the three answers: an error, no snapshot
	for _, cmd := range []string{"card stats", "olt show port", "onu status"} {
		s := ibSession(t)
		s.answers[cmd] = fixture(t, "invalid_command.txt")
		if snap, err := (Intelbras{}).Snapshot(context.Background(), s, nil); err == nil || len(snap.PONs) != 0 {
			t.Errorf("%s: invalid command accepted: %+v %v", cmd, snap, err)
		}
	}
	// no footer (cut): the PON is reported but NOT Verified
	whole := fixture(t, "onu_status.txt")
	cut := whole[:strings.Index(whole, "Configured ONUs: 13")]
	s := ibSession(t)
	s.answers["onu status"] = cut
	snap, err := Intelbras{}.Snapshot(context.Background(), s, nil)
	if err != nil {
		t.Fatal(err)
	}
	for _, p := range snap.PONs {
		if p.Verified {
			t.Errorf("PON %s Verified without a footer", p.Path)
		}
	}
	// a row missing (footer says 13, 12 rows): not Verified
	missing := strings.Replace(whole, "71  5E00000D  Active      OK            -22.15 dBm  -21.25 dBm  0.348                            11:6:23:8        yes    \n", "", 1)
	if missing == whole {
		t.Fatal("test setup: row not removed")
	}
	s.answers["onu status"] = missing
	snap, err = Intelbras{}.Snapshot(context.Background(), s, nil)
	if err != nil || snap.PONs[0].Verified || !snap.PONs[1].Verified {
		t.Fatalf("PON1 must not be Verified (12 of 13 rows), PON2 stays: %+v %v", snap.PONs, err)
	}
	// text with no GPON block at all
	s.answers["onu status"] = "something else\n"
	if _, err := (Intelbras{}).Snapshot(context.Background(), s, nil); err == nil {
		t.Fatal("no GPON block must be an error")
	}
	// PONs the OLT lists but `onu status` does not show: reported, never Verified
	s.answers["onu status"] = "\nGPON 1\n\nConfigured ONUs: 0, Active ONUs = 0\n"
	snap, err = Intelbras{}.Snapshot(context.Background(), s, nil)
	if err != nil || snap.PONs[1].Verified || snap.PONs[2].Verified || !snap.PONs[0].Verified {
		t.Fatalf("%+v %v", snap.PONs, err)
	}
}

func TestIntelbrasConfiguredPONsFilterAndUnknownPON(t *testing.T) {
	snap, err := Intelbras{}.Snapshot(context.Background(), ibSession(t), []string{"2"})
	if err != nil || len(snap.PONs) != 1 || snap.PONs[0].Path != "2" || len(snap.ONUs) != 3 {
		t.Fatalf("%+v %v", snap, err)
	}
	if _, err := (Intelbras{}).Snapshot(context.Background(), ibSession(t), []string{"9"}); err == nil {
		t.Fatal("a configured PON the OLT does not have must be an error")
	}
}

func TestIntelbrasSerialsAreUppercasedHex(t *testing.T) {
	blocks, err := parseIntelbrasONUs("GPON 1\n1   ab12cd34  Active      OK            -20.09 dBm  -17.72 dBm  0.269                            19:2:20:42       yes    \nConfigured ONUs: 1, Active ONUs = 1\n")
	if err != nil {
		t.Fatal(err)
	}
	if got := blocks["1"].onus[0].Serial; got != "AB12CD34" {
		t.Fatalf("serial = %q", got)
	}
}

// End to end over the fake Telnet server, through the same wrappers the collector uses.
func TestIntelbrasOverTelnetThroughReadOnlyAndBudget(t *testing.T) {
	f := newFakeTelnetOLT(t)
	raw := openFake(t, f)
	sess := NewBudget(ReadOnlySession{Inner: raw, Allowed: Intelbras{}.Allowed}, 8, 4<<20)
	id, err := Intelbras{}.Identify(context.Background(), sess)
	if err != nil || id.Model != "OLT8820PLUS" || id.Firmware != "2.112" {
		t.Fatalf("id=%+v err=%v (the banner must reach the driver through the wrappers)", id, err)
	}
	snap, err := Intelbras{}.Snapshot(context.Background(), sess, nil)
	if err != nil || len(snap.PONs) != 3 || len(snap.ONUs) != 16 || !snap.PONs[0].Verified {
		t.Fatalf("snap=%+v err=%v", snap, err)
	}
	if !EndProven(raw) {
		t.Fatal("the telnet session proved every command end")
	}
	raw.Close()
	deadline := time.Now().Add(time.Second)
	for time.Now().Before(deadline) && len(f.commands()) < 5 {
		time.Sleep(10 * time.Millisecond)
	}
	want := []string{"card stats", "card stats", "olt show port", "onu status", "logout"}
	got := f.commands()
	if strings.Join(got, "|") != strings.Join(want, "|") {
		t.Fatalf("device saw %v, want %v", got, want)
	}
}


func TestDisambiguateSerialsOnlyWhenRepeated(t *testing.T) {
	onus := []ONU{{Serial: "AAAA0001", PonPath: "1"}, {Serial: "BBBB0002", PonPath: "1"}, {Serial: "AAAA0001", PonPath: "2"}}
	disambiguateSerials(onus)
	if onus[0].Serial != "AAAA0001@1" || onus[2].Serial != "AAAA0001@2" || onus[1].Serial != "BBBB0002" {
		t.Fatalf("got %+v", onus)
	}
}
