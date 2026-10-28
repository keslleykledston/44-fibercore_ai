// Package olt holds read-only OLT drivers. A driver can only ask a ReadOnlySession to run commands, and the
// session refuses anything outside an exact-match allowlist. No driver exposes a write operation (Sprint 3 gate).
package olt

import (
	"context"
	"errors"
	"fmt"
	"strings"
)

var (
	ErrCommandDenied       = errors.New("command not in read-only allowlist")
	ErrUnsupportedFirmware = errors.New("firmware not covered by a homologated fixture")
)

// Session runs one CLI command and returns its output.
type Session interface {
	Run(ctx context.Context, cmd string) (string, error)
}

type Identity struct {
	Vendor, Model, Firmware string
}

type PON struct {
	Path   string
	Status string // up|down|unknown
}

type ONU struct {
	Serial  string
	PonPath string
	Status  string // online|offline|los|dying_gasp|unknown
	RxDBm   *float64
}

type Snapshot struct {
	Identity Identity
	PONs     []PON
	ONUs     []ONU
}

// Driver reads inventory. Implementations MUST only issue commands built by their own allowlisted builders.
type Driver interface {
	Vendor() string
	Allowed(cmd string) bool // exact-match allowlist of the read commands this driver may issue
	Identify(ctx context.Context, s Session) (Identity, error)
	Snapshot(ctx context.Context, s Session, ponPorts []string) (Snapshot, error)
}

// Level is the support level the Edge may declare. Parsers validated only against SYNTHETIC fixtures stay at
// "identified": "observed" requires fixtures captured from a real lab device (docs/engineering/DRIVER_SDK_INTERFACE.md).
type Level string

const (
	LevelIdentified Level = "identified"
	LevelObserved   Level = "observed"
)

type Homologation struct {
	Vendor, ModelPrefix, FirmwarePrefix string
	Level                               Level
	Evidence                            string
}

// Registry of firmware families whose output format is covered by a fixture set.
var Registry = []Homologation{
	{"huawei", "MA5800", "R018", LevelIdentified, "synthetic fixtures only (testdata/huawei_ma5800/R018); NOT captured from a device"},
	{"zte", "C300", "V2.1", LevelIdentified, "synthetic fixtures only (testdata/zte_c300/V2.1); NOT captured from a device"},
}

// Lookup returns the level for an identity, or ErrUnsupportedFirmware when the firmware has no fixture coverage.
func Lookup(id Identity) (Level, error) {
	for _, h := range Registry {
		if h.Vendor == strings.ToLower(id.Vendor) && strings.HasPrefix(strings.ToUpper(id.Model), h.ModelPrefix) &&
			strings.HasPrefix(id.Firmware, h.FirmwarePrefix) {
			return h.Level, nil
		}
	}
	return LevelIdentified, fmt.Errorf("%w: %s %s %s", ErrUnsupportedFirmware, id.Vendor, id.Model, id.Firmware)
}

// ReadOnlySession wraps a Session and only forwards commands that match the allowlist EXACTLY after validation.
type ReadOnlySession struct {
	Inner   Session
	Allowed func(cmd string) bool
}

func (r ReadOnlySession) Run(ctx context.Context, cmd string) (string, error) {
	if !SafeCommand(cmd) || !r.Allowed(cmd) {
		return "", fmt.Errorf("%w: %q", ErrCommandDenied, cmd)
	}
	return r.Inner.Run(ctx, cmd)
}

// SafeCommand rejects control characters and shell/CLI chaining metacharacters before any allowlist match.
func SafeCommand(cmd string) bool {
	if cmd == "" || len(cmd) > 128 {
		return false
	}
	for _, c := range cmd {
		if c < 0x20 || c == 0x7f || strings.ContainsRune(";|&`$<>\\\"'!", c) {
			return false
		}
	}
	return cmd == strings.TrimSpace(cmd)
}

// Budget bounds one OLT collection: total commands and bytes across ALL commands (the per-command output cap alone
// would still allow tens of GiB over hundreds of ports). Wrap the session innermost-last: Budget -> ReadOnly -> SSH.
type Budget struct {
	Inner       Session
	MaxCommands int
	MaxBytes    int
	cmds, bytes int
}

var ErrBudget = errors.New("collection budget exhausted")

func NewBudget(inner Session, maxCommands, maxBytes int) *Budget {
	return &Budget{Inner: inner, MaxCommands: maxCommands, MaxBytes: maxBytes}
}

func (b *Budget) Run(ctx context.Context, cmd string) (string, error) {
	if b.cmds >= b.MaxCommands {
		return "", fmt.Errorf("%w: more than %d commands", ErrBudget, b.MaxCommands)
	}
	b.cmds++
	out, err := b.Inner.Run(ctx, cmd)
	if err != nil {
		return "", err
	}
	b.bytes += len(out)
	if b.bytes > b.MaxBytes {
		return "", fmt.Errorf("%w: more than %d bytes", ErrBudget, b.MaxBytes)
	}
	return out, nil
}
