package olt

import (
	"context"
	"errors"
	"fmt"
	"regexp"
	"strconv"
	"strings"
)

// Datacom DmOS (DM46xx GPON OLTs). READ-ONLY. Parsers are covered by SANITISED fixtures of REAL captures (testdata/datacom_dmos, 2026-11-14), so the
// shipped Registry entries stay "identified" (see DRIVER_SDK_INTERFACE.md for the promotion checklist).
//
// Transport: SSH EXEC (no pty). DmOS prints no pager when the command ends in " | nomore", the only pipe this package ever admits (SafeCommand).
// Output has no prompt and no echo in exec mode; the end of a command is the end of the channel (EndProven).
type Datacom struct{}

func (Datacom) Vendor() string { return "datacom" }

const (
	dmCmdPlatform = "show platform"
	dmCmdGponAll  = "show interface gpon | nomore"
	dmMaxPON      = 24 // DM4615 has 16 PON ports; the shelf has one slot ("1/1")
	dmMaxONUID    = 127
)

var (
	dmPonRe = regexp.MustCompile(`^1/1/(\d{1,2})$`)
	// the ONLY three commands this driver may issue; ports come from dmOnuCmd (bounded), never from free text
	dmAllowedRe = regexp.MustCompile(`^(show platform|show interface gpon \| nomore|show interface gpon 1/1/\d{1,2} onu \| nomore)$`)

	dmChassisRe = regexp.MustCompile(`(?m)^\s*1\s{2,}(\S.*?)\s{2,}-\s+-\s+Not available\s*$`)
	dmActiveRe  = regexp.MustCompile(`(?m)^\s*\d+/\d+\s{2,}\S.*?\s{2,}Active\s+Ready\s+(\S+)\s*$`)
	dmLinkRe    = regexp.MustCompile(`(?m)^\s*Physical interface\s*:\s*gpon (1/1/\d{1,2}),\s*(\w+),\s*Physical link is (\w+)\s*$`)
	// Itf, ONU ID, Serial Number, Oper State, Software Download State, then an optional Name (which may hold blanks)
	dmOnuRowRe  = regexp.MustCompile(`^\s*(1/1/\d{1,2})\s+(\d+)\s+([0-9A-Za-z]{8,16})\s+(\S+)\s+(\S+)(?:\s.*)?$`)
	dmOnuHeadRe = regexp.MustCompile(`^\s*Itf\s+ONU ID\s+Serial Number\s+Oper State\b`)
	dmDashesRe  = regexp.MustCompile(`^\s*-{4,}[\s-]*$`)
	dmNoEntries = "% No entries found."
)

// ValidDatacomPort says whether p is a PON this driver would address ("1/1/N", N in 1..24).
func ValidDatacomPort(p string) bool {
	m := dmPonRe.FindStringSubmatch(p)
	if m == nil {
		return false
	}
	n, _ := strconv.Atoi(m[1])
	return n >= 1 && n <= dmMaxPON
}

// DatacomAllowed is the exact read allowlist: the three commands above, with the port bounded to 1..24.
func DatacomAllowed(cmd string) bool {
	if !dmAllowedRe.MatchString(cmd) {
		return false
	}
	if strings.HasPrefix(cmd, "show interface gpon 1/1/") {
		f := strings.Fields(cmd)
		return len(f) == 7 && ValidDatacomPort(f[3])
	}
	return true
}

func (Datacom) Allowed(cmd string) bool { return DatacomAllowed(cmd) }

func dmOnuCmd(port string) string { return "show interface gpon " + port + " onu | nomore" }

// dmRejected recognises the CLI's own refusals: output that is not data must never be read as data.
func dmRejected(out string) bool {
	l := strings.ToLower(out)
	return strings.Contains(l, "syntax error") || strings.Contains(l, "% invalid input") || strings.Contains(l, "element does not exist")
}

func (Datacom) Identify(ctx context.Context, s Session) (Identity, error) {
	out, err := s.Run(ctx, dmCmdPlatform)
	if err != nil {
		return Identity{}, err
	}
	return parseDatacomPlatform(out)
}

func parseDatacomPlatform(out string) (Identity, error) {
	if dmRejected(out) {
		return Identity{}, errors.New("datacom: show platform was refused by the CLI")
	}
	id := Identity{Vendor: "datacom"}
	if m := dmChassisRe.FindStringSubmatch(out); m != nil {
		id.Model = strings.TrimSpace(m[1])
	}
	for _, m := range dmActiveRe.FindAllStringSubmatch(out, -1) {
		if m[1] != "Not" && m[1] != "available" {
			id.Firmware = m[1]
			break
		}
	}
	if id.Model == "" || id.Firmware == "" {
		return id, errors.New("datacom: cannot parse show platform")
	}
	return id, nil
}

