package oltsecrets

import (
	"bytes"
	"encoding/json"
	"errors"
	"log/slog"
	"strings"

	"github.com/keslleykledston/44-fibercore_ai/agents/edge/internal/config"
	"github.com/keslleykledston/44-fibercore_ai/agents/edge/internal/managedolts"
)

// StaticOLT is an OLT of the static configuration (config.json olts[]). The Cloud never overrides one: a name, a device or a Cloud id that is already a static OLT's
// is a name_conflict.
type StaticOLT struct {
	Name      string
	DeviceKey string // config.DeviceKey of its address
	CloudID   string // olts[].cloud_id; may be empty
}

// Managed is what the Processor needs to accept the olt_connection kind (ADR-0046 D4/D6).
type Managed struct {
	Policy *managedolts.Policy
	Store  *managedolts.Store
	Static []StaticOLT
}

func (p *Processor) isStatic(name string) bool {
	if _, ok := p.Targets[name]; ok {
		return true
	}
	if p.Managed != nil {
		for _, s := range p.Managed.Static {
			if s.Name == name {
				return true
			}
		}
	}
	return false
}

// credentialTarget finds the credentials file a ssh_login / snmp_community delivery is for: the static OLT's credentials_file, or the automatic file of a managed OLT
// that is already in the registry (whatever its trust state: the credential is stored, and never USED before the local trust). Neither => target_not_configured.
func (p *Processor) credentialTarget(name, kind string) (path, code string) {
	if tgt, ok := p.Targets[name]; ok {
		if tgt.Path == "" || (tgt.Accepts != nil && !tgt.Accepts(kind)) {
			return "", CodeTargetNotConfigured
		}
		return tgt.Path, ""
	}
	if p.Managed == nil || p.Managed.Store == nil || p.isStatic(name) { // a static OLT without credentials_file does not take credentials from the Cloud
		return "", CodeTargetNotConfigured
	}
	it, found, err := p.Managed.Store.Get(name)
	if err != nil {
		p.logf().Error("olt secret delivery not applied: the managed registry is unreadable", "code", CodeStateUnreadable, "err", err)
		return "", CodeStateUnreadable
	}
	if !found {
		return "", CodeTargetNotConfigured
	}
	if (kind == config.KindSSHLogin && it.Entry.Transport != managedolts.TransportCLI) || (kind == config.KindSNMPCommunity && it.Entry.Transport != managedolts.TransportSNMP) {
		return "", CodeTargetNotConfigured // a credential the entry would never use is refused, not "applied" (same rule as the static entries)
	}
	return p.Managed.Store.CredsPath(name), ""
}

// connection is the validated plaintext of an olt_connection delivery.
type connection struct {
	Action string // set | remove
	Entry  managedolts.Entry
	// CloudID is the only field a remove carries (it is also Entry.CloudID for a set).
	CloudID string
}

const (
	actionSet    = "set"
	actionRemove = "remove"
)

var (
	setKeys    = []string{"kind", "action", "address", "port", "protocol", "vendor", "transport", "snmp_port", "host_key_sha256", "legacy_ssh", "ssh_mode", "cloud_id"}
	setNeeded  = []string{"kind", "action", "address", "port", "protocol", "vendor", "transport", "host_key_sha256", "cloud_id"} // snmp_port, legacy_ssh and ssh_mode may be absent or null
	removeKeys = []string{"kind", "action", "cloud_id"}
)

func hasKey(l []string, k string) bool {
	for _, x := range l {
		if x == k {
			return true
		}
	}
	return false
}

