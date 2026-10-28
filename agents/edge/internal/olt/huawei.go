package olt

import (
	"context"
	"fmt"
	"regexp"
	"strconv"
	"strings"
)

// Huawei MA5800 (VRP "display" family). Parsers are covered by SYNTHETIC fixtures only.
type Huawei struct{}

func (Huawei) Vendor() string { return "huawei" }

var (
	hwPort      = regexp.MustCompile(`^\d+/\d+/\d+$`)
	hwAllowed   = regexp.MustCompile(`^(display version|display ont info summary \d+/\d+/\d+|display ont optical-info \d+/\d+/\d+ all)$`)
	hwModel     = regexp.MustCompile(`(?m)^\s*VERSION\s*:\s*(\S+)`)
	hwProduct   = regexp.MustCompile(`(?m)^\s*PRODUCT\s*:\s*(\S+)`)
	hwOntRow    = regexp.MustCompile(`^\s*(\d+/\d+/\d+)\s+(\d+)\s+([0-9A-Fa-f]{16})\s+\S+\s+(\S+)\s+\S+\s+\S+\s+\S+\s*$`)
	hwOpticalRx = regexp.MustCompile(`^\s*(\d+)\s+(-?\d+(?:\.\d+)?|-)\s+(?:-?\d+(?:\.\d+)?|-)\s+(?:-?\d+(?:\.\d+)?|-)\s*$`)
)

func HuaweiAllowed(cmd string) bool {
	return hwAllowed.MatchString(cmd)
}

func (h Huawei) Identify(ctx context.Context, s Session) (Identity, error) {
	out, err := s.Run(ctx, "display version")
	if err != nil {
		return Identity{}, err
	}
	id := Identity{Vendor: "huawei"}
	if m := hwProduct.FindStringSubmatch(out); m != nil {
		id.Model = m[1]
	}
	if m := hwModel.FindStringSubmatch(out); m != nil {
		id.Firmware = m[1]
	}
	if id.Model == "" || id.Firmware == "" {
		return id, fmt.Errorf("huawei: cannot parse display version")
	}
	return id, nil
}

func (h Huawei) Snapshot(ctx context.Context, s Session, ports []string) (Snapshot, error) {
	id, err := h.Identify(ctx, s)
	if err != nil {
		return Snapshot{}, err
	}
	if isMA56(id) { // the MA5600 family needs the CLI-mode profile; never guess commands for it
		return Snapshot{}, fmt.Errorf("huawei: %s %s needs profile huawei_ma56_r015", id.Model, id.Firmware)
	}
	snap := Snapshot{Identity: id}
	for _, p := range ports {
		if !hwPort.MatchString(p) {
			return Snapshot{}, fmt.Errorf("invalid pon port %q", p)
		}
		sum, err := s.Run(ctx, "display ont info summary "+p)
		if err != nil {
			return Snapshot{}, err
		}
		opt, err := s.Run(ctx, "display ont optical-info "+p+" all")
		if err != nil {
			return Snapshot{}, err
		}
		onus, rx := parseHuaweiSummary(sum), parseHuaweiOptical(opt)
		for i := range onus {
			if v, ok := rx[onus[i].ontID]; ok {
				onus[i].ONU.RxDBm = v
			}
			snap.ONUs = append(snap.ONUs, onus[i].ONU)
		}
		snap.PONs = append(snap.PONs, PON{Path: p, Status: ponStatus(len(onus))})
	}
	return snap, nil
}

// An observed PON with ONUs listed is "up"; with none we cannot claim down, so it stays unknown.
func ponStatus(n int) string {
	if n > 0 {
		return "up"
	}
	return "unknown"
}

type hwOnt struct {
	ONU
	ontID string
}

func parseHuaweiSummary(out string) []hwOnt {
	var res []hwOnt
	for _, line := range strings.Split(out, "\n") {
		m := hwOntRow.FindStringSubmatch(line)
		if m == nil {
			continue
		}
		status := "unknown"
		switch strings.ToLower(m[4]) {
		case "online":
			status = "online"
		case "offline":
			status = "offline"
		}
		res = append(res, hwOnt{ONU: ONU{Serial: strings.ToUpper(m[3]), PonPath: m[1], Status: status}, ontID: m[2]})
	}
	return res
}

func parseHuaweiOptical(out string) map[string]*float64 {
	res := map[string]*float64{}
	for _, line := range strings.Split(out, "\n") {
		m := hwOpticalRx.FindStringSubmatch(line)
		if m == nil {
			continue
		}
		if m[2] == "-" {
			res[m[1]] = nil
			continue
		}
		if v, err := strconv.ParseFloat(m[2], 64); err == nil && v >= -50 && v <= 10 { // outside range => treat as no reading
			res[m[1]] = &v
		}
	}
	return res
}

func (Huawei) Allowed(cmd string) bool { return HuaweiAllowed(cmd) }
