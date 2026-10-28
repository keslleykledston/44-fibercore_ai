package main

import (
	"context"
	"flag"
	"log/slog"
	"net"
	"net/url"
	"os"
	"os/signal"
	"syscall"
	"time"

	"github.com/keslleykledston/44-fibercore_ai/agents/edge/internal/agent"
	"github.com/keslleykledston/44-fibercore_ai/agents/edge/internal/allowlist"
	"github.com/keslleykledston/44-fibercore_ai/agents/edge/internal/collector"
	"github.com/keslleykledston/44-fibercore_ai/agents/edge/internal/config"
	"github.com/keslleykledston/44-fibercore_ai/agents/edge/internal/gateway"
	"github.com/keslleykledston/44-fibercore_ai/agents/edge/internal/jobs"
	"github.com/keslleykledston/44-fibercore_ai/agents/edge/internal/nbi"
	"github.com/keslleykledston/44-fibercore_ai/agents/edge/internal/olt"
	"github.com/keslleykledston/44-fibercore_ai/agents/edge/internal/queue"
)

var version = "0.1.0-dev"

func main() {
	cfgPath := flag.String("config", "/etc/fibercore-edge/config.json", "config file (mode 0600)")
	flag.Parse()
	log := slog.New(slog.NewJSONHandler(os.Stdout, nil))
	cfg, err := config.Load(*cfgPath, version)
	if err != nil {
		log.Error("invalid config", "err", err)
		os.Exit(2)
	}
	secret, err := config.ReadSecret(cfg.SecretFile)
	if err != nil {
		log.Error("secret", "err", err)
		os.Exit(2)
	}
	al, err := allowlist.New(cfg.Allowlist)
	if err != nil {
		log.Error("allowlist", "err", err)
		os.Exit(2)
	}
	q, err := queue.Open(cfg.QueuePath)
	if err != nil {
		log.Error("queue", "err", err)
		os.Exit(2)
	}
	defer q.Close()

	// Gateway: its own single-destination allowlist derived from the LOCAL config (no proxies, no redirects).
	gwURL, _ := url.Parse(cfg.GatewayURL)
	gwHost := gwURL.Host
	if gwURL.Port() == "" {
		gwHost = net.JoinHostPort(gwURL.Hostname(), map[string]string{"https": "443", "http": "80"}[gwURL.Scheme])
	}
	gwAllow, _ := allowlist.New([]string{gwHost})
	gw := gateway.New(cfg.GatewayURL, cfg.ClientID, secret, gwAllow.HTTPClient(30*time.Second))

	var collectors []collector.Collector
	if cfg.NBIURL != "" {
		nbiAuth := ""
		if cfg.NBISecretFile != "" {
			if nbiAuth, err = config.ReadSecret(cfg.NBISecretFile); err != nil {
				log.Error("nbi secret", "err", err)
				os.Exit(2)
			}
		}
		nbiClient, err := nbi.New(cfg.NBIURL, al.HTTPClient(30*time.Second), nbiAuth)
		if err != nil {
			log.Error("nbi", "err", err)
			os.Exit(2)
		}
		collectors = append(collectors, &collector.GenieACS{EdgeID: cfg.EdgeID, ConnectorID: cfg.ConnectorID, Client: nbiClient})
	}

	if len(cfg.OLTs) > 0 {
		oc := &collector.OLT{EdgeID: cfg.EdgeID}
		for _, o := range cfg.OLTs {
			o := o
			var drv olt.Driver = olt.Huawei{}
			if o.Vendor == "zte" {
				drv = olt.ZTE{}
			}
			oc.Sources = append(oc.Sources, collector.OLTSource{
				Name: o.Name, Driver: drv, Ports: o.PonPorts, AllowUnverified: o.AllowUnverifiedFirmware,
				Open: func(ctx context.Context) (olt.Session, func(), error) {
					pw, err := config.ReadSecret(o.SecretFile)
					if err != nil {
						return nil, nil, err
					}
					s, err := olt.DialSSH(ctx, olt.SSHConfig{Addr: o.Address, User: o.Username, Password: pw,
						HostKeySHA256: o.HostKeySHA256, Dial: al.DialContext})
					if err != nil {
						return nil, nil, err
					}
					return s, func() { s.Close() }, nil
				},
			})
		}
		collectors = append(collectors, oc)
	}

	var verifier *jobs.Verifier
	if cfg.JobsEnabled {
		pub, err := jobs.ParsePublicKey(cfg.JobPublicKey)
		if err != nil {
			log.Error("job key", "err", err)
			os.Exit(2)
		}
		allowed := map[string]bool{}
		ops := cfg.AllowedOps
		if len(ops) == 0 {
			ops = []string{"collect", "refresh"}
		}
		for _, o := range ops {
			if !jobs.ReadOnlyOps[o] { // config can narrow the read-only set, never widen it
				log.Error("operation not allowed on this Edge build", "operation", o)
				os.Exit(2)
			}
			allowed[o] = true
		}
		verifier = &jobs.Verifier{Pub: pub, EdgeID: cfg.EdgeID, TenantID: cfg.TenantID, Allowed: allowed, Nonces: q, Now: time.Now}
	}

	ctx, stop := signal.NotifyContext(context.Background(), syscall.SIGINT, syscall.SIGTERM)
	defer stop()
	ag := &agent.Agent{
		EdgeID: cfg.EdgeID, TenantID: cfg.TenantID, Version: cfg.Version, GW: gw, Q: q, Collectors: collectors,
		Jobs: verifier, JobPollEvery: 15 * time.Second, HeartbeatEvery: cfg.HeartbeatEvery(), CollectEvery: cfg.CollectEvery(), Log: log,
	}
	log.Info("fibercore-edge starting", "version", cfg.Version, "edge_id", cfg.EdgeID, "collectors", len(collectors))
	ag.Run(ctx)
	log.Info("fibercore-edge stopped")
}
