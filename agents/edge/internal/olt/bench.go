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

// ADR-0030 H4 (bench only): reset or deactivate-and-reactivate ONE ONU on the real OLT. Everything that can reach the device is built here from
// integers of the Edge's LOCAL configuration; the Cloud sends neither a port, an ONT-ID nor any text. The command list is closed and exact (a
// string compare, not a pattern): `all` and `graceful` do not exist in it, so they cannot be sent whatever the inputs are.

var (
	ErrBenchOLTCommand  = errors.New("olt bench: command outside the closed list")
	ErrBenchOLTIdentity = errors.New("olt bench: the ONU on the OLT does not match the configured bench ONU")
	ErrBenchOLTRefused  = errors.New("olt bench: the OLT refused the command")
	ErrBenchOLTNoReturn = errors.New("olt bench: the ONU did not come back as expected within the wait")
	ErrBenchOLTStuck    = errors.New("olt bench: the ONU may be left deactivated; run `ont activate` on the OLT")
	ErrBenchOLTBefore   = errors.New("olt bench: refused before any command")
)

// BenchONU is the one ONU the maneuvers may touch (all from local configuration).
type BenchONU struct {
	Frame, Slot, Port, OntID int
	GPONSerial               string // 16 hex, upper case
}

func (b BenchONU) valid() bool {
	return b.Frame >= 0 && b.Frame <= 7 && b.Slot >= 0 && b.Slot <= 21 && b.Port >= 0 && b.Port <= 15 && b.OntID >= 0 && b.OntID <= 127 &&
		gponSerialRe.MatchString(b.GPONSerial)
}

var gponSerialRe = regexp.MustCompile(`^[0-9A-F]{16}$`)

func (b BenchONU) fsp() string { return fmt.Sprintf("%d/%d/%d", b.Frame, b.Slot, b.Port) }

// BenchCommands are the exact strings that may be sent for this ONU, and nothing else.
type BenchCommands struct {
	Enable, Config, Iface, BySN, Info, Reset, Deactivate, Activate, Quit string
}

func (b BenchONU) Commands() BenchCommands {
	return BenchCommands{
		Enable: "enable", Config: "config", Quit: "quit",
		Iface:      fmt.Sprintf("interface gpon %d/%d", b.Frame, b.Slot),
		BySN:       "display ont info by-sn " + b.GPONSerial,
		Info:       fmt.Sprintf("display ont info %d %d", b.Port, b.OntID),
		Reset:      fmt.Sprintf("ont reset %d %d", b.Port, b.OntID),
		Deactivate: fmt.Sprintf("ont deactivate %d %d", b.Port, b.OntID),
		Activate:   fmt.Sprintf("ont activate %d %d", b.Port, b.OntID),
	}
}

// benchSession lets only the exact commands of the plan through.
type benchSession struct {
	inner   Session
	allowed map[string]bool
	sent    []string
}

func newBenchSession(inner Session, c BenchCommands) *benchSession {
	a := map[string]bool{}
	for _, s := range []string{c.Enable, c.Config, c.Iface, c.BySN, c.Info, c.Reset, c.Deactivate, c.Activate, c.Quit} {
		a[s] = true
	}
	return &benchSession{inner: inner, allowed: a}
}

func (s *benchSession) Run(ctx context.Context, cmd string) (string, error) {
	if !s.allowed[cmd] {
		return "", fmt.Errorf("%w: %q", ErrBenchOLTCommand, cmd)
	}
	s.sent = append(s.sent, cmd)
	return s.inner.Run(ctx, cmd)
}

// ONTInfo is what the maneuver reads from `display ont info ...`.
type ONTInfo struct {
	FSP, ControlFlag, RunState, ConfigState, MatchState, SN, LastUp string
	OntID                                                           int
}

