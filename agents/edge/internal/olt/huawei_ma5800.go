package olt

import (
	"context"
	"encoding/hex"
	"fmt"
	"regexp"
	"strconv"
	"strings"
	"time"
)

// Huawei SmartAX MA5800-X2, releases MA5800V100R022 and MA5800V100R024 (profile "huawei_ma58_r02x").
//
// Captured read-only on two real devices on 2026-11-14 (testdata/huawei_ma5800_r02x, sanitized). The CLI opens in USER mode (`NAME>`); the ONT
// listings need the PRIVILEGED view (`enable`, no extra password on these devices, prompt `NAME#`). `enable` is the ONLY elevation this profile
// ever sends and it only widens what `display` may show: there is no `config`, no `interface gpon`, no `diagnose`, no `undo`, no `system-view`, no
// write of any kind. The session ends with `quit`; nothing is saved because nothing was changed.
//
// Two reads per PON, both `display`, both bounded by the allowlist below:
//
//	display ont info summary 0/S/P   run state, last up/down time and down cause of every ONT, and the CLI's own count ("the total of ONTs are: N")
//	display ont info 0 S P all       the serial number of every ONT, joined to the summary by ONT-ID
//
// The count in the summary header is the in-band proof that the listing is complete (an interactive shell cannot prove where a command ends), exactly
// like the R015 footer. Anything that does not add up leaves PON.Verified=false.
var (
	ma58Allowed = regexp.MustCompile(`^(display version|enable|quit|` +
		`display ont info summary 0/(?:[0-9]|1[0-9]|2[01])/(?:[0-9]|1[0-5])|` +
		`display ont info 0 (?:[0-9]|1[0-9]|2[01]) (?:[0-9]|1[0-5]) all)$`)
	ma58PortRe = regexp.MustCompile(`^0/([0-9]|1[0-9]|2[01])/([0-9]|1[0-5])$`)

	// "  5    offline 03/11/2026 03:05:23 03/11/2026 06:50:25 dying-gasp"; "-" while there is no time or cause
	ma58Row = regexp.MustCompile(`^\s*(\d{1,5})\s+(online|offline)\s+(\d{2}/\d{2}/\d{4} \d{2}:\d{2}:\d{2}|-)\s+(\d{2}/\d{2}/\d{4} \d{2}:\d{2}:\d{2}|-)\s+(\S+)\s*$`)
	// the table headers of the summary ("ONT  Run     Last ..." / "ID   State   UpTime ...")
	ma58Head    = regexp.MustCompile(`^\s*ONT\s+Run\s+Last\b`)
	ma58Head2   = regexp.MustCompile(`^\s*ID\s+State\b`)
	ma58Divider = regexp.MustCompile(`^\s*-{20,}\s*$`)
	// "  In port 0/1/0, the total of ONTs are: 57, online: 56"  (the `info ... all` footer spells it "0/ 1/0 ,")
	ma58Total = regexp.MustCompile(`(?m)^\s*In port\s+(\d+)/\s*(\d+)/\s*(\d+)\s*,\s*the total of ONTs are:\s*(\d+)\s*,\s*online:\s*(\d+)\s*$`)
	// "  0/ 1/0     5 ITBS5F453E48      active      offline  initial  initial  no"
	ma58InfoRow = regexp.MustCompile(`^\s*(\d+)/\s*(\d+)/\s*(\d+)\s+(\d+)\s+([0-9A-Za-z]{12,16})\s+(\S+)\s+(\S+)\s+(\S+)\s+(\S+)\s+(\S+)\s*$`)
	ma58Hex16   = regexp.MustCompile(`^[0-9A-Fa-f]{16}$`)
	ma58Vendor  = regexp.MustCompile(`^[0-9A-Za-z]{4}[0-9A-Fa-f]{8}$`)
	// device-side rejection of a command ("Failure: This board does not exist", "% Unknown command ...")
	ma58CLIError = regexp.MustCompile(`(?m)^\s*%\s|^\s*Failure\s*:|Unknown command|Parameter error|Too many parameters|Incomplete command`)
)

// ma58Releases are the only releases this profile was captured on; the enable step and the ONT commands are never sent to another one.
var ma58Releases = []string{"MA5800V100R022", "MA5800V100R024"}

// ValidMA58Port reports whether a PON path F/S/P is one this profile may touch (frame 0, slot 0..21, port 0..15, canonical numbers).
func ValidMA58Port(p string) bool { return ma58PortRe.MatchString(p) }

