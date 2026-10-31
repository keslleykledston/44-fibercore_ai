package nbi

import (
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"net/http"
	"net/http/httptest"
	"os"
	"strings"
	"sync"
	"testing"
	"time"
)

const (
	ifaceTR181  = "Device.IP.Interface.1"
	ifaceTR098  = "InternetGatewayDevice.WANDevice.1.WANConnectionDevice.2.WANIPConnection.1"
	urlDL       = "http://10.20.5.9:8080/dl/10mb"
	urlUL       = "http://10.20.5.9:8080/ul/10mb"
	speedObjDL  = "Device.IP.Diagnostics.DownloadDiagnostics"
	speedObjUL  = "Device.IP.Diagnostics.UploadDiagnostics"
	speedObjDL8 = "InternetGatewayDevice.DownloadDiagnostics"
	speedObjUL8 = "InternetGatewayDevice.UploadDiagnostics"
)

// speedACS simulates the NBI for the bench CPE (a TR-143 object under one data-model root) AND a production CPE that must never be touched.
type speedACS struct {
	mu          sync.Mutex
	root        string          // "tr181" | "tr098" | "both" | "" (no object cached)
	leaves      map[string]bool // result leaves the cached object lists; nil = the standard set
	writable    bool
	state       string // DiagnosticsState on the CPE now
	stateAt     time.Time
	informAt    string
	setCode     int  // 0/200 = apply; 202 = queued; other = refused/ambiguous
	fault       bool // the CPE faults the set
	getCode     int
	completeAt  int    // number of result reads after the set at which the test finishes (0 = never)
	final       string // state it finishes in
	staleResult bool   // the finished state carries an OLD timestamp (a previous test's result)
	counters    map[string]any
	log         []string
	sets        [][][]string
	tasks       []map[string]any
	seq, reads  int
	armed       bool
	other       map[string]int // writes seen per device
}

func newSpeedACS(root string) *speedACS {
	return &speedACS{root: root, writable: true, state: "None", stateAt: time.Now().Add(-time.Hour), final: speedCompleted, completeAt: 1,
		informAt: time.Now().UTC().Add(-time.Minute).Format(time.RFC3339), other: map[string]int{},
		counters: map[string]any{"BOMTime": time.Now().UTC().Format(time.RFC3339Nano), "EOMTime": time.Now().UTC().Add(8 * time.Second).Format(time.RFC3339Nano),
			"TestBytesReceived": 10000000.0, "TotalBytesReceived": 10001234.0, "TotalBytesSent": 10000000.0, "TestBytesSent": 9990000.0}}
}

var stdLeaves = map[string]bool{"DiagnosticsState": true, "BOMTime": true, "EOMTime": true, "TestBytesReceived": true, "TotalBytesReceived": true, "TotalBytesSent": true, "Interface": true}

func spLeaf(v any, at time.Time, writable bool) map[string]any {
	return map[string]any{"_value": v, "_timestamp": at.UTC().Format(time.RFC3339), "_writable": writable}
}

func nest(path string, node map[string]any) map[string]any {
	parts := strings.Split(path, ".")
	cur := node
	for i := len(parts) - 1; i >= 0; i-- {
		cur = map[string]any{parts[i]: cur}
	}
	return cur
}

func merge(dst, src map[string]any) {
	for k, v := range src {
		if m, ok := v.(map[string]any); ok {
			if d, ok := dst[k].(map[string]any); ok {
				merge(d, m)
				continue
			}
		}
		dst[k] = v
	}
}

func (f *speedACS) object() map[string]any {
	set := f.leaves
	if set == nil {
		set = stdLeaves
	}
	n := map[string]any{}
	for name := range set {
		switch name {
		case "DiagnosticsState":
			n[name] = spLeaf(f.state, f.stateAt, f.writable)
		case "Interface":
			n[name] = spLeaf("", time.Now(), true)
		default:
			n[name] = spLeaf(f.counters[name], f.stateAt, false)
		}
	}
	return n
}

