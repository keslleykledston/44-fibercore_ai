// Package managedolts is the Edge side of the OLTs the Cloud adds by signed delivery (ADR-0046 D4/D6): the LOCAL policy (what the Cloud may ask for), the registry
// of the OLTs it proposed, and the LOCAL trust that decides which of them this Edge may ever open a session to.
//
// The Cloud only proposes. An OLT it adds is "awaiting_local_trust": nothing connects, nothing collects and no credential is used until the administrator of
// THIS host runs `fibercore-edge managed-trust <name>` and retypes the SSH host key fingerprint. A change of any connection field zeroes that trust.
package managedolts

import (
	"encoding/base64"
	"errors"
	"fmt"
	"net/netip"
	"regexp"
	"sort"
	"strings"
)

// Violation codes of the ADR-0046 D5 list (the closed list the Cloud knows). They are the SAME strings as the failure codes of the delivery result.
const (
	CodeVendorNotSupported = "vendor_not_supported"
	CodeVendorNotAllowed   = "vendor_not_allowed"
	CodeLegacyNotAllowed   = "legacy_not_allowed"
	CodeAddressNotAllowed  = "address_not_allowed"
	CodePortNotAllowed     = "port_not_allowed"
)

// Protocols, transports and modes of an entry.
const (
	ProtocolSSH   = "ssh"
	TransportCLI  = "cli"
	TransportSNMP = "snmp"
	ModeExec      = "exec"
	ModeShell     = "shell"
	// DefaultSNMPPort is used when the delivery does not carry one.
	DefaultSNMPPort = 161
)

// Limits.
const (
	MaxOLTs        = 64 // total of OLTs of the Edge, static ones included (the same cap config.Validate has always had)
	MaxAllowedPort = 32
	maxPonPorts    = 256
	maxVendors     = 8
	// MinPrefixV4 / MinPrefixV6: a CIDR wider than /8 (IPv4) or /32 (IPv6) is not a management network, it is "everything".
	MinPrefixV4 = 8
	MinPrefixV6 = 32
)

// SupportedVendors are the OLT vendors this Edge build can read. SNMP is implemented for huawei only (config.Validate says the same for the static entries).
var SupportedVendors = []string{"huawei", "zte"}

// VendorSupported says whether this Edge can read that vendor over that transport.
func VendorSupported(vendor, transport string) bool {
	switch vendor {
	case "huawei":
		return true
	case "zte":
		return transport != TransportSNMP
	}
	return false
}

var (
	hostKeyRe = regexp.MustCompile(`^SHA256:[A-Za-z0-9+/]{43}$`)
	ponRe     = regexp.MustCompile(`^\d+/\d+/\d+$`)
	vendorRe  = regexp.MustCompile(`^[a-z0-9_-]{1,32}$`)
	cloudIDRe = regexp.MustCompile(`^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$`)
)

// ValidHostKey: "SHA256:" + the 43 characters of an unpadded base64 SHA-256 (what ssh.FingerprintSHA256 prints), canonical.
func ValidHostKey(s string) bool {
	if !hostKeyRe.MatchString(s) {
		return false
	}
	b, err := base64.RawStdEncoding.Strict().DecodeString(strings.TrimPrefix(s, "SHA256:"))
	return err == nil && len(b) == 32
}

// ValidCloudID: a lower-case UUID (the id of the OLT in the Cloud).
func ValidCloudID(s string) bool { return cloudIDRe.MatchString(s) }

// Config is the `managed_olts` section of config.json. PRESENT = the Cloud may add OLTs inside this policy; ABSENT = it cannot (managed_olts_disabled).
type Config struct {
	// StateDir (0700, owned by the Edge user) holds managed_olts.json, trust.json and creds/. Like the seal key directory, it is created when missing and refused when loose.
	StateDir string `json:"state_dir"`
	// AllowedCIDRs is MANDATORY: where the Cloud may point this Edge. 0.0.0.0/0, ::/0 and anything wider than /8 (IPv4) or /32 (IPv6) are refused.
	AllowedCIDRs []string `json:"allowed_cidrs"`
	// AllowedPorts: the TCP/UDP port the Edge will actually dial (ssh port for transport cli, snmp_port for snmp). Empty = [22].
	AllowedPorts []int `json:"allowed_ports"`
	// MaxOLTs: the most OLTs this Edge will carry in total, the static ones of config.json included (1..64).
	MaxOLTs int `json:"max_olts"`
	// AllowLegacySSH lets the Cloud ask for the old SSH algorithm set on a managed OLT. Default false.
	AllowLegacySSH bool `json:"allow_legacy_ssh"`
	// AllowedVendors: empty = every vendor this build supports.
	AllowedVendors []string `json:"allowed_vendors"`
	// PonPorts: the PON ports the Edge reads on EVERY managed OLT (e.g. "0/1/0"). The delivery of ADR-0046 does not carry PON ports, so the administrator of this host
	// names them here. Empty = managed OLTs are accepted and trusted but not collected (the log says so).
	PonPorts []string `json:"pon_ports"`
}

// Policy is the parsed form of Config. Immutable after NewPolicy.
type Policy struct {
	CIDRs    []netip.Prefix
	Ports    map[int]bool
	Max      int
	Legacy   bool
	Vendors  map[string]bool
	PonPorts []string
}

