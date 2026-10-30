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
	// gen counts the CLI snapshots applied. A run starts from one generation and its answers are kept only if no newer CLI snapshot was
	// applied meanwhile: a late answer must never put back a time that a newer snapshot (ONU seen online) has just cleared.
	gen uint64
	// attemptGen is the generation of the last run that was started: a run is started once per CLI snapshot, right after it, so that it ends
	// long before the next CLI snapshot.
	attemptGen uint64
	// cursor is the last PON a run finished. The next run starts after it (wrapping around), so a budget too short for every PON of a big chassis
	// still gets through all of them over successive runs instead of always re-reading the same first ones.
	cursor string
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
	st.gen++
}

// refreshLastDown reads the OLT's last down time of the ONUs that the last CLI snapshot showed offline. It never blocks the collection round:
// the read runs in the background with its OWN budget (the round's cancellation does not cut it), at most once per CLI snapshot, paced by its
// own guard entry (at most one run per Every, a cooldown after a failure). Best effort: whatever it cannot read stays "not reported".
func (o *OLT) refreshLastDown(ctx context.Context, src OLTSource) {
	ld := src.LastDown
	if ld == nil {
		return
	}
	o.ldMu.Lock()
	st := o.ldState(src.Name)
	if st.gen == 0 || st.gen == st.attemptGen || len(st.offlinePons) == 0 {
		o.ldMu.Unlock()
		return
	}
	o.ldMu.Unlock()
	bg := context.WithoutCancel(ctx)
	o.ldWG.Add(1)
	go func() {
		defer o.ldWG.Done()
		syn := OLTSource{Name: src.Name + "/last-down", SNMPKey: ld.Key, Interval: ld.Every, OpenSNMP: ld.Open}
		_, _ = o.guarded(bg, syn, func() ([]Item, error) {
			o.ldMu.Lock()
			st := o.ldState(src.Name)
			st.attemptGen = st.gen // this snapshot has its run, whatever its outcome
			gen := st.gen
			var ports []string
			for p := range st.offlinePons {
				ports = append(ports, p)
			}
			o.ldMu.Unlock()
			sort.Strings(ports)
			return nil, o.readLastDown(bg, src, ports, gen)
		})
	}()
}

// rotate returns ports (sorted) starting after the cursor, wrapping around.
func rotate(ports []string, cursor string) []string {
	i := sort.SearchStrings(ports, cursor)
	if i < len(ports) && ports[i] == cursor {
		i++
	}
	return append(append([]string(nil), ports[i:]...), ports[:i]...)
}

func (o *OLT) readLastDown(ctx context.Context, src OLTSource, ports []string, gen uint64) error {
	ld := src.LastDown
	o.ldMu.Lock()
	ports = rotate(ports, o.ldState(src.Name).cursor)
	o.ldMu.Unlock()
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
	for len(ports) > 0 {
		n := min(lastDownChunk, len(ports))
		snap, err := ld.Driver.Snapshot(ctx, r, ports[:n])
		if err != nil {
			if ctx.Err() != nil {
				return nil // our own budget ran out, not the agent's fault: keep the chunks done, the cursor continues from there next time
			}
			return err // a failed chunk keeps what earlier chunks gave; the guard cools the agent down
		}
		o.ldMu.Lock()
		st := o.ldState(src.Name)
		if st.gen != gen { // a newer CLI snapshot arrived: what was read may predate a bounce it has seen
			o.ldMu.Unlock()
			return nil
		}
		for _, u := range snap.ONUs {
			if u.LastDownAt != nil && u.Status != "online" && u.Status != "unknown" {
				st.at[u.Serial] = *u.LastDownAt
			}
		}
		st.cursor = ports[n-1]
		o.ldMu.Unlock()
		ports = ports[n:]
	}
	return nil
}
