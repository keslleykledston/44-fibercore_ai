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

// The OLT's own "last down time" of an offline ONU, read over the CLI: `display ont register-info <port> <ont-id>` inside `interface gpon 0/<slot>`
// (read-only; format captured on a real MA5608T, see testdata/huawei_ma5608t). It lists the registration history of the ONU, newest and oldest in
// no order the parser relies on; every record has UpTime / DownTime ("-" while the ONU is up) and DownCause.

// DownReads lets a driver read the last down time of chosen offline ONUs in the SAME session as the listing (no extra login).
type DownReads struct {
	// Pick is called once with the complete listing, after the tables were read, and returns the ONUs whose register-info should be read now.
	// It must only return offline ONUs of that listing that have an ONT-ID; the driver ignores anything else.
	Pick func(listing []ONU) []ONU
	// Done reports the outcome for one ONU: at != nil = the OLT's last down time; at == nil = the OLT has no usable record for it.
	// It is not called when the read itself failed (session error, device rejection): the ONU is simply picked again later.
	Done func(serial string, at *time.Time)
}

// DownReader is implemented by drivers that can read last down times while taking a snapshot.
type DownReader interface {
	SnapshotWithDownTimes(ctx context.Context, s Session, ports []string, r DownReads) (Snapshot, error)
}

var (
	reRegIndex = regexp.MustCompile(`(?m)^\s*Index\s*:\s*\d+\s*$`)
	reRegSN    = regexp.MustCompile(`(?m)^\s*SN\s*:\s*([0-9A-Fa-f]{16})\b`)
	reRegUp    = regexp.MustCompile(`(?m)^\s*UpTime\s*:\s*(.+?)\s*$`)
	reRegDown  = regexp.MustCompile(`(?m)^\s*DownTime\s*:\s*(.+?)\s*$`)
	reRegTotal = regexp.MustCompile(`(?m)^\s*Total\s*:\s*(\d+)\s*$`)
)

// ErrNoDownRecord: the register-info answer is well-formed but gives no usable down time for this ONU (never went down, or inconsistent).
var ErrNoDownRecord = errors.New("huawei r015: no usable down time in register-info")

// ParseLastDown returns the DownTime of the NEWEST record of the registration history of the ONU with this serial. The answer is only trusted
// when every record is for that serial, the footer total matches the records and EVERY record has a well-formed UpTime and DownTime (each either
// "-" or a real time): one malformed record anywhere rejects the answer, so an old outage can never be read as the current one. The newest record
// is the one with the greatest UpTime (the listing order is not relied on, ties are ambiguous and rejected); its DownTime must be a time at or
// after its UpTime.
func ParseLastDown(out, serial string) (time.Time, error) {
	idx := reRegIndex.FindAllStringIndex(out, -1)
	if len(idx) == 0 {
		return time.Time{}, ErrNoDownRecord
	}
	if t := reRegTotal.FindStringSubmatch(out); t == nil || t[1] != strconv.Itoa(len(idx)) {
		return time.Time{}, fmt.Errorf("%w: record count does not match the footer", ErrNoDownRecord)
	}
	var newestUp, newestDown time.Time
	tie, downOK := false, false
	for i, at := range idx {
		end := len(out)
		if i+1 < len(idx) {
			end = idx[i+1][0]
		}
		rec := out[at[0]:end]
		if m := reRegSN.FindStringSubmatch(rec); m == nil || !strings.EqualFold(m[1], serial) {
			return time.Time{}, fmt.Errorf("%w: record of another ONU", ErrNoDownRecord)
		}
		um, dm := reRegUp.FindStringSubmatch(rec), reRegDown.FindStringSubmatch(rec)
		if um == nil || dm == nil {
			return time.Time{}, fmt.Errorf("%w: record without UpTime/DownTime", ErrNoDownRecord)
		}
		up, upOK := parseRegisterTime(um[1])
		down, dOK := parseRegisterTime(dm[1])
		if !upOK || (!dOK && strings.TrimSpace(dm[1]) != "-") {
			return time.Time{}, fmt.Errorf("%w: malformed time in a record", ErrNoDownRecord)
		}
		switch {
		case newestUp.IsZero() || up.After(newestUp):
			newestUp, newestDown, downOK, tie = up, down, dOK, false
		case up.Equal(newestUp):
			tie = true
		}
	}
	if tie || !downOK || newestDown.Before(newestUp) {
		return time.Time{}, ErrNoDownRecord
	}
	return newestDown, nil
}

// parseRegisterTime reads "2026-01-02 00:00:00-04:00" (the zone is part of the value). "-" and anything else is not a time.
func parseRegisterTime(s string) (time.Time, bool) {
	t, err := time.Parse("2006-01-02 15:04:05-07:00", strings.TrimSpace(s))
	if err != nil || t.Year() < 2010 || t.Year() > 2100 {
		return time.Time{}, false
	}
	return t.UTC(), true
}

var r015RegisterQuery, _ = QueryByID("onu.register")

// allowsRegister: exactly `display ont register-info <port> <ont-id>` with the catalog's own bounds.
func allowsRegister(cmd string) bool { return matchesTemplate(r015RegisterQuery, cmd) }

// SnapshotWithDownTimes is Snapshot plus the register-info reads asked for in r. The extra reads are best effort: whatever goes wrong in them
// (session error, device rejection) ends them and the complete listing already read is returned as it is.
func (h HuaweiR015) SnapshotWithDownTimes(ctx context.Context, s Session, ports []string, r DownReads) (Snapshot, error) {
	snap, err := h.Snapshot(ctx, s, ports)
	if err != nil || !h.DownTimes || r.Pick == nil || r.Done == nil {
		return snap, err
	}
	bySlot := map[string][]ONU{}
	var order []string
	for _, u := range r.Pick(snap.ONUs) {
		f := strings.Split(u.PonPath, "/")
		if u.Status != "offline" || !u.HasOntID || len(f) != 3 || !ValidR015Port(u.PonPath) {
			continue
		}
		slot := f[0] + "/" + f[1]
		if _, ok := bySlot[slot]; !ok {
			order = append(order, slot)
		}
		bySlot[slot] = append(bySlot[slot], u)
	}
	if len(order) == 0 {
		return snap, nil
	}
	run := func(cmd string) (string, bool) {
		out, err := s.Run(ctx, cmd)
		return out, err == nil && !r015CLIError.MatchString(out)
	}
	// the snapshot ended back in config mode (every interface was left with quit), where the interface commands live
	for _, slot := range order {
		if _, ok := run("interface gpon " + slot); !ok {
			return snap, nil
		}
		for _, u := range bySlot[slot] {
			f := strings.Split(u.PonPath, "/")
			out, ok := run("display ont register-info " + f[2] + " " + strconv.Itoa(u.OntID))
			if !ok {
				run("quit")
				return snap, nil
			}
			if t, err := ParseLastDown(out, u.Serial); err == nil {
				tt := t
				r.Done(u.Serial, &tt)
			} else {
				r.Done(u.Serial, nil)
			}
		}
		if _, ok := run("quit"); !ok {
			return snap, nil
		}
	}
	return snap, nil
}
