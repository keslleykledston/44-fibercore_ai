package olt

import (
	"encoding/json"
	"errors"
	"regexp"
	"strconv"
	"strings"
	"time"
)

// Typed results of the validated queries (ADR-0029 item 4): the raw device output NEVER leaves the Edge. A parser builds a closed object from fields it
// recognises, each constrained to a safe alphabet and length; anything else makes the query fail (`bad_output`), it is not forwarded. A query without a
// parser here has none to run: it fails with `no_parser` before touching the device.

var (
	ErrNoParser  = errors.New("olt query: no parser for this query")
	ErrBadOutput = errors.New("olt query: output does not match the expected shape")
)

var (
	reProduct   = regexp.MustCompile(`^[A-Z0-9][A-Z0-9-]{1,23}$`)
	reRelease   = regexp.MustCompile(`^[A-Za-z0-9][A-Za-z0-9._ -]{1,39}$`)
	reUptime    = regexp.MustCompile(`Uptime is (\d{1,5}) day\(s\), (\d{1,2}) hour\(s\), (\d{1,2}) minute\(s\), (\d{1,2}) second\(s\)`)
	reBoardRow  = regexp.MustCompile(`^\s*(\d{1,2})\s+([A-Za-z0-9]{3,20})\s+([A-Za-z_]{3,24})(?:\s.*)?$`)
	reBoardSlot = regexp.MustCompile(`^\s*(\d{1,2})\s*$`)
)

// HasParser says whether a query can return a typed result.
func HasParser(queryID string) bool {
	switch queryID {
	case "olt.version", "olt.board", "olt.time", "olt.sync", "olt.temperature", "slot.cpu", "slot.mem", "olt.profile.line", "olt.profile.srv", "olt.profile.dba", "olt.profile.traffic":
		return true
	}
	return false
}

// ParseResult turns the device output of a validated query into its typed result (compact JSON).
func ParseResult(queryID, out string) (json.RawMessage, error) {
	switch queryID {
	case "olt.version":
		return parseVersion(out)
	case "olt.board":
		return parseBoard(out)
	case "olt.time":
		return parseTime(out)
	case "olt.sync":
		return parseSync(out)
	case "olt.temperature":
		return parseTemperature(out)
	case "slot.cpu":
		return parseOccupancy(out, "CPU", true)
	case "slot.mem":
		return parseOccupancy(out, "Memory", false)
	case "olt.profile.line", "olt.profile.srv":
		return parseProfileList(out)
	case "olt.profile.dba":
		return parseDBAProfiles(out)
	case "olt.profile.traffic":
		return parseTrafficTables(out)
	}
	return nil, ErrNoParser
}

func field(out, label string) string {
	for _, line := range strings.Split(out, "\n") {
		l := strings.TrimSpace(line)
		if strings.HasPrefix(l, label) {
			rest := strings.TrimSpace(strings.TrimPrefix(l, label))
			if strings.HasPrefix(rest, ":") {
				return strings.TrimSpace(strings.TrimPrefix(rest, ":"))
			}
		}
	}
	return ""
}

func parseVersion(out string) (json.RawMessage, error) {
	product, version, patch := field(out, "PRODUCT"), field(out, "VERSION"), field(out, "PATCH")
	m := reUptime.FindStringSubmatch(out)
	if !reProduct.MatchString(product) || !reRelease.MatchString(version) || !reRelease.MatchString(patch) || m == nil {
		return nil, ErrBadOutput
	}
	n := [4]int{}
	for i := range n {
		n[i], _ = strconv.Atoi(m[i+1])
	}
	if n[1] > 23 || n[2] > 59 || n[3] > 59 {
		return nil, ErrBadOutput
	}
	return json.Marshal(map[string]any{"product": product, "version": version, "patch": patch, "uptime_seconds": ((n[0]*24+n[1])*60+n[2])*60 + n[3]})
}

type boardRow struct {
	Slot   int    `json:"slot"`
	Name   string `json:"name"`
	Status string `json:"status"`
}

