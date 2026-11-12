package managedolts

import (
	"crypto/sha256"
	"encoding/hex"
	"errors"
	"net"
	"strconv"
	"strings"
	"unicode"
	"unicode/utf8"
)

// Entry is one OLT the Cloud proposed. Every field is already validated (Validate) before it is stored or used.
type Entry struct {
	Name          string `json:"name"`
	Vendor        string `json:"vendor"`
	Address       string `json:"address"` // IP literal, canonical form
	Port          int    `json:"port"`    // the ssh port
	Protocol      string `json:"protocol"`
	Transport     string `json:"transport"`
	SNMPPort      int    `json:"snmp_port"`
	HostKeySHA256 string `json:"host_key_sha256"`
	LegacySSH     bool   `json:"legacy_ssh"`
	SSHMode       string `json:"ssh_mode"`
	CloudID       string `json:"cloud_id"`
}

// ErrInvalidEntry is every format problem of an entry (the text never repeats a value: a registry file is operator-editable and a delivery is untrusted).
var ErrInvalidEntry = errors.New("managed olt entry is not valid")

// Validate checks the format of every field (not the local policy).
func (e Entry) Validate() error {
	a, ok := ParseLiteral(e.Address)
	switch {
	case !printableName(e.Name):
	case !vendorRe.MatchString(e.Vendor):
	case !ok || a.String() != e.Address:
	case e.Port < 1 || e.Port > 65535 || e.SNMPPort < 1 || e.SNMPPort > 65535:
	case e.Protocol != ProtocolSSH:
	case e.Transport != TransportCLI && e.Transport != TransportSNMP:
	case e.SSHMode != ModeExec && e.SSHMode != ModeShell:
	case !ValidHostKey(e.HostKeySHA256):
	case !ValidCloudID(e.CloudID):
	default:
		return nil
	}
	return ErrInvalidEntry
}

// printableName: 1..128 bytes of valid UTF-8, every rune printable (no control, no format/bidi character: the name is shown to the operator who confirms a trust, so it
// cannot carry an escape sequence or a line break), no space at either end.
func printableName(n string) bool {
	if n == "" || len(n) > 128 || !utf8.ValidString(n) || n != strings.TrimSpace(n) {
		return false
	}
	for _, r := range n {
		if !unicode.IsPrint(r) {
			return false
		}
	}
	return true
}

// DialPort is the port the Edge would actually connect to: the ssh port for the CLI, the SNMP port for SNMP.
func (e Entry) DialPort() int {
	if e.Transport == TransportSNMP {
		return e.SNMPPort
	}
	return e.Port
}

// HostPort is the ip:port the Edge would actually connect to (see DialPort).
func (e Entry) HostPort() string { return net.JoinHostPort(e.Address, strconv.Itoa(e.DialPort())) }

// Digest is the SHA-256 (hex) of the fields that trust is given to: name, address, port, protocol, transport, host key, SNMP port, ssh mode, legacy flag and vendor (the
// vendor picks the driver, i.e. the commands the Edge runs, so a change of it needs a new confirmation too; Codex r1). Trust is stored as this digest, never as a flag in
// the registry: editing the registry by hand cannot make anything trusted, and a change of any of these fields no longer matches the stored digest. Only the Cloud id is left
// out: it never changes where the Edge connects nor what it runs. Fields are length-prefixed, so none can shift into another.
func (e Entry) Digest() string {
	h := sha256.New()
	for _, f := range []string{
		"fibercore-managed-olt-trust-v2", e.Name, e.Address, strconv.Itoa(e.Port), e.Protocol, e.Transport, e.HostKeySHA256,
		strconv.Itoa(e.SNMPPort), e.SSHMode, strconv.FormatBool(e.LegacySSH), e.Vendor,
	} {
		h.Write([]byte(strconv.Itoa(len(f))))
		h.Write([]byte{':'})
		h.Write([]byte(f))
		h.Write([]byte{0})
	}
	return hex.EncodeToString(h.Sum(nil))
}

// DeviceKey is the identity of the physical device behind the address (the same rule as config.DeviceKey, which this package cannot import).
func (e Entry) DeviceKey() string {
	if a, ok := ParseLiteral(e.Address); ok {
		return a.String()
	}
	return strings.ToLower(e.Address)
}
