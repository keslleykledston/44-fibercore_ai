// Package ping is the local catalog of the ICMP ping destinations of the bench diagnostics (ADR-0030 amendment of 2026-10-31, ADR-0039 item 2).
//
// The Cloud names a destination only by a LOGICAL id; the address lives here, in the Edge's own configuration, validated with exactly the rules the throughput
// test destinations obey (internal/speed.ParseDestination): an IP literal (nothing to resolve), never loopback, link-local, metadata, multicast or reserved; an
// INTERNET destination never private, CGNAT or documentation; a CORE destination inside the configured prefixes. The Edge also fixes the test shape (number of
// repetitions and timeout): the Cloud can neither choose nor change them.
package ping

import (
	"errors"
	"fmt"
	"net/netip"
	"sort"

	"github.com/keslleykledston/44-fibercore_ai/agents/edge/internal/speed"
)

// The only shape a ping test ever has (ADR-0030 amendment, item 1, line Q1).
const (
	Repetitions = 5
	TimeoutMS   = 1000
	maxTargets  = 8
)

// TargetConfig is one entry of the local `ping.targets` list.
type TargetConfig struct {
	ID   string `json:"id"`
	Kind string `json:"kind"` // CORE | INTERNET
	Host string `json:"host"` // an IP literal
}

// Config is the local `ping` section.
type Config struct {
	Enabled   bool           `json:"enabled"`
	CoreCIDRs []string       `json:"core_cidrs"` // where a CORE target may live; required with any CORE target
	Targets   []TargetConfig `json:"targets"`
}

// Target is a validated destination.
type Target struct {
	ID   string
	Kind string
	Addr netip.Addr
}

// Catalog is the set of validated destinations.
type Catalog struct {
	byID map[string]Target
}

// ErrUnknownTarget is a destination id this Edge does not list.
var ErrUnknownTarget = errors.New("ping: destination unknown on this edge")

// New validates the section. Any problem is an error: the module must not start with a partly valid configuration.
func New(c Config) (*Catalog, error) {
	if len(c.Targets) < 1 || len(c.Targets) > maxTargets {
		return nil, fmt.Errorf("ping: targets must list 1 to %d entries", maxTargets)
	}
	core, err := speed.ParseCoreCIDRs(c.CoreCIDRs, "ping")
	if err != nil {
		return nil, err
	}
	cat := &Catalog{byID: map[string]Target{}}
	for _, t := range c.Targets {
		if !speed.IDRe.MatchString(t.ID) {
			return nil, errors.New("ping: target id must be a lower-case logical name")
		}
		if _, dup := cat.byID[t.ID]; dup {
			return nil, fmt.Errorf("ping: target %q listed twice", t.ID)
		}
		if t.Kind != speed.KindCore && t.Kind != speed.KindInternet {
			return nil, fmt.Errorf("ping: target %q kind must be CORE or INTERNET", t.ID)
		}
		ip, err := speed.ParseDestination("ping", t.ID, t.Kind, t.Host, core)
		if err != nil {
			return nil, err
		}
		cat.byID[t.ID] = Target{ID: t.ID, Kind: t.Kind, Addr: ip}
	}
	return cat, nil
}

// Target returns the validated destination for a logical id.
func (c *Catalog) Target(id string) (Target, bool) {
	t, ok := c.byID[id]
	return t, ok
}

// Check is what the envelope verifier runs: the signed destination must be one this Edge lists.
func (c *Catalog) Check(id string) error {
	if _, ok := c.byID[id]; !ok {
		return ErrUnknownTarget
	}
	return nil
}

// All returns the targets in a stable order.
func (c *Catalog) All() []Target {
	out := make([]Target, 0, len(c.byID))
	for _, t := range c.byID {
		out = append(out, t)
	}
	sort.Slice(out, func(i, j int) bool { return out[i].ID < out[j].ID })
	return out
}
