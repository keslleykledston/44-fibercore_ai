package olt

import (
	"context"
	"errors"
	"fmt"
	"strings"
	"testing"
)

// queryRec is a Session that answers from a table and records everything sent, behind the SAME allowlist the real session enforces.
type queryRec struct {
	allowed func(string) bool
	reply   map[string]string
	sent    []string
	failOn  string
}

func (r *queryRec) Run(_ context.Context, cmd string) (string, error) {
	r.sent = append(r.sent, cmd)
	if r.allowed != nil && !r.allowed(cmd) {
		return "", ErrCommandDenied
	}
	if r.failOn == cmd {
		return "", errors.New("link down")
	}
	return r.reply[cmd], nil
}

const r015VersionText = "  VERSION : MA5600V800R015C00\n  PRODUCT : MA5608T\n"

func newQueryRec(h HuaweiR015) *queryRec {
	return &queryRec{allowed: h.Allowed, reply: map[string]string{"display version": r015VersionText}}
}

func TestCatalogIsReadOnlyByConstruction(t *testing.T) {
	seen := map[string]bool{}
	for _, q := range Queries() {
		if seen[q.ID] {
			t.Fatalf("duplicate id %s", q.ID)
		}
		seen[q.ID] = true
		if !strings.HasPrefix(q.Template, "display ") {
			t.Fatalf("%s is not a display command: %s", q.ID, q.Template)
		}
		if writeVerbs.MatchString(q.Template) {
			t.Fatalf("%s contains a write/exit verb: %s", q.ID, q.Template)
		}
		pl, err := q.Render(maxParams(q))
		if err != nil {
			t.Fatalf("%s does not render with its maximum parameters: %v", q.ID, err)
		}
		if !queryLine.MatchString(pl.Command) || strings.ContainsAny(pl.Command, ";|&><`$\"'\\\n\r") {
			t.Fatalf("%s renders an unsafe line: %q", q.ID, pl.Command)
		}
	}
	for _, id := range []string{"olt.version", "olt.board", "pon.ont.info", "pon.ont.optical"} { // proven on the real OLT
		if q, _ := QueryByID(id); !q.Validated {
			t.Fatalf("%s was observed on the real OLT and must be Validated", id)
		}
	}
	if len(Queries()) < 20 {
		t.Fatal("catalog suspiciously small")
	}
}

func maxParams(q Query) Params {
	p := Params{}
	switch q.Scope {
	case ScopeSlot:
		p.Slot = maxSlot
	case ScopePON:
		p.Slot, p.Port = maxSlot, maxPort
	case ScopeONU:
		p.Slot, p.Port, p.ONT = maxSlot, maxPort, maxONT
	}
	return p
}

func TestRenderValidatesEveryParameterAndRejectsUnusedOnes(t *testing.T) {
	onu, _ := QueryByID("onu.register")
	pl, err := onu.Render(Params{Slot: 1, Port: 0, ONT: 5})
	if err != nil || pl.Enter != "interface gpon 0/1" || pl.Command != "display ont register-info 0 5" {
		t.Fatalf("%+v %v", pl, err)
	}
	for _, bad := range []Params{{Slot: -1, Port: 0, ONT: 5}, {Slot: 18, Port: 0, ONT: 5}, {Slot: 1, Port: 16, ONT: 5}, {Slot: 1, Port: 0, ONT: 128}, {Slot: 1, Port: 0, ONT: -3}} {
		if _, err := onu.Render(bad); !errors.Is(err, ErrBadQueryParams) {
			t.Fatalf("%+v must be rejected, got %v", bad, err)
		}
	}
	global, _ := QueryByID("olt.alarm.active")
	if _, err := global.Render(Params{Slot: 1}); !errors.Is(err, ErrBadQueryParams) {
		t.Fatal("a global query must not take parameters")
	}
	pon, _ := QueryByID("pon.ont.info")
	if _, err := pon.Render(Params{Slot: 1, Port: 2, ONT: 9}); !errors.Is(err, ErrBadQueryParams) {
		t.Fatal("a PON query must not take an ont-id")
	}
}