func (f *speedACS) doc() map[string]any {
	d := map[string]any{"_id": benchID, "_lastBoot": t0Boot, "_lastInform": f.informAt,
		"_deviceId": map[string]any{"_OUI": "00259E", "_ProductClass": "EG8145V5", "_SerialNumber": "48575443E2247AA5"}}
	for _, p := range []struct{ root, path string }{{"tr181", speedObjDL}, {"tr181", speedObjUL}, {"tr098", speedObjDL8}, {"tr098", speedObjUL8}} {
		if f.root == p.root || f.root == "both" {
			merge(d, nest(p.path, f.object()))
		}
	}
	return d
}

func (f *speedACS) finish() {
	f.state, f.stateAt = f.final, time.Now()
	if f.staleResult {
		f.stateAt = time.Now().Add(-time.Hour)
	}
	f.counters["BOMTime"] = time.Now().UTC().Format(time.RFC3339Nano)
	f.counters["EOMTime"] = time.Now().UTC().Add(8 * time.Second).Format(time.RFC3339Nano)
}

func (f *speedACS) handler() http.Handler {
	return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		f.mu.Lock()
		defer f.mu.Unlock()
		f.log = append(f.log, r.Method+" "+r.URL.Path)
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
			id := fmt.Sprintf("sptask%05d", f.seq)
			dev := strings.TrimSuffix(strings.TrimPrefix(r.URL.Path, "/devices/"), "/tasks")
			var b struct {
				Name   string     `json:"name"`
				Values [][]string `json:"parameterValues"`
			}
			_ = json.NewDecoder(r.Body).Decode(&b)
			if b.Name == "getParameterValues" {
				if f.getCode != 0 {
					w.WriteHeader(f.getCode)
					return
				}
				if f.armed {
					f.reads++
					if f.completeAt > 0 && f.reads >= f.completeAt {
						f.finish()
					}
				}
				_ = json.NewEncoder(w).Encode(map[string]any{"_id": id})
				return
			}
			f.sets = append(f.sets, b.Values)
			if dev != benchID {
				f.other[dev]++
			}
			switch {
			case f.setCode == 202:
				f.tasks = append(f.tasks, map[string]any{"_id": id, "name": b.Name, "device": dev, "timestamp": time.Now().UTC().Format(time.RFC3339)})
				w.WriteHeader(202)
				_ = json.NewEncoder(w).Encode(map[string]any{"_id": id})
			case f.setCode != 0 && f.setCode != 200:
				if f.setCode >= 500 {
					f.tasks = append(f.tasks, map[string]any{"_id": id, "name": b.Name, "device": dev, "timestamp": time.Now().UTC().Format(time.RFC3339)})
				}
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

func (f *speedACS) client(t *testing.T) *Client {
	srv := httptest.NewServer(f.handler())
	t.Cleanup(srv.Close)
	c, err := New(srv.URL, srv.Client(), "")
	if err != nil {
		t.Fatal(err)
	}
	return c
}

func dlReq() SpeedRequest {
	return SpeedRequest{Direction: "download", Root: "tr181", Interface: ifaceTR181, URL: urlDL}
}

func ulReq() SpeedRequest {
	return SpeedRequest{Direction: "upload", Root: "tr181", Interface: ifaceTR181, URL: urlUL, FileLength: 10_000_000}
}

func runSpeed(t *testing.T, f *speedACS, req SpeedRequest) (SpeedOutcome, error) {
	t.Helper()
	return f.client(t).RunBenchSpeed(context.Background(), benchDev, req, time.Now().Add(time.Hour), 600*time.Millisecond, 10*time.Millisecond, realNow)
}

func (f *speedACS) sentSets() int { f.mu.Lock(); defer f.mu.Unlock(); return len(f.sets) }

func TestSpeedDownloadHappyWritesOneTaskAndReturnsRawCounters(t *testing.T) {
	f := newSpeedACS("tr181")
	out, err := runSpeed(t, f, dlReq())
	if err != nil || out.Counters == nil || !out.Attempted {
		t.Fatalf("out=%+v err=%v", out, err)
	}
	c := out.Counters
	if c.State != "Completed" || c.BOM == "" || c.EOM == "" || c.TestBytesReceived == nil || *c.TestBytesReceived != 10_000_000 || *c.TotalBytesReceived != 10_001_234 {
		t.Fatalf("%+v", c)
	}
	if len(f.sets) != 1 {
		t.Fatalf("exactly one write, got %d", len(f.sets))
	}
	got := map[string]string{}
	for _, v := range f.sets[0] {
		got[v[0]] = v[1]
	}
	want := map[string]string{speedObjDL + ".Interface": ifaceTR181, speedObjDL + ".DownloadURL": urlDL, speedObjDL + ".DiagnosticsState": "Requested"}
	if len(got) != len(want) {
		t.Fatalf("leaves written: %v", got)
	}
	for k, v := range want {
		if got[k] != v {
			t.Fatalf("%s=%q want %q", k, got[k], v)
		}
	}
	if len(f.other) != 0 {
		t.Fatalf("a device other than the bench was written: %v", f.other)
	}
}

func TestSpeedUploadTR098WritesTheFileLengthAndTheUploadUrl(t *testing.T) {
	f := newSpeedACS("tr098")
	req := ulReq()
	req.Root, req.Interface = "tr098", ifaceTR098
	out, err := runSpeed(t, f, req)
	if err != nil || out.Counters == nil {
		t.Fatalf("out=%+v err=%v", out, err)
	}
	if out.Counters.TotalBytesSent == nil || *out.Counters.TotalBytesSent != 10_000_000 {
		t.Fatalf("%+v", out.Counters)
	}
	got := map[string][]string{}
	for _, v := range f.sets[0] {
		got[v[0]] = v
	}
	if got[speedObjUL8+".UploadURL"][1] != urlUL || got[speedObjUL8+".TestFileLength"][1] != "10000000" || got[speedObjUL8+".TestFileLength"][2] != "xsd:unsignedInt" ||
		got[speedObjUL8+".DiagnosticsState"][1] != "Requested" || got[speedObjUL8+".Interface"][1] != ifaceTR098 || len(got) != 4 {
		t.Fatalf("%v", got)
	}
	if _, bad := got[speedObjUL8+".DownloadURL"]; bad {
		t.Fatal("an upload must not write a download url")
	}
}

func TestSpeedUploadReadsTestBytesSentOnlyWhenTheObjectListsIt(t *testing.T) {
	f := newSpeedACS("tr181")
	f.leaves = map[string]bool{"DiagnosticsState": true, "BOMTime": true, "EOMTime": true, "TotalBytesSent": true, "Interface": true}
	out, err := runSpeed(t, f, ulReq())
	if err != nil || out.Counters == nil || out.Counters.TestBytesSent != nil {
		t.Fatalf("out=%+v err=%v", out, err)
	}
	g := newSpeedACS("tr181")
	g.leaves = map[string]bool{"DiagnosticsState": true, "BOMTime": true, "EOMTime": true, "TotalBytesSent": true, "TestBytesSent": true, "Interface": true}
	out, err = runSpeed(t, g, ulReq())
	if err != nil || out.Counters == nil || out.Counters.TestBytesSent == nil || *out.Counters.TestBytesSent != 9_990_000 {
		t.Fatalf("out=%+v err=%v", out, err)
	}
}

func TestSpeedRefusesBeforeWritingWhenTheObjectIsNotThere(t *testing.T) {
	for name, mk := range map[string]func() (*speedACS, SpeedRequest){
		"no object cached":   func() (*speedACS, SpeedRequest) { return newSpeedACS(""), dlReq() },
		"state not writable": func() (*speedACS, SpeedRequest) { f := newSpeedACS("tr181"); f.writable = false; return f, dlReq() },
		"other data model":   func() (*speedACS, SpeedRequest) { return newSpeedACS("tr098"), dlReq() },
		"both data models":   func() (*speedACS, SpeedRequest) { return newSpeedACS("both"), dlReq() },
		"required leaf missing": func() (*speedACS, SpeedRequest) {
			f := newSpeedACS("tr181")
			f.leaves = map[string]bool{"DiagnosticsState": true, "BOMTime": true}
			return f, dlReq()
		},
		"upload counter absent": func() (*speedACS, SpeedRequest) {
			f := newSpeedACS("tr181")
			f.leaves = map[string]bool{"DiagnosticsState": true, "BOMTime": true, "EOMTime": true}
			return f, ulReq()
		},
	} {
		f, req := mk()
		if _, err := runSpeed(t, f, req); !errors.Is(err, ErrSpeedUnsupported) {
			t.Errorf("%s: got %v", name, err)
		}
		if f.sentSets() != 0 {
			t.Errorf("%s: wrote %d tasks", name, f.sentSets())
		}
	}
}

func TestSpeedRefusesWhenADiagnosticIsAlreadyRequested(t *testing.T) {
	f := newSpeedACS("tr181")
	f.state, f.stateAt = speedRequested, time.Now()
	if _, err := runSpeed(t, f, dlReq()); !errors.Is(err, ErrSpeedBusy) {
		t.Fatalf("%v", err)
	}
	if f.sentSets() != 0 {
		t.Fatal("nothing may be written over a running test")
	}
}

func TestSpeedRefusesAnUnconfirmedOrOfflineOrBusyDevice(t *testing.T) {
	f := newSpeedACS("tr181")
	bad := benchDev
	bad.Serial = "48575443FFFFFFFF"
	if _, err := f.client(t).RunBenchSpeed(context.Background(), bad, dlReq(), time.Now().Add(time.Hour), time.Second, 10*time.Millisecond, realNow); !errors.Is(err, ErrBenchIdentity) {
		t.Fatalf("identity: %v", err)
	}
	g := newSpeedACS("tr181")
	g.informAt = time.Now().UTC().Add(-2 * time.Hour).Format(time.RFC3339)
	if _, err := runSpeed(t, g, dlReq()); !errors.Is(err, ErrBenchOffline) {
		t.Fatalf("offline: %v", err)
	}
	h := newSpeedACS("tr181")
	h.tasks = []map[string]any{{"_id": "pendtask0001", "name": "setParameterValues", "device": benchID, "timestamp": time.Now().UTC().Format(time.RFC3339)}}
	if _, err := runSpeed(t, h, dlReq()); !errors.Is(err, ErrBenchPending) {
		t.Fatalf("pending: %v", err)
	}
	for _, x := range []*speedACS{f, g, h} {
		if x.sentSets() != 0 {
			t.Fatal("no write on a refused device")
		}
	}
}

func TestSpeedQueuedTaskIsRemovedAndNothingRuns(t *testing.T) {
	f := newSpeedACS("tr181")
	f.setCode = 202
	out, err := runSpeed(t, f, dlReq())
	if !IsNotDelivered(err) || !out.Attempted || out.Counters != nil {
		t.Fatalf("out=%+v err=%v", out, err)
	}
	if len(f.tasks) != 0 {
		t.Fatalf("a queued speed task was left on the ACS: %v", f.tasks)
	}
	if f.sentSets() != 1 {
		t.Fatal("the request is never re-sent")
	}
}

func TestSpeedRefusalAndFaultAreNotDeliveredAmbiguityIsNot(t *testing.T) {
	for _, code := range []int{400, 403, 404, 422} {
		f := newSpeedACS("tr181")
		f.setCode = code
		if _, err := runSpeed(t, f, dlReq()); !IsNotDelivered(err) {
			t.Errorf("%d: %v", code, err)
		}
	}
	f := newSpeedACS("tr181")
	f.fault = true
	if _, err := runSpeed(t, f, dlReq()); !IsNotDelivered(err) {
		t.Errorf("fault: %v", err)
	}
	g := newSpeedACS("tr181")
	g.setCode = 503
	out, err := runSpeed(t, g, dlReq())
	if !errors.Is(err, errAmbiguous) || !out.Attempted {
		t.Fatalf("ambiguous: out=%+v err=%v", out, err)
	}
	if len(g.tasks) != 0 || g.sentSets() != 1 {
		t.Fatalf("ambiguous request: tasks left %v, writes %d", g.tasks, g.sentSets())
	}
}

func TestSpeedAnOldResultIsNotMistakenForThisTest(t *testing.T) {
	f := newSpeedACS("tr181")
	f.staleResult = true
	out, err := runSpeed(t, f, dlReq())
	if !errors.Is(err, ErrSpeedTimeout) || out.Counters != nil || !out.Attempted {
		t.Fatalf("out=%+v err=%v", out, err)
	}
}

func TestSpeedTimeoutKeepsTheAttemptAndNeverResends(t *testing.T) {
	f := newSpeedACS("tr181")
	f.completeAt = 0
	out, err := runSpeed(t, f, dlReq())
	if !errors.Is(err, ErrSpeedTimeout) || !out.Attempted || out.Counters != nil {
		t.Fatalf("out=%+v err=%v", out, err)
	}
	if f.sentSets() != 1 {
		t.Fatalf("the request must never be repeated, got %d writes", f.sentSets())
	}
}

func TestSpeedADeviceErrorStateIsReportedWithItsCounters(t *testing.T) {
	f := newSpeedACS("tr181")
	f.final = "Error_InitConnectionFailed"
	out, err := runSpeed(t, f, dlReq())
	if err != nil || out.Counters == nil || out.Counters.State != "Error_InitConnectionFailed" {
		t.Fatalf("out=%+v err=%v", out, err)
	}
}

func TestSpeedReadFailureDuringPollingIsATimeoutNotASuccess(t *testing.T) {
	f := newSpeedACS("tr181")
	f.completeAt = 1000
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		f.mu.Lock()
		armed := f.armed
		f.mu.Unlock()
		if armed && r.Method == http.MethodPost && strings.HasSuffix(r.URL.Path, "/tasks") {
			w.WriteHeader(500)
			return
		}
		f.handler().ServeHTTP(w, r)
	}))
	t.Cleanup(srv.Close)
	c, _ := New(srv.URL, srv.Client(), "")
	if _, err := c.RunBenchSpeed(context.Background(), benchDev, dlReq(), time.Now().Add(time.Hour), 300*time.Millisecond, 10*time.Millisecond, realNow); !errors.Is(err, ErrSpeedTimeout) {
		t.Fatalf("%v", err)
	}
}