var (
	fieldRe = func(name string) *regexp.Regexp {
		return regexp.MustCompile(`(?m)^\s*` + regexp.QuoteMeta(name) + `\s*:\s*(\S+)`)
	}
	reFSP   = fieldRe("F/S/P")
	reID    = fieldRe("ONT-ID")
	reCtl   = fieldRe("Control flag")
	reRun   = fieldRe("Run state")
	reCfg   = fieldRe("Config state")
	reMatch = fieldRe("Match state")
	reSN    = regexp.MustCompile(`(?m)^\s*SN\s*:\s*([0-9A-Fa-f]{16})\b`)
	reUp    = regexp.MustCompile(`(?m)^\s*Last up time\s*:\s*(.+?)\s*$`)
)

// ParseONTInfo requires EXACTLY one ONU record (one F/S/P line). Anything else is an error: a listing of several ONUs is never read as one.
func ParseONTInfo(out string) (ONTInfo, error) {
	if strings.Count(out, "F/S/P") != 1 {
		return ONTInfo{}, fmt.Errorf("%w: not exactly one ONU in the answer", ErrBenchOLTIdentity)
	}
	get := func(re *regexp.Regexp) string {
		if m := re.FindStringSubmatch(out); m != nil {
			return m[1]
		}
		return ""
	}
	id, err := strconv.Atoi(get(reID))
	if err != nil {
		return ONTInfo{}, fmt.Errorf("%w: no ONT-ID", ErrBenchOLTIdentity)
	}
	return ONTInfo{FSP: get(reFSP), OntID: id, ControlFlag: get(reCtl), RunState: get(reRun), ConfigState: get(reCfg), MatchState: get(reMatch),
		SN: strings.ToUpper(get(reSN)), LastUp: get(reUp)}, nil
}

// identityOK: the ONU on the OLT is the configured one and healthy enough to be touched.
func (b BenchONU) identityOK(i ONTInfo) bool {
	return i.FSP == b.fsp() && i.OntID == b.OntID && i.SN == b.GPONSerial && strings.EqualFold(i.RunState, "online") &&
		strings.EqualFold(i.ConfigState, "normal") && strings.EqualFold(i.MatchState, "match") && strings.EqualFold(i.ControlFlag, "active")
}

// refusedRe: only the CLI's own rejection forms (a reset report may legitimately print the word "failure" with a zero count).
var refusedRe = regexp.MustCompile(`(?im)(unknown command|parameter error|too many parameters|incomplete command|^\s*%\s)`)

// ManeuverOutcome: Sent = a command that changes the ONU was sent; Done = everything was observed as expected (including the way back).
type ManeuverOutcome struct {
	Sent, Done bool
	Detail     string
}

