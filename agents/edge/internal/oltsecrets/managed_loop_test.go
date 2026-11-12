package oltsecrets

import (
	"context"
	"net/http"
	"net/http/httptest"
	"os"
	"path/filepath"
	"strings"
	"testing"
	"time"

	"github.com/keslleykledston/44-fibercore_ai/agents/edge/internal/config"
	"github.com/keslleykledston/44-fibercore_ai/agents/edge/internal/gateway"
	"github.com/keslleykledston/44-fibercore_ai/agents/edge/internal/managedolts"
)

func newManagedLoop(t *testing.T) (*menv, *loop, *StateReporter) {
	t.Helper()
	m := newManagedEnv(t, nil)
	f := &fakeCloud{t: t}
	srv := httptest.NewServer(http.HandlerFunc(f.handler))
	t.Cleanup(srv.Close)
	gw := gateway.New(srv.URL, "cid", "sec", srv.Client())
	l := &loop{e: m.env, cloud: f, gw: gw, clock: time.Unix(1_800_000_000, 0)}
	rep := &StateReporter{Store: m.st, Cloud: gw, Log: m.proc.Log, Now: func() time.Time { return l.clock }}
	m.proc.Managed.OnRemoved = rep.NoteRemoved
	l.worker = &Worker{Cloud: gw, Proc: m.proc, Log: m.proc.Log, Now: func() time.Time { return l.clock }, State: rep}
	return m, l, rep
}

func (l *loop) lastReport() []gateway.ManagedState {
	if len(l.cloud.stateReports) == 0 {
		return nil
	}
	return l.cloud.stateReports[len(l.cloud.stateReports)-1]
}

func TestLoopAppliedResultCarriesAwaitingLocalTrustAndTheStateIsReported(t *testing.T) {
	m, l, _ := newManagedLoop(t)
	l.enqueue(spec{id: mDelivID, olt: mName, kind: config.KindOLTConnection, plaintext: connBody(nil)})
	l.tick()
	if len(l.cloud.results) != 1 || l.cloud.results[0]["outcome"] != "applied" || l.cloud.results[0]["code"] != "awaiting_local_trust" {
		t.Fatalf("results: %v", l.cloud.results)
	}
	if rep := l.lastReport(); len(rep) != 1 || rep[0].CloudID != mCloudID || rep[0].State != "awaiting_local_trust" {
		t.Fatalf("report: %v", l.cloud.stateReports)
	}
	// nothing changed: not repeated every round
	n := len(l.cloud.stateReports)
	l.tick()
	l.tick()
	if len(l.cloud.stateReports) != n {
		t.Fatalf("an unchanged state must not be re-sent every round: %d -> %d", n, len(l.cloud.stateReports))
	}
	// the operator trusts it locally: the next round reports it
	m.trust()
	l.tick()
	if rep := l.lastReport(); len(l.cloud.stateReports) != n+1 || rep[0].State != "trusted" {
		t.Fatalf("%v", l.cloud.stateReports)
	}
	// and it is repeated now and then even when nothing changed
	l.clock = l.clock.Add(ReportEvery)
	l.worker.Tick(context.Background())
	if len(l.cloud.stateReports) != n+2 {
		t.Fatalf("the periodic repeat is missing: %d", len(l.cloud.stateReports))
	}
	// a remove is reported once as "removed"
	l.enqueue(spec{id: mDeliv2, olt: mName, kind: config.KindOLTConnection, plaintext: `{"kind":"olt_connection","action":"remove","cloud_id":"` + mCloudID + `"}`})
	l.tick()
	if rep := l.lastReport(); len(rep) != 1 || rep[0].CloudID != mCloudID || rep[0].State != "removed" {
		t.Fatalf("%v", l.cloud.stateReports)
	}
	n = len(l.cloud.stateReports)
	l.tick()
	l.tick()
	if len(l.cloud.stateReports) != n {
		t.Fatal("removed must be reported once, and an empty registry reports nothing")
	}
}

func TestStateReportBodyIsExactlyTheContract(t *testing.T) {
	var bodies []string
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.URL.Path == "/v1/auth/service-token" {
			w.Write([]byte(`{"access_token":"tok"}`))
			return
		}
		b := make([]byte, 4096)
		n, _ := r.Body.Read(b)
		bodies = append(bodies, r.Method+" "+r.URL.Path+" "+string(b[:n]))
		w.WriteHeader(204)
	}))
	defer srv.Close()
	gw := gateway.New(srv.URL, "cid", "sec", srv.Client())
	out, st, err := gw.ReportManagedState(context.Background(), []gateway.ManagedState{{CloudID: mCloudID, State: "trusted"}, {CloudID: cid(7), State: "removed"}})
	if out != gateway.Delivered || st != 204 || err != nil {
		t.Fatalf("%v %d %v", out, st, err)
	}
	want := `POST /v1/edge/managed-olts/state {"items":[{"cloud_id":"` + mCloudID + `","state":"trusted"},{"cloud_id":"` + cid(7) + `","state":"removed"}]}`
	if len(bodies) != 1 || bodies[0] != want {
		t.Fatalf("%q", bodies)
	}
	if o, _, _ := gw.ReportManagedState(context.Background(), nil); o != gateway.Rejected {
		t.Fatal("an empty report is not sent")
	}
	if o, _, _ := gw.ReportManagedState(context.Background(), make([]gateway.ManagedState, 65)); o != gateway.Rejected {
		t.Fatal("more than 64 items is not sent")
	}
}

