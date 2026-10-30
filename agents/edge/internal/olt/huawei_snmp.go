package olt

import (
	"context"
	"encoding/hex"
	"errors"
	"fmt"
	"regexp"
	"sort"
	"strconv"
	"strings"
	"time"
)

// HuaweiSNMP reads a Huawei MA5600-family OLT (validated on a MA5608T, MA5600V800R015C00) over SNMP v2c, read-only.
// OIDs are from HUAWEI-XPON-MIB (1.3.6.1.4.1.2011.6.128.1.1.2); the columns and scales used here were cross-checked against
// the CLI on the same device (SN 12/12, run state 12/12, Rx identical, down cause 10/10), see DRIVER_SDK_INTERFACE.md.
type HuaweiSNMP struct{}

// SNMPDriver is the SNMP counterpart of Driver.
type SNMPDriver interface {
	Vendor() string
	Identify(ctx context.Context, r SNMPReader, ports []string) (Identity, error)
	Snapshot(ctx context.Context, r SNMPReader, ports []string) (Snapshot, error)
}

const (
	hwXpon    = "1.3.6.1.4.1.2011.6.128.1.1.2"
	oidIfDesc = "1.3.6.1.2.1.2.2.1.2"
	noReading = 2147483647 // sentinel the agent returns when there is no optical reading (offline ONT)
	maxONTs   = 128        // GPON ONT-ID space per PON
)

var hwIfDesc = regexp.MustCompile(`^Huawei-(MA\d{4})-(V\d+R\d+)-GPON`)

func (HuaweiSNMP) Vendor() string { return "huawei" }

// ponIfIndex: ifIndex of a GPON port = 0xFA000000 + slot*8192 + port*256 (frame 0 only; anything else is refused, not guessed).
func ponIfIndex(path string) (int, error) {
	p := strings.Split(path, "/")
	if len(p) != 3 || p[0] != "0" {
		return 0, fmt.Errorf("snmp: pon %q not supported (frame 0 only)", path)
	}
	slot, e1 := strconv.Atoi(p[1])
	port, e2 := strconv.Atoi(p[2])
	if e1 != nil || e2 != nil || slot < 0 || slot > 20 || port < 0 || port > 15 {
		return 0, fmt.Errorf("snmp: invalid pon %q", path)
	}
	return 0xFA000000 + slot*8192 + port*256, nil
}

func (h HuaweiSNMP) Identify(ctx context.Context, r SNMPReader, ports []string) (Identity, error) {
	if len(ports) == 0 {
		return Identity{}, fmt.Errorf("snmp: no pon to identify the device from")
	}
	ifx, err := ponIfIndex(ports[0])
	if err != nil {
		return Identity{}, err
	}
	oid := fmt.Sprintf("%s.%d", oidIfDesc, ifx)
	got, err := r.Get(ctx, []string{oid})
	if err != nil {
		return Identity{}, err
	}
	v := got[oid]
	m := hwIfDesc.FindStringSubmatch(string(v.Bytes))
	if m == nil || !v.IsBytes {
		return Identity{}, fmt.Errorf("snmp: %s is not a recognised Huawei GPON interface", ports[0])
	}
	// The interface name carries the family and release only (no sub-model, no patch level).
	return Identity{Vendor: "huawei", Model: m[1], Firmware: m[1] + m[2]}, nil
}

func (h HuaweiSNMP) Snapshot(ctx context.Context, r SNMPReader, ports []string) (Snapshot, error) {
	id, err := h.Identify(ctx, r, ports)
	if err != nil {
		return Snapshot{}, err
	}
	if !strings.HasPrefix(id.Firmware, r015Firmware) { // only the validated release; nothing else is read
		return Snapshot{}, fmt.Errorf("snmp: %s %s not validated (only %s*)", id.Model, id.Firmware, r015Firmware)
	}
	snap := Snapshot{Identity: id}
	for _, path := range ports {
		onus, pon, err := h.readPon(ctx, r, path)
		if err != nil {
			return Snapshot{}, fmt.Errorf("pon %s: %w", path, err)
		}
		snap.ONUs = append(snap.ONUs, onus...)
		snap.PONs = append(snap.PONs, pon)
	}
	return snap, nil
}