// CheckCIDR validates one allowed CIDR of the configuration and returns its masked form.
func CheckCIDR(s string) (netip.Prefix, error) {
	p, err := netip.ParsePrefix(strings.TrimSpace(s))
	if err != nil {
		return netip.Prefix{}, fmt.Errorf("allowed_cidrs: %q is not a CIDR", s)
	}
	if p.Addr().Zone() != "" || p.Addr().Is4In6() {
		return netip.Prefix{}, fmt.Errorf("allowed_cidrs: %q must be a plain IPv4 or IPv6 network (no zone, no IPv4-mapped form)", s)
	}
	if (p.Addr().Is4() && p.Bits() < MinPrefixV4) || (p.Addr().Is6() && p.Bits() < MinPrefixV6) {
		return netip.Prefix{}, fmt.Errorf("allowed_cidrs: %q is wider than /%d (IPv4) or /%d (IPv6): name the management network of the OLTs, not a whole range", s, MinPrefixV4, MinPrefixV6)
	}
	return p.Masked(), nil
}

// NewPolicy validates the section and builds the policy. Every problem is reported (joined).
func NewPolicy(c Config) (*Policy, error) {
	var errs []error
	p := &Policy{Ports: map[int]bool{}, Vendors: map[string]bool{}, Max: c.MaxOLTs, Legacy: c.AllowLegacySSH}
	if len(c.AllowedCIDRs) == 0 {
		errs = append(errs, errors.New("managed_olts.allowed_cidrs is required (the networks the Cloud may point this Edge at)"))
	}
	for _, s := range c.AllowedCIDRs {
		if pr, err := CheckCIDR(s); err != nil {
			errs = append(errs, fmt.Errorf("managed_olts.%w", err))
		} else {
			p.CIDRs = append(p.CIDRs, pr)
		}
	}
	ports := c.AllowedPorts
	if len(ports) == 0 {
		ports = []int{22}
	}
	if len(ports) > MaxAllowedPort {
		errs = append(errs, fmt.Errorf("managed_olts.allowed_ports: at most %d ports", MaxAllowedPort))
	}
	for _, n := range ports {
		if n < 1 || n > 65535 {
			errs = append(errs, fmt.Errorf("managed_olts.allowed_ports: %d is not a port (1..65535)", n))
			continue
		}
		p.Ports[n] = true
	}
	if c.MaxOLTs < 1 || c.MaxOLTs > MaxOLTs {
		errs = append(errs, fmt.Errorf("managed_olts.max_olts must be between 1 and %d (the total of OLTs of this Edge, the static ones included)", MaxOLTs))
	}
	if len(c.AllowedVendors) > maxVendors {
		errs = append(errs, errors.New("managed_olts.allowed_vendors: too many entries"))
	}
	for _, v := range c.AllowedVendors {
		if !vendorRe.MatchString(v) || !contains(SupportedVendors, v) {
			errs = append(errs, fmt.Errorf("managed_olts.allowed_vendors: %q is not a vendor this Edge supports (%s)", v, strings.Join(SupportedVendors, ", ")))
			continue
		}
		p.Vendors[v] = true
	}
	if len(c.AllowedVendors) == 0 {
		for _, v := range SupportedVendors {
			p.Vendors[v] = true
		}
	}
	if len(c.PonPorts) > maxPonPorts {
		errs = append(errs, errors.New("managed_olts.pon_ports: at most 256 entries"))
	}
	seen := map[string]bool{}
	for _, pp := range c.PonPorts {
		if !ponRe.MatchString(pp) {
			errs = append(errs, fmt.Errorf("managed_olts.pon_ports: invalid pon port %q", pp))
			continue
		}
		if !seen[pp] {
			seen[pp] = true
			p.PonPorts = append(p.PonPorts, pp)
		}
	}
	if err := errors.Join(errs...); err != nil {
		return nil, err
	}
	return p, nil
}

func contains(l []string, s string) bool {
	for _, x := range l {
		if x == s {
			return true
		}
	}
	return false
}

// SpecialAddress says whether an address is never a management address, whatever the CIDRs say: loopback, multicast, link-local, unspecified, the IPv4 "this network"
// block and the limited broadcast.
func SpecialAddress(a netip.Addr) bool {
	if a.IsLoopback() || a.IsMulticast() || a.IsLinkLocalUnicast() || a.IsLinkLocalMulticast() || a.IsInterfaceLocalMulticast() || a.IsUnspecified() {
		return true
	}
	if a.Is4() {
		b := a.As4()
		return b[0] == 0 || a == netip.AddrFrom4([4]byte{255, 255, 255, 255})
	}
	return false
}

// ParseLiteral parses an IP literal in its plain form: no zone, no IPv4-mapped IPv6. ok=false means "not an acceptable literal" (a host name, a scoped or mapped address).
func ParseLiteral(s string) (netip.Addr, bool) {
	a, err := netip.ParseAddr(s)
	if err != nil || a.Zone() != "" || a.Is4In6() {
		return netip.Addr{}, false
	}
	return a, true
}

// Check applies the policy to a (format-valid) entry and returns the code of the first violation, or "". Order: vendor, legacy, address, port.
func (p *Policy) Check(e Entry) string {
	if !VendorSupported(e.Vendor, e.Transport) {
		return CodeVendorNotSupported
	}
	if !p.Vendors[e.Vendor] {
		return CodeVendorNotAllowed
	}
	if e.LegacySSH && !p.Legacy {
		return CodeLegacyNotAllowed
	}
	a, ok := ParseLiteral(e.Address)
	if !ok || SpecialAddress(a) {
		return CodeAddressNotAllowed
	}
	in := false
	for _, c := range p.CIDRs {
		if c.Contains(a) {
			in = true
			break
		}
	}
	if !in {
		return CodeAddressNotAllowed
	}
	if !p.Ports[e.DialPort()] {
		return CodePortNotAllowed
	}
	return ""
}

// SortedPorts lists the allowed ports (for messages).
func (p *Policy) SortedPorts() []int {
	var l []int
	for n := range p.Ports {
		l = append(l, n)
	}
	sort.Ints(l)
	return l
}
