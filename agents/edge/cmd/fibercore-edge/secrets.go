package main

import (
	"errors"
	"flag"
	"fmt"
	"io"
	"log/slog"
	"os"

	"github.com/keslleykledston/44-fibercore_ai/agents/edge/internal/config"
	"github.com/keslleykledston/44-fibercore_ai/agents/edge/internal/credfile"
	"github.com/keslleykledston/44-fibercore_ai/agents/edge/internal/gateway"
	"github.com/keslleykledston/44-fibercore_ai/agents/edge/internal/jobs"
	"github.com/keslleykledston/44-fibercore_ai/agents/edge/internal/oltsecrets"
)

// runSealFingerprint implements `fibercore-edge seal-fingerprint [-config PATH]` (ADR-0045): it prints the fingerprint and key id of THIS Edge's sealing key so the
// operator can compare them with what the Cloud screen shows before confirming. It reads the key, never creates it and never prints anything secret.
func runSealFingerprint(args []string, stdout, stderr io.Writer) int {
	fs := flag.NewFlagSet("seal-fingerprint", flag.ContinueOnError)
	fs.SetOutput(stderr)
	cfgPath := fs.String("config", "/etc/fibercore-edge/config.json", "config file (mode 0600)")
	if err := fs.Parse(args); err != nil {
		return 2
	}
	cfg, err := config.Load(*cfgPath, version)
	if err != nil {
		fmt.Fprintln(stderr, "invalid config:", err)
		return 2
	}
	if cfg.OLTSecrets == nil {
		fmt.Fprintln(stderr, "olt_secrets is not enabled in this configuration")
		return 2
	}
	k, err := oltsecrets.LoadKey(cfg.OLTSecrets.SealKeyFile)
	if err != nil {
		if errors.Is(err, os.ErrNotExist) {
			fmt.Fprintln(stderr, "the seal key does not exist yet: start fibercore-edge once (it generates the key at the first start), then run this again")
		} else {
			fmt.Fprintln(stderr, "seal key:", err)
		}
		return 1
	}
	fmt.Fprintf(stdout, "fingerprint: %s\nkey_id: %s\npublic_key: %s\n", k.Fingerprint(), k.KeyID(), k.PublicB64())
	return 0
}

// setupSecrets prepares the ADR-0045 delivery loop, or returns nil when the section is absent (the whole feature is then off). Any problem with the key or the store is
// returned: the caller refuses to start, like for every other secret of this Edge.
func setupSecrets(cfg *config.Config, gw *gateway.Client, log *slog.Logger) (*oltsecrets.Worker, error) {
	s := cfg.OLTSecrets
	if s == nil {
		return nil, nil
	}
	pub, err := jobs.ParsePublicKey(cfg.JobPublicKey)
	if err != nil {
		return nil, err
	}
	key, created, err := oltsecrets.LoadOrCreateKey(s.SealKeyFile)
	if err != nil {
		return nil, fmt.Errorf("seal key: %w", err)
	}
	if created {
		log.Warn("olt secrets: a new seal key was generated; confirm its fingerprint in the Cloud screen before any delivery (run: fibercore-edge seal-fingerprint)", "key_id", key.KeyID())
	}
	targets := map[string]oltsecrets.Target{}
	for _, o := range cfg.OLTs {
		if o.CredentialsFile == "" {
			continue
		}
		credfile.RemoveLeftovers(o.CredentialsFile) // a temporary file an earlier crash left behind (the directory must already exist, 0700)
		targets[o.Name] = oltsecrets.Target{Name: o.Name, Path: o.CredentialsFile, Accepts: o.AcceptsKind}
	}
	store := &oltsecrets.AppliedStore{Path: s.AppliedPath(cfg.QueuePath), Log: log}
	proc := &oltsecrets.Processor{TenantID: cfg.TenantID, EdgeID: cfg.EdgeID, Key: key, Pub: pub, Targets: targets, Store: store, Log: log}
	log.Info("olt secrets enabled", "key_id", key.KeyID(), "olts_accepting", len(targets))
	return &oltsecrets.Worker{Cloud: gw, Proc: proc, Log: log}, nil
}