func TestOnlyValidatedQueriesAreAllowedUntilTheOperatorEnablesOne(t *testing.T) {
	h := HuaweiR015{}
	for cmd, want := range map[string]bool{
		"display version": true, "display board 0": true, "display ont info 3 all": true, "display ont optical-info 3 all": true,
		"display alarm active all": false, "display ont register-info 0 5": false, "display cpu 0/3": false,
		// never allowed whatever the policy
		"display ont info 3 all; reload": false, "reboot": false, "undo ont add 0 5": false, "save": false, "display\nreload": false,
		"display ont register-info 0 5 | include x": false, "display version 1": false,
		// bounds are enforced by the allowlist itself, also for the validated queries
		"display ont info 15 all": true, "display ont info 16 all": false, "display ont info 999 all": false, "display ont info 007 all": false,
		"display ont optical-info 99 all": false, "display ont optical-info -1 all": false, "display board 1": false,
		// the generic Huawei forms with unbounded F/S/P are not part of this profile
		"display ont optical-info 999/999/999 all": false, "display ont optical-info 0/1/0 all": false, "display ont info summary 0/1/0": false,
		// CLI mode words: interface context is frame 0, slot 0..17, canonical numbers
		"enable": true, "config": true, "quit": true, "interface gpon 0/0": true, "interface gpon 0/1": true, "interface gpon 0/17": true,
		"interface gpon 0/18": false, "interface gpon 1/1": false, "interface gpon 999/999": false, "interface gpon 0/01": false,
		"interface gpon 0/1 ": false, "interface gpon 0/-1": false, "interface gpon 0/1; reload": false, "reload": false, "system-view": false,
	} {
		if got := h.Allowed(cmd); got != want {
			t.Fatalf("Allowed(%q)=%v want %v", cmd, got, want)
		}
	}
	h2 := HuaweiR015{Queries: QueryPolicy{Enabled: map[string]bool{"onu.register": true, "olt.alarm.active": true}}}
	for cmd, want := range map[string]bool{
		"display ont register-info 0 5": true, "display ont register-info 15 127": true, "display ont register-info 16 5": false,
		"display ont register-info 0 128": false, "display ont register-info 0 05": false, "display alarm active all": true,
		"display cpu 0/3": false, "display alarm history all list": false, "display ont register-info 0 5; reload": false,
		"display ont register-info 0 5 6": false,
	} {
		if got := h2.Allowed(cmd); got != want {
			t.Fatalf("enabled: Allowed(%q)=%v want %v", cmd, got, want)
		}
	}
	if (QueryPolicy{Enabled: map[string]bool{"ghost": true}}).allows("display ghost") {
		t.Fatal("an enabled id that is not in the catalog must allow nothing")
	}
}

func TestRunQueryWalksModesAndAlwaysLeavesTheInterface(t *testing.T) {
	h := HuaweiR015{Queries: QueryPolicy{Enabled: map[string]bool{"onu.register": true}}}
	r := newQueryRec(h)
	r.reply["display ont register-info 0 5"] = "  ONT registration times : 3\n"
	res, err := h.RunQuery(context.Background(), r, "onu.register", Params{Slot: 1, Port: 0, ONT: 5})
	if err != nil || !strings.Contains(res.Output, "registration times") || res.Truncated {
		t.Fatalf("%+v %v", res, err)
	}
	want := []string{"display version", "enable", "config", "interface gpon 0/1", "display ont register-info 0 5", "quit"}
	if fmt.Sprint(r.sent) != fmt.Sprint(want) {
		t.Fatalf("sent %v want %v", r.sent, want)
	}
	// global query: no interface context, no quit
	r = newQueryRec(h)
	if _, err := h.RunQuery(context.Background(), r, "olt.board", Params{}); err != nil || fmt.Sprint(r.sent) != "[display version enable config display board 0]" {
		t.Fatalf("%v %v", r.sent, err)
	}
	// a failing query still leaves the interface
	r = newQueryRec(h)
	r.failOn = "display ont register-info 0 5"
	if _, err := h.RunQuery(context.Background(), r, "onu.register", Params{Slot: 1, Port: 0, ONT: 5}); err == nil || r.sent[len(r.sent)-1] != "quit" {
		t.Fatalf("err=%v sent=%v", err, r.sent)
	}
}