func parseBoard(out string) (json.RawMessage, error) {
	boards := []boardRow{}
	empty := []int{}
	seen := map[int]bool{}
	inTable := false
	for _, line := range strings.Split(out, "\n") {
		l := strings.TrimRight(line, " \r\t")
		if strings.Contains(l, "SlotID") && strings.Contains(l, "BoardName") {
			inTable = true
			continue
		}
		if !inTable {
			continue
		}
		if strings.HasPrefix(strings.TrimSpace(l), "---") || strings.TrimSpace(l) == "" {
			continue
		}
		if m := reBoardRow.FindStringSubmatch(l); m != nil {
			slot, _ := strconv.Atoi(m[1])
			if seen[slot] || slot > maxSlot {
				return nil, ErrBadOutput
			}
			seen[slot] = true
			boards = append(boards, boardRow{Slot: slot, Name: m[2], Status: m[3]})
			continue
		}
		if m := reBoardSlot.FindStringSubmatch(l); m != nil { // a slot with no board
			slot, _ := strconv.Atoi(m[1])
			if seen[slot] || slot > maxSlot {
				return nil, ErrBadOutput
			}
			seen[slot] = true
			empty = append(empty, slot)
			continue
		}
		if strings.HasSuffix(l, "#") || strings.HasSuffix(l, ">") { // the prompt ends the listing
			break
		}
		return nil, ErrBadOutput
	}
	if !inTable || len(boards) == 0 {
		return nil, ErrBadOutput
	}
	return json.Marshal(map[string]any{"boards": boards, "empty_slots": empty})
}

// ---- lot 1 of the supervised capture (ADR-0032): shapes seen on the real MA5608T (MA5600V800R015C00), nothing else is guessed.

var (
	reDeviceTime = regexp.MustCompile(`^\s*(\d{4}-\d{2}-\d{2}) (\d{2}:\d{2}:\d{2})([+-]\d{2}):(\d{2})\s*$`)
	reTempRow    = regexp.MustCompile(`^\s*SlotID:\s*(\d{1,2})\s+BoardName:\s*([A-Za-z0-9]{3,20})\s+Temperature:\s*(-?\d{1,3})C\(\s*-?\d{1,3}F\)\s*$`)
)

// isEcho tells the lines that only repeat the command or carry the prompt: they hold no data.
func isEcho(l string) bool {
	t := strings.TrimSpace(l)
	return t == "" || t == "Command:" || strings.HasPrefix(t, "display ") || strings.HasSuffix(t, "#") || strings.HasSuffix(t, ">")
}

// parseTime: the OLT's wall clock WITH its UTC offset. It is the device's own clock (it can be minutes off): the Cloud keeps it inside `data` and never uses it as the observation time.
func parseTime(out string) (json.RawMessage, error) {
	var found string
	for _, line := range strings.Split(out, "\n") {
		if isEcho(line) {
			continue
		}
		m := reDeviceTime.FindStringSubmatch(strings.TrimRight(line, "\r"))
		if m == nil || found != "" {
			return nil, ErrBadOutput
		}
		t, err := time.Parse("2006-01-02T15:04:05-07:00", m[1]+"T"+m[2]+m[3]+":"+m[4])
		if err != nil || t.Year() < 2000 || t.Year() > 2100 {
			return nil, ErrBadOutput
		}
		found = t.Format(time.RFC3339)
	}
	if found == "" {
		return nil, ErrBadOutput
	}
	return json.Marshal(map[string]any{"time": found})
}

// parseSync: the only answer seen is the single-control-board one. Any other wording is refused rather than guessed (another firmware, or a standby board present,
// answers differently and needs its own capture before it can be called valid).
func parseSync(out string) (json.RawMessage, error) {
	seen := false
	for _, line := range strings.Split(out, "\n") {
		if isEcho(line) {
			continue
		}
		if strings.TrimSpace(line) != "Standby board fault or not exist" || seen {
			return nil, ErrBadOutput
		}
		seen = true
	}
	if !seen {
		return nil, ErrBadOutput
	}
	return json.Marshal(map[string]any{"standby": "absent_or_fault"})
}

type tempRow struct {
	Slot    int    `json:"slot"`
	Name    string `json:"name"`
	Celsius int    `json:"celsius"`
}

