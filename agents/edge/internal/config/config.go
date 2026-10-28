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
	"regexp"
	"strings"
	"time"
)

type Config struct {
	GatewayURL       string      `json:"gateway_url"`
	EdgeID           string      `json:"edge_id"`
	TenantID         string      `json:"tenant_id"`
	ClientID         string      `json:"client_id"`
	SecretFile       string      `json:"secret_file"` // file with the service-account secret, mode 0600
	ConnectorID      string      `json:"connector_id"`
	NBIURL           string      `json:"nbi_url"`
	NBISecretFile    string      `json:"nbi_secret_file"` // optional: NBI Basic credentials "user:pass", mode 0600
	Allowlist        []string    `json:"allowlist"`       // host:port the Edge may connect to (NBI, gateway excluded)
	QueuePath        string      `json:"queue_path"`
	HeartbeatSeconds int         `json:"heartbeat_seconds"`
	CollectSeconds   int         `json:"collect_seconds"`
	AllowInsecureDev bool        `json:"allow_insecure_dev"` // permits http:// gateway ONLY on loopback
	OLTs             []OLTConfig `json:"olts"`
	JobsEnabled      bool        `json:"jobs_enabled"`       // poll the Cloud for signed read-only jobs
	JobPublicKey     string      `json:"job_public_key"`     // base64 Ed25519 public key of the Cloud, pinned locally
	AllowedOps       []string    `json:"allowed_operations"` // narrows the compile-time read-only set (collect, refresh)
	Version          string      `json:"-"`
}

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
	for i, o := range c.OLTs {
		p := fmt.Sprintf("olts[%d]", i)
		if o.Name == "" || len(o.Name) > 128 || seen[o.Name] {
			errs = append(errs, fmt.Errorf("%s: name required, unique, <=128 chars", p))
		}
		seen[o.Name] = true
		if o.Vendor != "huawei" && o.Vendor != "zte" {
			errs = append(errs, fmt.Errorf("%s: vendor must be huawei or zte", p))
		}
		if _, _, err := net.SplitHostPort(o.Address); err != nil || !allowed[strings.ToLower(o.Address)] {
			errs = append(errs, fmt.Errorf("%s: address must be host:port AND listed in allowlist", p))
		}
		if o.Username == "" || o.SecretFile == "" {
			errs = append(errs, fmt.Errorf("%s: username and secret_file required", p))
		}
		if !strings.HasPrefix(o.HostKeySHA256, "SHA256:") {
			errs = append(errs, fmt.Errorf("%s: host_key_sha256 (SHA256:...) is mandatory", p))
		}
		if len(o.PonPorts) == 0 || len(o.PonPorts) > 256 {
			errs = append(errs, fmt.Errorf("%s: pon_ports required (1..256)", p))
		}
		for _, pp := range o.PonPorts {
			if !ponRe.MatchString(pp) {
				errs = append(errs, fmt.Errorf("%s: invalid pon port %q", p, pp))
			}
		}
	}
	if c.HeartbeatSeconds < 5 || c.CollectSeconds < 30 {
		errs = append(errs, errors.New("intervals too small (heartbeat>=5s, collect>=30s)"))
	}
	return errors.Join(errs...)
}

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
