package main

import (
	"context"
	"errors"
	"flag"
	"fmt"
	"log/slog"
	"net"
	"net/url"
	"os"
	"os/signal"
	"strings"
	"syscall"
	"time"

	"github.com/keslleykledston/44-fibercore_ai/agents/edge/internal/agent"
	"github.com/keslleykledston/44-fibercore_ai/agents/edge/internal/allowlist"
	"github.com/keslleykledston/44-fibercore_ai/agents/edge/internal/bench"
	"github.com/keslleykledston/44-fibercore_ai/agents/edge/internal/collector"
	"github.com/keslleykledston/44-fibercore_ai/agents/edge/internal/config"
	"github.com/keslleykledston/44-fibercore_ai/agents/edge/internal/gateway"
	"github.com/keslleykledston/44-fibercore_ai/agents/edge/internal/jobs"
	"github.com/keslleykledston/44-fibercore_ai/agents/edge/internal/nbi"
	"github.com/keslleykledston/44-fibercore_ai/agents/edge/internal/olt"
	"github.com/keslleykledston/44-fibercore_ai/agents/edge/internal/oltquery"
	"github.com/keslleykledston/44-fibercore_ai/agents/edge/internal/queue"
	"github.com/keslleykledston/44-fibercore_ai/agents/edge/internal/singleton"
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

	lockPath, guardPath := config.StateFiles(cfg.QueuePath) // per DIRECTORY: another queue file cannot bypass them
	// One Edge per state directory: the OLT pacing guard is a file and cannot coordinate two processes by itself.
	lock, err := singleton.Acquire(lockPath)
	if err != nil {
		log.Error("single instance", "err", err)
		os.Exit(2)
	}
	defer lock.Close()

	var collectors []collector.Collector
	var refresher agent.RefreshFunc
	var benchACS bench.ACS
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
		benchACS = nbiClient
		if cfg.RefreshTasks {
			guard := &nbi.RefreshGuard{Path: config.RefreshGuardFile(cfg.QueuePath), MinPerDevice: 10 * time.Minute, MaxPerHour: 20}
			refresher = func(ctx context.Context, ref string) (string, error) {
				if err := guard.Reserve(ref); err != nil { // persisted BEFORE anything is sent
					return "", err
				}
				rep, err := nbiClient.RefreshParams(ctx, ref)
				if hold := nbi.RefreshHold(rep, err); hold > 0 {
					// local log only (device id stays on the site): the operator must look at this device in the ACS
					log.Error("refresh left the device on hold", "device", ref, "hold", hold.String(), "groups", rep.Groups, "faulted", rep.Faulted, "uncleaned", rep.Uncleaned, "unproven", errors.Is(err, nbi.ErrRefreshUnproven))
					if herr := guard.Hold(ref, hold); herr != nil {
						log.Error("could not persist the hold (kept in memory for this process; refreshes also fail closed while the state cannot be written)", "err", herr)
					}
				}
				if err != nil {
					return "", err
				}
				res, rerr := nbiClient.CachedParams(ctx, []string{ref})
				readable, rejected := 0, 0
				if rerr == nil && len(res) == 1 {
					readable, rejected = len(res[0].Metrics), res[0].Rejected
				}
				return fmt.Sprintf("acs refresh (%s): groups=%d completed=%d faulted=%d queued=%d cleaned=%d; readable_metrics=%d rejected=%d",
					rep.DataModel, rep.Groups, rep.Completed, rep.Faulted, rep.Queued, rep.Cleaned, readable, rejected), nil
			}
		}
		collectors = append(collectors, &collector.GenieACS{EdgeID: cfg.EdgeID, ConnectorID: cfg.ConnectorID, Client: nbiClient, Params: nbiClient,
			OnSkip: func(reason string, n int) { log.Info("genieacs: devices left out", "reason", reason, "count", n) }})
	}

	var oltCol *collector.OLT
	if len(cfg.OLTs) > 0 {
		oc := &collector.OLT{EdgeID: cfg.EdgeID, Guard: collector.FileGuard{Path: guardPath},
			OnCollected: func(name string, took time.Duration, items int, err error) {
				if err != nil {
					log.Warn("olt collection failed", "olt", name, "took_ms", took.Milliseconds(), "err", err)
					return
				}
				log.Info("olt collected", "olt", name, "took_ms", took.Milliseconds(), "chunks", items)
			}}
		for _, o := range cfg.OLTs {
			o := o
			if o.Transport == "snmp" {
				oc.Sources = append(oc.Sources, collector.OLTSource{
					Name: o.Name, Ports: o.PonPorts, AllowUnverified: o.AllowUnverifiedFirmware, SNMPDriver: olt.HuaweiSNMP{},
					SNMPKey: config.DeviceKey(o.SNMPAddress), Interval: o.OLTInterval(), Cooldown: o.OLTCooldown(),
					OpenSNMP: func(ctx context.Context) (olt.SNMPReader, func(), error) {
						community, err := config.ReadSecret(o.SNMPCommunityFile)
						if err != nil {
							return nil, nil, err
						}
						return olt.DialSNMP(ctx, olt.SNMPConfig{Addr: o.SNMPAddress, Community: community, Allowed: al.Allowed,
							Pace: time.Duration(o.SNMPPaceMillis) * time.Millisecond, MaxReqs: o.SNMPMaxRequests})
					},
				})
				continue
			}
			var drv olt.Driver = olt.Huawei{}
			if o.Vendor == "zte" {
				drv = olt.ZTE{}
			}
			if o.Profile == "huawei_ma56_r015" {
				drv = olt.HuaweiR015{DownTimes: o.DownTimes != nil}
			}
			src := collector.OLTSource{
				Name: o.Name, Driver: drv, Ports: o.PonPorts, AllowUnverified: o.AllowUnverifiedFirmware, CloudID: o.CloudID,
				SNMPKey: config.DeviceKey(o.Address), Interval: o.OLTInterval(), Cooldown: o.OLTCooldown(),
				Open: func(ctx context.Context) (olt.Session, func(), error) {
					pw, err := config.ReadSecret(o.SecretFile)
					if err != nil {
						return nil, nil, err
					}
					s, err := olt.DialSSH(ctx, olt.SSHConfig{Addr: o.Address, User: o.Username, Password: pw,
						HostKeySHA256: o.HostKeySHA256, Dial: al.DialContext,
						Shell: o.SSHMode == "shell", Legacy: o.LegacySSH, PagerSpace: o.SSHPagerSpace})
					if err != nil {
						return nil, nil, err
					}
					return s, func() { s.Close() }, nil
				},
			}
			if d := o.DownTimes; d != nil { // read-only: the OLT's last down time of offline ONUs, over this same CLI session
				src.DownTimes = &collector.DownTimesSource{MaxPerRound: d.Max(),
					Report: func(name string, picked, read, found int, why map[string]int) {
						log.Info("olt last down times", "olt", name, "picked", picked, "read", read, "found", found, "why_not", why)
					}}
			}
			if l := o.LastDown; l != nil { // read-only SNMP side channel: the OLT's own "last down time" of the offline ONUs
				l := l
				src.LastDown = &collector.LastDownSource{
					Key: "last-down|" + config.DeviceKey(l.SNMPAddress), Every: l.Every(), Settle: l.Settle(), Driver: olt.HuaweiSNMP{},
					Open: func(ctx context.Context) (olt.SNMPReader, func(), error) {
						community, err := config.ReadSecret(l.SNMPCommunityFile)
						if err != nil {
							return nil, nil, err
						}
						return olt.DialSNMP(ctx, olt.SNMPConfig{Addr: l.SNMPAddress, Community: community, Allowed: al.Allowed,
							Pace: l.Pace(), MaxReqs: l.MaxRequests})
					},
				}
			}
			oc.Sources = append(oc.Sources, src)
		}
		oltCol = oc
		collectors = append(collectors, oc)
	}

	var verifier *jobs.Verifier
	var queryStore *oltquery.Store
	var oltLease *jobs.LeaseHolder
	var benchRunner *bench.Runner
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
		benchOn := cfg.Bench != nil && cfg.Bench.Enabled
		for _, o := range ops {
			if jobs.BenchWriteOps[o] && benchOn { // a bench write is only ever allowed through the explicit bench section (ADR-0030)
				allowed[o] = true
				continue
			}
			if jobs.QueryOps[o] && cfg.OLTQueryEnabled { // ADR-0029: only through the explicit olt_query_enabled switch
				allowed[o] = true
				continue
			}
			if !jobs.ReadOnlyOps[o] { // config can narrow the read-only set, never widen it
				log.Error("operation not allowed on this Edge build", "operation", o)
				os.Exit(2)
			}
			allowed[o] = true
		}
		verifier = &jobs.Verifier{Pub: pub, EdgeID: cfg.EdgeID, TenantID: cfg.TenantID, Allowed: allowed, BenchEnabled: benchOn, Nonces: q, Now: time.Now}
		if cfg.OLTQueryEnabled {
			if oltCol == nil {
				log.Error("olt_query_enabled needs the olts collector")
				os.Exit(2)
			}
			qs := &oltquery.Store{Path: config.OLTQueriesFile(cfg.QueuePath)}
			unknown, expired, err := qs.Recover() // a query that was claimed when the last process died has an unknown outcome and is never run again
			if err != nil {
				log.Error("olt query queue cannot be opened; refusing to start with olt_query enabled", "err", err)
				os.Exit(2)
			}
			log.Info("olt query queue recovered", "unknown_outcome", unknown, "expired", expired)
			known := map[string]bool{}
			for _, o := range cfg.OLTs {
				if o.CloudID != "" {
					known[o.CloudID] = true
				}
			}
			oltLease = &jobs.LeaseHolder{Schema: "olt-lease/1", Pub: pub, EdgeID: cfg.EdgeID, TenantID: cfg.TenantID}
			oltCol.Queries = &collector.Queries{Store: qs, Run: olt.HuaweiR015{}.RunQueryInConfig, Lease: oltLease}
			verifier.QueryEnabled = true
			verifier.QueryCheck = func(params map[string]any, targetID string) error {
				in, err := olt.ParseIntent(params)
				if err != nil {
					return err
				}
				if in.OLTRef != targetID || !known[in.OLTRef] {
					return errors.New("olt_ref is not an OLT of this edge")
				}
				return nil
			}
			queryStore = qs
		}
		if benchOn {
			claims, err := jobs.OpenClaims(config.BenchClaimsFile(cfg.QueuePath))
			if err != nil || benchACS == nil {
				log.Error("bench writes enabled but their state cannot be opened; refusing to start", "err", err)
				os.Exit(2)
			}
			devs := map[string]nbi.BenchDevice{}
			for _, d := range cfg.Bench.Devices {
				devs[d.ID()] = nbi.BenchDevice{DeviceID: d.ID(), OUI: d.OUI, ProductClass: d.ProductClass, Serial: d.Serial}
			}
			minGap, perHour := cfg.Bench.BenchPacing()
			benchRunner = &bench.Runner{
				Devices: devs, Claims: claims, ACS: benchACS, RestoreFile: config.BenchRestoreFile(cfg.QueuePath), Wait: 4 * time.Minute, Poll: 10 * time.Second, Log: log,
				Lease: &jobs.LeaseHolder{Pub: pub, EdgeID: cfg.EdgeID, TenantID: cfg.TenantID},
				// per-device pacing (default 30 min, 2 per hour; the configuration may lower it down to the floor); reservation persisted before sending
				Guard: &nbi.RefreshGuard{Path: config.BenchGuardFile(cfg.QueuePath), MinPerDevice: minGap, MaxPerHour: perHour},
			}
			if bo := cfg.Bench.OLT; bo != nil {
				if oltCol == nil {
					log.Error("bench.olt needs the olts collector")
					os.Exit(2)
				}
				onu := olt.BenchONU{Frame: bo.Frame, Slot: bo.Slot, Port: bo.Port, OntID: bo.OntID, GPONSerial: strings.ToUpper(bo.GPONSerial)}
				gap, wait, cool := 15*time.Minute, 4*time.Minute, time.Duration(0)
				if bo.MinGapSeconds > 0 {
					gap = time.Duration(bo.MinGapSeconds) * time.Second
				}
				if bo.CooldownSeconds > 0 {
					cool = time.Duration(bo.CooldownSeconds) * time.Second
				}
				if bo.WaitSeconds > 0 {
					wait = time.Duration(bo.WaitSeconds) * time.Second
				}
				var src collector.OLTSource
				for _, x := range oltCol.Sources {
					if x.Name == bo.Name {
						src = x
					}
				}
				benchRunner.OLT = func(ctx context.Context, op string, notAfter time.Time, before func() error) (olt.ManeuverOutcome, error) {
					var out olt.ManeuverOutcome
					xerr := oltCol.Exclusive(ctx, bo.Name, gap, cool, func(opened func()) error {
						cctx, cancel := context.WithTimeout(ctx, wait+3*time.Minute) // login + commands + the wait for the ONU to come back
						defer cancel()
						raw, closeFn, err := src.Open(cctx)
						if err != nil {
							return err
						}
						defer closeFn()
						opened() // the login worked: from here a failure may use the shorter cooldown
						var rerr error
						out, rerr = olt.RunBenchManeuver(cctx, raw, onu, op, notAfter, before, wait, 10*time.Second, time.Now)
						return rerr
					})
					return out, xerr
				}
				log.Warn("bench OLT maneuvers ENABLED for ONE ONU", "olt", bo.Name, "min_gap", gap.String(), "cooldown", cool.String())
			}
			log.Warn("bench writes ENABLED for a closed list of devices", "devices", len(devs), "min_interval", minGap.String(), "max_per_hour", perHour)
		}
	}

	ctx, stop := signal.NotifyContext(context.Background(), syscall.SIGINT, syscall.SIGTERM)
	defer stop()
	if oltCol != nil {
		oltCol.Lifecycle = ctx // background OLT reads stop with the service
	}
	ag := &agent.Agent{
		EdgeID: cfg.EdgeID, TenantID: cfg.TenantID, Version: cfg.Version, GW: gw, Q: q, Collectors: collectors,
		Jobs: verifier, Queries: queryStore, OLTLease: oltLease, Refresher: refresher, Bench: benchRunner, JobPollEvery: 15 * time.Second, HeartbeatEvery: cfg.HeartbeatEvery(), CollectEvery: cfg.CollectEvery(), Log: log,
	}
	log.Info("fibercore-edge starting", "version", cfg.Version, "edge_id", cfg.EdgeID, "collectors", len(collectors))
	ag.Run(ctx)
	log.Info("fibercore-edge stopped")
}