func parseTemperature(out string) (json.RawMessage, error) {
	rows := []tempRow{}
	seen := map[int]bool{}
	for _, line := range strings.Split(out, "\n") {
		l := strings.TrimRight(line, "\r")
		if isEcho(l) {
			continue
		}
		m := reTempRow.FindStringSubmatch(l)
		if m == nil {
			return nil, ErrBadOutput
		}
		slot, _ := strconv.Atoi(m[1])
		c, _ := strconv.Atoi(m[3])
		if seen[slot] || slot > maxSlot || c < -40 || c > 150 {
			return nil, ErrBadOutput
		}
		seen[slot] = true
		rows = append(rows, tempRow{Slot: slot, Name: m[2], Celsius: c})
	}
	if len(rows) == 0 {
		return nil, ErrBadOutput
	}
	return json.Marshal(map[string]any{"boards": rows})
}

const cpuPreamble = "Send message for inquiring board cpu occupancy successfully, board executing..."

var reOccupancy = regexp.MustCompile(`^(CPU|Memory) occupancy:\s*(\d{1,3})%$`)

// parseOccupancy: a board's CPU or memory use, one integer percentage. A line-card answers with a fixed "Send message ... board executing..." line first (only for
// the CPU query); the control board answers with the occupancy alone. The slot is NOT in the output: it is the one the query asked for (the cloud keys the cache by it).
func parseOccupancy(out, label string, preamble bool) (json.RawMessage, error) {
	pct, seen, pre := -1, 0, false
	for _, line := range strings.Split(out, "\n") {
		l := strings.TrimSpace(strings.TrimRight(line, "\r"))
		if isEcho(l) {
			continue
		}
		if preamble && l == cpuPreamble && !pre && seen == 0 {
			pre = true
			continue
		}
		m := reOccupancy.FindStringSubmatch(l)
		if m == nil || m[1] != label {
			return nil, ErrBadOutput
		}
		v, _ := strconv.Atoi(m[2])
		if v > 100 {
			return nil, ErrBadOutput
		}
		pct = v
		seen++
	}
	if seen != 1 {
		return nil, ErrBadOutput
	}
	return json.Marshal(map[string]int{"percent": pct})
}

var (
	reProfileHeader = regexp.MustCompile(`^Profile-ID\s+Profile-name\s+Binding times$`)
	reProfileRule   = regexp.MustCompile(`^-{20,}$`)
	reProfileRow    = regexp.MustCompile(`^(\d{1,5})\s+([A-Za-z0-9][A-Za-z0-9._-]{0,63})\s+(\d{1,6})$`)
	reProfileTotal  = regexp.MustCompile(`^Total:\s*(\d{1,5})$`)
)

type profileRow struct {
	ID           int     `json:"id"`
	Name         *string `json:"name"` // null unless the Edge's owner opted in (ScrubProfileNames): a label is the operator's free text
	BindingTimes int     `json:"binding_times"`
}

// parseProfileList: the OLT's own list of ONT line or service profiles (ID, name, how many ONTs use it). It carries no ONT, serial or subscriber text; the name is
// the operator's label and is kept to a safe alphabet. Strict: the header, the Total line and the number of rows must agree, IDs are unique, anything else is bad_output.
func parseProfileList(out string) (json.RawMessage, error) {
	rows := []profileRow{}
	seen := map[int]bool{}
	header, total := false, -1
	for _, line := range strings.Split(out, "\n") {
		l := strings.TrimSpace(strings.TrimRight(line, "\r"))
		switch {
		case isEcho(l), reProfileRule.MatchString(l):
			continue
		case reProfileHeader.MatchString(l):
			if header || len(rows) > 0 {
				return nil, ErrBadOutput
			}
			header = true
		case reProfileTotal.MatchString(l):
			if total >= 0 {
				return nil, ErrBadOutput
			}
			total, _ = strconv.Atoi(reProfileTotal.FindStringSubmatch(l)[1])
		default:
			m := reProfileRow.FindStringSubmatch(l)
			if m == nil || !header || total >= 0 {
				return nil, ErrBadOutput
			}
			id, _ := strconv.Atoi(m[1])
			n, _ := strconv.Atoi(m[3])
			if seen[id] || len(rows) >= 2048 {
				return nil, ErrBadOutput
			}
			seen[id] = true
			name := m[2]
			rows = append(rows, profileRow{ID: id, Name: &name, BindingTimes: n})
		}
	}
	if !header || total != len(rows) {
		return nil, ErrBadOutput
	}
	return json.Marshal(map[string]any{"profiles": rows})
}

