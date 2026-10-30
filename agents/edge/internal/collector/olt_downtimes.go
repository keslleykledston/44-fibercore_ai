package collector

import (
	"time"

	"github.com/keslleykledston/44-fibercore_ai/agents/edge/internal/olt"
)

// dtState is what the Edge remembers, per OLT, about the last down times read over the CLI. A time is the OLT's record of ONE outage, so once
// read it is kept for as long as the ONU stays offline and never read again; an ONU seen online forgets it (its next drop is a new outage).
type dtState struct {
	at   map[string]time.Time // serial -> the OLT's last down time
	none map[string]bool      // serial -> the OLT had no usable record for the current outage: not asked again until the ONU has been online
}

func (o *OLT) dtStateFor(name string) *dtState {
	if o.dt == nil {
		o.dt = map[string]*dtState{}
	}
	st := o.dt[name]
	if st == nil {
		st = &dtState{at: map[string]time.Time{}, none: map[string]bool{}}
		o.dt[name] = st
	}
	return st
}

// downReads builds the callbacks of one collection: Pick forgets what no longer applies (every ONU that is not offline) and chooses up to
// MaxPerRound offline ONUs the Edge has no answer for yet, in listing order, so every outage is read once over successive rounds.
func (o *OLT) downReads(src OLTSource) olt.DownReads {
	return olt.DownReads{
		Pick: func(listing []olt.ONU) []olt.ONU {
			o.ldMu.Lock()
			defer o.ldMu.Unlock()
			st := o.dtStateFor(src.Name)
			var picks []olt.ONU
			for _, u := range listing {
				if u.Status == "offline" {
					_, known := st.at[u.Serial]
					if !known && !st.none[u.Serial] && u.HasOntID && len(picks) < src.DownTimes.MaxPerRound {
						picks = append(picks, u)
					}
					continue
				}
				if u.Status == "online" { // "unknown" says nothing about the outage: keep what is known
					delete(st.at, u.Serial)
					delete(st.none, u.Serial)
				}
			}
			return picks
		},
		Done: func(serial string, at *time.Time) {
			o.ldMu.Lock()
			defer o.ldMu.Unlock()
			st := o.dtStateFor(src.Name)
			if at != nil {
				st.at[serial] = *at
			} else {
				st.none[serial] = true
			}
		},
	}
}

// applyDownTimes puts the remembered time on the offline ONUs of the snapshot.
func (o *OLT) applyDownTimes(src OLTSource, snap *olt.Snapshot) {
	if src.DownTimes == nil {
		return
	}
	o.ldMu.Lock()
	defer o.ldMu.Unlock()
	st := o.dtStateFor(src.Name)
	for i := range snap.ONUs {
		u := &snap.ONUs[i]
		if t, ok := st.at[u.Serial]; ok && u.Status == "offline" {
			tt := t
			u.LastDownAt = &tt
		}
	}
}
