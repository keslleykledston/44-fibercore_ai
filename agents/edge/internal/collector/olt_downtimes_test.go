package collector

import (
	"context"
	"encoding/json"
	"fmt"
	"testing"
	"time"

	"github.com/keslleykledston/44-fibercore_ai/agents/edge/internal/olt"
)

// dtDriver is a CLI driver that implements olt.DownReader: the "OLT" knows a last down time for some serials.
type dtDriver struct {
	onus  *[]olt.ONU
	times map[string]time.Time
	asked *[]string
	nopeS map[string]bool // serials the OLT has no usable record for
}

func (dtDriver) Vendor() string      { return "huawei" }
func (dtDriver) Allowed(string) bool { return true }
func (dtDriver) Identify(context.Context, olt.Session) (olt.Identity, error) {
	return olt.Identity{Vendor: "huawei", Model: "MA5608T", Firmware: "MA5600V800R015C00"}, nil
}
func (d dtDriver) Snapshot(context.Context, olt.Session, []string) (olt.Snapshot, error) {
	return olt.Snapshot{PONs: []olt.PON{{Path: "0/0/1", Status: "up"}}, ONUs: append([]olt.ONU(nil), *d.onus...)}, nil
}
func (d dtDriver) SnapshotWithDownTimes(ctx context.Context, s olt.Session, ports []string, r olt.DownReads) (olt.Snapshot, error) {
	snap, _ := d.Snapshot(ctx, s, ports)
	for _, u := range r.Pick(snap.ONUs) {
		*d.asked = append(*d.asked, u.Serial)
		if t, ok := d.times[u.Serial]; ok && !d.nopeS[u.Serial] {
			tt := t
			r.Done(u.Serial, &tt)
		} else {
			r.Done(u.Serial, nil)
		}
	}
	return snap, nil
}

func newDT(t *testing.T, max int, n int) (*OLT, *ldClock, *[]olt.ONU, *dtDriver, *[]string) {
	t.Helper()
	clock := &ldClock{t: time.Date(2026, 10, 30, 12, 0, 0, 0, time.UTC)}
	var onus []olt.ONU
	times := map[string]time.Time{}
	for i := 1; i <= n; i++ {
		s := fmt.Sprintf("HWTC%08d", i)
		onus = append(onus, olt.ONU{Serial: s, PonPath: "0/0/1", Status: "offline", OntID: i, HasOntID: true})
		times[s] = time.Date(2026, 10, 28, 8, i, 0, 0, time.UTC)
	}
	var asked []string
	drv := &dtDriver{onus: &onus, times: times, asked: &asked, nopeS: map[string]bool{}}
	src := OLTSource{Name: "OLT-DT", Driver: drv, Ports: []string{"0/0/1"}, AllowUnverified: true, Interval: 15 * time.Minute, SNMPKey: "10.0.0.9",
		Open: func(context.Context) (olt.Session, func(), error) {
			return countingSession{new(int), nil}, func() {}, nil
		},
		DownTimes: &DownTimesSource{MaxPerRound: max}}
	return &OLT{EdgeID: "e", Sources: []OLTSource{src}, Now: clock.now}, clock, &onus, drv, &asked
}

func collectDT(t *testing.T, o *OLT) map[string]string {
	t.Helper()
	items, err := o.Collect(context.Background())
	if err != nil {
		t.Fatal(err)
	}
	out := map[string]string{}
	for _, it := range items {
		var p struct {
			ONUs []struct {
				Serial     string `json:"serial"`
				LastDownAt string `json:"last_down_at"`
			} `json:"onus"`
		}
		if err := json.Unmarshal(it.Payload, &p); err != nil {
			t.Fatal(err)
		}
		for _, u := range p.ONUs {
			out[u.Serial] = u.LastDownAt
		}
	}
	return out
}

func TestDownTimesAreReadAFewPerRoundAndKeptWhileTheOnuStaysOffline(t *testing.T) {
	o, clock, _, _, asked := newDT(t, 2, 5)
	got := collectDT(t, o) // round 1: HWTC1, HWTC2 read and already on this round's payload
	if got["HWTC00000001"] != "2026-10-28T08:01:00Z" || got["HWTC00000002"] != "2026-10-28T08:02:00Z" || got["HWTC00000003"] != "" {
		t.Fatalf("round 1: %v", got)
	}
	clock.add(16 * time.Minute)
	got = collectDT(t, o)
	if got["HWTC00000001"] == "" || got["HWTC00000003"] == "" || got["HWTC00000004"] == "" || got["HWTC00000005"] != "" {
		t.Fatalf("round 2 keeps the first two and reads the next two: %v", got)
	}
	clock.add(16 * time.Minute)
	got = collectDT(t, o)
	for s, v := range got {
		if v == "" {
			t.Errorf("%s still without a time after three rounds", s)
		}
	}
	if len(*asked) != 5 {
		t.Fatalf("each outage is read exactly once, asked=%v", *asked)
	}
	clock.add(16 * time.Minute)
	collectDT(t, o)
	if len(*asked) != 5 {
		t.Fatalf("nothing left to read, asked=%v", *asked)
	}
}

func TestDownTimeIsForgottenWhenTheOnuIsSeenOnlineAndReadAgainOnTheNextDrop(t *testing.T) {
	o, clock, onus, drv, asked := newDT(t, 10, 1)
	collectDT(t, o)
	(*onus)[0].Status = "online"
	clock.add(16 * time.Minute)
	if got := collectDT(t, o); got["HWTC00000001"] != "" {
		t.Fatalf("an online ONU carries no down time: %v", got)
	}
	drv.times["HWTC00000001"] = time.Date(2026, 10, 30, 12, 10, 0, 0, time.UTC) // the new drop
	(*onus)[0].Status = "offline"
	clock.add(16 * time.Minute)
	if got := collectDT(t, o); got["HWTC00000001"] != "2026-10-30T12:10:00Z" || len(*asked) != 2 {
		t.Fatalf("the new drop must be read again, not inherit the old time: %v asked=%v", got, *asked)
	}
}

func TestOnuWithoutAUsableRecordIsNotAskedAgainDuringTheSameOutage(t *testing.T) {
	o, clock, onus, drv, asked := newDT(t, 10, 2)
	drv.nopeS["HWTC00000001"] = true
	got := collectDT(t, o)
	if got["HWTC00000001"] != "" || got["HWTC00000002"] == "" {
		t.Fatalf("%v", got)
	}
	clock.add(16 * time.Minute)
	collectDT(t, o)
	if len(*asked) != 2 {
		t.Fatalf("a missing record must not be asked again every round: %v", *asked)
	}
	(*onus)[0].Status = "online"
	clock.add(16 * time.Minute)
	collectDT(t, o)
	(*onus)[0].Status = "offline"
	delete(drv.nopeS, "HWTC00000001")
	clock.add(16 * time.Minute)
	if got := collectDT(t, o); got["HWTC00000001"] == "" || len(*asked) != 3 {
		t.Fatalf("after being online it is asked again: %v %v", got, *asked)
	}
}

func TestUnknownStateDoesNotForgetTheDownTime(t *testing.T) {
	o, clock, onus, _, asked := newDT(t, 10, 1)
	collectDT(t, o)
	(*onus)[0].Status = "unknown"
	clock.add(16 * time.Minute)
	collectDT(t, o)
	(*onus)[0].Status = "offline"
	clock.add(16 * time.Minute)
	if got := collectDT(t, o); got["HWTC00000001"] == "" || len(*asked) != 1 {
		t.Fatalf("unknown says nothing about the outage: %v %v", got, *asked)
	}
}
