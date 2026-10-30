package olt

import (
	"encoding/json"
	"errors"
	"regexp"
	"strconv"
	"strings"
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
func HasParser(queryID string) bool { return queryID == "olt.version" || queryID == "olt.board" }

// ParseResult turns the device output of a validated query into its typed result (compact JSON).
func ParseResult(queryID, out string) (json.RawMessage, error) {
	switch queryID {
	case "olt.version":
		return parseVersion(out)
	case "olt.board":
		return parseBoard(out)
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