func (HuaweiSNMP) readPon(ctx context.Context, r SNMPReader, path string) ([]ONU, PON, error) {
	ifx, err := ponIfIndex(path)
	if err != nil {
		return nil, PON{}, err
	}
	descOID := fmt.Sprintf("%s.%d", oidIfDesc, ifx)
	d, err := r.Get(ctx, []string{descOID})
	if err != nil {
		return nil, PON{}, err
	}
	if !hwIfDesc.MatchString(string(d[descOID].Bytes)) { // the ifIndex formula must land on a real GPON port, or refuse
		return nil, PON{}, fmt.Errorf("ifIndex %d is not a GPON port", ifx)
	}
	// Two independent walks of the same PON must list the same ONT-IDs; each walk finishing without error is the proof that
	// it reached the end of the table (see SNMPReader.Walk).
	states, err := r.Walk(ctx, fmt.Sprintf("%s.46.1.15.%d", hwXpon, ifx), maxONTs)
	if err != nil {
		return nil, PON{}, err
	}
	serials, err := r.Walk(ctx, fmt.Sprintf("%s.43.1.3.%d", hwXpon, ifx), maxONTs)
	if err != nil {
		return nil, PON{}, err
	}
	verified := len(states) == len(serials)
	run := map[int]int64{}
	for _, row := range states {
		id, ok := ontID(row.Suffix)
		if _, dup := run[id]; dup || !ok || !row.Value.IsInt {
			verified = false
			continue
		}
		run[id] = row.Value.Int
	}
	sn := map[int]string{}
	seen := map[string]bool{}
	for _, row := range serials {
		id, ok := ontID(row.Suffix)
		if !ok || !row.Value.IsBytes || len(row.Value.Bytes) != 8 {
			verified = false
			continue
		}
		s := strings.ToUpper(hex.EncodeToString(row.Value.Bytes))
		if _, dup := sn[id]; dup || seen[s] {
			verified = false
			continue
		}
		sn[id], seen[s] = s, true
	}
	var ids []int
	for id := range run {
		if _, ok := sn[id]; !ok {
			verified = false // listed as having a state but no serial (or the reverse): the table moved under us
			continue
		}
		ids = append(ids, id)
	}
	if len(ids) != len(sn) || len(ids) != len(run) {
		verified = false
	}
	sort.Ints(ids)
	var rxOIDs, causeOIDs []string
	for _, id := range ids {
		switch run[id] {
		case 1:
			rxOIDs = append(rxOIDs, fmt.Sprintf("%s.51.1.4.%d.%d", hwXpon, ifx, id))
		case 2:
			causeOIDs = append(causeOIDs, fmt.Sprintf("%s.46.1.24.%d.%d", hwXpon, ifx, id))
		default:
			verified = false // a run state we have not seen on the device: do not claim a complete, understood listing
		}
	}
	rx, err := r.Get(ctx, rxOIDs)
	if err != nil {
		return nil, PON{}, err
	}
	cause, err := r.Get(ctx, causeOIDs)
	if err != nil {
		return nil, PON{}, err
	}
	down := HuaweiSNMP{}.lastDown(ctx, r, ifx, ids, run)
	var onus []ONU
	for _, id := range ids {
		u := ONU{Serial: sn[id], PonPath: path, Status: "unknown"}
		switch run[id] {
		case 1:
			u.Status = "online"
			if v := rx[fmt.Sprintf("%s.51.1.4.%d.%d", hwXpon, ifx, id)]; v.IsInt && v.Int != noReading && v.Int >= -5000 && v.Int <= 1000 {
				f := float64(v.Int) / 100
				u.RxDBm = &f
			}
		case 2:
			u.Status = "offline"
			if t, ok := down[id]; ok {
				tt := t
				u.LastDownAt = &tt
			}
			switch c := cause[fmt.Sprintf("%s.46.1.24.%d.%d", hwXpon, ifx, id)]; {
			case c.IsInt && c.Int == 13:
				u.Status = "dying_gasp"
			case c.IsInt && c.Int == 2:
				u.Status = "los"
			}
		}
		onus = append(onus, u)
	}
	return onus, PON{Path: path, Status: ponStatus(len(onus)), Verified: verified}, nil
}

// downBatch is how many OIDs one GET carries. The agent is rate-limited (one request per second), so the offline ONUs of a PON cost a handful of
// requests, not one each.
const downBatch = 20

// lastDown reads hwGponDeviceOntControlLastDownTime (column 23, DateAndTime) of the OFFLINE ONUs. It is best effort: any failure (budget, timeout,
// a value that does not parse) only means "not reported" for the affected ONUs and never fails the snapshot.
func (HuaweiSNMP) lastDown(ctx context.Context, r SNMPReader, ifx int, ids []int, run map[int]int64) map[int]time.Time {
	var oids []string
	idOf := map[string]int{}
	for _, id := range ids {
		if run[id] == 2 {
			o := fmt.Sprintf("%s.46.1.23.%d.%d", hwXpon, ifx, id)
			oids, idOf[o] = append(oids, o), id
		}
	}
	out := map[int]time.Time{}
	for len(oids) > 0 {
		n := min(downBatch, len(oids))
		got, err := r.Get(ctx, oids[:n])
		if err != nil {
			return out // keep what was read so far
		}
		for _, o := range oids[:n] {
			if v := got[o]; v.IsBytes && !v.Missing {
				if t, ok := parseDateAndTime(v.Bytes); ok {
					out[idOf[o]] = t
				}
			}
		}
		oids = oids[n:]
	}
	return out
}

// DownTarget names ONE offline ONU for the focused last-down read: where it is (port + ONT-ID, from the CLI listing) and the serial it must have.
type DownTarget struct {
	PonPath string
	OntID   int
	Serial  string
}

