package config

import (
	"encoding/base64"
	"errors"
	"fmt"
	"path/filepath"
	"time"

	"github.com/keslleykledston/44-fibercore_ai/agents/edge/internal/credfile"
)

// OLTSecretsConfig (ADR-0045) turns on the delivery of OLT credentials typed in the Cloud screen, sealed to a key that never leaves this host. The WHOLE feature is
// opt-in: without this section the Edge neither publishes a key nor asks for deliveries, and no OLT accepts a credentials_file (Validate refuses one).
type OLTSecretsConfig struct {
	// SealKeyFile holds the private ECDH P-256 key of this Edge (generated at the first start, file 0600 in a 0700 directory, never logged, never sent).
	SealKeyFile string `json:"seal_key_file"`
	// AppliedFile is the store of applied delivery ids (idempotency and anti-rollback). Empty = olt-secrets-applied.json next to the queue.
	AppliedFile string `json:"applied_file"`
	// PollSeconds is how often the Edge asks the Cloud for a delivery (0 = 30; 15..300). It also asks right after a heartbeat, never more than every 10 s.
	PollSeconds int `json:"poll_seconds"`
}

// Poll is the interval between two asks for a delivery.
func (s OLTSecretsConfig) Poll() time.Duration {
	if s.PollSeconds <= 0 {
		return 30 * time.Second
	}
	return time.Duration(s.PollSeconds) * time.Second
}

// AppliedPath is where the applied-delivery store lives.
func (s OLTSecretsConfig) AppliedPath(queuePath string) string {
	if s.AppliedFile != "" {
		return s.AppliedFile
	}
	return filepath.Join(filepath.Dir(queuePath), "olt-secrets-applied.json")
}

// Kinds of delivery of ADR-0045.
const (
	KindSSHLogin      = "ssh_login"
	KindSNMPCommunity = "snmp_community"
)

// AcceptsKind says whether a delivery of this kind would ever be USED by this OLT entry: an ssh_login is read by CLI sessions, a community by an SNMP entry or by
// the last_down side channel of a CLI entry. A credential the entry can never use is refused (target_not_configured) instead of reported as applied.
func (o OLTConfig) AcceptsKind(kind string) bool {
	if o.CredentialsFile == "" {
		return false
	}
	switch kind {
	case KindSSHLogin:
		return o.Transport != "snmp"
	case KindSNMPCommunity:
		return o.Transport == "snmp" || o.LastDown != nil
	}
	return false
}

var errNoLogin = errors.New("no username or password for this OLT (neither credentials_file nor the static configuration has them)")

// SSHLogin is the username and password of ONE CLI session (ADR-0045 precedence): a field present in credentials_file wins; an absent one falls back to the static
// configuration (username, secret_file). A credentials_file that exists but cannot be read, is loose or invalid is an error of the session: there is NO fallback.
// The static secret file is not even opened when the credentials file already has the password.
func (o OLTConfig) SSHLogin() (user, pass string, err error) {
	user, pass = o.Username, ""
	if o.CredentialsFile != "" {
		c, _, err := credfile.Read(o.CredentialsFile)
		if err != nil {
			return "", "", fmt.Errorf("credentials_file: %w", err)
		}
		if c.Username != "" {
			user = c.Username
		}
		pass = c.Password
	}
	if pass == "" && o.SecretFile != "" {
		if pass, err = ReadSecret(o.SecretFile); err != nil {
			return "", "", err
		}
	}
	if user == "" || pass == "" {
		return "", "", errNoLogin
	}
	return user, pass, nil
}

