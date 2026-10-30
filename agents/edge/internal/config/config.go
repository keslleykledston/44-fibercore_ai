// Package config loads and validates the Edge configuration. Security-relevant values (NBI URL,
// allowlist, secrets) come ONLY from this local file, never from the Cloud (anti-SSRF).
package config

import (
	"encoding/json"
	"errors"
	"fmt"
	"net"
	"net/url"
	"os"
	"path/filepath"
	"regexp"
	"strings"
	"time"

	"github.com/keslleykledston/44-fibercore_ai/agents/edge/internal/olt"
)

type Config struct {
	GatewayURL       string       `json:"gateway_url"`
	EdgeID           string       `json:"edge_id"`
	TenantID         string       `json:"tenant_id"`
	ClientID         string       `json:"client_id"`
	SecretFile       string       `json:"secret_file"` // file with the service-account secret, mode 0600
	ConnectorID      string       `json:"connector_id"`
	NBIURL           string       `json:"nbi_url"`
	NBISecretFile    string       `json:"nbi_secret_file"` // optional: NBI Basic credentials "user:pass", mode 0600
	Allowlist        []string     `json:"allowlist"`       // host:port the Edge may connect to (NBI, gateway excluded)
	QueuePath        string       `json:"queue_path"`
	HeartbeatSeconds int          `json:"heartbeat_seconds"`
	CollectSeconds   int          `json:"collect_seconds"`
	AllowInsecureDev bool         `json:"allow_insecure_dev"` // permits http:// gateway ONLY on loopback
	OLTs             []OLTConfig  `json:"olts"`
	JobsEnabled      bool         `json:"jobs_enabled"`       // poll the Cloud for signed read-only jobs
	JobPublicKey     string       `json:"job_public_key"`     // base64 Ed25519 public key of the Cloud, pinned locally
	AllowedOps       []string     `json:"allowed_operations"` // narrows the compile-time read-only set (collect, refresh)
	Bench            *BenchConfig `json:"bench"`              // ADR-0030: closed list of bench devices that may receive homologated writes (nil = none)
	RefreshTasks     bool         `json:"refresh_tasks"`      // ADR-SD-002 item 4: let signed refresh jobs ask the ACS to read ONE CPE (needs nbi_url + jobs_enabled)
	Version          string       `json:"-"`
}

// BenchConfig is the Edge's own, independent copy of the bench list (ADR-0030): the Cloud can name a device, never add one here.
type BenchConfig struct {
	Enabled bool `json:"bench_writes_enabled"`
	// Pacing of bench writes per device. 0 = the defaults (30 min, 2 per hour). Homologation may lower them; never below the floors below.
	MinIntervalSeconds int                 `json:"min_interval_seconds"`
	MaxPerHour         int                 `json:"max_per_hour"`
	Devices            []BenchDeviceConfig `json:"devices"`
	// OLT is the bench ONU for the H4 maneuvers (onu_reset, onu_deactivate): the ONLY ONU they may touch. Port and ONT-ID live here, never in the Cloud.
	OLT *BenchOLTConfig `json:"olt"`
}

// BenchOLTConfig names the OLT (one of `olts`, CLI transport) and the position of the bench ONU on it.
type BenchOLTConfig struct {
	Name          string `json:"name"`
	Frame         int    `json:"frame"`
	Slot          int    `json:"slot"`
	Port          int    `json:"port"`
	OntID         int    `json:"ont_id"`
	GPONSerial    string `json:"gpon_serial"`     // 16 hex, must equal the serial of one bench device
	MinGapSeconds int    `json:"min_gap_seconds"` // between two OLT sessions (any kind); 0 = 900 (15 min); floor 60
	WaitSeconds   int    `json:"wait_seconds"`    // how long to watch the ONU come back; 0 = 240; 30..600
}

// BenchDeviceConfig: the ACS identity (the three parts of the GenieACS _id) of one bench device, in clear: it is checked against the ACS.
type BenchDeviceConfig struct {
	OUI          string `json:"oui"`
	ProductClass string `json:"product_class"`
	Serial       string `json:"serial"`
}

// ID is the GenieACS _id form of the device.
func (d BenchDeviceConfig) ID() string { return d.OUI + "-" + d.ProductClass + "-" + d.Serial }

