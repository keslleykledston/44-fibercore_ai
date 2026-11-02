package olt

import (
	"context"
	"errors"
	"fmt"
	"regexp"
	"strconv"
	"strings"
	"time"
)

// ADR-0030 amendment H5 (bench only): `onu_reauthorize` removes the bench ONU's registration from the OLT and authorizes it again, with the SAME profiles and the SAME
// service port it had, then proves the way back. It is the homologation of the OLT-side authorization of an ONU (`ont add` + `service-port`) on the one ONU that may be
// touched. Every value that goes into a command comes from the Edge's LOCAL configuration (ReauthSpec), is compared with what the OLT reports BEFORE anything changes,
// and is compared again at the end; the Cloud sends nothing but the operation name. The command list is closed and exact.

var (
	ErrReauthBaseline = errors.New("olt bench: the ONU or its service port on the OLT do not match the configured baseline")
	ErrReauthRestore  = errors.New("olt bench: the ONU may be left unauthorized or without its service port; restore it by hand")
)

// ReauthSpec is the baseline of the bench ONU, pinned in the Edge's local configuration (never learned from the Cloud, never changed by the maneuver).
type ReauthSpec struct {
	LineProfileID, SrvProfileID int
	ServicePortIndex, VLAN, Gem int
	Description                 string // may be empty; the same text the ONU already has on the OLT
}

var descRe = regexp.MustCompile(`^[A-Za-z0-9._-]{0,64}$`)

// Valid: every number in range and the description inside a safe alphabet (it is typed into a command).
func (r ReauthSpec) Valid() bool {
	return r.LineProfileID >= 0 && r.LineProfileID <= 1024 && r.SrvProfileID >= 0 && r.SrvProfileID <= 1024 && r.ServicePortIndex >= 0 && r.ServicePortIndex <= 20479 &&
		r.VLAN >= 1 && r.VLAN <= 4094 && r.Gem >= 0 && r.Gem <= 127 && descRe.MatchString(r.Description)
}

// ReauthCommands are the exact strings that may be sent, for this ONU and this baseline, and nothing else.
type ReauthCommands struct {
	BenchCommands
	ListSP, DetailSP, UndoSP, Delete, Add, AddSP, Autofind string
}

func (b BenchONU) ReauthCommands(r ReauthSpec) ReauthCommands {
	add := fmt.Sprintf("ont add %d %d sn-auth %s omci ont-lineprofile-id %d ont-srvprofile-id %d", b.Port, b.OntID, b.GPONSerial, r.LineProfileID, r.SrvProfileID)
	if r.Description != "" {
		add += " desc " + r.Description
	}
	return ReauthCommands{
		BenchCommands: b.Commands(),
		ListSP:        fmt.Sprintf("display service-port port %s ont %d", b.fsp(), b.OntID),
		DetailSP:      fmt.Sprintf("display service-port %d", r.ServicePortIndex),
		UndoSP:        fmt.Sprintf("undo service-port %d", r.ServicePortIndex),
		Delete:        fmt.Sprintf("ont delete %d %d", b.Port, b.OntID),
		Add:           add,
		AddSP: fmt.Sprintf("service-port %d vlan %d gpon %s ont %d gemport %d multi-service user-vlan %d tag-transform translate",
			r.ServicePortIndex, r.VLAN, b.fsp(), b.OntID, r.Gem, r.VLAN),
		Autofind: "display ont autofind all",
	}
}

// ReauthConfirm: the question each mutating command may ask. Observed so far: NONE of these were run on the bench OLT yet; an unexpected question fails closed
// (the session ends at the prompt, which cancels the command). The first real run records the exact text; it is added here by amendment.
var ReauthConfirm = map[string]*regexp.Regexp{
	"delete": regexp.MustCompile(`^\s*Are you sure to delete the ONT\(s\)\? \(y/n\)\[n\]:\s*$`),
}

