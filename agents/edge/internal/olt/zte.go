package olt

import (
	"context"
	"fmt"
	"regexp"
	"strconv"
	"strings"
)

// ZTE ZXA10 C300 (CLI "show" family). Parsers are covered by SYNTHETIC fixtures only.
type ZTE struct{}

func (ZTE) Vendor() string { return "zte" }

var (
	zPort     = regexp.MustCompile(`^\d+/\d+/\d+$`)
	zAllowed  = regexp.MustCompile(`^(show version|show gpon onu state gpon-olt_\d+/\d+/\d+|show gpon onu baseinfo gpon-olt_\d+/\d+/\d+|show pon power onu-rx gpon-olt_\d+/\d+/\d+)$`)
	zModel    = regexp.MustCompile(`(?m)^\s*Model\s*:\s*(\S+)`)
	zFirmware = regexp.MustCompile(`(?m)^\s*Software Version\s*:\s*(\S+)`)
	zState    = regexp.MustCompile(`^\s*(\d+/\d+/\d+:\d+)\s+\S+\s+\S+\s+(\S+)\s+\S+\s*$`)
	zBase     = regexp.MustCompile(`^\s*gpon-onu_(\d+/\d+/\d+:\d+)\s+\S+\s+\S+\s+SN:([0-9A-Za-z]{8,16})\s*$`)
	zRx       = regexp.MustCompile(`^\s*gpon-onu_(\d+/\d+/\d+:\d+)\s+(?:(-?\d+(?:\.\d+)?)\(dbm\)|N/A)\s*$`)
)

func ZTEAllowed(cmd string) bool { return zAllowed.MatchString(cmd) }

func (ZTE) Identify(ctx context.Context, s Session) (Identity, error) {
	out, err := s.Run(ctx, "show version")
	if err != nil {
		return Identity{}, err
	}
	id := Identity{Vendor: "zte"}
	if m := zModel.FindStringSubmatch(out); m != nil {
		id.Model = m[1]
	}
	if m := zFirmware.FindStringSubmatch(out); m != nil {
		id.Firmware = m[1]
	}
	if id.Model == "" || id.Firmware == "" {
		return id, fmt.Errorf("zte: cannot parse show version")
	}
	return id, nil
}

func (z ZTE) Snapshot(ctx context.Context, s Session, ports []string) (Snapshot, error) {
	id, err := z.Identify(ctx, s)
	if err != nil {
		return Snapshot{}, err
	}
	snap := Snapshot{Identity: id}
	for _, p := range ports {
		if !zPort.MatchString(p) {
			return Snapshot{}, fmt.Errorf("invalid pon port %q", p)
		}
		var outs [3]string
		for i, c := range []string{"show gpon onu state gpon-olt_", "show gpon onu baseinfo gpon-olt_", "show pon power onu-rx gpon-olt_"} {
			if outs[i], err = s.Run(ctx, c+p); err != nil {
				return Snapshot{}, err
			}
		}
		states, serials, rx := map[string]string{}, map[string]string{}, map[string]*float64{}
		var order []string
		for _, line := range strings.Split(outs[0], "\n") {
			if m := zState.FindStringSubmatch(line); m != nil {
				states[m[1]] = strings.ToLower(m[2])
				order = append(order, m[1])
			}
		}
		for _, line := range strings.Split(outs[1], "\n") {
			if m := zBase.FindStringSubmatch(line); m != nil {
				serials[m[1]] = strings.ToUpper(m[2])
			}
		}
		for _, line := range strings.Split(outs[2], "\n") {
			if m := zRx.FindStringSubmatch(line); m != nil {
				if m[2] == "" {
					rx[m[1]] = nil
				} else if v, err := strconv.ParseFloat(m[2], 64); err == nil && v >= -50 && v <= 10 {
					rx[m[1]] = &v
				}
			}
		}
		n := 0
		for _, idx := range order {
			serial, ok := serials[idx]
			if !ok {
				continue // cannot key an ONU without serial; never invent identity
			}
			snap.ONUs = append(snap.ONUs, ONU{Serial: serial, PonPath: p, Status: zStatus(states[idx]), RxDBm: rx[idx]})
			n++
		}
		snap.PONs = append(snap.PONs, PON{Path: p, Status: ponStatus(n)})
	}
	return snap, nil
}

func zStatus(phase string) string {
	switch phase {
	case "working":
		return "online"
	case "los":
		return "los"
	case "dyinggasp":
		return "dying_gasp"
	case "offline":
		return "offline"
	}
	return "unknown"
}

func (ZTE) Allowed(cmd string) bool { return ZTEAllowed(cmd) }
