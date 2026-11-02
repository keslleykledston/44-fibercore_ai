package olt

import (
	"context"
	"fmt"
	"regexp"
	"strings"
	"testing"
	"time"
)

var spec14 = ReauthSpec{LineProfileID: 179, SrvProfileID: 179, ServicePortIndex: 1708, VLAN: 1400, Gem: 1, Description: "BANCADA-HW"}

// fakeAuthOLT simulates the CLI for the bench ONU's registration and service port, with switches to break each step.
type fakeAuthOLT struct {
	sent                          []string
	ontPresent, spPresent, inAuto bool
	line, srv                     int
	desc, tag, lastUp             string
	refuse                        map[string]bool // command prefix -> "% Parameter error"
	addFailsOnce                  bool
	neverInAutofind               bool
	extraSP                       bool
	addCount                      int
}

func newAuth() *fakeAuthOLT {
	return &fakeAuthOLT{ontPresent: true, spPresent: true, line: 179, srv: 179, desc: "BANCADA-HW", tag: "translate", lastUp: "2026-11-02 10:00:00-04:00", refuse: map[string]bool{}}
}

func (f *fakeAuthOLT) info() string {
	return fmt.Sprintf("  -----------------------------\n  F/S/P                   : 0/0/14\n  ONT-ID                  : 10\n  Control flag            : active\n  Run state               : online\n  Config state            : normal\n  Match state             : match\n  SN                      : 48575443E2247AA5\n  Description             : %s\n  Last up time            : %s\n  Line profile ID         : %d\n  Service profile ID      : %d\n", f.desc, f.lastUp, f.line, f.srv)
}

func (f *fakeAuthOLT) Run(_ context.Context, cmd string) (string, error) {
	f.sent = append(f.sent, cmd)
	for p := range f.refuse {
		if strings.HasPrefix(cmd, p) {
			return "  % Parameter error, the error locates at '^'", nil
		}
	}
	switch {
	case strings.HasPrefix(cmd, "display ont info"):
		if !f.ontPresent {
			return "  Failure: The ONT does not exist\n", nil
		}
		return f.info(), nil
	case strings.HasPrefix(cmd, "display service-port port"):
		if !f.spPresent {
			return "  Failure: No service virtual port can be operated\n", nil
		}
		rows := "   1708 1400 common   gpon 0/0 /14 10   1     vlan  1400       -    -    up   \n"
		n := 1
		if f.extraSP {
			rows += "   1709 1401 common   gpon 0/0 /14 10   2     vlan  1401       -    -    up   \n"
			n = 2
		}
		return "  Switch-Oriented Flow List\n" + rows + fmt.Sprintf("  Total : %d  (Up/Down :    %d/0)\n", n, n), nil
	case strings.HasPrefix(cmd, "display service-port 1708"):
		return fmt.Sprintf("Index               : 1708\nVLAN ID             : 1400\nPort type           : gpon\nF/S/P               : 0/0/14\nONT ID              : 10\nGEM port index      : 1\nFlow type           : vlan\nFlow para           : 1400\nInbound table name  : -\nOutbound table name : -\nAdmin status        : enable\nState               : up\nTag transform       : %s\n", f.tag), nil
	case strings.HasPrefix(cmd, "undo service-port"):
		f.spPresent = false
	case strings.HasPrefix(cmd, "ont delete"):
		f.ontPresent, f.inAuto = false, !f.neverInAutofind
	case cmd == "display ont autofind all":
		if f.inAuto {
			return "  Number              : 1\n  Ont SN              : 48575443E2247AA5 (HWTC-E2247AA5)\n", nil
		}
		return "  Failure: The automatically found ONTs do not exist\n", nil
	case strings.HasPrefix(cmd, "ont add"):
		f.addCount++
		if f.addFailsOnce && f.addCount == 1 {
			return "  % Parameter error, the error locates at '^'", nil
		}
		f.ontPresent, f.inAuto, f.lastUp = true, false, "2026-11-02 10:30:00-04:00"
		if !strings.Contains(cmd, "ont-lineprofile-id 179") {
			f.line = 1
		}
	case strings.HasPrefix(cmd, "service-port 1708"):
		f.spPresent = true
	}
	return "", nil
}

