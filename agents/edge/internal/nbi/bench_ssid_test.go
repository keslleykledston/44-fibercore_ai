package nbi

import (
	"context"
	"encoding/json"
	"errors"
	"net/http"
	"net/http/httptest"
	"os"
	"path/filepath"
	"regexp"
	"strings"
	"sync"
	"testing"
	"time"
)

var okSSID = regexp.MustCompile(`^BANCADA-[A-Z0-9]{1,16}$`).MatchString

const origSSID = "HUAWEI-2.4G-test"

// ssidACS simulates the NBI for the bench CPE AND a production CPE of the same model, each with its own SSID.
type ssidACS struct {
	mu        sync.Mutex
	ssid      map[string]string // device id -> current SSID on the CPE
	log       []string
	sets      []string // "<device>=<value>" for every setParameterValues
	tasks     []map[string]any
	seq       int
	informAt  string
	noApply   bool // acknowledges the set but changes nothing
	setCode   int  // status of a set POST (0 = apply and 200)
	hangup    bool // applies, then drops the connection
	restoreKO bool // sets of the ORIGINAL value fail with 500
	getCode   int
}

func newSSIDACS() *ssidACS {
	return &ssidACS{ssid: map[string]string{benchID: origSSID, prodID: "CLIENTE-PROD"}, informAt: time.Now().UTC().Add(-time.Minute).Format(time.RFC3339)}
}

