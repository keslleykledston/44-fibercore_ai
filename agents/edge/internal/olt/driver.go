// Package olt holds read-only OLT drivers. A driver can only ask a ReadOnlySession to run commands, and the
// session refuses anything outside an exact-match allowlist. No driver exposes a write operation (Sprint 3 gate).
package olt

import (
	"context"
	"errors"
	"fmt"
	"regexp"
	"strings"
	"time"
)

var (
	ErrCommandDenied       = errors.New("command not in read-only allowlist")
	ErrUnsupportedFirmware = errors.New("firmware not covered by a homologated fixture")
	// ErrPaginated: the CLI stopped at a "-- More --" prompt. The Edge cannot send keys or disable paging (exec channel, read-only
	// allowlist), so the output is truncated. A truncated list must never be reported as a complete PON.
	ErrPaginated = errors.New("cli output is paginated (truncated)")
)

// paginationMarker matches the pager prompts of the supported CLIs, e.g. "---- More ( Press 'Q' to break ) ----" (VRP),
// "--More--" (ZXROS and most others) and "press any key to continue".
var paginationMarker = regexp.MustCompile(`(?i)-{2,}\s*more\b|\bpress\s+'?q'?\s+to\s+break\b|\bpress\s+any\s+key\b`)

// Paginated reports whether CLI output ends in (or contains) a pager prompt.
func Paginated(out string) bool { return paginationMarker.MatchString(out) }

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
	// Verified: the driver proved IN BAND that the listing is complete (the CLI itself declared how many ONTs the port has and
	// exactly that many rows were parsed). It is what lets an interactive-shell transport, which cannot prove where a command
	// ends, still report a complete PON.
	Verified bool
}

type ONU struct {
	Serial  string
	PonPath string
	Status  string // online|offline|los|dying_gasp|unknown
	RxDBm   *float64
	// LastDownAt: when the OLT itself says the ONU last went down (SNMP only, offline ONUs only); nil = not reported. The OLT's clock may be off by
	// minutes: it is good for "hours offline", not for correlating with other systems to the second.
	LastDownAt *time.Time
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
	// Real capture exists (testdata/huawei_ma5608t) but covers ONE PON (12 ONTs, online/offline only). It stays "identified"
	// until the promotion checklist in DRIVER_SDK_INTERFACE.md is met: an empty PON, a PON that pages several times, a second
	// slot, and the offline causes (LOS/dying-gasp). Until then no PON of this firmware can be reported complete.
	{"huawei", "MA5608T", "MA5600V800R015", LevelIdentified,
		"real capture 2026-10-28 (testdata/huawei_ma5608t/MA5600V800R015C00), single PON 0/0/14; NOT enough to declare observed"},
	// Identity seen over SNMP carries only the family/release (ifDescr "Huawei-MA5600-V800R015-GPON_UNI"). Same evidence and
	// same limits as the CLI entry above: stays identified.
	{"huawei", "MA5600", "MA5600V800R015", LevelIdentified, "SNMP identity (family+release); see MA5608T entry"},
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
	out, err := r.Inner.Run(ctx, cmd)
	if err != nil {
		return "", err
	}
	if Paginated(out) {
		return "", fmt.Errorf("%w: %q", ErrPaginated, cmd)
	}
	return out, nil
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

// EndProver is implemented by transports whose command end is NOT unambiguous. SSH exec ends with EOF + exit status, but an
// interactive shell only infers the end from a prompt the device itself controls, and no fixed silence proves nothing more
// follows. Such transports must never let a PON be declared complete on their own.
type EndProver interface{ EndProven() bool }

// EndProven reports whether the transport delivers an unambiguous end of command (true for transports that do not say).
func EndProven(s Session) bool {
	if p, ok := s.(EndProver); ok {
		return p.EndProven()
	}
	return true
}