func (f *fakeAuthOLT) mutating() []string {
	var out []string
	for _, c := range f.sent {
		if strings.HasPrefix(c, "ont ") || strings.HasPrefix(c, "undo ") || strings.HasPrefix(c, "service-port ") {
			out = append(out, c)
		}
	}
	return out
}

func runAuth(f *fakeAuthOLT, sp ReauthSpec, before func() error, notAfter time.Time) (ManeuverOutcome, error) {
	if before == nil {
		before = func() error { return nil }
	}
	return RunBenchReauthorize(context.Background(), f, onu14, sp, notAfter, before, 500*time.Millisecond, time.Millisecond, time.Now, nil)
}

func TestReauthorizeHappyPathSendsTheClosedSequenceAndEndsOnTheBaseline(t *testing.T) {
	f := newAuth()
	var saved string
	out, err := RunBenchReauthorize(context.Background(), f, onu14, spec14, far(), func() error { return nil }, 500*time.Millisecond, time.Millisecond, time.Now,
		func(name, text string) { saved = name + "|" + text })
	if err != nil || !out.Sent || !out.Done {
		t.Fatalf("out=%+v err=%v", out, err)
	}
	want := []string{"undo service-port 1708", "ont delete 14 10",
		"ont add 14 10 sn-auth 48575443E2247AA5 omci ont-lineprofile-id 179 ont-srvprofile-id 179 desc BANCADA-HW",
		"service-port 1708 vlan 1400 gpon 0/0/14 ont 10 gemport 1 multi-service user-vlan 1400 tag-transform translate"}
	if got := f.mutating(); strings.Join(got, "|") != strings.Join(want, "|") {
		t.Fatalf("mutating commands %v", got)
	}
	if !strings.HasPrefix(saved, "autofind-after-delete|") || !strings.Contains(saved, "48575443E2247AA5") {
		t.Fatalf("the autofind text must be handed to the local capture: %q", saved)
	}
	// nothing outside the closed list, nothing broader than ONE ONU / ONE service port
	bad := regexp.MustCompile(`\ball\b|graceful|undo ont|reset|reboot|save|port 0/0/1[^4]|ont 1[1-9]`)
	for _, c := range f.sent {
		if bad.MatchString(c) && !strings.HasPrefix(c, "display") {
			t.Errorf("command outside the plan: %q", c)
		}
	}
}

func TestReauthorizeRefusesBeforeAnyChangeWhenTheBaselineDiffers(t *testing.T) {
	cases := map[string]func(*fakeAuthOLT, *ReauthSpec){
		"another line profile on the OLT":  func(f *fakeAuthOLT, _ *ReauthSpec) { f.line = 5 },
		"another service profile":          func(f *fakeAuthOLT, _ *ReauthSpec) { f.srv = 5 },
		"another description":              func(f *fakeAuthOLT, _ *ReauthSpec) { f.desc = "OUTRO" },
		"service port with another detail": func(f *fakeAuthOLT, _ *ReauthSpec) { f.tag = "transparent" },
		"a second service port":            func(f *fakeAuthOLT, _ *ReauthSpec) { f.extraSP = true },
		"no service port at all":           func(f *fakeAuthOLT, _ *ReauthSpec) { f.spPresent = false },
		"configured index differs":         func(_ *fakeAuthOLT, s *ReauthSpec) { s.ServicePortIndex = 1709 },
		"configured vlan differs":          func(_ *fakeAuthOLT, s *ReauthSpec) { s.VLAN = 1401 },
	}
	for name, mod := range cases {
		f, sp := newAuth(), spec14
		mod(f, &sp)
		_, err := runAuth(f, sp, func() error { t.Errorf("%s: beforeSend must not run", name); return nil }, far())
		if err == nil || len(f.mutating()) != 0 {
			t.Errorf("%s: err=%v mutating=%v", name, err, f.mutating())
		}
	}
}