// parseDatacomLinks returns the PON ports the OLT lists, in order, with their physical link ("up"|"down").
func parseDatacomLinks(out string) (ports []string, link map[string]string, err error) {
	if dmRejected(out) {
		return nil, nil, errors.New("datacom: show interface gpon was refused by the CLI")
	}
	link = map[string]string{}
	for _, m := range dmLinkRe.FindAllStringSubmatch(out, -1) {
		if !ValidDatacomPort(m[1]) {
			continue
		}
		if _, dup := link[m[1]]; !dup {
			ports = append(ports, m[1])
		}
		if strings.EqualFold(m[3], "Up") {
			link[m[1]] = "up"
		} else {
			link[m[1]] = "down"
		}
	}
	if len(ports) == 0 {
		return nil, nil, errors.New("datacom: no PON found in show interface gpon")
	}
	return ports, link, nil
}

func dmStatus(state string) string {
	switch strings.ToLower(state) {
	case "up":
		return "online"
	case "down":
		return "offline" // this listing does not say LOS or dying gasp: never invent a cause
	}
	return "unknown"
}

// parseDatacomONUs parses one PON's listing. It is strict ON PURPOSE: the result is either "this PON, fully read" (rows, or the CLI's own "no entries"), or an error.
// A refusal, a pager, a missing header, a row of another PON or a half-printed last row is never a complete (or empty) PON.
func parseDatacomONUs(out, port string) ([]ONU, error) {
	if dmRejected(out) {
		return nil, fmt.Errorf("datacom: %s: onu listing was refused by the CLI", port)
	}
	if Paginated(out) {
		return nil, fmt.Errorf("datacom: %s: %w", port, ErrPaginated)
	}
	lines := strings.Split(strings.ReplaceAll(out, "\r", ""), "\n")
	var body []string
	for _, l := range lines {
		if strings.TrimSpace(l) != "" {
			body = append(body, l)
		}
	}
	if len(body) == 0 {
		return nil, fmt.Errorf("datacom: %s: empty output (a PON without ONUs says so)", port)
	}
	if len(body) == 1 && strings.TrimSpace(body[0]) == dmNoEntries {
		return []ONU{}, nil // the CLI's own statement: this PON has no ONU
	}
	if len(body) < 2 || !dmOnuHeadRe.MatchString(body[0]) || !dmDashesRe.MatchString(body[1]) {
		return nil, fmt.Errorf("datacom: %s: unrecognised onu listing (no header)", port)
	}
	var onus []ONU
	seen := map[int]bool{}
	for _, l := range body[2:] {
		m := dmOnuRowRe.FindStringSubmatch(l)
		if m == nil || m[1] != port {
			return nil, fmt.Errorf("datacom: %s: unparsable row (truncated or foreign output)", port)
		}
		id, err := strconv.Atoi(m[2])
		if err != nil || id < 0 || id > dmMaxONUID || seen[id] {
			return nil, fmt.Errorf("datacom: %s: invalid or repeated ONU id %q", port, m[2])
		}
		seen[id] = true
		onus = append(onus, ONU{Serial: strings.ToUpper(m[3]), PonPath: port, Status: dmStatus(m[4]), OntID: id, HasOntID: true})
	}
	if len(onus) == 0 {
		return nil, fmt.Errorf("datacom: %s: header without rows is not a listing", port)
	}
	return onus, nil
}

func (d Datacom) Snapshot(ctx context.Context, s Session, ports []string) (Snapshot, error) {
	id, err := d.Identify(ctx, s)
	if err != nil {
		return Snapshot{}, err
	}
	for _, p := range ports {
		if !ValidDatacomPort(p) {
			return Snapshot{}, fmt.Errorf("invalid pon port %q", p)
		}
	}
	all, err := s.Run(ctx, dmCmdGponAll)
	if err != nil {
		return Snapshot{}, err
	}
	listed, link, err := parseDatacomLinks(all)
	if err != nil {
		return Snapshot{}, err
	}
	if len(ports) == 0 {
		ports = listed
	}
	snap := Snapshot{Identity: id}
	for _, p := range ports {
		out, err := s.Run(ctx, dmOnuCmd(p))
		if err != nil {
			return Snapshot{}, err
		}
		onus, err := parseDatacomONUs(out, p)
		if err != nil {
			return Snapshot{}, err
		}
		st, ok := link[p]
		if !ok {
			st = "unknown" // asked for a port this OLT does not list
		}
		snap.ONUs = append(snap.ONUs, onus...)
		snap.PONs = append(snap.PONs, PON{Path: p, Status: st, Verified: true}) // parsed whole: rows, or the CLI's own "no entries"
	}
	return snap, nil
}
