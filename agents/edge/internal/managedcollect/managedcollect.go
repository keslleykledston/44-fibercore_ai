// Package managedcollect turns the managed OLTs of ADR-0046 into collector sources, fresh at every collection round.
//
// Only OLTs that the administrator of this host TRUSTED locally (trust.json holds the digest of exactly their present connection fields) and that the CURRENT policy still
// admits are returned; their dial list is the static allowlist plus the exact ip:port of each of them. An OLT that is awaiting trust, was removed, was changed, or no longer
// fits the policy is simply not in the list: no session, no credential read, no packet.
package managedcollect

import (
	"context"
	"errors"
	"fmt"
	"log/slog"
	"net"
	"sort"
	"sync"

	"github.com/keslleykledston/44-fibercore_ai/agents/edge/internal/allowlist"
	"github.com/keslleykledston/44-fibercore_ai/agents/edge/internal/collector"
	"github.com/keslleykledston/44-fibercore_ai/agents/edge/internal/config"
	"github.com/keslleykledston/44-fibercore_ai/agents/edge/internal/managedolts"
	"github.com/keslleykledston/44-fibercore_ai/agents/edge/internal/olt"
)

// Static names a static OLT of config.json: a managed OLT that clashes with one is never collected (the static one wins).
type Static struct {
	Name      string
	DeviceKey string
}

// ErrNotTrusted: at the moment a session was about to open, the OLT was no longer trusted (removed, changed or untrusted meanwhile).
var ErrNotTrusted = errors.New("managed olt is not trusted (anymore): nothing was opened")

// Builder produces the collector sources of the managed OLTs.
type Builder struct {
	Store  *managedolts.Store
	Policy *managedolts.Policy
	Allow  *allowlist.List // the static allowlist
	Static []Static
	Log    *slog.Logger

	// OpenSSH / OpenSNMP are test hooks; nil = the real drivers (olt.DialSSH / olt.DialSNMP) with the allowlist dialer.
	OpenSSH  func(ctx context.Context, cfg olt.SSHConfig) (olt.Session, func(), error)
	OpenSNMP func(ctx context.Context, cfg olt.SNMPConfig) (olt.SNMPReader, func(), error)

	mu     sync.Mutex
	warned map[string]string
}

func (b *Builder) warnOnce(key, msg string, args ...any) {
	if b.Log == nil {
		return
	}
	b.mu.Lock()
	if b.warned == nil {
		b.warned = map[string]string{}
	}
	if b.warned[key] == msg {
		b.mu.Unlock()
		return
	}
	b.warned[key] = msg
	b.mu.Unlock()
	b.Log.Warn(msg, args...)
}

func (b *Builder) clearWarn(key string) {
	b.mu.Lock()
	delete(b.warned, key)
	b.mu.Unlock()
}

// Sources reads the registry NOW and returns the sources of the trusted, policy-conformant managed OLTs. It is the collector's Extra hook: it runs at every round.
func (b *Builder) Sources() []collector.OLTSource {
	items, err := b.Store.List()
	if err != nil {
		b.warnOnce("registry", "managed olts: the registry cannot be used; no managed OLT is collected (fail closed)", "err", err)
		return nil
	}
	b.clearWarn("registry")
	staticName, staticDev := map[string]bool{}, map[string]bool{}
	for _, s := range b.Static {
		staticName[s.Name], staticDev[s.DeviceKey] = true, true
	}
	var use []managedolts.Entry
	seenDev := map[string]bool{}
	for _, it := range items {
		e := it.Entry
		if !it.Trusted {
			continue
		}
		switch {
		case staticName[e.Name] || staticDev[e.DeviceKey()]:
			b.warnOnce("conflict|"+e.Name, "managed olts: not collected, it clashes with a static OLT (the static one wins)", "olt", e.Name)
			continue
		case seenDev[e.DeviceKey()]:
			b.warnOnce("dup|"+e.Name, "managed olts: not collected, another managed OLT already is this device", "olt", e.Name)
			continue
		}
		if code := b.Policy.Check(e); code != "" {
			b.warnOnce("policy|"+e.Name, "managed olts: not collected, it no longer fits the local policy", "olt", e.Name, "code", code)
			continue
		}
		if len(b.Static)+len(use) >= b.Policy.Max {
			b.warnOnce("max|"+e.Name, "managed olts: not collected, the maximum of OLTs of this Edge (managed_olts.max_olts) is reached", "olt", e.Name)
			continue
		}
		if len(b.Policy.PonPorts) == 0 {
			b.warnOnce("pon|"+e.Name, "managed olts: trusted but not collected: managed_olts.pon_ports is empty (the delivery does not carry PON ports)", "olt", e.Name)
			continue
		}
		b.clearWarn("conflict|" + e.Name)
		b.clearWarn("dup|" + e.Name)
		b.clearWarn("policy|" + e.Name)
		b.clearWarn("max|" + e.Name)
		b.clearWarn("pon|" + e.Name)
		seenDev[e.DeviceKey()] = true
		use = append(use, e)
	}
	if len(use) == 0 {
		return nil
	}
	hostports := make([]string, 0, len(use))
	for _, e := range use {
		hostports = append(hostports, e.HostPort())
	}
	sort.Strings(hostports)
	list, err := b.Allow.With(hostports)
	if err != nil {
		b.warnOnce("allowlist", "managed olts: the dial list could not be built; nothing is collected", "err", err)
		return nil
	}
	out := make([]collector.OLTSource, 0, len(use))
	for _, e := range use {
		out = append(out, b.source(e, list))
	}
	return out
}