var (
	reDBAHeader1 = regexp.MustCompile(`^Profile-ID\s+type\s+Bandwidth\s+Fix\s+Assure\s+Max\s+Bind$`)
	reDBAHeader2 = regexp.MustCompile(`^compensation\s+\(kbps\)\s+\(kbps\)\s+\(kbps\)\s+times$`)
	reDBARow     = regexp.MustCompile(`^(\d{1,5})\s+([1-5])\s+(Yes|No)\s+(\d{1,8})\s+(\d{1,8})\s+(\d{1,8})\s+(\d{1,6})$`)
)

type dbaRow struct {
	ID           int  `json:"id"`
	Type         int  `json:"type"`
	Compensation bool `json:"compensation"`
	FixKbps      int  `json:"fixed_kbps"`
	AssureKbps   int  `json:"assured_kbps"`
	MaxKbps      int  `json:"maximum_kbps"`
	BindingTimes int  `json:"binding_times"`
}

// parseDBAProfiles: the OLT's DBA profiles (upstream bandwidth: type 1 fixed, 2 assured, 3 assured+maximum, 4 maximum, 5 all three). Numbers only, no ONT or text.
// Strict like the others: the two header lines, unique IDs, and a rate that the type does not use must be zero.
func parseDBAProfiles(out string) (json.RawMessage, error) {
	rows := []dbaRow{}
	seen := map[int]bool{}
	stage := 0      // 0 nothing, 1 first header, 2 both headers
	closed := false // the table ends with its closing rule: without it the output may have been cut after a few rows
	for _, line := range strings.Split(out, "\n") {
		l := strings.TrimSpace(strings.TrimRight(line, "\r"))
		switch {
		case isEcho(l):
			continue
		case reProfileRule.MatchString(l):
			closed = stage == 2 && len(rows) > 0
			continue
		case reDBAHeader1.MatchString(l):
			if stage != 0 {
				return nil, ErrBadOutput
			}
			stage = 1
		case reDBAHeader2.MatchString(l):
			if stage != 1 {
				return nil, ErrBadOutput
			}
			stage = 2
		default:
			m := reDBARow.FindStringSubmatch(l)
			if m == nil || stage != 2 || closed {
				return nil, ErrBadOutput
			}
			a := func(i int) int { v, _ := strconv.Atoi(m[i]); return v }
			r := dbaRow{ID: a(1), Type: a(2), Compensation: m[3] == "Yes", FixKbps: a(4), AssureKbps: a(5), MaxKbps: a(6), BindingTimes: a(7)}
			uses := map[int][3]bool{1: {true, false, false}, 2: {false, true, false}, 3: {false, true, true}, 4: {false, false, true}, 5: {true, true, true}}[r.Type]
			if (!uses[0] && r.FixKbps != 0) || (!uses[1] && r.AssureKbps != 0) || (!uses[2] && r.MaxKbps != 0) || seen[r.ID] || len(rows) >= 2048 {
				return nil, ErrBadOutput
			}
			seen[r.ID] = true
			rows = append(rows, r)
		}
	}
	if stage != 2 || len(rows) == 0 || !closed {
		return nil, ErrBadOutput
	}
	return json.Marshal(map[string]any{"profiles": rows})
}

