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
	case "olt.version", "olt.board", "olt.time", "olt.sync", "olt.temperature", "slot.cpu", "slot.mem":
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