// Community is the SNMP v2c community of ONE session: the field of credentials_file when present, else the static file (the one of the transport "snmp" entry or the
// one of last_down). Same fail-closed rule as SSHLogin.
func (o OLTConfig) Community(staticFile string) (string, error) {
	if o.CredentialsFile != "" {
		c, _, err := credfile.Read(o.CredentialsFile)
		if err != nil {
			return "", fmt.Errorf("credentials_file: %w", err)
		}
		if c.SNMPCommunity != "" {
			return c.SNMPCommunity, nil
		}
	}
	if staticFile == "" {
		return "", errors.New("no snmp community for this OLT (neither credentials_file nor the static configuration has one)")
	}
	return ReadSecret(staticFile)
}

// validateOLTSecrets checks the olt_secrets section and every credentials_file against it.
func (c *Config) validateOLTSecrets() []error {
	var errs []error
	// Files that already exist in old configurations may be shared (one password file for several OLTs): they are only compared WITH the new ones, never among
	// themselves, so an old configuration keeps loading exactly as before.
	static := map[string]string{filepath.Clean(c.SecretFile): "secret_file", filepath.Clean(c.QueuePath): "queue_path"}
	if c.NBISecretFile != "" {
		static[filepath.Clean(c.NBISecretFile)] = "nbi_secret_file"
	}
	for i, o := range c.OLTs {
		for what, f := range map[string]string{"secret_file": o.SecretFile, "snmp_community_file": o.SNMPCommunityFile} {
			if f != "" {
				static[filepath.Clean(f)] = fmt.Sprintf("olts[%d].%s", i, what)
			}
		}
		if o.LastDown != nil && o.LastDown.SNMPCommunityFile != "" {
			static[filepath.Clean(o.LastDown.SNMPCommunityFile)] = fmt.Sprintf("olts[%d].last_down.snmp_community_file", i)
		}
	}
	fresh := map[string]string{}
	claim := func(what, p string) {
		if p == "" {
			return
		}
		k := filepath.Clean(p)
		if prev, dup := static[k]; dup {
			errs = append(errs, fmt.Errorf("%s and %s name the same file", prev, what))
			return
		}
		if prev, dup := fresh[k]; dup {
			errs = append(errs, fmt.Errorf("%s and %s name the same file", prev, what))
			return
		}
		fresh[k] = what
	}
	s := c.OLTSecrets
	if s != nil {
		claim("olt_secrets.seal_key_file", s.SealKeyFile)
		claim("olt_secrets.applied_file", s.AppliedFile)
		if s.SealKeyFile == "" || !filepath.IsAbs(s.SealKeyFile) {
			errs = append(errs, errors.New("olt_secrets.seal_key_file is required and must be an absolute path"))
		}
		if s.AppliedFile != "" && !filepath.IsAbs(s.AppliedFile) {
			errs = append(errs, errors.New("olt_secrets.applied_file must be an absolute path"))
		}
		if s.PollSeconds != 0 && (s.PollSeconds < 15 || s.PollSeconds > 300) {
			errs = append(errs, errors.New("olt_secrets.poll_seconds must be 0 (30) or between 15 and 300"))
		}
		// the signature of every delivery is checked with the pinned job_public_key (ADR-0045): without it nothing can be authenticated
		if b, err := base64.StdEncoding.DecodeString(c.JobPublicKey); err != nil || len(b) != 32 {
			errs = append(errs, errors.New("olt_secrets requires job_public_key (base64 Ed25519 public key, 32 bytes: the Cloud's delivery signature is checked with it)"))
		}
	}
	for i, o := range c.OLTs {
		p := fmt.Sprintf("olts[%d]", i)
		if o.CredentialsFile == "" {
			continue
		}
		claim(p+".credentials_file", o.CredentialsFile)
		claim(p+".credentials_file (lock)", o.CredentialsFile+".lock")
		if s == nil {
			errs = append(errs, fmt.Errorf("%s: credentials_file requires the olt_secrets section (the feature is opt-in as a whole)", p))
		}
		if !filepath.IsAbs(o.CredentialsFile) {
			errs = append(errs, fmt.Errorf("%s: credentials_file must be an absolute path (a file in a 0700 directory)", p))
		}
	}
	return errs
}