var (
	reTrafficHeader1 = regexp.MustCompile(`^TID\s+CIR\s+CBS\s+PIR\s+PBS\s+Pri\s+Copy-policy\s+Pri-Policy$`)
	reTrafficHeader2 = regexp.MustCompile(`^\(kbps\)\s+\(bytes\)\s+\(kbps\)\s+\(bytes\)$`)
	reTrafficRow     = regexp.MustCompile(`^(\d{1,5})\s+(\d{1,9}|off)\s+(\d{1,9}|off)\s+(\d{1,9}|off)\s+(\d{1,9}|off)\s+([0-7])\s+(-|user-cos|[a-z]+(?:-[a-z]+){0,2})\s+([a-z]+(?:-[a-z]+){0,2})$`)
	reTrafficTotal   = regexp.MustCompile(`^Total Num\s*:\s*(\d{1,5})$`)
)

type trafficRow struct {
	ID         int    `json:"id"`
	CIRKbps    *int   `json:"cir_kbps"` // null = the table says "off" (no limit)
	CBSBytes   *int   `json:"cbs_bytes"`
	PIRKbps    *int   `json:"pir_kbps"`
	PBSBytes   *int   `json:"pbs_bytes"`
	Priority   int    `json:"priority"`
	CopyPolicy string `json:"copy_policy"`
	PriPolicy  string `json:"pri_policy"`
}

// parseTrafficTables: the OLT's IP traffic tables (rate limits applied per service-port). Numbers and two closed keywords per row, no ONT or free text.
func parseTrafficTables(out string) (json.RawMessage, error) {
	rows := []trafficRow{}
	seen := map[int]bool{}
	stage, total := 0, -1
	for _, line := range strings.Split(out, "\n") {
		l := strings.TrimSpace(strings.TrimRight(line, "\r"))
		switch {
		case isEcho(l), reProfileRule.MatchString(l):
			continue
		case reTrafficHeader1.MatchString(l):
			if stage != 0 {
				return nil, ErrBadOutput
			}
			stage = 1
		case reTrafficHeader2.MatchString(l):
			if stage != 1 {
				return nil, ErrBadOutput
			}
			stage = 2
		case reTrafficTotal.MatchString(l):
			if total >= 0 {
				return nil, ErrBadOutput
			}
			total, _ = strconv.Atoi(reTrafficTotal.FindStringSubmatch(l)[1])
		default:
			m := reTrafficRow.FindStringSubmatch(l)
			if m == nil || stage != 2 || total >= 0 {
				return nil, ErrBadOutput
			}
			a := func(i int) int { v, _ := strconv.Atoi(m[i]); return v }
			rate := func(i int) *int {
				if m[i] == "off" {
					return nil
				}
				v := a(i)
				return &v
			}
			r := trafficRow{ID: a(1), CIRKbps: rate(2), CBSBytes: rate(3), PIRKbps: rate(4), PBSBytes: rate(5), Priority: a(6), CopyPolicy: m[7], PriPolicy: m[8]}
			if seen[r.ID] || len(rows) >= 2048 {
				return nil, ErrBadOutput
			}
			seen[r.ID] = true
			rows = append(rows, r)
		}
	}
	if stage != 2 || total != len(rows) {
		return nil, ErrBadOutput
	}
	return json.Marshal(map[string]any{"tables": rows})
}

var reLongDigits = regexp.MustCompile(`\d{8,}`)

// ScrubProfileNames is applied to a typed result BEFORE it is stored for the Cloud. A profile name is text the operator chose: nothing in its alphabet stops it from
// carrying a customer's name, address or a serial, so by default the Cloud gets the profile's number and its rates only (name: null). The Edge's owner can opt in
// (olt_profile_names_to_cloud); even then a name with a run of 8+ digits (phone, document, serial) is dropped. Other queries pass through untouched.
func ScrubProfileNames(queryID string, typed json.RawMessage, keepNames bool) (json.RawMessage, error) {
	if queryID != "olt.profile.line" && queryID != "olt.profile.srv" {
		return typed, nil
	}
	var v struct {
		Profiles []profileRow `json:"profiles"`
	}
	if err := json.Unmarshal(typed, &v); err != nil {
		return nil, ErrBadOutput
	}
	for i := range v.Profiles {
		if !keepNames || v.Profiles[i].Name == nil || reLongDigits.MatchString(*v.Profiles[i].Name) {
			v.Profiles[i].Name = nil
		}
	}
	return json.Marshal(map[string]any{"profiles": v.Profiles})
}
