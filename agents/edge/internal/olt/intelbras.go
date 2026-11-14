package olt

import (
	"context"
	"errors"
	"fmt"
	"regexp"
	"strconv"
	"strings"
)

// Intelbras OLT 8820i / 8820 Plus (Intelbras Embedded Platform CLI, Telnet only). Parsers are written from a REAL read-only capture of 2026-11-14 (sanitized
// fixtures in testdata/intelbras_8820), but the capture does not cover an empty PON of a live device, so the registry keeps it at "identified".
//
// The CLI has no top-level `show` and no pager. The Edge asks for exactly three fixed commands and never types a `?` (the prompt keeps the text typed
// after it, so a later command would be glued to it):
//
//	card stats      -> firmware (s/w version)
//	olt show port   -> the PON ports
//	onu status      -> every ONU of every PON, with each PON footer ("Configured ONUs: N, Active ONUs = M") as the in-band completeness proof
//
// The model comes from the banner the Telnet session reads at login ("Intelbras Embedded Platform 16.2 olt8820plus").
type Intelbras struct{}

func (Intelbras) Vendor() string { return "intelbras" }

// IntelbrasPrompt is what ends every command of this CLI.
var IntelbrasPrompt = regexp.MustCompile(`intelbras-olt>`)

// IntelbrasNoise is printed while the OLT is busy and is not part of any answer.
var IntelbrasNoise = regexp.MustCompile(`(?i)the olt system is processing|waiting to execute command`)

// Exact-match: three fixed read commands. No regex, no arguments, no `?`.
var intelbrasCommands = map[string]struct{}{"card stats": {}, "olt show port": {}, "onu status": {}}

// IntelbrasAllowed is the exact-match allowlist of the driver.
func IntelbrasAllowed(cmd string) bool { _, ok := intelbrasCommands[cmd]; return ok }

func (Intelbras) Allowed(cmd string) bool { return IntelbrasAllowed(cmd) }

var (
	ibModel      = regexp.MustCompile(`(?i)\b(olt\d{4}[a-z]*)\b`)
	ibCardRow    = regexp.MustCompile(`^\s*(\d+)\s+[\d.]+\s+[\d.]+\s+[\d.]+\s+\d+\s+\d+\s+(.+?)\s+\d+:\d+:\d+:\d+\s+(\d+(?:\.\d+)+)\s*$`)
	ibPortRow    = regexp.MustCompile(`^\s*(\d{1,3})\s+-?\d+ C\s+[\d.]+ V\s+\d+ mA\s+-?[\d.]+ dBm\s+(?:-?[\d.]+ dBm|-)\s+(\S+)\s*$`)
	ibPortHeader = regexp.MustCompile(`GPON\s+Temperature\s+Voltage`)
	ibGPON       = regexp.MustCompile(`^\s*GPON\s+(\d{1,3})\s*$`)
	ibOnuRow     = regexp.MustCompile(`^\s*(\d+)\s+([0-9A-Fa-f]{8})\s+(Active|Inactive)\s+(\S+)\s+(?:(-?\d+(?:\.\d+)?) dBm|-)\s+(?:(-?\d+(?:\.\d+)?) dBm|-)\s+(\S+)(?:\s+(\S.*?))?\s*$`)
	ibFooter     = regexp.MustCompile(`^\s*Configured ONUs:\s*(\d+),\s*Active ONUs\s*=\s*(\d+)\s*$`)
	ibInvalid    = regexp.MustCompile(`(?m)^\s*%%?\s*(invalid command|unknown command|incomplete command)`)
	ibClock      = regexp.MustCompile(`^\d+:\d+:\d+:\d+$`)
)

// Unwrap lets a driver reach the transport under the Budget/ReadOnlySession wrappers (the banner lives there).
func (r ReadOnlySession) Unwrap() Session { return r.Inner }
func (b *Budget) Unwrap() Session         { return b.Inner }

type bannered interface{ Banner() string }

func bannerOf(s Session) string {
	for i := 0; i < 8 && s != nil; i++ {
		if b, ok := s.(bannered); ok {
			return b.Banner()
		}
		u, ok := s.(interface{ Unwrap() Session })
		if !ok {
			return ""
		}
		s = u.Unwrap()
	}
	return ""
}

func ibCheck(cmd, out string) error {
	if ibInvalid.MatchString(out) {
		return fmt.Errorf("intelbras: %q was rejected by the device", cmd)
	}
	return nil
}

func (Intelbras) Identify(ctx context.Context, s Session) (Identity, error) {
	id := Identity{Vendor: "intelbras"}
	if m := ibModel.FindStringSubmatch(bannerOf(s)); m != nil {
		id.Model = strings.ToUpper(m[1])
	}
	out, err := s.Run(ctx, "card stats")
	if err != nil {
		return Identity{}, err
	}
	if err := ibCheck("card stats", out); err != nil {
		return Identity{}, err
	}
	for _, line := range strings.Split(out, "\n") {
		if m := ibCardRow.FindStringSubmatch(line); m != nil {
			id.Firmware = m[3]
			break
		}
	}
	if id.Model == "" || id.Firmware == "" {
		return id, fmt.Errorf("intelbras: cannot read the model (login banner) and the firmware (card stats)")
	}
	return id, nil
}