// verify is the last look before a session: the entry must still be the trusted one (a remove, a change or an untrust between the round's start and now stops it).
func (b *Builder) verify(e managedolts.Entry) error {
	it, found, err := b.Store.Get(e.Name)
	if err != nil {
		return fmt.Errorf("managed olt state: %w", err)
	}
	if !found || !it.Trusted || it.Entry.Digest() != e.Digest() {
		return ErrNotTrusted
	}
	if code := b.Policy.Check(it.Entry); code != "" {
		return fmt.Errorf("%w: %s", ErrNotTrusted, code)
	}
	return nil
}

// verifyShared is verify under the SHARED side of the state lock: a revocation (remove, change, untrust) takes the exclusive side, so it waits for whoever is inside here and
// blocks whoever comes after it. An error taking the lock is a refusal (fail closed).
func (b *Builder) verifyShared(e managedolts.Entry) error {
	release, err := b.Store.RLock()
	if err != nil {
		return fmt.Errorf("managed olt state: %w", err)
	}
	defer release()
	return b.verify(e)
}

// guardedSession checks the trust before EVERY command and holds the shared lock while the command runs (bounded by the command timeout of the session), so after a
// revocation has returned no further command is sent to the OLT, and a revocation never waits for more than the command in flight. It forwards EndProven: the transport's
// own answer about where a command ends must still reach the collector.
type guardedSession struct {
	inner olt.Session
	b     *Builder
	e     managedolts.Entry
}

func (g guardedSession) Run(ctx context.Context, cmd string) (string, error) {
	release, err := g.b.Store.RLock()
	if err != nil {
		return "", fmt.Errorf("managed olt state: %w", err)
	}
	defer release()
	if err := g.b.verify(g.e); err != nil {
		return "", err
	}
	return g.inner.Run(ctx, cmd)
}

func (g guardedSession) EndProven() bool { return olt.EndProven(g.inner) }

// guardedSNMP checks the trust before every Get and every Walk (an operation can take many paced requests, so the lock is not held across it: after a revocation no NEW
// operation starts, and the one in flight ends within its own request budget).
type guardedSNMP struct {
	inner olt.SNMPReader
	b     *Builder
	e     managedolts.Entry
}

func (g guardedSNMP) Get(ctx context.Context, oids []string) (map[string]olt.SNMPValue, error) {
	if err := g.b.verifyShared(g.e); err != nil {
		return nil, err
	}
	return g.inner.Get(ctx, oids)
}

func (g guardedSNMP) Walk(ctx context.Context, root string, maxRows int) ([]olt.SNMPRow, error) {
	if err := g.b.verifyShared(g.e); err != nil {
		return nil, err
	}
	return g.inner.Walk(ctx, root, maxRows)
}

func (b *Builder) source(e managedolts.Entry, list *allowlist.List) collector.OLTSource {
	creds := config.OLTConfig{CredentialsFile: b.Store.CredsPath(e.Name), Transport: e.Transport}
	src := collector.OLTSource{
		Name: e.Name, Ports: b.Policy.PonPorts, CloudID: e.CloudID,
		SNMPKey: config.DeviceKey(e.HostPort()), Interval: creds.OLTInterval(),
	}
	if e.Transport == managedolts.TransportSNMP {
		src.SNMPDriver = olt.HuaweiSNMP{}
		src.OpenSNMP = func(ctx context.Context) (olt.SNMPReader, func(), error) {
			if err := b.verify(e); err != nil {
				return nil, nil, err
			}
			community, err := creds.Community("") // the automatic credentials file only: no static fallback exists for a managed OLT
			if err != nil {
				return nil, nil, err
			}
			// the trust is looked at once more at the moment the agent is contacted (the allowlist is asked exactly there), not only before the credentials were read
			cfg := olt.SNMPConfig{Addr: e.HostPort(), Community: community, Allowed: func(hp string) bool { return b.verifyShared(e) == nil && list.Allowed(hp) }}
			open := olt.DialSNMP
			if b.OpenSNMP != nil {
				open = b.OpenSNMP
			}
			r, closeFn, err := open(ctx, cfg)
			if err != nil {
				return nil, nil, err
			}
			return guardedSNMP{inner: r, b: b, e: e}, closeFn, nil
		}
		return src
	}
	var drv olt.Driver = olt.Huawei{}
	if e.Vendor == "zte" {
		drv = olt.ZTE{}
	}
	src.Driver = drv
	src.Open = func(ctx context.Context) (olt.Session, func(), error) {
		if err := b.verify(e); err != nil {
			return nil, nil, err
		}
		user, pw, err := creds.SSHLogin()
		if err != nil {
			return nil, nil, err
		}
		// the trust is looked at once more at the moment the TCP connection is made, after the credentials were read, and the shared lock is held until the connection is
		// established: a revocation that returned is never followed by a connection authorised before it (it waits for the dial in flight and blocks the next ones)
		dial := func(ctx context.Context, network, addr string) (net.Conn, error) {
			release, err := b.Store.RLock()
			if err != nil {
				return nil, fmt.Errorf("managed olt state: %w", err)
			}
			defer release()
			if err := b.verify(e); err != nil {
				return nil, err
			}
			return list.DialContext(ctx, network, addr)
		}
		cfg := olt.SSHConfig{Addr: e.HostPort(), User: user, Password: pw, HostKeySHA256: e.HostKeySHA256, Dial: dial,
			Shell: e.SSHMode == managedolts.ModeShell, Legacy: e.LegacySSH}
		var raw olt.Session
		var closeFn func()
		if b.OpenSSH != nil {
			if raw, closeFn, err = b.OpenSSH(ctx, cfg); err != nil {
				return nil, nil, err
			}
		} else {
			s, err := olt.DialSSH(ctx, cfg)
			if err != nil {
				return nil, nil, err
			}
			raw, closeFn = s, func() { s.Close() }
		}
		return guardedSession{inner: raw, b: b, e: e}, closeFn, nil
	}
	return src
}