func TestReauthorizeNeverStartsOutsideTheWindowOrWhenTheClaimFails(t *testing.T) {
	f := newAuth()
	if _, err := runAuth(f, spec14, nil, time.Now().Add(-time.Second)); err == nil || len(f.mutating()) != 0 {
		t.Fatalf("window over: err=%v mutating=%v", err, f.mutating())
	}
	f = newAuth()
	if _, err := runAuth(f, spec14, func() error { return fmt.Errorf("claim taken") }, far()); err == nil || len(f.mutating()) != 0 {
		t.Fatalf("claim failed: err=%v mutating=%v", err, f.mutating())
	}
}

func TestReauthorizeRestoresTheBaselineWhenTheAddFailsOnce(t *testing.T) {
	f := newAuth()
	f.addFailsOnce = true
	out, err := runAuth(f, spec14, nil, far())
	if err == nil || !out.Sent || out.Done || !strings.Contains(out.Detail, "baseline was restored") {
		t.Fatalf("out=%+v err=%v", out, err)
	}
	if !f.ontPresent || !f.spPresent || f.line != 179 {
		t.Fatalf("the ONU and its service port must be back: %+v", f)
	}
}

func TestReauthorizeRestoresWhenTheSerialNeverShowsInAutofind(t *testing.T) {
	f := newAuth()
	f.neverInAutofind = true
	out, err := runAuth(f, spec14, nil, far())
	if err == nil || !out.Sent || out.Done || !f.ontPresent || !f.spPresent {
		t.Fatalf("out=%+v err=%v state ont=%v sp=%v", out, err, f.ontPresent, f.spPresent)
	}
}

func TestReauthorizeReportsWhenItCannotRestore(t *testing.T) {
	f := newAuth()
	f.refuse["ont add"] = true
	out, err := runAuth(f, spec14, nil, far())
	if err == nil || !out.Sent || out.Done || !strings.Contains(err.Error(), "restore it by hand") {
		t.Fatalf("out=%+v err=%v", out, err)
	}
}

func TestReauthorizeUndoRefusedMeansNothingChanged(t *testing.T) {
	f := newAuth()
	f.refuse["undo service-port"] = true
	out, err := runAuth(f, spec14, nil, far())
	if err == nil || out.Sent || !f.ontPresent {
		t.Fatalf("out=%+v err=%v", out, err)
	}
}

func TestReauthorizeCommandsAreExactAndSpecIsValidated(t *testing.T) {
	c := onu14.ReauthCommands(spec14)
	if c.Delete != "ont delete 14 10" || c.UndoSP != "undo service-port 1708" {
		t.Fatalf("%+v", c)
	}
	for _, bad := range []ReauthSpec{{LineProfileID: 2000, SrvProfileID: 1, ServicePortIndex: 1, VLAN: 10, Gem: 1}, {LineProfileID: 1, SrvProfileID: 1, ServicePortIndex: 1, VLAN: 0, Gem: 1},
		{LineProfileID: 1, SrvProfileID: 1, ServicePortIndex: 1, VLAN: 10, Gem: 1, Description: "x; reboot"}, {LineProfileID: 1, SrvProfileID: 1, ServicePortIndex: 1, VLAN: 10, Gem: 1, Description: "a b"}} {
		if bad.Valid() {
			t.Errorf("must be invalid: %+v", bad)
		}
		if _, err := RunBenchReauthorize(context.Background(), newAuth(), onu14, bad, far(), func() error { return nil }, time.Millisecond, time.Millisecond, time.Now, nil); err == nil {
			t.Errorf("must refuse before anything: %+v", bad)
		}
	}
}

func TestParseServicePortsIsStrict(t *testing.T) {
	if rows, err := ParseServicePorts("  Failure: No service virtual port can be operated\n"); err != nil || len(rows) != 0 {
		t.Fatalf("empty list: %v %v", rows, err)
	}
	if _, err := ParseServicePorts("something unexpected"); err == nil {
		t.Fatal("an answer that is neither rows nor the known empty form must not be read as empty")
	}
	if _, err := ParseServicePorts("   1708 1400 common   gpon 0/0 /14 10   1     vlan  1400       -    -    up   \n  Total : 2  (Up/Down :    2/0)\n"); err == nil {
		t.Fatal("a count that does not match must be refused")
	}
}