// Snapshot ignores ponPorts: the device itself lists its PONs (`olt show port`) and the config does not have to repeat them. When the config does list some, only
// those PONs are reported (a PON the config names that the OLT does not have is an error, never silently dropped).
func (Intelbras) Snapshot(ctx context.Context, s Session, ponPorts []string) (Snapshot, error) {
	var snap Snapshot
	ident, err := Intelbras{}.Identify(ctx, s)
	if err != nil {
		return Snapshot{}, err
	}
	snap.Identity = ident

	portsOut, err := s.Run(ctx, "olt show port")
	if err != nil {
		return Snapshot{}, err
	}
	if err := ibCheck("olt show port", portsOut); err != nil {
		return Snapshot{}, err
	}
	pons, err := parseIntelbrasPorts(portsOut)
	if err != nil {
		return Snapshot{}, err
	}
	want := map[string]bool{}
	for _, p := range ponPorts {
		want[p] = true
	}
	have := map[string]bool{}
	for _, p := range pons {
		have[p.Path] = true
	}
	for p := range want {
		if !have[p] {
			return Snapshot{}, fmt.Errorf("intelbras: configured PON %q is not in `olt show port`", p)
		}
	}

	onuOut, err := s.Run(ctx, "onu status")
	if err != nil {
		return Snapshot{}, err
	}
	if err := ibCheck("onu status", onuOut); err != nil {
		return Snapshot{}, err
	}
	blocks, err := parseIntelbrasONUs(onuOut)
	if err != nil {
		return Snapshot{}, err
	}
	for _, p := range pons {
		if len(want) > 0 && !want[p.Path] {
			continue
		}
		// a PON without a block, or whose block has no footer, or whose rows do not add up to the footer, is never Verified
		if b := blocks[p.Path]; b != nil {
			p.Verified = b.footer && b.rows == b.configured && b.activeRows == b.active
			snap.ONUs = append(snap.ONUs, b.onus...)
		}
		snap.PONs = append(snap.PONs, p)
	}
	return snap, nil
}

// parseIntelbrasPorts reads `olt show port`. The status column is the transceiver "End Of Life Status", not a link state, so the PON status stays "unknown".
func parseIntelbrasPorts(out string) ([]PON, error) {
	if !ibPortHeader.MatchString(out) {
		return nil, errors.New("intelbras: `olt show port` has no port table")
	}
	var pons []PON
	seen := map[string]bool{}
	for _, line := range strings.Split(out, "\n") {
		if m := ibPortRow.FindStringSubmatch(line); m != nil {
			n := strconv.Itoa(atoiSafe(m[1]))
			if seen[n] {
				return nil, fmt.Errorf("intelbras: PON %s listed twice", n)
			}
			seen[n] = true
			pons = append(pons, PON{Path: n, Status: "unknown"})
		}
	}
	if len(pons) == 0 {
		return nil, errors.New("intelbras: `olt show port` lists no PON")
	}
	return pons, nil
}

type ibBlock struct {
	onus               []ONU
	rows, activeRows   int
	configured, active int
	footer             bool
	hints              map[string]string // ONU number -> "GPON ONU Status" column (DGI, LOAMI...): only a hint, never the ONU status
}

// parseIntelbrasONUs reads `onu status`: one "GPON N" block per PON, rows, and a footer. Rows only count inside a block; a text with no block is an error.
func parseIntelbrasONUs(out string) (map[string]*ibBlock, error) {
	blocks := map[string]*ibBlock{}
	var cur *ibBlock
	for _, line := range strings.Split(out, "\n") {
		if m := ibGPON.FindStringSubmatch(line); m != nil {
			n := strconv.Itoa(atoiSafe(m[1]))
			if _, dup := blocks[n]; dup {
				return nil, fmt.Errorf("intelbras: PON %s appears twice in `onu status`", n)
			}
			cur = &ibBlock{hints: map[string]string{}}
			blocks[n] = cur
			continue
		}
		if cur == nil {
			continue
		}
		if m := ibFooter.FindStringSubmatch(line); m != nil {
			cur.configured, cur.active, cur.footer = atoiSafe(m[1]), atoiSafe(m[2]), true
			continue
		}
		if m := ibOnuRow.FindStringSubmatch(line); m != nil && !cur.footer {
			u := ONU{Serial: strings.ToUpper(m[2]), Status: "offline"}
			if m[3] == "Active" {
				u.Status = "online"
				cur.activeRows++
			}
			if m[6] != "" { // "ONU Rx Power", the second power column; the first is the OLT's own reading
				if v, err := strconv.ParseFloat(m[6], 64); err == nil && v >= -50 && v <= 10 {
					u.RxDBm = &v
				}
			}
			cur.rows++
			if rest := strings.Fields(m[8]); len(rest) > 0 && !ibClock.MatchString(rest[0]) && rest[0] != "-" && rest[0] != "yes" && rest[0] != "no" {
				cur.hints[m[1]] = rest[0]
			}
			cur.onus = append(cur.onus, u)
		}
	}
	if len(blocks) == 0 {
		return nil, errors.New("intelbras: `onu status` has no GPON block")
	}
	// PonPath is the block's number: set after the fact so the row parser stays independent of it
	for n, b := range blocks {
		for i := range b.onus {
			b.onus[i].PonPath = n
		}
	}
	return blocks, nil
}

func atoiSafe(s string) int { n, _ := strconv.Atoi(s); return n }
