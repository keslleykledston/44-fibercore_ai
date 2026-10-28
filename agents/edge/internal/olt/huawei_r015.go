package olt

import (
	"context"
	"fmt"
	"regexp"
	"strconv"
	"strings"
)

// Huawei SmartAX MA5600 family, firmware MA5600V800R015 (validated against a real MA5608T, see testdata/huawei_ma5608t).
// ONT commands only exist inside the GPON interface context (config -> interface gpon F/S), so this profile walks the CLI
// modes. Everything stays read-only: the allowlist below is the exact set of commands this profile may send.
var (
	hwR015Allowed = regexp.MustCompile(`^(enable|config|quit|interface gpon \d+/\d+|display board 0|display ont info \d+ all|display ont optical-info \d+ all)$`)

	// "  0/ 0/14   7  4857544310001A2B  active      online   normal   match    no"
	r015OntRow = regexp.MustCompile(`^\s*(\d+)/\s*(\d+)/\s*(\d+)\s+(\d+)\s+([0-9A-Fa-f]{16})\s+(\S+)\s+(\S+)\s+(\S+)\s+(\S+)\s+(\S+)\s*$`)
	// "    7  -13.28      2.38        -12.30      39           3.300       10"
	r015Optical = regexp.MustCompile(`^\s*(\d+)\s+(-?\d+(?:\.\d+)?|-)\s+(?:-?\d+(?:\.\d+)?|-)\s+(?:-?\d+(?:\.\d+)?|-)\s+\S+\s+\S+\s+\S+\s*$`)
	// "  In port 0/ 0/14, the total of ONTs are: 12, online: 3"
	r015Total = regexp.MustCompile(`(?m)^\s*In port\s+(\d+)/\s*(\d+)/\s*(\d+)\s*,\s*the total of ONTs are:\s*(\d+)\s*,\s*online:\s*(\d+)\s*$`)
	// device-side rejection of a command
	r015CLIError = regexp.MustCompile(`(?m)^\s*%\s|Unknown command|Parameter error|Too many parameters|Incomplete command`)
)

func isMA56(id Identity) bool { return strings.HasPrefix(strings.ToUpper(id.Model), "MA56") }

// HuaweiR015 is selected by the OLT config (profile "huawei_ma56_r015"). Its allowlist includes the CLI mode commands
// (enable, config, interface gpon F/S, quit) that the generic Huawei driver must never be able to send.
type HuaweiR015 struct{ Huawei }

func (HuaweiR015) Allowed(cmd string) bool {
	return HuaweiAllowed(cmd) || hwR015Allowed.MatchString(cmd)
}

func (h HuaweiR015) Snapshot(ctx context.Context, s Session, ports []string) (Snapshot, error) {
	id, err := h.Identify(ctx, s)
	if err != nil {
		return Snapshot{}, err
	}
	if !isMA56(id) {
		return Snapshot{}, fmt.Errorf("huawei_ma56_r015 profile on %s %s", id.Model, id.Firmware)
	}
	return h.snapshotR015(ctx, s, id, ports)
}

type r015Port struct {
	path, f, s, p string
}

func (h Huawei) snapshotR015(ctx context.Context, s Session, id Identity, ports []string) (Snapshot, error) {
	var order []string
	bySlot := map[string][]r015Port{}
	for _, p := range ports {
		if !hwPort.MatchString(p) {
			return Snapshot{}, fmt.Errorf("invalid pon port %q", p)
		}
		f := strings.Split(p, "/")
		slot := f[0] + "/" + f[1]
		if _, ok := bySlot[slot]; !ok {
			order = append(order, slot)
		}
		bySlot[slot] = append(bySlot[slot], r015Port{path: p, f: f[0], s: f[1], p: f[2]})
	}
	run := func(cmd string) (string, error) {
		out, err := s.Run(ctx, cmd)
		if err != nil {
			return "", err
		}
		if r015CLIError.MatchString(out) {
			return "", fmt.Errorf("huawei r015: device rejected %q", cmd)
		}
		return out, nil
	}
	snap := Snapshot{Identity: id}
	if len(ports) == 0 {
		return snap, nil
	}
	// Mode changes only: enable (privileged view) and config (the context ONT displays live in). No setting is touched.
	for _, c := range []string{"enable", "config"} {
		if _, err := run(c); err != nil {
			return Snapshot{}, err
		}
	}
	for _, slot := range order {
		if _, err := run("interface gpon " + slot); err != nil {
			return Snapshot{}, err
		}
		for _, pt := range bySlot[slot] {
			info, err := run("display ont info " + pt.p + " all")
			if err != nil {
				return Snapshot{}, err
			}
			opt, err := run("display ont optical-info " + pt.p + " all")
			if err != nil {
				return Snapshot{}, err
			}
			onus, pon := parseR015Port(pt, info, opt)
			snap.ONUs = append(snap.ONUs, onus...)
			snap.PONs = append(snap.PONs, pon)
		}
		if _, err := run("quit"); err != nil { // back to config; only ever sent from inside interface gpon
			return Snapshot{}, err
		}
	}
	return snap, nil
}

// parseR015Port builds the ONUs of one PON and decides whether the listing is provably complete: the CLI footer must name
// THIS port, the parsed rows must be exactly the declared total (unique ONT-IDs, all on this port, known run states) and the
// online rows must match the declared online count. Anything else leaves Verified=false.
func parseR015Port(pt r015Port, info, optical string) ([]ONU, PON) {
	var onus []ONU
	ids := map[string]bool{}
	online, clean := 0, true
	rx := map[string]*float64{}
	for _, line := range strings.Split(optical, "\n") {
		if m := r015Optical.FindStringSubmatch(line); m != nil && m[2] != "-" {
			if v, err := strconv.ParseFloat(m[2], 64); err == nil && v >= -50 && v <= 10 { // outside range => no reading
				rx[m[1]] = &v
			}
		}
	}
	for _, line := range strings.Split(info, "\n") {
		m := r015OntRow.FindStringSubmatch(line)
		if m == nil {
			continue
		}
		if m[1]+"/"+m[2]+"/"+m[3] != pt.path || ids[m[4]] {
			clean = false
			continue
		}
		ids[m[4]] = true
		status := "unknown"
		switch strings.ToLower(m[7]) { // Run state
		case "online":
			status, online = "online", online+1
		case "offline":
			status = "offline"
		default:
			clean = false
		}
		u := ONU{Serial: strings.ToUpper(m[5]), PonPath: pt.path, Status: status}
		if v, ok := rx[m[4]]; ok && status == "online" { // an offline ONT may show a stale reading
			u.RxDBm = v
		}
		onus = append(onus, u)
	}
	verified := false
	if t := r015Total.FindStringSubmatch(info); t != nil && clean && len(r015Total.FindAllString(info, -1)) == 1 {
		total, _ := strconv.Atoi(t[4])
		on, _ := strconv.Atoi(t[5])
		verified = t[1]+"/"+t[2]+"/"+t[3] == pt.path && total == len(onus) && on == online
	}
	return onus, PON{Path: pt.path, Status: ponStatus(len(onus)), Verified: verified}
}
