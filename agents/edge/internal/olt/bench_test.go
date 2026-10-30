package olt

import (
	"context"
	"errors"
	"fmt"
	"strings"
	"sync"
	"testing"
	"time"
)

var onu14 = BenchONU{Frame: 0, Slot: 0, Port: 14, OntID: 10, GPONSerial: "48575443E2247AA5"}

// fakeOLT simulates the CLI of the OLT for the bench ONU (and shows what a wrong ONU would look like).
type fakeOLT struct {
	mu                   sync.Mutex
	sent                 []string
	ctl, run, lastUp     string
	fsp, sn, cfg, match  string
	records              int
	infoCallsAfterChange int
	returnAfter          int  // info calls after reset/activate before the ONU is back online
	neverReturn          bool // the ONU stays offline
	refuse               string
	activateErr          error
	resetOut             string
	pendingUp            bool
	noDown               bool // a deactivate does not show in the state
}

func newFake() *fakeOLT {
	return &fakeOLT{ctl: "active", run: "online", lastUp: "2026-10-30 05:00:00-04:00", fsp: "0/0/14", sn: "48575443E2247AA5", cfg: "normal", match: "match", records: 1, returnAfter: 1}
}

func (f *fakeOLT) render() string {
	var b strings.Builder
	for i := 0; i < f.records; i++ {
		fmt.Fprintf(&b, "  -----------------------------\n  F/S/P                   : %s\n  ONT-ID                  : 10\n  Control flag            : %s\n  Run state               : %s\n  Config state            : %s\n  Match state             : %s\n  SN                      : %s (HWTC-E2247AA5)\n  Memory occupation       : 38%%\n  Last up time            : %s\n", f.fsp, f.ctl, f.run, f.cfg, f.match, f.sn, f.lastUp)
	}
	return b.String()
}

func (f *fakeOLT) Run(_ context.Context, cmd string) (string, error) {
	f.mu.Lock()
	defer f.mu.Unlock()
	f.sent = append(f.sent, cmd)
	if f.refuse != "" && strings.HasPrefix(cmd, f.refuse) {
		return "  % Parameter error, the error locates at '^'", nil
	}
	switch {
	case strings.HasPrefix(cmd, "display ont info"):
		if f.pendingUp {
			f.infoCallsAfterChange++
			if !f.neverReturn && f.infoCallsAfterChange >= f.returnAfter {
				f.run, f.pendingUp = "online", false
				if f.ctl == "active" {
					f.lastUp = "2026-10-30 05:09:00-04:00"
				}
			}
		}
		return f.render(), nil
	case strings.HasPrefix(cmd, "ont reset"):
		f.run, f.pendingUp, f.infoCallsAfterChange = "offline", true, 0
		return f.resetOut, nil
	case strings.HasPrefix(cmd, "ont deactivate"):
		if !f.noDown {
			f.ctl, f.run = "deactivate", "offline"
		}
		return "", nil
	case strings.HasPrefix(cmd, "ont activate"):
		if f.activateErr != nil {
			return "", f.activateErr
		}
		f.ctl, f.run, f.pendingUp, f.infoCallsAfterChange = "active", "offline", true, 0
		return "", nil
	}
	return "", nil
}

func (f *fakeOLT) changing() []string {
	var out []string
	for _, c := range f.sent {
		if strings.HasPrefix(c, "ont ") {
			out = append(out, c)
		}
	}
	return out
}

func far() time.Time { return time.Now().Add(time.Hour) }

func run(t *testing.T, f *fakeOLT, op string, before func() error) (ManeuverOutcome, error) {
	if before == nil {
		before = func() error { return nil }
	}
	return RunBenchManeuver(context.Background(), f, onu14, op, far(), before, 500*time.Millisecond, time.Millisecond, time.Now)
}

func TestResetHappyPathSendsExactlyOneFixedCommand(t *testing.T) {
	f := newFake()
	out, err := run(t, f, "onu_reset", nil)
	if err != nil || !out.Sent || !out.Done {
		t.Fatalf("out=%+v err=%v", out, err)
	}
	if got := f.changing(); len(got) != 1 || got[0] != "ont reset 14 10" {
		t.Fatalf("changing commands %v", got)
	}
	want := []string{"enable", "display ont info by-sn 48575443E2247AA5", "config", "interface gpon 0/0"}
	for i, w := range want {
		if f.sent[i] != w {
			t.Fatalf("step %d: %q want %q (all %v)", i, f.sent[i], w, f.sent)
		}
	}
}

func TestDeactivateIsAlwaysFollowedByTheReactivation(t *testing.T) {
	f := newFake()
	out, err := run(t, f, "onu_deactivate", nil)
	if err != nil || !out.Done {
		t.Fatalf("out=%+v err=%v", out, err)
	}
	if got := strings.Join(f.changing(), ","); got != "ont deactivate 14 10,ont activate 14 10" {
		t.Fatalf("got %s", got)
	}
	if f.ctl != "active" {
		t.Fatal("the ONU must end active")
	}
	// the deactivation does not show in the state: still reactivated, and the result says it was not proven
	f = newFake()
	f.noDown = true
	out, err = run(t, f, "onu_deactivate", nil)
	if !errors.Is(err, ErrBenchOLTNoReturn) || out.Done || strings.Join(f.changing(), ",") != "ont deactivate 14 10,ont activate 14 10" {
		t.Fatalf("out=%+v err=%v sent=%v", out, err, f.changing())
	}
}