func TestSpeedNothingIsSentAfterTheDeadline(t *testing.T) {
	f := newSpeedACS("tr181")
	past := time.Now().Add(-time.Second)
	if _, err := f.client(t).RunBenchSpeed(context.Background(), benchDev, dlReq(), past, time.Second, 10*time.Millisecond, realNow); err == nil {
		t.Fatal("must refuse")
	}
	if f.sentSets() != 0 {
		t.Fatal("no write after the deadline")
	}
}

func TestSpeedRequestShapeIsClosed(t *testing.T) {
	bad := map[string]SpeedRequest{}
	mut := func(name string, fn func(r *SpeedRequest)) {
		r := dlReq()
		fn(&r)
		bad[name] = r
	}
	mut("url with credentials", func(r *SpeedRequest) { r.URL = "http://user:pw@10.20.5.9:8080/dl/10mb" })
	mut("url with a query", func(r *SpeedRequest) { r.URL = "http://10.20.5.9:8080/dl/10mb?x=1" })
	mut("url with a hostname", func(r *SpeedRequest) { r.URL = "http://speedtest.example.com:8080/dl/10mb" })
	mut("url over https", func(r *SpeedRequest) { r.URL = "https://10.20.5.9:8080/dl/10mb" })
	mut("url with another path", func(r *SpeedRequest) { r.URL = "http://10.20.5.9:8080/etc/passwd" })
	mut("url of the other direction", func(r *SpeedRequest) { r.URL = urlUL })
	mut("url with a profile outside the list", func(r *SpeedRequest) { r.URL = "http://10.20.5.9:8080/dl/1gb" })
	mut("no port", func(r *SpeedRequest) { r.URL = "http://10.20.5.9/dl/10mb" })
	mut("no interface", func(r *SpeedRequest) { r.Interface = "" })
	mut("interface with a separator", func(r *SpeedRequest) { r.Interface = "Device.IP.Interface.1;Device.IP.Interface.2" })
	mut("unknown root", func(r *SpeedRequest) { r.Root = "tr369" })
	mut("unknown direction", func(r *SpeedRequest) { r.Direction = "both" })
	mut("download with a file length", func(r *SpeedRequest) { r.FileLength = 10 })
	u := ulReq()
	u.FileLength = 0
	bad["upload without a file length"] = u
	u2 := ulReq()
	u2.FileLength = 300_000_000
	bad["upload above the largest profile"] = u2
	for name, r := range bad {
		f := newSpeedACS("tr181")
		if _, err := runSpeed(t, f, r); !errors.Is(err, ErrSpeedInvalid) {
			t.Errorf("%s: %v", name, err)
		}
		if f.sentSets() != 0 || len(f.log) != 0 {
			t.Errorf("%s: the ACS was contacted: %v", name, f.log)
		}
	}
}