// OLTConfig describes one OLT the Edge may READ. Its address must also be listed in `allowlist`.
type OLTConfig struct {
	Name                    string   `json:"name"`
	Vendor                  string   `json:"vendor"` // huawei | zte
	Address                 string   `json:"address"`
	Username                string   `json:"username"`
	SecretFile              string   `json:"secret_file"`
	HostKeySHA256           string   `json:"host_key_sha256"` // mandatory pinned SSH host key
	PonPorts                []string `json:"pon_ports"`
	AllowUnverifiedFirmware bool     `json:"allow_unverified_firmware"`
	Transport               string   `json:"transport"`           // "" | "cli" (SSH, default) | "snmp" (v2c, read-only)
	SNMPAddress             string   `json:"snmp_address"`        // ip:161 - an IP LITERAL that is also in `allowlist`
	SNMPCommunityFile       string   `json:"snmp_community_file"` // file (mode 0600) holding the read-only v2c community
	SNMPPaceMillis          int      `json:"snmp_pace_ms"`        // pause before every SNMP request (0 = 1000; minimum 1000): the OLT agent rate-limits
	SNMPMaxRequests         int      `json:"snmp_max_requests"`   // SNMP packets per collection cycle (default 400, max 1000)
	SSHMode                 string   `json:"ssh_mode"`            // "" | "exec" (default) | "shell" (interactive pty; firmwares that ignore exec)
	SSHPagerSpace           bool     `json:"ssh_pager_space"`     // shell mode: answer the VRP "---- More ----" pager with a single Space
	Profile                 string   `json:"profile"`             // "" | "huawei_ma56_r015" (CLI-mode profile for the MA5600 family)
	CollectSeconds          int      `json:"collect_seconds"`     // minimum seconds between two collections of THIS olt (0 = default: 900 for cli, every cycle for snmp)
	CooldownSeconds         int      `json:"cooldown_seconds"`    // seconds to leave this olt alone after a failure (0 = default: 900 cli, 300 snmp)
	LegacySSH               bool     `json:"legacy_ssh"`          // explicit per-OLT opt-in to old SSH algorithms (SHA1 DH, ssh-rsa, AES-CBC)
}

var ponRe = regexp.MustCompile(`^\d+/\d+/\d+$`)

var uuidRe = regexp.MustCompile(`^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$`)

func Load(path, version string) (*Config, error) {
	if err := RequirePrivate(path); err != nil {
		return nil, err
	}
	b, err := os.ReadFile(path)
	if err != nil {
		return nil, err
	}
	var c Config
	dec := json.NewDecoder(strings.NewReader(string(b)))
	dec.DisallowUnknownFields()
	if err := dec.Decode(&c); err != nil {
		return nil, fmt.Errorf("config: %w", err)
	}
	c.Version = version
	if c.HeartbeatSeconds == 0 {
		c.HeartbeatSeconds = 30
	}
	if c.CollectSeconds == 0 {
		c.CollectSeconds = 300
	}
	return &c, c.Validate()
}