// parseConnection validates the plaintext of an olt_connection delivery (ADR-0046 D4/D6). It returns a failure code (never the offending value). Fields beyond those of the
// ADR, a missing required one, a wrong type or a malformed value are invalid_payload; a protocol other than "ssh" (telnet included) is protocol_not_supported.
func parseConnection(pt []byte, name string) (*connection, string) {
	var raw map[string]json.RawMessage
	if json.Unmarshal(pt, &raw) != nil || raw == nil {
		return nil, CodeInvalidPayload
	}
	get := func(k string, into any) bool {
		v, ok := raw[k]
		if !ok || string(bytes.TrimSpace(v)) == "null" {
			return false
		}
		dec := json.NewDecoder(bytes.NewReader(v))
		dec.DisallowUnknownFields()
		return dec.Decode(into) == nil && !dec.More()
	}
	var kind, action string
	if !get("kind", &kind) || kind != config.KindOLTConnection || !get("action", &action) || (action != actionSet && action != actionRemove) {
		return nil, CodeInvalidPayload
	}
	c := &connection{Action: action}
	if action == actionRemove {
		for k := range raw {
			if !hasKey(removeKeys, k) {
				return nil, CodeInvalidPayload
			}
		}
		if !get("cloud_id", &c.CloudID) {
			return nil, CodeInvalidPayload
		}
		c.CloudID = strings.ToLower(c.CloudID)
		if !managedolts.ValidCloudID(c.CloudID) {
			return nil, CodeInvalidPayload
		}
		c.Entry = managedolts.Entry{Name: name, CloudID: c.CloudID}
		return c, ""
	}
	// protocol first: a Telnet proposal is a clear "not supported", whatever else it lacks (it has no host key to carry)
	var protocol string
	if !get("protocol", &protocol) {
		return nil, CodeInvalidPayload
	}
	if protocol != managedolts.ProtocolSSH {
		return nil, CodeProtocolNotSupported
	}
	for k := range raw {
		if !hasKey(setKeys, k) {
			return nil, CodeInvalidPayload
		}
	}
	for _, k := range setNeeded {
		if v, ok := raw[k]; !ok || string(bytes.TrimSpace(v)) == "null" {
			return nil, CodeInvalidPayload
		}
	}
	e := managedolts.Entry{Name: name, Protocol: protocol, SNMPPort: managedolts.DefaultSNMPPort, SSHMode: managedolts.ModeExec}
	var addr string
	ok := get("address", &addr) && get("port", &e.Port) && get("vendor", &e.Vendor) && get("transport", &e.Transport) && get("host_key_sha256", &e.HostKeySHA256) && get("cloud_id", &e.CloudID)
	if !ok {
		return nil, CodeInvalidPayload
	}
	if v, present := raw["snmp_port"]; present && string(bytes.TrimSpace(v)) != "null" && !get("snmp_port", &e.SNMPPort) {
		return nil, CodeInvalidPayload
	}
	if v, present := raw["legacy_ssh"]; present && string(bytes.TrimSpace(v)) != "null" && !get("legacy_ssh", &e.LegacySSH) {
		return nil, CodeInvalidPayload
	}
	if v, present := raw["ssh_mode"]; present && string(bytes.TrimSpace(v)) != "null" && !get("ssh_mode", &e.SSHMode) {
		return nil, CodeInvalidPayload
	}
	a, lit := managedolts.ParseLiteral(addr)
	if !lit {
		return nil, CodeInvalidPayload
	}
	e.Address = a.String()
	e.CloudID = strings.ToLower(e.CloudID)
	if e.Validate() != nil {
		return nil, CodeInvalidPayload
	}
	c.Entry, c.CloudID = e, e.CloudID
	return c, ""
}

// checkConnection applies the LOCAL policy and the conflict rules to a `set` (a remove only has the static-name rule). Order: a name that is a static OLT's, vendor, legacy,
// address (special addresses, then the CIDRs), port, the same device / Cloud id already in use, and the maximum.
func (p *Processor) checkConnection(c *connection) string {
	m := p.Managed
	if p.isStatic(c.Entry.Name) {
		return CodeNameConflict // the static OLT wins; the Cloud never overrides it (not even to remove it)
	}
	if c.Action == actionRemove {
		return ""
	}
	if code := m.Policy.Check(c.Entry); code != "" {
		return code
	}
	reg, err := m.Store.List()
	if err != nil && !errors.Is(err, managedolts.ErrState) {
		return CodeWriteFailed
	}
	if err != nil { // an unreadable registry: nothing can be decided about it, and nothing is written over it
		p.logf().Error("olt secret delivery not applied: the managed registry is unreadable", "code", CodeStateUnreadable, "err", err)
		return CodeStateUnreadable
	}
	exists := false
	for _, s := range m.Static {
		if s.DeviceKey == c.Entry.DeviceKey() || (s.CloudID != "" && s.CloudID == c.Entry.CloudID) {
			return CodeNameConflict // the same physical device, or the same Cloud id, is already a static OLT
		}
	}
	for _, it := range reg {
		if it.Entry.Name == c.Entry.Name {
			exists = true
			continue
		}
		if it.Entry.DeviceKey() == c.Entry.DeviceKey() || it.Entry.CloudID == c.Entry.CloudID {
			return CodeNameConflict // another managed OLT already is this device / this Cloud id
		}
	}
	if !exists && len(m.Static)+len(reg)+1 > m.Policy.Max {
		return CodeTooManyOLTs
	}
	return ""
}

// writeConnection is step (4) of an olt_connection: the registry (and the trust that must not survive a change), or the removal of registry, trust and credentials.
func (p *Processor) writeConnection(c *connection, log *slog.Logger) string {
	st := p.Managed.Store
	if c.Action == actionRemove {
		if _, err := st.Remove(c.Entry.Name); err != nil {
			code := CodeWriteFailed
			if errors.Is(err, managedolts.ErrState) {
				code = CodeStateUnreadable
			}
			log.Error("olt secret delivery not applied: the managed OLT could not be deleted", "code", code, "err", err)
			return code
		}
		return ""
	}
	res, err := st.Upsert(c.Entry)
	if err != nil {
		code := CodeWriteFailed
		if errors.Is(err, managedolts.ErrState) {
			code = CodeStateUnreadable
		}
		log.Error("olt secret delivery not applied: the managed registry could not be written", "code", code, "err", err)
		return code
	}
	if res.TrustCleared {
		log.Warn("managed olt: a connection field changed; the local trust was cleared (run managed-trust again)")
	}
	return ""
}

// connectionResult is the result to report for an olt_connection that is applied: for a set, `awaiting_local_trust` rides the applied outcome until the local trust exists.
func (p *Processor) connectionResult(name string, c *connection) Result {
	if c.Action == actionSet {
		if it, found, err := p.Managed.Store.Get(name); err == nil && found && !it.Trusted {
			return Result{Outcome: OutcomeApplied, Code: CodeAwaitingLocalTrust}
		}
	}
	return Result{Outcome: OutcomeApplied}
}
