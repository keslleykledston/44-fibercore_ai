package nbi

import (
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"net/http"
	"net/http/httptest"
	"strings"
	"sync"
	"testing"
	"time"
)

// pingACS simulates the NBI for the bench CPE with an IPPing object under one data-model root, plus the service WAN's own status leaf.
type pingACS struct {
	mu         sync.Mutex
	root       string // "tr181" | "tr098" | "" (no object cached)
	writable   bool
	state      string
	stateAt    time.Time
	informAt   string
	setCode    int  // 0/200 = apply; 202 = queued; other = refused/ambiguous
	fault      bool // the CPE faults the set
	completeAt int  // number of result reads after the set at which the test finishes (0 = never)
	final      string
	wanDown    bool
	missing    string // a result leaf the cached object does not list
	counters   map[string]any
	sets       [][][]string
	tasks      []map[string]any
	seq, reads int
	armed      bool
}

func newPingACS(root string) *pingACS {
	return &pingACS{root: root, writable: true, state: "None", stateAt: time.Now().Add(-time.Hour), final: speedCompleted, completeAt: 1,
		informAt: time.Now().UTC().Add(-time.Minute).Format(time.RFC3339),
		counters: map[string]any{"SuccessCount": 5.0, "FailureCount": 0.0, "AverageResponseTime": 12.0, "MinimumResponseTime": 9.0, "MaximumResponseTime": 21.0}}
}

func (f *pingACS) obj() (string, string) {
	if f.root == "tr181" {
		return pingTR181, ifaceTR181
	}
	return pingTR098, ifaceTR098
}

func (f *pingACS) doc() map[string]any {
	d := map[string]any{"_id": benchID, "_lastBoot": t0Boot, "_lastInform": f.informAt,
		"_deviceId": map[string]any{"_OUI": "00259E", "_ProductClass": "EG8145V5", "_SerialNumber": "48575443E2247AA5"}}
	if f.root == "" {
		return d
	}
	path, wan := f.obj()
	n := map[string]any{"DiagnosticsState": spLeaf(f.state, f.stateAt, f.writable), "Interface": spLeaf("", time.Now(), true), "Host": spLeaf("", time.Now(), true),
		"NumberOfRepetitions": spLeaf(0.0, time.Now(), true), "Timeout": spLeaf(0.0, time.Now(), true)}
	for k, v := range f.counters {
		if k != f.missing {
			n[k] = spLeaf(v, f.stateAt, false)
		}
	}
	merge(d, nest(path, n))
	leaf, up, down := "ConnectionStatus", "Connected", "Disconnected"
	if f.root == "tr181" {
		leaf, up, down = "Status", "Up", "Down"
	}
	v := up
	if f.wanDown {
		v = down
	}
	merge(d, nest(wan, map[string]any{leaf: spLeaf(v, time.Now(), false)}))
	return d
}

func (f *pingACS) handler() http.Handler {
	return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		f.mu.Lock()
		defer f.mu.Unlock()
		switch {
		case r.Method == http.MethodGet && r.URL.Path == "/devices":
			var q map[string]string
			_ = json.Unmarshal([]byte(r.URL.Query().Get("query")), &q)
			if q["_id"] != benchID {
				_ = json.NewEncoder(w).Encode([]any{})
				return
			}
			_ = json.NewEncoder(w).Encode([]any{f.doc()})
		case r.Method == http.MethodGet && r.URL.Path == "/tasks":
			_ = json.NewEncoder(w).Encode(f.tasks)
		case r.Method == http.MethodPost && strings.HasSuffix(r.URL.Path, "/tasks"):
			f.seq++
			id := fmt.Sprintf("pgtask%05d", f.seq)
			var b struct {
				Name   string     `json:"name"`
				Values [][]string `json:"parameterValues"`
			}
			_ = json.NewDecoder(r.Body).Decode(&b)
			if b.Name == "getParameterValues" {
				if f.armed {
					f.reads++
					if f.completeAt > 0 && f.reads >= f.completeAt {
						f.state, f.stateAt = f.final, time.Now()
					}
				}
				_ = json.NewEncoder(w).Encode(map[string]any{"_id": id})
				return
			}
			f.sets = append(f.sets, b.Values)
			switch {
			case f.setCode == 202:
				f.tasks = append(f.tasks, map[string]any{"_id": id, "name": b.Name, "device": benchID, "timestamp": time.Now().UTC().Format(time.RFC3339)})
				w.WriteHeader(202)
				_ = json.NewEncoder(w).Encode(map[string]any{"_id": id})
			case f.setCode != 0 && f.setCode != 200:
				w.WriteHeader(f.setCode)
			case f.fault:
				_ = json.NewEncoder(w).Encode(map[string]any{"_id": id, "fault": map[string]any{"code": "9007"}})
			default:
				f.armed, f.state, f.stateAt = true, speedRequested, time.Now()
				_ = json.NewEncoder(w).Encode(map[string]any{"_id": id})
			}
		case r.Method == http.MethodDelete && strings.HasPrefix(r.URL.Path, "/tasks/"):
			id := strings.TrimPrefix(r.URL.Path, "/tasks/")
			keep := f.tasks[:0]
			for _, t := range f.tasks {
				if t["_id"] != id {
					keep = append(keep, t)
				}
			}
			f.tasks = keep
		default:
			w.WriteHeader(404)
		}
	})
}