func (c *Config) Validate() error {
	var errs []error
	for name, v := range map[string]string{"edge_id": c.EdgeID, "tenant_id": c.TenantID, "client_id": c.ClientID} {
		if !uuidRe.MatchString(v) {
			errs = append(errs, fmt.Errorf("%s must be a UUID", name))
		}
	}
	gw, err := url.Parse(c.GatewayURL)
	if err != nil || gw.Host == "" {
		errs = append(errs, errors.New("gateway_url invalid"))
	} else if gw.Scheme != "https" {
		host, _, _ := net.SplitHostPort(gw.Host)
		if host == "" {
			host = gw.Host
		}
		ip := net.ParseIP(host)
		if !(gw.Scheme == "http" && c.AllowInsecureDev && (host == "localhost" || (ip != nil && ip.IsLoopback()))) {
			errs = append(errs, errors.New("gateway_url must be https (http allowed only for loopback with allow_insecure_dev)"))
		}
	}
	if c.SecretFile == "" || c.QueuePath == "" || c.ConnectorID == "" {
		errs = append(errs, errors.New("secret_file, queue_path and connector_id are required"))
	}
	if c.NBIURL != "" {
		u, err := url.Parse(c.NBIURL)
		if err != nil || u.Host == "" || (u.Scheme != "http" && u.Scheme != "https") {
			errs = append(errs, errors.New("nbi_url invalid"))
		}
	}
	if c.RefreshTasks && (c.NBIURL == "" || !c.JobsEnabled) {
		errs = append(errs, errors.New("refresh_tasks requires nbi_url and jobs_enabled (active reads only run from signed jobs)"))
	}
	if c.Bench != nil && c.Bench.Enabled {
		b := c.Bench
		switch {
		case !c.JobsEnabled || c.NBIURL == "":
			errs = append(errs, errors.New("bench.bench_writes_enabled requires jobs_enabled and nbi_url"))
		case len(b.Devices) < 1 || len(b.Devices) > 4:
			errs = append(errs, errors.New("bench.devices must list 1 to 4 devices"))
		}
		if b.MinIntervalSeconds != 0 && (b.MinIntervalSeconds < BenchMinIntervalFloor || b.MinIntervalSeconds > 1800) {
			errs = append(errs, fmt.Errorf("bench.min_interval_seconds must be 0 (30 min) or between %d and 1800", BenchMinIntervalFloor))
		}
		if b.MaxPerHour < 0 || b.MaxPerHour > 20 {
			errs = append(errs, errors.New("bench.max_per_hour must be 0 (2) or between 1 and 20"))
		}
		if o := b.OLT; o != nil {
			cli := false
			for _, x := range c.OLTs {
				cli = cli || (x.Name == o.Name && x.Transport != "snmp")
			}
			serialOK := false
			for _, d := range b.Devices {
				serialOK = serialOK || strings.EqualFold(d.Serial, o.GPONSerial)
			}
			switch {
			case !cli:
				errs = append(errs, errors.New("bench.olt.name must be one of the configured olts with CLI transport"))
			case o.Frame < 0 || o.Frame > 7 || o.Slot < 0 || o.Slot > 21 || o.Port < 0 || o.Port > 15 || o.OntID < 0 || o.OntID > 127:
				errs = append(errs, errors.New("bench.olt frame/slot/port/ont_id out of range"))
			case !gponSerialRe.MatchString(o.GPONSerial) || !serialOK:
				errs = append(errs, errors.New("bench.olt.gpon_serial must be 16 upper-case hex and equal to the serial of a bench device"))
			case o.MinGapSeconds != 0 && (o.MinGapSeconds < BenchMinIntervalFloor || o.MinGapSeconds > 3600):
				errs = append(errs, fmt.Errorf("bench.olt.min_gap_seconds must be 0 (15 min) or between %d and 3600", BenchMinIntervalFloor))
			case o.WaitSeconds != 0 && (o.WaitSeconds < 30 || o.WaitSeconds > 600):
				errs = append(errs, errors.New("bench.olt.wait_seconds must be 0 (240) or between 30 and 600"))
			}
		}
		oltOps := false
		for _, o := range c.AllowedOps {
			oltOps = oltOps || o == "onu_reset" || o == "onu_deactivate"
		}
		if oltOps && b.OLT == nil {
			errs = append(errs, errors.New("onu_reset/onu_deactivate in allowed_operations need bench.olt"))
		}
		ids := map[string]bool{}
		for _, d := range b.Devices {
			if !benchPartRe.MatchString(d.OUI) || !benchPartRe.MatchString(d.ProductClass) || !benchPartRe.MatchString(d.Serial) || ids[d.ID()] {
				errs = append(errs, errors.New("bench.devices: oui, product_class and serial are required (letters, digits, . _ only) and unique"))
				break
			}
			ids[d.ID()] = true
		}
		ok := false
		for _, o := range c.AllowedOps {
			ok = ok || o == "reboot_cpe" || o == "set_wifi_ssid" || o == "onu_reset" || o == "onu_deactivate"
		}
		if !ok {
			errs = append(errs, errors.New("bench writes need \"reboot_cpe\" and/or \"set_wifi_ssid\" listed in allowed_operations (explicit)"))
		}
	}
	if c.JobsEnabled && c.JobPublicKey == "" {
		errs = append(errs, errors.New("jobs_enabled requires job_public_key (pinned locally, never fetched from the Cloud)"))
	}
	seen := map[string]bool{}
	allowed := map[string]bool{}
	for _, a := range c.Allowlist {
		allowed[strings.ToLower(a)] = true
	}
	if len(c.OLTs) > 64 {
		errs = append(errs, errors.New("too many olts (max 64)"))
	}
	deviceSeen := map[string]bool{}
	for i, o := range c.OLTs {
		p := fmt.Sprintf("olts[%d]", i)
		if o.Name == "" || len(o.Name) > 128 || seen[o.Name] {
			errs = append(errs, fmt.Errorf("%s: name required, unique, <=128 chars", p))
		}
		seen[o.Name] = true
		if o.Vendor != "huawei" && o.Vendor != "zte" {
			errs = append(errs, fmt.Errorf("%s: vendor must be huawei or zte", p))
		}
		if o.Transport != "snmp" {
			if _, _, err := net.SplitHostPort(o.Address); err != nil || !allowed[strings.ToLower(o.Address)] {
				errs = append(errs, fmt.Errorf("%s: address must be host:port AND listed in allowlist", p))
			}
		}
		if o.SSHMode != "" && o.SSHMode != "exec" && o.SSHMode != "shell" {
			errs = append(errs, fmt.Errorf("%s: ssh_mode must be exec or shell", p))
		}
		if o.Profile != "" && (o.Profile != "huawei_ma56_r015" || o.Vendor != "huawei") {
			errs = append(errs, fmt.Errorf("%s: profile must be empty or huawei_ma56_r015 (huawei only)", p))
		}
		if o.SSHPagerSpace && o.SSHMode != "shell" {
			errs = append(errs, fmt.Errorf("%s: ssh_pager_space requires ssh_mode shell", p))
		}
		// One physical device must not be configured twice (another name, another transport or port): the per-device lock, interval
		// and cooldown are keyed by host, and two entries would otherwise be two independent clients of the same OLT.
		if h, _, err := net.SplitHostPort(o.Address); o.Transport != "snmp" && err == nil && net.ParseIP(h) == nil {
			errs = append(errs, fmt.Errorf("%s: address must be an IP literal (a host name and an IP of the same OLT would be two guard identities)", p))
		}
		devAddr := o.Address
		if o.Transport == "snmp" {
			devAddr = o.SNMPAddress
		}
		if devAddr != "" {
			if k := DeviceKey(devAddr); deviceSeen[k] {
				errs = append(errs, fmt.Errorf("%s: the device at %s is already configured by another olt entry (one entry per physical OLT)", p, devAddr))
			} else {
				deviceSeen[k] = true
			}
		}
		switch o.Transport {
		case "", "cli":
			if o.Username == "" || o.SecretFile == "" {
				errs = append(errs, fmt.Errorf("%s: username and secret_file required", p))
			}
			if !strings.HasPrefix(o.HostKeySHA256, "SHA256:") {
				errs = append(errs, fmt.Errorf("%s: host_key_sha256 (SHA256:...) is mandatory", p))
			}
			if o.SNMPAddress != "" || o.SNMPCommunityFile != "" || o.SNMPPaceMillis != 0 || o.SNMPMaxRequests != 0 {
				errs = append(errs, fmt.Errorf("%s: snmp_* fields require transport snmp", p))
			}
		case "snmp":
			h, port, err := net.SplitHostPort(o.SNMPAddress)
			if err != nil || net.ParseIP(h) == nil || !allowed[strings.ToLower(o.SNMPAddress)] {
				errs = append(errs, fmt.Errorf("%s: snmp_address must be ip:port (IP literal) AND listed in allowlist", p))
			} else {
				_ = port
			}
			if o.Vendor != "huawei" {
				errs = append(errs, fmt.Errorf("%s: snmp transport is implemented for huawei only", p))
			}
			if o.SNMPCommunityFile == "" || (o.SNMPPaceMillis != 0 && o.SNMPPaceMillis < 1000) || o.SNMPPaceMillis > 10000 || o.SNMPMaxRequests < 0 || o.SNMPMaxRequests > 1000 {
				errs = append(errs, fmt.Errorf("%s: snmp_community_file required, snmp_pace_ms 0 (=1000) or 1000..10000, snmp_max_requests 0..1000", p))
			}
			if o.Username != "" || o.SecretFile != "" || o.HostKeySHA256 != "" || o.SSHMode != "" || o.Profile != "" || o.LegacySSH || o.SSHPagerSpace {
				errs = append(errs, fmt.Errorf("%s: ssh fields are not allowed with transport snmp", p))
			}
		default:
			errs = append(errs, fmt.Errorf("%s: transport must be cli or snmp", p))
		}
		if (o.CollectSeconds != 0 && (o.CollectSeconds < 60 || o.CollectSeconds > 86400)) ||
			(o.CooldownSeconds != 0 && (o.CooldownSeconds < 60 || o.CooldownSeconds > 86400)) {
			errs = append(errs, fmt.Errorf("%s: collect_seconds/cooldown_seconds must be 0 (default) or 60..86400", p))
		}
		if len(o.PonPorts) == 0 || len(o.PonPorts) > 256 {
			errs = append(errs, fmt.Errorf("%s: pon_ports required (1..256)", p))
		}
		for _, pp := range o.PonPorts {
			if !ponRe.MatchString(pp) {
				errs = append(errs, fmt.Errorf("%s: invalid pon port %q", p, pp))
			} else if o.Profile == "huawei_ma56_r015" && !olt.ValidR015Port(pp) {
				errs = append(errs, fmt.Errorf("%s: pon port %q outside huawei_ma56_r015 limits (frame 0, slot 0..17, port 0..15)", p, pp))
			}
		}
	}
	if c.HeartbeatSeconds < 5 || c.CollectSeconds < 30 {
		errs = append(errs, errors.New("intervals too small (heartbeat>=5s, collect>=30s)"))
	}
	return errors.Join(errs...)
}