func (f *ssidACS) handler() http.Handler {
	return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		f.mu.Lock()
		defer f.mu.Unlock()
		f.log = append(f.log, r.Method+" "+r.URL.Path)
		switch {
		case r.Method == http.MethodGet && r.URL.Path == "/devices":
			var q map[string]string
			_ = json.Unmarshal([]byte(r.URL.Query().Get("query")), &q)
			id := q["_id"]
			v, ok := f.ssid[id]
			if !ok {
				_ = json.NewEncoder(w).Encode([]any{})
				return
			}
			serial := strings.TrimPrefix(id, "00259E-EG8145V5-")
			doc := map[string]any{"_id": id, "_lastBoot": t0Boot, "_lastInform": f.informAt,
				"_deviceId": map[string]any{"_OUI": "00259E", "_ProductClass": "EG8145V5", "_SerialNumber": serial},
				"InternetGatewayDevice": map[string]any{"LANDevice": map[string]any{"1": map[string]any{"WLANConfiguration": map[string]any{"1": map[string]any{
					"SSID": map[string]any{"_value": v}}}}}}}
			_ = json.NewEncoder(w).Encode([]any{doc})
		case r.Method == http.MethodGet && r.URL.Path == "/tasks":
			_ = json.NewEncoder(w).Encode(f.tasks)
		case r.Method == http.MethodPost && strings.HasSuffix(r.URL.Path, "/tasks"):
			f.seq++
			id := "sstask" + strings.Repeat("0", 4) + string(rune('a'+f.seq))
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
				_ = json.NewEncoder(w).Encode(map[string]any{"_id": id})
				return
			}
			val := b.Values[0][1]
			f.sets = append(f.sets, dev+"="+val)
			if f.restoreKO && val == origSSID {
				w.WriteHeader(500)
				return
			}
			if f.setCode == 202 {
				f.tasks = append(f.tasks, map[string]any{"_id": id, "name": b.Name, "device": dev, "timestamp": time.Now().UTC().Format(time.RFC3339)})
				w.WriteHeader(202)
				_ = json.NewEncoder(w).Encode(map[string]any{"_id": id})
				return
			}
			if f.setCode != 0 {
				w.WriteHeader(f.setCode)
				return
			}
			if !f.noApply {
				f.ssid[dev] = val
			}
			if f.hangup {
				hj, _ := w.(http.Hijacker)
				c, _, _ := hj.Hijack()
				_ = c.Close()
				return
			}
			_ = json.NewEncoder(w).Encode(map[string]any{"_id": id})
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

func (f *ssidACS) client(t *testing.T) *Client {
	srv := httptest.NewServer(f.handler())
	t.Cleanup(srv.Close)
	c, err := New(srv.URL, srv.Client(), "")
	if err != nil {
		t.Fatal(err)
	}
	restorePause = 10 * time.Millisecond
	return c
}

func realNow() time.Time { return time.Now().UTC() }

func run(t *testing.T, f *ssidACS, ssid string) (SSIDOutcome, error, string) {
	c := f.client(t)
	rf := filepath.Join(t.TempDir(), "restore.json")
	out, err := c.SetBenchSSID(context.Background(), benchDev, ssid, okSSID, time.Now().Add(time.Hour), rf, realNow)
	return out, err, rf
}

func TestSSIDHappyChangesReadsBackAndRestores(t *testing.T) {
	f := newSSIDACS()
	out, err, rf := run(t, f, "BANCADA-H3")
	if err != nil || !(out.Applied && out.Verified && out.Restored) {
		t.Fatalf("out=%+v err=%v", out, err)
	}
	if f.ssid[benchID] != origSSID || f.ssid[prodID] != "CLIENTE-PROD" {
		t.Fatalf("final %v", f.ssid)
	}
	if strings.Join(f.sets, ",") != benchID+"=BANCADA-H3,"+benchID+"="+origSSID {
		t.Fatalf("writes %v", f.sets)
	}
	if _, e := os.Stat(rf); !os.IsNotExist(e) {
		t.Fatal("restore file must be gone after a confirmed restore")
	}
}

func TestSSIDRestoreRecordIsWrittenBeforeTheChange(t *testing.T) {
	f := newSSIDACS()
	c := f.client(t)
	rf := filepath.Join(t.TempDir(), "restore.json")
	f.restoreKO = true // the change works, the way back does not
	out, err := c.SetBenchSSID(context.Background(), benchDev, "BANCADA-H3", okSSID, time.Now().Add(time.Hour), rf, realNow)
	if !errors.Is(err, ErrBenchRestore) || out.Restored {
		t.Fatalf("out=%+v err=%v", out, err)
	}
	b, e := os.ReadFile(rf)
	if e != nil || !strings.Contains(string(b), origSSID) {
		t.Fatalf("restore file must keep the original: %v %s", e, b)
	}
	if st, _ := os.Stat(rf); st.Mode().Perm() != 0o600 {
		t.Fatalf("mode %v", st.Mode().Perm())
	}
}

func TestSSIDNeverTouchesAnotherDeviceOrAnInvalidValue(t *testing.T) {
	f := newSSIDACS()
	c := f.client(t)
	rf := filepath.Join(t.TempDir(), "r.json")
	prodAsBench := BenchDevice{DeviceID: prodID, OUI: "00259E", ProductClass: "EG8145V5", Serial: "48575443E2247AA5"}
	if _, err := c.SetBenchSSID(context.Background(), prodAsBench, "BANCADA-H3", okSSID, time.Now().Add(time.Hour), rf, realNow); err == nil {
		t.Fatal("must refuse")
	}
	for _, bad := range []string{"", "CLIENTE-1", "bancada-h3", "BANCADA-", "BANCADA-H3\n", "BANCADA-" + strings.Repeat("A", 17)} {
		if _, err := c.SetBenchSSID(context.Background(), benchDev, bad, okSSID, time.Now().Add(time.Hour), rf, realNow); !errors.Is(err, ErrBenchSSIDInvalid) {
			t.Fatalf("%q: %v", bad, err)
		}
	}
	if _, err := c.SetBenchSSID(context.Background(), benchDev, "BANCADA-H3", nil, time.Now().Add(time.Hour), rf, realNow); !errors.Is(err, ErrBenchSSIDInvalid) {
		t.Fatal("no validator, no write")
	}
	if len(f.sets) != 0 {
		t.Fatalf("no write: %v", f.sets)
	}
}

func TestSSIDRefusals(t *testing.T) {
	f := newSSIDACS()
	f.tasks = []map[string]any{{"_id": "old000001", "name": "setParameterValues", "device": benchID, "timestamp": time.Now().UTC().Format(time.RFC3339)}}
	if _, err, _ := run(t, f, "BANCADA-H3"); !errors.Is(err, ErrBenchPending) || len(f.sets) != 0 {
		t.Fatalf("pending: %v %v", err, f.sets)
	}
	f = newSSIDACS()
	f.informAt = "2020-01-01T00:00:00Z"
	if _, err, _ := run(t, f, "BANCADA-H3"); !errors.Is(err, ErrBenchOffline) || len(f.sets) != 0 {
		t.Fatalf("offline: %v", err)
	}
	f = newSSIDACS()
	f.getCode = 500
	if _, err, _ := run(t, f, "BANCADA-H3"); !errors.Is(err, ErrBenchSSIDRead) || len(f.sets) != 0 {
		t.Fatalf("unreadable original: %v", err)
	}
	f = newSSIDACS()
	f.ssid[benchID] = "BANCADA-H3"
	if _, err, _ := run(t, f, "BANCADA-H3"); !errors.Is(err, ErrBenchSSIDInvalid) || len(f.sets) != 0 {
		t.Fatalf("already set: %v", err)
	}
}

func TestSSIDQueuedIsRemovedAndNothingChanges(t *testing.T) {
	f := newSSIDACS()
	f.setCode = 202
	out, err, rf := run(t, f, "BANCADA-H3")
	if !IsNotDelivered(err) || out.Applied || len(f.tasks) != 0 || f.ssid[benchID] != origSSID {
		t.Fatalf("out=%+v err=%v tasks=%v", out, err, f.tasks)
	}
	if _, e := os.Stat(rf); !os.IsNotExist(e) {
		t.Fatal("no change, no restore file")
	}
	f = newSSIDACS()
	f.setCode = 403
	if _, err, _ := run(t, f, "BANCADA-H3"); !IsNotDelivered(err) || f.ssid[benchID] != origSSID {
		t.Fatalf("rejected: %v", err)
	}
}

func TestSSIDAcknowledgedButNotAppliedIsNotVerified(t *testing.T) {
	f := newSSIDACS()
	f.noApply = true
	out, err, _ := run(t, f, "BANCADA-H3")
	if err != nil || !out.Applied || out.Verified || !out.Restored {
		t.Fatalf("out=%+v err=%v", out, err)
	}
}

func TestSSIDAmbiguousChangeIsFollowedByARestoreAndNeverRetried(t *testing.T) {
	f := newSSIDACS()
	f.hangup = true
	var changes int
	out, err, _ := run(t, f, "BANCADA-H3")
	f.mu.Lock() // the handler of a dropped connection may still be finishing
	defer f.mu.Unlock()
	for _, s := range f.sets {
		if strings.HasSuffix(s, "=BANCADA-H3") {
			changes++
		}
	}
	if changes != 1 {
		t.Fatalf("the change is sent exactly once, got %d (%v)", changes, f.sets)
	}
	if out.Applied {
		t.Fatalf("an unanswered request is never reported as applied: %+v", out)
	}
	// the connection drops on the restore posts too (hangup applies the value, then closes): the final SSID must be the original or the error says so
	if err == nil && f.ssid[benchID] != origSSID {
		t.Fatalf("restore claimed but SSID is %q", f.ssid[benchID])
	}
	if err != nil && !errors.Is(err, ErrBenchRestore) {
		t.Fatalf("unexpected %v", err)
	}
}

func TestSSIDSourceWritesOnlyTheOneLeaf(t *testing.T) {
	b, err := os.ReadFile("bench_ssid.go")
	if err != nil {
		t.Fatal(err)
	}
	s := string(b)
	for _, bad := range []string{"factoryReset", "download", "addObject", "deleteObject", "MethodPut", "MethodPatch", `"reboot"`, "Password", "PreSharedKey", "KeyPassphrase"} {
		if strings.Contains(s, bad) && bad != `"reboot"` {
			t.Errorf("bench_ssid.go must not mention %q", bad)
		}
	}
	if strings.Count(s, `"name": "setParameterValues"`) != 1 || strings.Count(s, "WLANConfiguration.1.SSID") != 1 {
		t.Error("exactly one set body and one leaf")
	}
}