func (f *pingACS) client(t *testing.T) *Client {
	srv := httptest.NewServer(f.handler())
	t.Cleanup(srv.Close)
	c, err := New(srv.URL, srv.Client(), "")
	if err != nil {
		t.Fatal(err)
	}
	return c
}

func (f *pingACS) sentSets() int { f.mu.Lock(); defer f.mu.Unlock(); return len(f.sets) }

func pgReq(root string) PingRequest {
	if root == "tr098" {
		return PingRequest{Root: "tr098", Interface: ifaceTR098, Host: "10.20.5.9", Repetitions: 5, TimeoutMS: 1000}
	}
	return PingRequest{Root: "tr181", Interface: ifaceTR181, Host: "10.20.5.9", Repetitions: 5, TimeoutMS: 1000}
}

func runPing(t *testing.T, f *pingACS, req PingRequest) (PingOutcome, error) {
	t.Helper()
	return f.client(t).RunBenchPing(context.Background(), benchDev, req, time.Now().Add(time.Hour), 600*time.Millisecond, 10*time.Millisecond, realNow)
}

func TestPingHappyWritesOneTaskShapeAndReturnsRawCounters(t *testing.T) {
	for _, root := range []string{"tr181", "tr098"} {
		f := newPingACS(root)
		out, err := runPing(t, f, pgReq(root))
		if err != nil || !out.Attempted || out.Counters == nil {
			t.Fatalf("%s: %+v %v", root, out, err)
		}
		c := out.Counters
		if c.State != "Completed" || *c.Success != 5 || *c.Failure != 0 || *c.AvgMS != 12 || *c.MinMS != 9 || *c.MaxMS != 21 {
			t.Fatalf("%s: raw counters not carried through: %+v", root, c)
		}
		if f.sentSets() != 1 {
			t.Fatalf("%s: exactly ONE write task, got %d", root, f.sentSets())
		}
		obj, _ := f.obj()
		got := map[string]string{}
		for _, v := range f.sets[0] {
			got[strings.TrimPrefix(v[0], obj+".")] = v[1]
		}
		want := map[string]string{"Interface": pgReq(root).Interface, "Host": "10.20.5.9", "NumberOfRepetitions": "5", "Timeout": "1000", "DiagnosticsState": "Requested"}
		if len(got) != len(want) {
			t.Fatalf("%s: the task must touch exactly these leaves of the IPPing object: %v", root, got)
		}
		for k, v := range want {
			if got[k] != v {
				t.Fatalf("%s: %s = %q, want %q", root, k, got[k], v)
			}
		}
		for _, v := range f.sets[0] {
			if !strings.HasPrefix(v[0], obj+".") {
				t.Fatalf("%s: a leaf outside the IPPing object was written: %s", root, v[0])
			}
		}
	}
}

func TestPingRefusesBeforeWritingWhenTheServiceWANIsNotConnectedOrCannotBeRead(t *testing.T) {
	f := newPingACS("tr181")
	f.wanDown = true
	out, err := runPing(t, f, pgReq("tr181"))
	if !errors.Is(err, ErrSpeedWANDown) || out.Attempted || f.sentSets() != 0 {
		t.Fatalf("a WAN that is not connected must refuse before any write: %v %v %d", err, out.Attempted, f.sentSets())
	}
}