// LastDownReader is the focused, read-only SNMP operation behind the CLI entries' last_down side channel.
type LastDownReader interface {
	// LastDowns returns serial -> the OLT's "last down time" for the targets of ONE port. Nothing else is read.
	LastDowns(ctx context.Context, r SNMPReader, targets []DownTarget) (map[string]time.Time, error)
}

// snmpGetOIDs is the most OIDs the transport puts in ONE request (snmpClient.Get splits anything longer into several paced requests).
const snmpGetOIDs = 10

// downPairs is how many ONUs one request carries: two OIDs each, the time and the serial that proves the ONT-ID still names that ONU.
const downPairs = snmpGetOIDs / 2

// LastDowns reads, for the offline ONUs of ONE port, hwGponDeviceOntControlLastDownTime (col 23) together with the ONT's serial (col 3 of the
// serial table). A time is accepted only when the serial the OLT reports for that ONT-ID is the target's: if the table moved since the CLI
// listing the ONU is simply not reported. One request per five ONUs (the first one carries four plus the port check); the reader paces them.
func (HuaweiSNMP) LastDowns(ctx context.Context, r SNMPReader, targets []DownTarget) (map[string]time.Time, error) {
	out := map[string]time.Time{}
	if len(targets) == 0 {
		return out, nil
	}
	ifx, err := ponIfIndex(targets[0].PonPath)
	if err != nil {
		return nil, err
	}
	for _, t := range targets {
		if t.PonPath != targets[0].PonPath || t.OntID < 0 || t.OntID >= maxONTs {
			return nil, errors.New("last-down targets must belong to one port with valid ONT-IDs")
		}
	}
	descOID := fmt.Sprintf("%s.%d", oidIfDesc, ifx)
	for first := true; len(targets) > 0; first = false {
		n := min(downPairs, len(targets))
		var oids []string
		if first { // the ifIndex formula must land on a real GPON port, or nothing from this port is trusted
			oids = append(oids, descOID)
			n = min(downPairs-1, len(targets)) // the port check takes one OID of the first request
		}
		for _, t := range targets[:n] {
			oids = append(oids, fmt.Sprintf("%s.46.1.23.%d.%d", hwXpon, ifx, t.OntID), fmt.Sprintf("%s.43.1.3.%d.%d", hwXpon, ifx, t.OntID))
		}
		got, err := r.Get(ctx, oids)
		if err != nil {
			return out, fmt.Errorf("last-down port %s ont-ids %d..%d: %w", targets[0].PonPath, targets[0].OntID, targets[n-1].OntID, err) // where the agent stopped answering
		}
		if first && !hwIfDesc.MatchString(string(got[descOID].Bytes)) {
			return out, fmt.Errorf("ifIndex %d is not a GPON port", ifx)
		}
		for _, t := range targets[:n] {
			tm := got[fmt.Sprintf("%s.46.1.23.%d.%d", hwXpon, ifx, t.OntID)]
			sn := got[fmt.Sprintf("%s.43.1.3.%d.%d", hwXpon, ifx, t.OntID)]
			if !tm.IsBytes || tm.Missing || !sn.IsBytes || sn.Missing || len(sn.Bytes) != 8 || !strings.EqualFold(hex.EncodeToString(sn.Bytes), t.Serial) {
				continue
			}
			if at, ok := parseDateAndTime(tm.Bytes); ok {
				out[strings.ToUpper(t.Serial)] = at
			}
		}
		targets = targets[n:]
	}
	return out, nil
}

// parseDateAndTime decodes an SNMPv2 DateAndTime (RFC 2579) WITH a time zone (11 bytes). An 8-byte value has no zone and is refused rather than
// guessed; the all-zero / pre-2010 "never" value is not a time.
func parseDateAndTime(b []byte) (time.Time, bool) {
	if len(b) != 11 {
		return time.Time{}, false
	}
	year := int(b[0])<<8 | int(b[1])
	if year < 2010 || year > 2100 || b[2] < 1 || b[2] > 12 || b[3] < 1 || b[3] > 31 || b[4] > 23 || b[5] > 59 || b[6] > 59 || b[7] > 9 || (b[8] != '+' && b[8] != '-') || b[9] > 14 || b[10] > 59 || (b[9] == 14 && b[10] != 0) {
		return time.Time{}, false
	}
	off := int(b[9])*3600 + int(b[10])*60
	if b[8] == '-' {
		off = -off
	}
	t := time.Date(year, time.Month(b[2]), int(b[3]), int(b[4]), int(b[5]), int(b[6]), int(b[7])*100e6, time.FixedZone("", off))
	if t.Day() != int(b[3]) { // 31 February and friends roll over: not a real date
		return time.Time{}, false
	}
	return t.UTC(), true
}

func ontID(suffix string) (int, bool) {
	n, err := strconv.Atoi(suffix)
	return n, err == nil && n >= 0 && n < maxONTs
}