func TestOlderCloudWithoutTheRouteIsNotAnError(t *testing.T) {
	m, l, _ := newManagedLoop(t)
	l.cloud.stateStatus = 404
	l.enqueue(spec{id: mDelivID, olt: mName, kind: config.KindOLTConnection, plaintext: connBody(nil)})
	l.tick()
	l.tick()
	l.tick()
	// the delivery itself is unaffected
	if len(l.cloud.results) != 1 || l.cloud.results[0]["outcome"] != "applied" {
		t.Fatalf("%v", l.cloud.results)
	}
	if n := strings.Count(m.logs.String(), "older Cloud"); n != 1 {
		t.Fatalf("the 404 must be logged exactly once, got %d", n)
	}
	// the route appears later (the Cloud is upgraded): reported after the retry window
	l.cloud.stateStatus = 0
	l.clock = l.clock.Add(OldCloudRetry)
	l.worker.Tick(context.Background())
	if rep := l.lastReport(); len(rep) != 1 || rep[0].State != "awaiting_local_trust" {
		t.Fatalf("%v", l.cloud.stateReports)
	}
}

func TestTransientStateFailuresAreRetriedAndNeverFailADelivery(t *testing.T) {
	_, l, _ := newManagedLoop(t)
	l.cloud.stateStatus = 503
	l.enqueue(spec{id: mDelivID, olt: mName, kind: config.KindOLTConnection, plaintext: connBody(nil)})
	l.tick()
	l.tick()
	if len(l.cloud.results) != 1 || l.cloud.results[0]["outcome"] != "applied" || len(l.cloud.stateReports) != 0 {
		t.Fatalf("%v %v", l.cloud.results, l.cloud.stateReports)
	}
	l.cloud.stateStatus = 0
	l.tick()
	if len(l.cloud.stateReports) != 1 {
		t.Fatalf("a 5xx must be retried at the next round: %v", l.cloud.stateReports)
	}
	// 429: the wait is respected (nothing sent during it), then it goes out
	_, l2, _ := newManagedLoop(t)
	l2.cloud.stateStatus = 429
	l2.enqueue(spec{id: mDelivID, olt: mName, kind: config.KindOLTConnection, plaintext: connBody(nil)})
	l2.tick()
	if len(l2.cloud.results) != 1 || len(l2.cloud.stateReports) != 0 {
		t.Fatalf("%v %v", l2.cloud.results, l2.cloud.stateReports)
	}
	// any other refusal waits a few minutes
	_, l3, _ := newManagedLoop(t)
	l3.cloud.stateStatus = 422
	l3.enqueue(spec{id: mDelivID, olt: mName, kind: config.KindOLTConnection, plaintext: connBody(nil)})
	l3.tick()
	l3.cloud.stateStatus = 0
	l3.tick()
	if len(l3.cloud.stateReports) != 0 {
		t.Fatal("a refused report must back off")
	}
	l3.clock = l3.clock.Add(RefusedBackoff)
	l3.worker.Tick(context.Background())
	if len(l3.cloud.stateReports) != 1 {
		t.Fatal("and try again after the backoff")
	}
}

type recCloud struct {
	reports [][]gateway.ManagedState
}

func (r *recCloud) ReportManagedState(_ context.Context, items []gateway.ManagedState) (gateway.Outcome, int, error) {
	r.reports = append(r.reports, append([]gateway.ManagedState{}, items...))
	return gateway.Delivered, 204, nil
}
func (r *recCloud) SecretsWaitUntil() time.Time { return time.Time{} }

func TestStateReportIsSplitIntoChunksOfAtMost64(t *testing.T) {
	m := newManagedEnv(t, nil)
	cloud := &recCloud{}
	rep := &StateReporter{Store: m.st, Cloud: cloud, Now: func() time.Time { return m.now }}
	for i := 0; i < 70; i++ {
		rep.NoteRemoved(cid(i))
	}
	rep.Tick(context.Background())
	if len(cloud.reports) != 2 || len(cloud.reports[0]) != 64 || len(cloud.reports[1]) != 6 {
		t.Fatalf("%d chunks", len(cloud.reports))
	}
	for _, c := range cloud.reports {
		for _, it := range c {
			if it.State != "removed" {
				t.Fatalf("%+v", it)
			}
		}
	}
	rep.Tick(context.Background())
	if len(cloud.reports) != 2 {
		t.Fatal("reported once")
	}
	// an OLT added again is not "removed"
	m.wantSet(mDelivID, nil, CodeAwaitingLocalTrust)
	rep.NoteRemoved(mCloudID)
	rep.Tick(context.Background())
	last := cloud.reports[len(cloud.reports)-1]
	if len(last) != 1 || last[0].State != "awaiting_local_trust" {
		t.Fatalf("%v", last)
	}
}

func TestUnreadableRegistryIsNotReported(t *testing.T) {
	m := newManagedEnv(t, nil)
	cloud := &recCloud{}
	rep := &StateReporter{Store: m.st, Cloud: cloud}
	m.wantSet(mDelivID, nil, CodeAwaitingLocalTrust)
	chmodLoose(t, m)
	rep.Tick(context.Background())
	if len(cloud.reports) != 0 {
		t.Fatal("nothing may be reported from a registry that cannot be trusted")
	}
}

func chmodLoose(t *testing.T, m *menv) {
	t.Helper()
	if err := os.Chmod(filepath.Join(m.dir, managedolts.RegistryFile), 0o644); err != nil {
		t.Fatal(err)
	}
}