func isMA58R02x(id Identity) bool {
	if !strings.HasPrefix(strings.ToUpper(id.Model), "MA5800") {
		return false
	}
	for _, r := range ma58Releases {
		if strings.HasPrefix(id.Firmware, r) {
			return true
		}
	}
	return false
}

// HuaweiMA58 is selected by the OLT config (profile "huawei_ma58_r02x", ssh_mode "shell").
type HuaweiMA58 struct {
	Huawei
	// Zone is the time zone of the OLT clock. The listing prints "dd/mm/yyyy hh:mm:ss" with NO zone, so LastDownAt is only reported when the
	// operator says which zone the device runs in; nil = never guess (LastDownAt stays unset, the status and causes are still reported).
	Zone *time.Location
}

func (h HuaweiMA58) Allowed(cmd string) bool { return ma58Allowed.MatchString(cmd) }

func (h HuaweiMA58) Snapshot(ctx context.Context, s Session, ports []string) (Snapshot, error) {
	for _, p := range ports { // before ANY command, identification included: a bad port must not even touch the device
		if !hwPort.MatchString(p) || !ValidMA58Port(p) {
			return Snapshot{}, fmt.Errorf("invalid pon port %q for huawei_ma58_r02x", p)
		}
	}
	id, err := h.Identify(ctx, s) // user mode is enough for `display version`: nothing is elevated on a device this profile does not cover
	if err != nil {
		return Snapshot{}, err
	}
	if !isMA58R02x(id) { // only display version has been sent so far
		return Snapshot{}, fmt.Errorf("huawei_ma58_r02x profile on %s %s (validated only on %s)", id.Model, id.Firmware, strings.Join(ma58Releases, ", "))
	}
	snap := Snapshot{Identity: id}
	if len(ports) == 0 {
		return snap, nil
	}
	run := func(cmd string) (string, error) {
		out, err := s.Run(ctx, cmd)
		if err != nil {
			return "", err
		}
		if ma58CLIError.MatchString(out) {
			return "", fmt.Errorf("huawei ma58: device rejected %q%s", cmd, rejection(out))
		}
		return out, nil
	}
	// The one elevation, and the first step of the session after identification. It either lands on the privileged prompt or the collection stops.
	out, err := run("enable")
	if err != nil {
		return Snapshot{}, err
	}
	if !ma58EnableOK(out) {
		return Snapshot{}, fmt.Errorf("huawei ma58: enable did not reach the privileged view (denied or unexpected answer); nothing else was sent")
	}
	for _, p := range ports {
		sum, err := run("display ont info summary " + p)
		if err != nil {
			return Snapshot{}, err
		}
		f := strings.Split(p, "/")
		all, err := run("display ont info 0 " + f[1] + " " + f[2] + " all")
		if err != nil {
			return Snapshot{}, err
		}
		onus, pon := parseMA58Port(p, sum, all, h.Zone)
		snap.ONUs = append(snap.ONUs, onus...)
		snap.PONs = append(snap.PONs, pon)
	}
	// Leave the session. Best effort: everything was already read, a device that asks a question or drops the link here changes nothing, and the
	// shell never answers a question.
	_, _ = s.Run(ctx, "quit")
	return snap, nil
}

// rejection returns the device's own one-line refusal (its fixed vocabulary, e.g. "Failure: This board does not exist"), bounded, for the error.
func rejection(out string) string {
	for _, l := range strings.Split(out, "\n") {
		if t := strings.TrimSpace(l); ma58CLIError.MatchString(t) {
			if len(t) > 100 {
				t = t[:100]
			}
			return ": " + t
		}
	}
	return ""
}

// ma58EnableOK: after `enable` the only text allowed is the command echo and PRIVILEGED prompts (`NAME#`). A user-mode prompt (`NAME>`) means the
// device did not elevate; any other text (a banner, a refusal, a question) is not something this profile understands.
func ma58EnableOK(out string) bool {
	for _, l := range strings.Split(stripCtl(out), "\n") {
		t := strings.TrimSpace(l)
		switch {
		case t == "" || t == "enable":
		case promptRe.MatchString(t):
			if !strings.HasSuffix(t, "#") {
				return false
			}
		default:
			return false
		}
	}
	return true
}

// ma58Serial gives the serial in the canonical form the other Huawei sources use (16 hex digits, upper case: the MA5600 CLI and SNMP). The MA5800
// prints the 8 serial bytes as 4 vendor characters + 8 hex digits ("ITBS5F453E48"); the vendor characters are converted to their hex bytes.
func ma58Serial(tok string) (string, bool) {
	switch {
	case ma58Hex16.MatchString(tok):
		return strings.ToUpper(tok), true
	case ma58Vendor.MatchString(tok):
		return strings.ToUpper(hex.EncodeToString([]byte(tok[:4])) + tok[4:]), true
	}
	return "", false
}