func TestPingRefusesBeforeWritingWhenTheObjectOrALeafIsNotThereOrAStateIsAlreadyRequested(t *testing.T) {
	f := newPingACS("")
	if _, err := runPing(t, f, pgReq("tr181")); !errors.Is(err, ErrSpeedUnsupported) || f.sentSets() != 0 {
		t.Fatalf("no IPPing object: %v", err)
	}
	g := newPingACS("tr181")
	g.writable = false
	if _, err := runPing(t, g, pgReq("tr181")); !errors.Is(err, ErrSpeedUnsupported) || g.sentSets() != 0 {
		t.Fatalf("a state leaf that is not writable: %v", err)
	}
	h := newPingACS("tr181")
	h.missing = "AverageResponseTime"
	if _, err := runPing(t, h, pgReq("tr181")); !errors.Is(err, ErrSpeedUnsupported) || h.sentSets() != 0 {
		t.Fatalf("a missing result leaf: %v", err)
	}
	b := newPingACS("tr181")
	b.state = speedRequested
	if _, err := runPing(t, b, pgReq("tr181")); !errors.Is(err, ErrSpeedBusy) || b.sentSets() != 0 {
		t.Fatalf("a diagnostic already requested: %v", err)
	}
}

func TestPingQueuedTaskIsRemovedAndNothingRuns(t *testing.T) {
	f := newPingACS("tr181")
	f.setCode = 202
	out, err := runPing(t, f, pgReq("tr181"))
	if !IsNotDelivered(err) || !out.Attempted || len(f.tasks) != 0 || f.sentSets() != 1 {
		t.Fatalf("a queued request must be removed and never resent: %v %+v tasks=%d sets=%d", err, out, len(f.tasks), f.sentSets())
	}
}

func TestPingRefusalAndFaultAreNotDeliveredAmbiguityIsNot(t *testing.T) {
	r := newPingACS("tr181")
	r.setCode = 400
	if _, err := runPing(t, r, pgReq("tr181")); !IsNotDelivered(err) {
		t.Fatalf("a refusal is not delivered: %v", err)
	}
	fl := newPingACS("tr181")
	fl.fault = true
	if _, err := runPing(t, fl, pgReq("tr181")); !IsNotDelivered(err) {
		t.Fatalf("a CPE fault is not delivered: %v", err)
	}
	a := newPingACS("tr181")
	a.setCode = 503
	if _, err := runPing(t, a, pgReq("tr181")); err == nil || IsNotDelivered(err) {
		t.Fatalf("a 5xx is ambiguous, never 'not delivered': %v", err)
	}
	if a.sentSets() != 1 {
		t.Fatalf("never resent: %d", a.sentSets())
	}
}

func TestPingTimeoutKeepsTheAttemptAndNeverResends(t *testing.T) {
	f := newPingACS("tr181")
	f.completeAt = 0
	out, err := runPing(t, f, pgReq("tr181"))
	if !errors.Is(err, ErrPingTimeout) || !out.Attempted || out.Counters != nil || f.sentSets() != 1 {
		t.Fatalf("%v %+v sets=%d", err, out, f.sentSets())
	}
}

func TestPingADeviceErrorStateIsReportedAndAnOldResultIsNotMistakenForThisTest(t *testing.T) {
	e := newPingACS("tr181")
	e.final = "Error_CannotResolveHostName"
	out, err := runPing(t, e, pgReq("tr181"))
	if err != nil || out.Counters == nil || out.Counters.State != "Error_CannotResolveHostName" {
		t.Fatalf("%+v %v", out, err)
	}
	// a finished state older than the request is an earlier test's result
	o := newPingACS("tr181")
	o.state, o.stateAt = speedCompleted, time.Now().Add(-time.Hour)
	if cn := finishedPing(map[string]speedLeaf{speedStateLeaf: {Value: speedCompleted, At: o.stateAt}}, time.Now()); cn != nil {
		t.Fatalf("an old result must be ignored: %+v", cn)
	}
}

