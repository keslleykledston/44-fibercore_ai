package olt

import (
	"context"
	"encoding/hex"
	"fmt"
	"regexp"
	"sort"
	"strconv"
	"strings"
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

func ontID(suffix string) (int, bool) {
	n, err := strconv.Atoi(suffix)
	return n, err == nil && n >= 0 && n < maxONTs
}