func TestDeactivateThatCannotBeReactivatedSaysSo(t *testing.T) {
	f := newFake()
	f.activateErr = errors.New("session broke")
	out, err := run(t, f, "onu_deactivate", nil)
	if !errors.Is(err, ErrBenchOLTStuck) || !out.Sent {
		t.Fatalf("out=%+v err=%v", out, err)
	}
}

func TestResetThatDoesNotComeBackIsReportedAndNeverRepeated(t *testing.T) {
	f := newFake()
	f.neverReturn = true
	out, err := run(t, f, "onu_reset", nil)
	if !errors.Is(err, ErrBenchOLTNoReturn) || !out.Sent || out.Done {
		t.Fatalf("out=%+v err=%v", out, err)
	}
	if len(f.changing()) != 1 {
		t.Fatalf("a reset is sent once: %v", f.changing())
	}
}

func TestNothingIsSentWhenTheIdentityDoesNotMatch(t *testing.T) {
	cases := map[string]func(*fakeOLT){
		"other port":       func(f *fakeOLT) { f.fsp = "0/0/13" },
		"other serial":     func(f *fakeOLT) { f.sn = "48575443AAAAAAAA" },
		"two records":      func(f *fakeOLT) { f.records = 2 },
		"offline":          func(f *fakeOLT) { f.run = "offline" },
		"already inactive": func(f *fakeOLT) { f.ctl = "deactivate" },
		"config not ok":    func(f *fakeOLT) { f.cfg = "failed" },
		"no match":         func(f *fakeOLT) { f.match = "mismatch" },
	}
	for name, mut := range cases {
		for _, op := range []string{"onu_reset", "onu_deactivate"} {
			f := newFake()
			mut(f)
			called := false
			_, err := run(t, f, op, func() error { called = true; return nil })
			if err == nil || called || len(f.changing()) != 0 {
				t.Errorf("%s/%s: err=%v called=%v sent=%v", name, op, err, called, f.changing())
			}
		}
	}
}

func TestBeforeSendFailureAndExpiryStopEverything(t *testing.T) {
	f := newFake()
	_, err := run(t, f, "onu_reset", func() error { return errors.New("pacing") })
	if !errors.Is(err, ErrBenchOLTBefore) || len(f.changing()) != 0 {
		t.Fatalf("err=%v sent=%v", err, f.changing())
	}
	f = newFake()
	called := false
	_, err = RunBenchManeuver(context.Background(), f, onu14, "onu_reset", time.Now().Add(-time.Second), func() error { called = true; return nil }, time.Second, time.Millisecond, time.Now)
	if err == nil || called || len(f.changing()) != 0 {
		t.Fatalf("expired: err=%v called=%v", err, called)
	}
}

func TestRefusalIsNotASend(t *testing.T) {
	f := newFake()
	f.refuse = "ont reset"
	out, err := run(t, f, "onu_reset", nil)
	if !errors.Is(err, ErrBenchOLTRefused) || out.Sent {
		t.Fatalf("out=%+v err=%v", out, err)
	}
	f = newFake()
	f.resetOut = "Number of ONTs that can be reset: 1, success: 1\nFailure: 0"
	if out, err := run(t, f, "onu_reset", nil); err != nil || !out.Done {
		t.Fatalf("a report that prints 'Failure: 0' is not a refusal: %+v %v", out, err)
	}
}

func TestOnlyTheClosedListOfCommandsCanBeSent(t *testing.T) {
	f := newFake()
	s := newBenchSession(f, onu14.Commands())
	for _, bad := range []string{"ont reset 14 all", "ont reset 14 graceful", "ont reset 14 11", "ont reset 13 10", "ont deactivate 14 all", "ont activate 14 all",
		"display ont info 14 all", "undo ont add 14 10", "interface gpon 0/1", "reboot", "ont reset 14 10 ", "ont reset 14 10; ont reset 14 11", "save", "display version"} {
		if _, err := s.Run(context.Background(), bad); !errors.Is(err, ErrBenchOLTCommand) {
			t.Errorf("%q must be refused: %v", bad, err)
		}
	}
	if len(f.sent) != 0 {
		t.Fatalf("nothing reached the device: %v", f.sent)
	}
	for _, p := range []BenchONU{{0, 0, 16, 10, onu14.GPONSerial}, {0, 0, 14, 128, onu14.GPONSerial}, {0, 0, 14, 10, "short"}, {0, 0, 14, 10, "48575443e2247aa5"}, {-1, 0, 14, 10, onu14.GPONSerial}} {
		if p.valid() {
			t.Errorf("%+v must be invalid", p)
		}
	}
	src := fmt.Sprintf("%v", onu14.Commands())
	if strings.Contains(src, "all") || strings.Contains(src, "graceful") {
		t.Fatalf("the command list must not contain all/graceful: %s", src)
	}
}

func TestParseONTInfoNeedsExactlyOneRecord(t *testing.T) {
	f := newFake()
	i, err := ParseONTInfo(f.render())
	if err != nil || i.OntID != 10 || i.SN != "48575443E2247AA5" || i.RunState != "online" || i.LastUp == "" {
		t.Fatalf("%+v %v", i, err)
	}
	f.records = 2
	if _, err := ParseONTInfo(f.render()); err == nil {
		t.Fatal("two records must be refused")
	}
	if _, err := ParseONTInfo("garbage"); err == nil {
		t.Fatal("no record must be refused")
	}
}
