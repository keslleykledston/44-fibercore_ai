package olt

import (
	"context"
	"errors"
	"fmt"
	"strings"
	"testing"
)

var r015ID = Identity{Vendor: "huawei", Model: "MA5608T", Firmware: "MA5600V800R015C00"}

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

func newQueryRec(h HuaweiR015) *queryRec {
	return &queryRec{allowed: h.Allowed, reply: map[string]string{}}
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
	} {
		if got := h.Allowed(cmd); got != want {
			t.Fatalf("Allowed(%q)=%v want %v", cmd, got, want)
		}
	}
	h2 := HuaweiR015{Queries: QueryPolicy{Enabled: map[string]bool{"onu.register": true, "olt.alarm.active": true}}}
	for cmd, want := range map[string]bool{
		"display ont register-info 0 5": true, "display alarm active all": true,
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
	res, err := h.RunQuery(context.Background(), r, r015ID, "onu.register", Params{Slot: 1, Port: 0, ONT: 5})
	if err != nil || !strings.Contains(res.Output, "registration times") || res.Truncated {
		t.Fatalf("%+v %v", res, err)
	}
	want := []string{"enable", "config", "interface gpon 0/1", "display ont register-info 0 5", "quit"}
	if fmt.Sprint(r.sent) != fmt.Sprint(want) {
		t.Fatalf("sent %v want %v", r.sent, want)
	}
	// global query: no interface context, no quit
	r = newQueryRec(h)
	if _, err := h.RunQuery(context.Background(), r, r015ID, "olt.board", Params{}); err != nil || fmt.Sprint(r.sent) != "[enable config display board 0]" {
		t.Fatalf("%v %v", r.sent, err)
	}
	// a failing query still leaves the interface
	r = newQueryRec(h)
	r.failOn = "display ont register-info 0 5"
	if _, err := h.RunQuery(context.Background(), r, r015ID, "onu.register", Params{Slot: 1, Port: 0, ONT: 5}); err == nil || r.sent[len(r.sent)-1] != "quit" {
		t.Fatalf("err=%v sent=%v", err, r.sent)
	}
}

func TestRunQueryRefusesBeforeTouchingTheDevice(t *testing.T) {
	h := HuaweiR015{}
	for name, tc := range map[string]struct {
		id  string
		p   Params
		idn Identity
		err error
	}{
		"unknown id":        {"onu.reboot", Params{}, r015ID, ErrUnknownQuery},
		"not enabled":       {"onu.register", Params{Slot: 1, ONT: 5}, r015ID, ErrQueryNotEnabled},
		"bad params":        {"pon.ont.info", Params{Slot: 99, Port: 0}, r015ID, ErrBadQueryParams},
		"other firmware":    {"olt.board", Params{}, Identity{Vendor: "huawei", Model: "MA5608T", Firmware: "MA5600V800R018C10"}, ErrQueryFirmware},
		"other model":       {"olt.board", Params{}, Identity{Vendor: "huawei", Model: "MA5800-X7", Firmware: "MA5600V800R015C00"}, ErrQueryFirmware},
		"free-form command": {"display version; reload", Params{}, r015ID, ErrUnknownQuery},
	} {
		r := newQueryRec(h)
		if _, err := h.RunQuery(context.Background(), r, tc.idn, tc.id, tc.p); !errors.Is(err, tc.err) || len(r.sent) != 0 {
			t.Fatalf("%s: err=%v sent=%v", name, err, r.sent)
		}
	}
}

func TestRunQueryFailsClosedOnDeviceRejectionPaginationAndCapsOutput(t *testing.T) {
	h := HuaweiR015{}
	r := newQueryRec(h)
	r.reply["display board 0"] = "  Unknown command, the error locates at '^'\n"
	if _, err := h.RunQuery(context.Background(), r, r015ID, "olt.board", Params{}); !errors.Is(err, ErrDeviceRejected) {
		t.Fatalf("%v", err)
	}
	r = newQueryRec(h)
	r.reply["display board 0"] = "line\n---- More ( Press 'Q' to break ) ----"
	if _, err := h.RunQuery(context.Background(), r, r015ID, "olt.board", Params{}); !errors.Is(err, ErrPaginated) {
		t.Fatalf("%v", err)
	}
	r = newQueryRec(h)
	r.reply["display board 0"] = strings.Repeat("x", MaxQueryOutput+10)
	res, err := h.RunQuery(context.Background(), r, r015ID, "olt.board", Params{})
	if err != nil || !res.Truncated || len(res.Output) != MaxQueryOutput {
		t.Fatalf("truncated=%v len=%d err=%v", res.Truncated, len(res.Output), err)
	}
}