var (
	reProfLine = regexp.MustCompile(`(?m)^\s*Line profile ID\s*:\s*(\d+)\s*$`)
	reProfSrv  = regexp.MustCompile(`(?m)^\s*Service profile ID\s*:\s*(\d+)\s*$`)
	reDesc     = regexp.MustCompile(`(?m)^\s*Description\s*:[ \t]*(.*?)[ \t]*$`)
	reSPRow    = regexp.MustCompile(`(?m)^\s*(\d+)\s+(\d+)\s+(\w+)\s+gpon\s+(\d+)/(\d+)\s*/(\d+)\s+(\d+)\s+(\d+)\s+(\w+)\s+(\S+)\s+\S+\s+\S+\s+(up|down)\s*$`)
	reSPTotal  = regexp.MustCompile(`(?m)^\s*Total\s*:\s*(\d+)\b`)
)

// ONTProfiles: the line and service profile IDs and the description the OLT reports for the ONU.
type ONTProfiles struct {
	Line, Srv   int
	Description string
}

func ParseONTProfiles(out string) (ONTProfiles, error) {
	l, s := reProfLine.FindStringSubmatch(out), reProfSrv.FindStringSubmatch(out)
	if l == nil || s == nil || len(reProfLine.FindAllString(out, -1)) != 1 || len(reProfSrv.FindAllString(out, -1)) != 1 {
		return ONTProfiles{}, fmt.Errorf("%w: profile ids not found exactly once", ErrBenchOLTIdentity)
	}
	line, _ := strconv.Atoi(l[1])
	srv, _ := strconv.Atoi(s[1])
	p := ONTProfiles{Line: line, Srv: srv}
	if d := reDesc.FindStringSubmatch(out); d != nil {
		p.Description = d[1]
	}
	return p, nil
}

// ServicePort is one row of `display service-port port F/S/P ont N`.
type ServicePort struct {
	Index, VLAN, Gem, OntID int
	FSP, FlowType, FlowPara string
	Up                      bool
}

// ParseServicePorts returns the rows; an answer with no row and a "Failure" line is an empty list, and an answer with neither rows nor that line is an error (never
// guessed as empty). The row count must match "Total".
func ParseServicePorts(out string) ([]ServicePort, error) {
	var rows []ServicePort
	for _, m := range reSPRow.FindAllStringSubmatch(out, -1) {
		idx, _ := strconv.Atoi(m[1])
		vlan, _ := strconv.Atoi(m[2])
		ont, _ := strconv.Atoi(m[7])
		gem, _ := strconv.Atoi(m[8])
		rows = append(rows, ServicePort{Index: idx, VLAN: vlan, OntID: ont, Gem: gem, FSP: m[4] + "/" + m[5] + "/" + m[6], FlowType: m[9], FlowPara: m[10], Up: m[11] == "up"})
	}
	if len(rows) == 0 {
		if regexp.MustCompile(`(?i)failure|does not exist|no service virtual port`).MatchString(out) && !reSPTotal.MatchString(out) {
			return nil, nil
		}
		return nil, fmt.Errorf("%w: service port list not understood", ErrBenchOLTRefused)
	}
	if t := reSPTotal.FindStringSubmatch(out); t == nil || t[1] != strconv.Itoa(len(rows)) {
		return nil, fmt.Errorf("%w: service port count does not match", ErrBenchOLTRefused)
	}
	return rows, nil
}

// spOK: the one service port the ONU has is the baseline one.
func spOK(rows []ServicePort, b BenchONU, r ReauthSpec) bool {
	return len(rows) == 1 && rows[0].Index == r.ServicePortIndex && rows[0].VLAN == r.VLAN && rows[0].Gem == r.Gem && rows[0].OntID == b.OntID && rows[0].FSP == b.fsp() &&
		rows[0].FlowType == "vlan" && rows[0].FlowPara == strconv.Itoa(r.VLAN) && rows[0].Up
}