// DeviceKey is the identity of one PHYSICAL device behind an address, whatever the transport or port: the IP literal in canonical
// form, or the lower-cased host name. The collection lock, interval and cooldown are keyed by it, so an SSH entry and an SNMP
// entry (or two aliases) of the same OLT share them instead of reaching the device concurrently.
func DeviceKey(addr string) string {
	h, _, err := net.SplitHostPort(addr)
	if err != nil {
		h = addr
	}
	if ip := net.ParseIP(h); ip != nil {
		return ip.String()
	}
	return strings.ToLower(h)
}

// StateFiles returns the single-instance lock and the OLT guard file of a state directory. They hang off the DIRECTORY of the queue
// file, never off its name, so two configs with different queue files in one directory share both.
func StateFiles(queuePath string) (lock, guard string) {
	d := filepath.Dir(queuePath)
	return filepath.Join(d, "edge.lock"), filepath.Join(d, "olt-guard.json")
}

// BenchMinIntervalFloor is the shortest interval between two bench writes on one device that a configuration may ask for.
const BenchMinIntervalFloor = 60

// BenchPacing resolves the configured pacing to the guard's values.
func (b BenchConfig) BenchPacing() (time.Duration, int) {
	min, per := 30*time.Minute, 2
	if b.MinIntervalSeconds > 0 {
		min = time.Duration(b.MinIntervalSeconds) * time.Second
	}
	if b.MaxPerHour > 0 {
		per = b.MaxPerHour
	}
	return min, per
}

