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
	GatewayURL       string   `json:"gateway_url"`
	EdgeID           string   `json:"edge_id"`
	TenantID         string   `json:"tenant_id"`
	ClientID         string   `json:"client_id"`
	SecretFile       string   `json:"secret_file"` // file with the service-account secret, mode 0600
	ConnectorID      string   `json:"connector_id"`
	NBIURL           string   `json:"nbi_url"`
	NBISecretFile    string   `json:"nbi_secret_file"` // optional: NBI Basic credentials "user:pass", mode 0600
	Allowlist        []string `json:"allowlist"`       // host:port the Edge may connect to (NBI, gateway excluded)
	QueuePath        string   `json:"queue_path"`
	HeartbeatSeconds int      `json:"heartbeat_seconds"`
	CollectSeconds   int      `json:"collect_seconds"`
	AllowInsecureDev bool     `json:"allow_insecure_dev"` // permits http:// gateway ONLY on loopback
	Version          string   `json:"-"`
}

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