func TestSpeedCounterConversion(t *testing.T) {
	for in, want := range map[string]string{"2026-10-31T12:00:00Z": "2026-10-31T12:00:00Z", "2026-10-31T12:00:00.123456Z": "2026-10-31T12:00:00.123456Z",
		"2026-10-31T09:00:00-03:00": "2026-10-31T12:00:00Z", "2026-10-31T12:00:00": "", "0001-01-01T00:00:00Z": "", "garbage": "", "": ""} {
		if got := speedTime(in); got != want {
			t.Errorf("time %q = %q want %q", in, got, want)
		}
	}
	if speedTime(12345) != "" || speedTime(nil) != "" {
		t.Error("a non-string time is dropped")
	}
	for in, want := range map[any]int64{float64(5): 5, "7": 7, float64(0): 0} {
		if got := speedInt(in); got == nil || *got != want {
			t.Errorf("int %v", in)
		}
	}
	for _, in := range []any{float64(-1), float64(1.5), float64(2e12), "-3", "x", "99999999999999999999", nil, true, []any{1}} {
		if speedInt(in) != nil {
			t.Errorf("int %v must be dropped", in)
		}
	}
}

func TestSpeedSourceWritesOneTaskShapeAndTouchesNoOtherObject(t *testing.T) {
	b, err := os.ReadFile("speed.go")
	if err != nil {
		t.Fatal(err)
	}
	s := string(b)
	for _, bad := range []string{"factoryReset", "addObject", "deleteObject", "refreshObject", "MethodPut", "MethodPatch", `"name": "reboot"`, "Password", "PreSharedKey", "KeyPassphrase", "SSID", "Username"} {
		if strings.Contains(s, bad) {
			t.Errorf("speed.go must not mention %q", bad)
		}
	}
	if strings.Count(s, `"name": "setParameterValues"`) != 1 {
		t.Error("exactly one write task body")
	}
	if strings.Count(s, "http.MethodPost") != 1 {
		t.Error("exactly one POST call site")
	}
}