var reKV = func(k string) *regexp.Regexp {
	return regexp.MustCompile(`(?m)^` + regexp.QuoteMeta(k) + `\s*:\s*(.*?)\s*$`)
}

// spDetailOK checks `display service-port <index>`: tag transform `translate`, no traffic tables, enabled and up, on this ONU's position.
func spDetailOK(out string, b BenchONU, r ReauthSpec) bool {
	get := func(k string) string {
		if m := reKV(k).FindStringSubmatch(out); m != nil {
			return m[1]
		}
		return "\x00"
	}
	return get("Index") == strconv.Itoa(r.ServicePortIndex) && get("VLAN ID") == strconv.Itoa(r.VLAN) && get("Port type") == "gpon" && get("F/S/P") == b.fsp() &&
		get("ONT ID") == strconv.Itoa(b.OntID) && get("GEM port index") == strconv.Itoa(r.Gem) && get("Flow type") == "vlan" && get("Flow para") == strconv.Itoa(r.VLAN) &&
		get("Inbound table name") == "-" && get("Outbound table name") == "-" && get("Admin status") == "enable" && get("State") == "up" && get("Tag transform") == "translate"
}

// RunBenchReauthorize runs the H5 cycle over an already open CLI session. Order: baseline reads (nothing changes) -> beforeSend -> undo service-port -> ont delete ->
// the serial must show up in the autofind list (its raw text goes to saveRaw, local only) -> ont add -> wait for the ONU online with the baseline profiles ->
// service-port again -> final comparison. After the first change, a failure never stops half way silently: the restore path re-reads the state and adds back whatever
// is missing (the ONU, then its service port) before it reports. The result is Done only if the end state equals the baseline.
func RunBenchReauthorize(ctx context.Context, raw Session, onu BenchONU, spec ReauthSpec, notAfter time.Time, beforeSend func() error, wait, poll time.Duration,
	now func() time.Time, saveRaw func(name, text string)) (ManeuverOutcome, error) {
	if !onu.valid() || !spec.Valid() {
		return ManeuverOutcome{}, ErrBenchOLTBefore
	}
	c := onu.ReauthCommands(spec)
	allowed := []string{c.Enable, c.Config, c.Iface, c.BySN, c.Info, c.Quit, c.ListSP, c.DetailSP, c.UndoSP, c.Delete, c.Add, c.AddSP, c.Autofind}
	s := newBenchSessionWith(raw, allowed, map[string]bool{c.UndoSP: true}, map[string]*regexp.Regexp{c.Delete: ReauthConfirm["delete"]}, notAfter, now)
	mode := "enable"
	step := func(cmd string) (string, error) {
		out, err := s.Run(ctx, cmd)
		if err == nil && refusedRe.MatchString(out) {
			err = fmt.Errorf("%w: %s", ErrBenchOLTRefused, cmd)
		}
		return out, err
	}
	toConfig := func() error {
		switch mode {
		case "iface":
			if _, err := step(c.Quit); err != nil {
				return err
			}
		case "enable":
			if _, err := step(c.Config); err != nil {
				return err
			}
		}
		mode = "config"
		return nil
	}
	toIface := func() error {
		if mode != "config" {
			if err := toConfig(); err != nil {
				return err
			}
		}
		if _, err := step(c.Iface); err != nil {
			return err
		}
		mode = "iface"
		return nil
	}
	readONU := func() (ONTInfo, ONTProfiles, error) { // in interface mode: the details (profiles, description) are printed there
		if err := toIface(); err != nil {
			return ONTInfo{}, ONTProfiles{}, err
		}
		o, err := step(c.Info)
		if err != nil {
			return ONTInfo{}, ONTProfiles{}, err
		}
		i, err := ParseONTInfo(o)
		if err != nil {
			return ONTInfo{}, ONTProfiles{}, err
		}
		p, err := ParseONTProfiles(o)
		return i, p, err
	}
	readSP := func() ([]ServicePort, error) {
		if err := toConfig(); err != nil {
			return nil, err
		}
		o, err := step(c.ListSP)
		if err != nil {
			return nil, err
		}
		return ParseServicePorts(o)
	}
	// ---- baseline: nothing changes until every one of these reads agrees with the configuration
	out, err := s.Run(ctx, c.Enable)
	if err != nil || refusedRe.MatchString(out) {
		return ManeuverOutcome{}, fmt.Errorf("%w: enable", ErrBenchOLTBefore)
	}
	out, err = s.Run(ctx, c.BySN)
	if err != nil {
		return ManeuverOutcome{}, err
	}
	before, err := ParseONTInfo(out)
	if err != nil || !onu.identityOK(before) {
		return ManeuverOutcome{}, ErrBenchOLTIdentity
	}
	rows, err := readSP()
	if err != nil || !spOK(rows, onu, spec) {
		return ManeuverOutcome{}, ErrReauthBaseline
	}
	det, err := step(c.DetailSP)
	if err != nil || !spDetailOK(det, onu, spec) {
		return ManeuverOutcome{}, ErrReauthBaseline
	}
	info, prof, err := readONU()
	if err != nil || !onu.identityOK(info) || info.LastUp != before.LastUp || prof.Line != spec.LineProfileID || prof.Srv != spec.SrvProfileID || prof.Description != spec.Description {
		return ManeuverOutcome{}, ErrReauthBaseline
	}
	if !now().Before(notAfter) {
		return ManeuverOutcome{}, fmt.Errorf("%w: envelope or authorization window over", ErrBenchOLTBefore)
	}
	if err := beforeSend(); err != nil {
		return ManeuverOutcome{}, fmt.Errorf("%w: %v", ErrBenchOLTBefore, err)
	}
	if !now().Before(notAfter) {
		return ManeuverOutcome{}, fmt.Errorf("%w: window over after the claim; nothing was sent", ErrBenchOLTBefore)
	}
	res := ManeuverOutcome{}
	waitFor := func(ok func() bool, limit time.Duration) bool {
		deadline := time.Now().Add(limit)
		for {
			if ok() {
				return true
			}
			if time.Now().After(deadline) || ctx.Err() != nil {
				return false
			}
			select {
			case <-ctx.Done():
				return false
			case <-time.After(poll):
			}
		}
	}
	// restore: converge to the baseline from whatever state the OLT is in. It only ADDS what is missing (the ONU, then its service port); it never deletes anything.
	restore := func() error {
		present := func() (bool, error) {
			if err := toConfig(); err != nil {
				return false, err
			}
			o, err := s.Run(ctx, c.BySN)
			if err != nil {
				return false, err
			}
			i, perr := ParseONTInfo(o)
			if perr == nil {
				return i.SN == onu.GPONSerial && i.FSP == onu.fsp() && i.OntID == onu.OntID, nil
			}
			if regexp.MustCompile(`(?i)does not exist|failure`).MatchString(o) && !strings.Contains(o, "F/S/P") {
				return false, nil
			}
			return false, perr
		}
		ok, err := present()
		if err != nil {
			return err
		}
		if ok { // the ONU is there (for instance `ont delete` was refused or its outcome is unknown): it must be the BASELINE ONU, not just any ONU at this position
			i, p, e := readONU()
			if e != nil || !onu.identityOK(i) || p.Line != spec.LineProfileID || p.Srv != spec.SrvProfileID || p.Description != spec.Description {
				return ErrReauthBaseline
			}
		}
		if !ok {
			if err := toIface(); err != nil {
				return err
			}
			if _, err := step(c.Add); err != nil {
				return err
			}
			if !waitFor(func() bool {
				i, p, e := readONU()
				return e == nil && onu.identityOK(i) && p.Line == spec.LineProfileID && p.Srv == spec.SrvProfileID
			}, wait) {
				return ErrBenchOLTNoReturn
			}
		}
		rows, err := readSP()
		if err != nil {
			return err
		}
		if len(rows) == 0 {
			if _, err := step(c.AddSP); err != nil {
				return err
			}
			rows, err = readSP()
			if err != nil {
				return err
			}
		}
		if !spOK(rows, onu, spec) {
			return ErrReauthBaseline
		}
		return nil
	}
	fail := func(sent bool, detail string, err error) (ManeuverOutcome, error) {
		res.Sent, res.Detail = sent, detail
		if sent {
			if rerr := restore(); rerr != nil {
				return res, fmt.Errorf("%w: %v (first error: %v)", ErrReauthRestore, rerr, err)
			}
			res.Detail += "; the baseline was restored"
		}
		return res, err
	}
	// ---- 1) the service port goes first (the ONU cannot be removed while it holds one on some firmwares, and it is the thing restore re-adds last)
	if err := toConfig(); err != nil {
		return res, err
	}
	if _, err := step(c.UndoSP); err != nil {
		res.Sent = !(errors.Is(err, ErrBenchOLTRefused) || errors.Is(err, ErrBenchOLTBefore) || (errors.Is(err, ErrInteractive) && !errors.Is(err, ErrAfterAnswer)))
		if res.Sent {
			return fail(true, "undo service-port was sent and not confirmed", err)
		}
		return res, err
	}
	res.Sent = true
	// ---- 2) the registration is removed
	if err := toIface(); err != nil {
		return fail(true, "could not reach the interface mode after removing the service port", err)
	}
	if _, err := step(c.Delete); err != nil {
		return fail(true, "ont delete was not accepted", err)
	}
	// ---- 3) the serial must now be waiting in the autofind list (this is also the capture of its real format, kept on this host only)
	if err := toConfig(); err != nil {
		return fail(true, "could not reach the config mode to read autofind", err)
	}
	af, err := step(c.Autofind)
	if err != nil {
		return fail(true, "autofind could not be read", err)
	}
	if saveRaw != nil {
		saveRaw("autofind-after-delete", af)
	}
	if !strings.Contains(strings.ToUpper(af), onu.GPONSerial) {
		return fail(true, "the serial did not show up in the autofind list after the delete", ErrBenchOLTNoReturn)
	}
	// ---- 4) authorized again with the baseline profiles, and the service port back; fail() converges on the baseline too
	if err := toIface(); err != nil {
		return fail(true, "could not reach the interface mode to authorize", err)
	}
	if _, err := step(c.Add); err != nil {
		return fail(true, "ont add was not accepted", err)
	}
	if !waitFor(func() bool {
		i, p, e := readONU()
		return e == nil && onu.identityOK(i) && p.Line == spec.LineProfileID && p.Srv == spec.SrvProfileID && p.Description == spec.Description
	}, wait) {
		return fail(true, "the ONU was added but not seen online with the baseline profiles", ErrBenchOLTNoReturn)
	}
	if err := toConfig(); err != nil {
		return fail(true, "could not reach the config mode to restore the service port", err)
	}
	if _, err := step(c.AddSP); err != nil {
		return fail(true, "service-port was not accepted", err)
	}
	rows, err = readSP()
	if err != nil || !spOK(rows, onu, spec) {
		return fail(true, "the service port is not the baseline one after the cycle", ErrReauthBaseline)
	}
	det, err = step(c.DetailSP)
	if err != nil || !spDetailOK(det, onu, spec) {
		return fail(true, "the service port detail differs from the baseline after the cycle", ErrReauthBaseline)
	}
	res.Done, res.Detail = true, "service port removed, ONU deleted, seen in autofind, authorized again with the baseline profiles, service port restored and equal"
	if mode == "iface" {
		_, _ = s.Run(ctx, c.Quit)
	}
	_, _ = s.Run(ctx, c.Quit)
	return res, nil
}