func TestRunQueryRefusesBeforeTouchingTheDevice(t *testing.T) {
	h := HuaweiR015{}
	for name, tc := range map[string]struct {
		id  string
		p   Params
		err error
	}{
		"unknown id":        {"onu.reboot", Params{}, ErrUnknownQuery},
		"not enabled":       {"onu.register", Params{Slot: 1, ONT: 5}, ErrQueryNotEnabled},
		"bad params":        {"pon.ont.info", Params{Slot: 99, Port: 0}, ErrBadQueryParams},
		"free-form command": {"display version; reload", Params{}, ErrUnknownQuery},
	} {
		r := newQueryRec(h)
		if _, err := h.RunQuery(context.Background(), r, tc.id, tc.p); !errors.Is(err, tc.err) || len(r.sent) != 0 {
			t.Fatalf("%s: err=%v sent=%v", name, err, r.sent)
		}
	}
}

func TestRunQueryTrustsTheSessionNotTheCaller(t *testing.T) {
	h := HuaweiR015{}
	for name, version := range map[string]string{
		"other release": "  VERSION : MA5600V800R018C10\n  PRODUCT : MA5608T\n",
		"other model":   "  VERSION : MA5600V800R015C00\n  PRODUCT : MA5800-X7\n",
		"unreadable":    "garbage\n",
	} {
		r := newQueryRec(h)
		r.reply["display version"] = version
		_, err := h.RunQuery(context.Background(), r, "olt.board", Params{})
		if err == nil || (name != "unreadable" && !errors.Is(err, ErrQueryFirmware)) { // unreadable: refused by Identify itself
			t.Fatalf("%s: %v", name, err)
		}
		if fmt.Sprint(r.sent) != "[display version]" {
			t.Fatalf("%s: only the identification may be sent to an unverified device, sent %v", name, r.sent)
		}
	}
	r := newQueryRec(h)
	r.failOn = "display version"
	if _, err := h.RunQuery(context.Background(), r, "olt.board", Params{}); err == nil || len(r.sent) != 1 {
		t.Fatalf("identification failure must stop the query: %v %v", err, r.sent)
	}
}

func TestRunQueryFailsClosedOnDeviceRejectionPaginationAndCapsOutput(t *testing.T) {
	h := HuaweiR015{}
	r := newQueryRec(h)
	r.reply["display board 0"] = "  Unknown command, the error locates at '^'\n"
	if _, err := h.RunQuery(context.Background(), r, "olt.board", Params{}); !errors.Is(err, ErrDeviceRejected) {
		t.Fatalf("%v", err)
	}
	r = newQueryRec(h)
	r.reply["display board 0"] = "line\n---- More ( Press 'Q' to break ) ----"
	if _, err := h.RunQuery(context.Background(), r, "olt.board", Params{}); !errors.Is(err, ErrPaginated) {
		t.Fatalf("%v", err)
	}
	r = newQueryRec(h)
	r.reply["display board 0"] = strings.Repeat("x", MaxQueryOutput+10)
	res, err := h.RunQuery(context.Background(), r, "olt.board", Params{})
	if err != nil || !res.Truncated || len(res.Output) != MaxQueryOutput {
		t.Fatalf("truncated=%v len=%d err=%v", res.Truncated, len(res.Output), err)
	}
}

func TestSnapshotRejectsInvalidPortsBeforeSendingAnyCommand(t *testing.T) {
	h := HuaweiR015{}
	for _, ports := range [][]string{{"1/0/14"}, {"0/18/1"}, {"0/0/16"}, {"0/0/14", "0/0/99"}, {"0/00/1"}, {"abc"}, {"0/0/1; reload"}} {
		r := newQueryRec(h)
		if _, err := h.Snapshot(context.Background(), r, ports); err == nil || len(r.sent) != 0 {
			t.Fatalf("%v: err=%v sent=%v (must refuse with zero commands, identification included)", ports, err, r.sent)
		}
	}
	if !ValidR015Port("0/17/15") || ValidR015Port("0/17/16") || ValidR015Port("1/0/0") {
		t.Fatal("ValidR015Port limits drifted from the catalog")
	}
}
