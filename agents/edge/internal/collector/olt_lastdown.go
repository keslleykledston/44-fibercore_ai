package collector

import (
	"context"
	"sort"
	"time"

	"github.com/keslleykledston/44-fibercore_ai/agents/edge/internal/olt"
)

// LastDownSource is the optional, read-only SNMP side channel of a CLI source: it fetches the OLT's own "last down time" of the offline ONUs
// (the CLI listing does not carry it). It never changes which OLT a snapshot belongs to and never fails a collection.
type LastDownSource struct {
	Key     string // guard key; MUST differ from the CLI entry's so that an SNMP run does not spend the CLI interval/cooldown (or the reverse)
	Every   time.Duration
	Driver  olt.SNMPDriver
	Open    func(ctx context.Context) (olt.SNMPReader, func(), error)
	Timeout time.Duration // wall-clock budget of one run (0 = lastDownTimeout)
}

const (
	lastDownTimeout = 8 * time.Minute
	lastDownChunk   = 8 // PONs per driver call: a run cut short by the budget keeps the chunks it finished
)

// lastDownState is what the Edge remembers between collections of one OLT.
type lastDownState struct {
	offlinePons map[string]bool      // PONs that had a non-online ONU in the last CLI snapshot: the only ones worth reading
	at          map[string]time.Time // serial -> the OLT's "last down time" (only for ONUs still offline)
}

func (o *OLT) ldState(name string) *lastDownState {
	if o.ld == nil {
		o.ld = map[string]*lastDownState{}
	}
	st := o.ld[name]
	if st == nil {
		st = &lastDownState{offlinePons: map[string]bool{}, at: map[string]time.Time{}}
		o.ld[name] = st
	}
	return st
}

// applyLastDown runs right after a CLI snapshot: it remembers which PONs have offline ONUs, forgets the time of any ONU that is no longer
// offline (a new drop must be read again, never inherit the old one) and adds the remembered time to the ONUs still offline.
func (o *OLT) applyLastDown(src OLTSource, snap *olt.Snapshot) {
	if src.LastDown == nil {
		return
	}
	o.ldMu.Lock()
	defer o.ldMu.Unlock()
	st := o.ldState(src.Name)
	pons, at := map[string]bool{}, map[string]time.Time{}
	for i := range snap.ONUs {
		u := &snap.ONUs[i]
		if u.Status == "online" || u.Status == "unknown" {
			continue
		}
		pons[u.PonPath] = true
		if t, ok := st.at[u.Serial]; ok {
			at[u.Serial] = t
			tt := t
			u.LastDownAt = &tt
		}
	}
	st.offlinePons, st.at = pons, at
}

// refreshLastDown reads the OLT's last down time of the ONUs that the last CLI snapshot showed offline. Paced by its own guard entry (at most one
// run per Every, a cooldown after a failure), best effort: whatever it cannot read stays "not reported".
func (o *OLT) refreshLastDown(ctx context.Context, src OLTSource) {
	ld := src.LastDown
	if ld == nil {
		return
	}
	o.ldMu.Lock()
	var ports []string
	for p := range o.ldState(src.Name).offlinePons {
		ports = append(ports, p)
	}
	o.ldMu.Unlock()
	if len(ports) == 0 {
		return
	}
	sort.Strings(ports)
	syn := OLTSource{Name: src.Name + "/last-down", SNMPKey: ld.Key, Interval: ld.Every, OpenSNMP: ld.Open}
	_, _ = o.guarded(ctx, syn, func() ([]Item, error) { return nil, o.readLastDown(ctx, src, ports) })
}

func (o *OLT) readLastDown(ctx context.Context, src OLTSource, ports []string) error {
	ld := src.LastDown
	budget := ld.Timeout
	if budget <= 0 {
		budget = lastDownTimeout
	}
	ctx, cancel := context.WithTimeout(ctx, budget)
	defer cancel()
	r, closeFn, err := ld.Open(ctx)
	if err != nil {
		return err
	}
	defer closeFn()
	var firstErr error
	for len(ports) > 0 {
		n := min(lastDownChunk, len(ports))
		snap, err := ld.Driver.Snapshot(ctx, r, ports[:n])
		if err != nil {
			firstErr = err // a failed chunk keeps what earlier chunks gave; the guard cools the agent down
			break
		}
		o.ldMu.Lock()
		st := o.ldState(src.Name)
		for _, u := range snap.ONUs {
			if u.LastDownAt != nil && u.Status != "online" && u.Status != "unknown" {
				st.at[u.Serial] = *u.LastDownAt
			}
		}
		o.ldMu.Unlock()
		ports = ports[n:]
	}
	return firstErr
}