// RunBenchManeuver runs `onu_reset` or `onu_deactivate` for the configured ONU over an already open CLI session. beforeSend runs once, after the
// identity was confirmed on the OLT and immediately before the first changing command (the caller reserves its pacing and spends the single-use
// authorization there); if it fails nothing is sent. wait/poll bound the observation of the ONU's return.
func RunBenchManeuver(ctx context.Context, raw Session, onu BenchONU, op string, notAfter time.Time, beforeSend func() error,
	wait, poll time.Duration, now func() time.Time) (ManeuverOutcome, error) {
	if !onu.valid() || (op != "onu_reset" && op != "onu_deactivate") {
		return ManeuverOutcome{}, ErrBenchOLTBefore
	}
	c := onu.Commands()
	s := newBenchSession(raw, c)
	step := func(cmd string) (string, error) {
		out, err := s.Run(ctx, cmd)
		if err == nil && refusedRe.MatchString(out) {
			err = fmt.Errorf("%w: %s", ErrBenchOLTRefused, cmd)
		}
		return out, err
	}
	if _, err := step(c.Enable); err != nil {
		return ManeuverOutcome{}, err
	}
	out, err := s.Run(ctx, c.BySN) // identity BEFORE anything changes, in this same session
	if err != nil {
		return ManeuverOutcome{}, err
	}
	before, err := ParseONTInfo(out)
	if err != nil {
		return ManeuverOutcome{}, err
	}
	if !onu.identityOK(before) {
		return ManeuverOutcome{}, ErrBenchOLTIdentity
	}
	if _, err := step(c.Config); err != nil {
		return ManeuverOutcome{}, err
	}
	if _, err := step(c.Iface); err != nil {
		return ManeuverOutcome{}, err
	}
	// the last read before the mutation, in the very mode the command will be typed in: same ONU, same state, nothing changed since the first read
	chk, err := s.Run(ctx, c.Info)
	if err != nil {
		return ManeuverOutcome{}, err
	}
	again, err := ParseONTInfo(chk)
	if err != nil {
		return ManeuverOutcome{}, err
	}
	if !onu.identityOK(again) || again.LastUp != before.LastUp {
		return ManeuverOutcome{}, ErrBenchOLTIdentity
	}
	if !now().Before(notAfter) {
		return ManeuverOutcome{}, fmt.Errorf("%w: envelope or authorization window over", ErrBenchOLTBefore)
	}
	if err := beforeSend(); err != nil {
		return ManeuverOutcome{}, fmt.Errorf("%w: %v", ErrBenchOLTBefore, err)
	}
	if !now().Before(notAfter) { // the durable writes of beforeSend may have taken long: the window is checked once more, right before the send
		return ManeuverOutcome{}, fmt.Errorf("%w: window over after the claim; nothing was sent", ErrBenchOLTBefore)
	}
	info := func() (ONTInfo, error) {
		o, err := s.Run(ctx, c.Info)
		if err != nil {
			return ONTInfo{}, err
		}
		return ParseONTInfo(o)
	}
	waitFor := func(ok func(ONTInfo) bool, limit time.Duration) (ONTInfo, bool) {
		deadline := time.Now().Add(limit)
		for {
			if i, err := info(); err == nil && ok(i) {
				return i, true
			}
			if time.Now().After(deadline) || ctx.Err() != nil {
				return ONTInfo{}, false
			}
			select {
			case <-ctx.Done():
				return ONTInfo{}, false
			case <-time.After(poll):
			}
		}
	}
	back := func(i ONTInfo) bool { return onu.identityOK(i) && i.LastUp != "" && i.LastUp != before.LastUp }
	res := ManeuverOutcome{Sent: true}
	switch op {
	case "onu_reset":
		if _, err := step(c.Reset); err != nil {
			if errors.Is(err, ErrBenchOLTRefused) {
				res.Sent = false // the OLT said no: the command did not run
			}
			return res, err
		}
		if _, ok := waitFor(back, wait); !ok {
			res.Detail = "reset sent; the ONU was not seen online again with a new up time"
			return res, ErrBenchOLTNoReturn
		}
		res.Done, res.Detail = true, "reset sent and the ONU came back online"
	case "onu_deactivate":
		if _, err := step(c.Deactivate); err != nil {
			if errors.Is(err, ErrBenchOLTRefused) {
				res.Sent = false
			}
			return res, err
		}
		_, down := waitFor(func(i ONTInfo) bool {
			return !strings.EqualFold(i.ControlFlag, "active") || !strings.EqualFold(i.RunState, "online")
		}, min(wait, 30*time.Second))
		// the way back is sent whatever was observed: never leave the ONU deactivated
		if _, err := step(c.Activate); err != nil {
			res.Detail = "deactivate sent and the reactivation was not accepted"
			return res, fmt.Errorf("%w: %v", ErrBenchOLTStuck, err)
		}
		if _, ok := waitFor(func(i ONTInfo) bool { return onu.identityOK(i) }, wait); !ok {
			res.Detail = "reactivated, but the ONU was not seen online and active again"
			return res, ErrBenchOLTNoReturn
		}
		if !down {
			res.Detail = "the deactivation was not observed; the ONU is active again"
			return res, ErrBenchOLTNoReturn
		}
		res.Done, res.Detail = true, "deactivated (observed), reactivated and online again"
	}
	_, _ = s.Run(ctx, c.Quit)
	_, _ = s.Run(ctx, c.Quit)
	return res, nil
}