func TestPingRequestShapeIsClosed(t *testing.T) {
	bad := []PingRequest{
		{Root: "tr069", Interface: ifaceTR181, Host: "10.20.5.9", Repetitions: 5, TimeoutMS: 1000},
		{Root: "tr181", Interface: "", Host: "10.20.5.9", Repetitions: 5, TimeoutMS: 1000},
		{Root: "tr181", Interface: "Device.IP.Interface.1;x", Host: "10.20.5.9", Repetitions: 5, TimeoutMS: 1000},
		{Root: "tr181", Interface: ifaceTR181, Host: "dns.example.test", Repetitions: 5, TimeoutMS: 1000},
		{Root: "tr181", Interface: ifaceTR181, Host: "fe80::1%eth0", Repetitions: 5, TimeoutMS: 1000},
		{Root: "tr181", Interface: ifaceTR181, Host: "::ffff:9.9.9.9", Repetitions: 5, TimeoutMS: 1000},
		{Root: "tr181", Interface: ifaceTR181, Host: "10.20.5.9", Repetitions: 0, TimeoutMS: 1000},
		{Root: "tr181", Interface: ifaceTR181, Host: "10.20.5.9", Repetitions: 11, TimeoutMS: 1000},
		{Root: "tr181", Interface: ifaceTR181, Host: "10.20.5.9", Repetitions: 5, TimeoutMS: 50},
		{Root: "tr181", Interface: ifaceTR181, Host: "10.20.5.9", Repetitions: 5, TimeoutMS: 60000},
	}
	for i, r := range bad {
		f := newPingACS("tr181")
		if _, err := runPing(t, f, r); !errors.Is(err, ErrPingInvalid) || f.sentSets() != 0 {
			t.Errorf("case %d must be refused before any request: %v", i, err)
		}
	}
}

func TestPingCounterConversionKeepsOnlyInRangeIntegers(t *testing.T) {
	for in, want := range map[any]int64{5.0: 5, "12": 12, 0.0: 0} {
		if g := pingInt(in); g == nil || *g != want {
			t.Errorf("%v -> %v", in, g)
		}
	}
	for _, in := range []any{5.5, -1.0, "x", nil, 1e12, 90_000_000.0} {
		if pingInt(in) != nil {
			t.Errorf("%v must be 'not reported'", in)
		}
	}
}

func TestPingACounterTheCPEDidNotReturnAfterTheRequestIsLeftOutNeverReusedFromAnEarlierTest(t *testing.T) {
	since := time.Now()
	fresh, old := since.Add(time.Second), since.Add(-time.Hour)
	l := map[string]speedLeaf{
		speedStateLeaf: {Value: speedCompleted, At: fresh}, "SuccessCount": {Value: 5.0, At: fresh}, "FailureCount": {Value: 0.0, At: fresh},
		"AverageResponseTime": {Value: 12.0, At: old}, "MinimumResponseTime": {Value: 9.0, At: fresh}, // the average was NOT re-read: it still carries an earlier test's value
	}
	cn := finishedPing(l, since)
	if cn == nil || cn.AvgMS != nil || cn.MaxMS != nil || cn.Success == nil || *cn.Success != 5 || cn.MinMS == nil || *cn.MinMS != 9 {
		t.Fatalf("only leaves read after the request may be reported: %+v", cn)
	}
}

func TestACounterReadBeforeTheRequestIsNeverReportedEvenInsideTheClockTolerance(t *testing.T) {
	since := time.Now()
	inside := since.Add(-taskClockSkew / 2) // older than the request, but within the tolerance the STATE leaf enjoys
	l := map[string]speedLeaf{speedStateLeaf: {Value: speedCompleted, At: inside}, "SuccessCount": {Value: 5.0, At: inside}, "FailureCount": {Value: 0.0, At: since.Add(time.Second)},
		"AverageResponseTime": {Value: 12.0, At: since}, "MinimumResponseTime": {Value: 9.0, At: since.Add(time.Second)}, "MaximumResponseTime": {Value: 21.0, At: since.Add(time.Second)}}
	cn := finishedPing(l, since)
	if cn == nil || cn.Success != nil || cn.AvgMS != nil || cn.Failure == nil || cn.MinMS == nil || cn.MaxMS == nil {
		t.Fatalf("ping: a counter stamped at or before the request must be left out: %+v", cn)
	}
	sl := map[string]speedLeaf{speedStateLeaf: {Value: speedCompleted, At: inside}, "BOMTime": {Value: "2026-10-31T12:00:00Z", At: inside}, "EOMTime": {Value: "2026-10-31T12:00:08Z", At: since.Add(time.Second)},
		"TestBytesReceived": {Value: 10_000_000.0, At: since}, "TotalBytesReceived": {Value: 10_001_234.0, At: since.Add(time.Second)}}
	sc := finishedCounters(sl, since)
	if sc == nil || sc.BOM != "" || sc.TestBytesReceived != nil || sc.EOM == "" || sc.TotalBytesReceived == nil {
		t.Fatalf("speed: the same rule: %+v", sc)
	}
}