type ma58Ont struct {
	id         int
	online     bool
	downAt     string
	cause      string
	listedDown bool
}

// parseMA58Summary reads the run-state table of `display ont info summary`. clean=false when anything inside the table is not a well-formed row,
// an ONT-ID repeats, or the table/footer structure is not the single one expected.
func parseMA58Summary(out string) (rows []ma58Ont, clean bool) {
	clean = true
	state, seenDiv, heads := 0, false, 0 // 0 before the table, 1 inside, 2 closed
	ids := map[int]bool{}
	for _, line := range strings.Split(out, "\n") {
		switch {
		case ma58Head.MatchString(line):
			heads++
			if state == 0 {
				state, seenDiv = 1, false
			}
		case state != 1:
		case ma58Divider.MatchString(line):
			if seenDiv {
				state = 2
			} else {
				seenDiv = true
			}
		case strings.TrimSpace(line) == "" || ma58Head2.MatchString(line):
		case !seenDiv:
			clean = false
		default:
			m := ma58Row.FindStringSubmatch(line)
			if m == nil {
				clean = false
				continue
			}
			id, _ := strconv.Atoi(m[1])
			if ids[id] || id >= maxONTs {
				clean = false
				continue
			}
			ids[id] = true
			rows = append(rows, ma58Ont{id: id, online: m[2] == "online", downAt: m[4], cause: m[5], listedDown: m[4] != "-"})
		}
	}
	if heads != 1 || state != 2 {
		clean = false
	}
	return rows, clean
}

func ma58Cause(c string) string {
	switch strings.ToLower(c) {
	case "dying-gasp":
		return "dying_gasp"
	case "losi/lobi", "losi", "lobi", "los":
		return "los"
	}
	return ""
}

// parseMA58Port builds the ONUs of one PON from the summary and the `info ... all` listing and decides whether the PON is provably complete: the
// summary header must name THIS port with a total and an online count that match the parsed rows, and the serial listing must carry exactly the same
// ONT-IDs, each with one valid, unique serial. Anything else leaves Verified=false.
func parseMA58Port(path, summary, all string, zone *time.Location) ([]ONU, PON) {
	rows, clean := parseMA58Summary(summary)
	serial := map[int]string{}
	serialSeen := map[string]bool{}
	for _, line := range strings.Split(all, "\n") {
		m := ma58InfoRow.FindStringSubmatch(line)
		if m == nil {
			continue
		}
		id, _ := strconv.Atoi(m[4])
		sn, ok := ma58Serial(m[5])
		if m[1]+"/"+m[2]+"/"+m[3] != path || !ok || serial[id] != "" || serialSeen[sn] {
			clean = false
			continue
		}
		serial[id], serialSeen[sn] = sn, true
	}
	var onus []ONU
	online := 0
	for _, r := range rows {
		sn := serial[r.id]
		if sn == "" { // no serial, no identity: the ONU cannot be reported, and the PON cannot be called complete
			clean = false
			continue
		}
		u := ONU{Serial: sn, PonPath: path, OntID: r.id, HasOntID: true, Status: "online"}
		if r.online {
			online++
		} else {
			u.Status = "offline"
			if c := ma58Cause(r.cause); c != "" {
				u.Status = c
			}
			if zone != nil && r.listedDown { // the OLT's own last down time, offline ONUs only
				if t, err := time.ParseInLocation("02/01/2006 15:04:05", r.downAt, zone); err == nil && t.Year() >= 2010 && t.Year() <= 2100 {
					tt := t.UTC()
					u.LastDownAt = &tt
				}
			}
		}
		onus = append(onus, u)
	}
	for id := range serial { // a serial listed for an ONT-ID the summary does not know: the two reads disagree
		known := false
		for _, r := range rows {
			if r.id == id {
				known = true
				break
			}
		}
		if !known {
			clean = false
		}
	}
	verified := false
	if t := ma58Total.FindStringSubmatch(summary); t != nil && clean && len(ma58Total.FindAllString(summary, -1)) == 1 {
		total, _ := strconv.Atoi(t[4])
		on, _ := strconv.Atoi(t[5])
		verified = t[1]+"/"+t[2]+"/"+t[3] == path && total == len(rows) && len(onus) == len(rows) && on == online
	}
	return onus, PON{Path: path, Status: ponStatus(len(onus)), Verified: verified}
}