var gponSerialRe = regexp.MustCompile(`^[0-9A-F]{16}$`)

var benchPartRe = regexp.MustCompile(`^[A-Za-z0-9._]{2,64}$`)

// BenchClaimsFile and BenchGuardFile are the durable state of the bench writes (spent authorizations, pacing); they live next to the queue.
func BenchClaimsFile(queuePath string) string {
	return filepath.Join(filepath.Dir(queuePath), "bench-claims.json")
}

// BenchRestoreFile keeps the original SSID (H3) on this host until its restore is confirmed.
func BenchRestoreFile(queuePath string) string {
	return filepath.Join(filepath.Dir(queuePath), "bench-restore.json")
}

func BenchGuardFile(queuePath string) string {
	return filepath.Join(filepath.Dir(queuePath), "bench-guard.json")
}

// RefreshGuardFile is the pacing state of the active CPE reads; it lives next to the other state files.
func RefreshGuardFile(queuePath string) string {
	return filepath.Join(filepath.Dir(queuePath), "refresh-guard.json")
}

// OLTInterval is the minimum time between two collections of one OLT. A CLI session is a login on a real device (and the pager
// makes it slow), so it defaults to 15 minutes; SNMP is already throttled per packet and follows the global cycle.
func (o OLTConfig) OLTInterval() time.Duration {
	if o.CollectSeconds > 0 {
		return time.Duration(o.CollectSeconds) * time.Second
	}
	if o.Transport == "snmp" {
		return 0
	}
	return 15 * time.Minute
}

func (o OLTConfig) OLTCooldown() time.Duration { return time.Duration(o.CooldownSeconds) * time.Second }

func (c *Config) HeartbeatEvery() time.Duration {
	return time.Duration(c.HeartbeatSeconds) * time.Second
}
func (c *Config) CollectEvery() time.Duration { return time.Duration(c.CollectSeconds) * time.Second }

// RequirePrivate refuses files readable by group/others (config and secrets).
func RequirePrivate(path string) error {
	fi, err := os.Stat(path)
	if err != nil {
		return err
	}
	if fi.Mode().Perm()&0o077 != 0 {
		return fmt.Errorf("%s must not be accessible by group/others (chmod 600)", path)
	}
	return nil
}

// ReadSecret reads a secret file (mode 0600 enforced), trimming the trailing newline.
func ReadSecret(path string) (string, error) {
	if err := RequirePrivate(path); err != nil {
		return "", err
	}
	b, err := os.ReadFile(path)
	if err != nil {
		return "", err
	}
	s := strings.TrimRight(string(b), "\r\n")
	if s == "" {
		return "", fmt.Errorf("%s is empty", path)
	}
	return s, nil
}
