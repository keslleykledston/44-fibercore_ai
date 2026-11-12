package main

import (
	"errors"
	"flag"
	"fmt"
	"io"
	"log/slog"
	"os"
	"path/filepath"

	"github.com/keslleykledston/44-fibercore_ai/agents/edge/internal/config"
	"github.com/keslleykledston/44-fibercore_ai/agents/edge/internal/credfile"
	"github.com/keslleykledston/44-fibercore_ai/agents/edge/internal/gateway"
	"github.com/keslleykledston/44-fibercore_ai/agents/edge/internal/jobs"
	"github.com/keslleykledston/44-fibercore_ai/agents/edge/internal/managedolts"
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
		if err := credfile.CheckPrivateDir(filepath.Dir(o.CredentialsFile)); err != nil {
			// not fatal for the rest of the Edge: collection keeps using the static configuration while there is no file; deliveries and sessions that need the file fail closed
			log.Warn("olt secrets: the directory of this OLT's credentials_file is not usable (create it mode 0700, owned by the Edge user)", "olt", o.Name, "err", err)
		}
		credfile.RemoveLeftovers(o.CredentialsFile) // a temporary file an earlier crash left behind
		targets[o.Name] = oltsecrets.Target{Name: o.Name, Path: o.CredentialsFile, Accepts: o.AcceptsKind}
	}
	store := &oltsecrets.AppliedStore{Path: s.AppliedPath(cfg.QueuePath), Log: log}
	if err := credfile.CheckStateDir(filepath.Dir(store.Path)); err != nil && !errors.Is(err, os.ErrNotExist) {
		log.Warn("olt secrets: the directory of the applied-delivery store is not safe; deliveries will fail with state_unreadable until it is fixed (or set olt_secrets.applied_file in a private directory)", "err", err)
	}
	proc := &oltsecrets.Processor{TenantID: cfg.TenantID, EdgeID: cfg.EdgeID, Key: key, Pub: pub, Targets: targets, Store: store, Log: log}
	w := &oltsecrets.Worker{Cloud: gw, Proc: proc, Log: log}
	if cfg.ManagedOLTs != nil { // ADR-0046: the OLTs the Cloud may add, inside the local policy; each one waits for the local trust before anything touches it
		pol, mstore, err := openManaged(cfg)
		if err != nil {
			return nil, err
		}
		rep := &oltsecrets.StateReporter{Store: mstore, Cloud: gw, Log: log}
		static := make([]oltsecrets.StaticOLT, 0, len(cfg.OLTs))
		for _, o := range cfg.OLTs {
			addr := o.Address
			if o.Transport == "snmp" {
				addr = o.SNMPAddress
			}
			static = append(static, oltsecrets.StaticOLT{Name: o.Name, DeviceKey: config.DeviceKey(addr), CloudID: o.CloudID})
		}
		proc.Managed = &oltsecrets.Managed{Policy: pol, Store: mstore, Static: static}
		w.State = rep
		log.Info("managed olts enabled: the Cloud may add OLTs inside the local policy; each waits for managed-trust", "state_dir", cfg.ManagedOLTs.StateDir, "max_olts", pol.Max, "cidrs", len(pol.CIDRs))
	}
	log.Info("olt secrets enabled", "key_id", key.KeyID(), "olts_accepting", len(targets))
	return w, nil
}

// openManaged builds the policy and prepares the state directory (created 0700 when missing; anything loose is an error: the Edge refuses to start, like for the seal key).
func openManaged(cfg *config.Config) (*managedolts.Policy, *managedolts.Store, error) {
	pol, err := managedolts.NewPolicy(*cfg.ManagedOLTs)
	if err != nil {
		return nil, nil, err
	}
	st := &managedolts.Store{Dir: cfg.ManagedOLTs.StateDir}
	if err := st.Init(); err != nil {
		return nil, nil, fmt.Errorf("managed olts state: %w", err)
	}
	return pol, st, nil
}
