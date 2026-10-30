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
	benchID   = "00259E-EG8145V5-48575443E2247AA5"
	prodID    = "00259E-EG8145V5-48575443AAAAAAAA" // a production ONT of the same model: must never be touched
	t0Boot    = "2026-10-01T10:00:00.000Z"
	benchTime = "2026-10-30T12:00:00Z"
)

// benchACS simulates the NBI with a bench device AND a production device of the same model.
type benchACS struct {
	mu        sync.Mutex
	informAt  string
	postCode  int  // 0 = 200
	hangup    bool // creates the task, then closes the connection
	reboots   bool // a delivered reboot advances _lastBoot
	bootAfter string
	dup       bool
	log       []string
	tasks     []map[string]any
	seq       int
	delCode   int
}

func (f *benchACS) device(id, serial, boot string) map[string]any {
	return map[string]any{"_id": id, "_lastBoot": boot, "_lastInform": f.informAt,
		"_deviceId": map[string]any{"_OUI": "00259E", "_ProductClass": "EG8145V5", "_SerialNumber": serial}}
}

func (f *benchACS) handler() http.Handler {
	return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		f.mu.Lock()
		defer f.mu.Unlock()
		f.log = append(f.log, r.Method+" "+r.URL.Path)
		switch {
		case r.Method == http.MethodGet && r.URL.Path == "/devices":
			var q map[string]string
			_ = json.Unmarshal([]byte(r.URL.Query().Get("query")), &q)
			boot := t0Boot
			if f.bootAfter != "" {
				boot = f.bootAfter
			}
			var out []map[string]any
			if q["_id"] == benchID {
				out = append(out, f.device(benchID, "48575443E2247AA5", boot))
				if f.dup {
					out = append(out, f.device(benchID, "48575443E2247AA5", boot))
				}
			}
			if q["_id"] == prodID {
				out = append(out, f.device(prodID, "48575443AAAAAAAA", t0Boot))
			}
			_ = json.NewEncoder(w).Encode(out)
		case r.Method == http.MethodGet && r.URL.Path == "/tasks":
			_ = json.NewEncoder(w).Encode(f.tasks)
		case r.Method == http.MethodPost && strings.HasSuffix(r.URL.Path, "/tasks"):
			f.seq++
			id := fmt.Sprintf("rbtask%05d", f.seq)
			dev := strings.TrimSuffix(strings.TrimPrefix(r.URL.Path, "/devices/"), "/tasks")
			var b map[string]any
			_ = json.NewDecoder(r.Body).Decode(&b)
			if f.postCode == 202 || f.hangup {
				f.tasks = append(f.tasks, map[string]any{"_id": id, "name": b["name"], "device": dev, "timestamp": time.Now().UTC().Format(time.RFC3339)})
			}
			if f.hangup {
				hj, _ := w.(http.Hijacker)
				c, _, _ := hj.Hijack()
				_ = c.Close()
				return
			}
			if f.postCode != 0 && f.postCode != 200 {
				w.WriteHeader(f.postCode)
				if f.postCode == 202 {
					_ = json.NewEncoder(w).Encode(map[string]any{"_id": id})
				}
				return
			}
			if f.reboots {
				f.bootAfter = time.Now().UTC().Add(time.Second).Format("2006-01-02T15:04:05.000Z")
			}
			_ = json.NewEncoder(w).Encode(map[string]any{"_id": id})
		case r.Method == http.MethodDelete && strings.HasPrefix(r.URL.Path, "/tasks/"):
			if f.delCode != 0 {
				w.WriteHeader(f.delCode)
				return
			}
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

func (f *benchACS) setup(t *testing.T) *Client {
	srv := httptest.NewServer(f.handler())
	t.Cleanup(srv.Close)
	c, err := New(srv.URL, srv.Client(), "")
	if err != nil {
		t.Fatal(err)
	}
	return c
}

var farFuture = time.Now().Add(24 * time.Hour)

var benchDev = BenchDevice{DeviceID: benchID, OUI: "00259E", ProductClass: "EG8145V5", Serial: "48575443E2247AA5"}

func fixedNow() time.Time { t, _ := time.Parse(time.RFC3339, benchTime); return t }

func (f *benchACS) wrote() []string {
	var w []string
	for _, l := range f.log {
		if !strings.HasPrefix(l, "GET ") {
			w = append(w, l)
		}
	}
	return w
}

func TestBenchRebootHappy(t *testing.T) {
	f := &benchACS{informAt: "2026-10-30T11:55:00Z", reboots: true}
	// _lastBoot after the request must be later than "since": use a clock just before real time
	c := f.setup(t)
	now := func() time.Time { return time.Now().UTC().Add(-time.Second) }
	f.informAt = now().Format(time.RFC3339)
	out, err := c.RebootBench(context.Background(), benchDev, farFuture, 3*time.Second, 50*time.Millisecond, now)
	if err != nil || !out.Accepted || !out.PostcheckOK {
		t.Fatalf("out=%+v err=%v", out, err)
	}
	w := f.wrote()
	if len(w) != 1 || w[0] != "POST /devices/"+benchID+"/tasks" {
		t.Fatalf("exactly one write to the bench device expected, got %v", w)
	}
}

func TestBenchNeverTouchesOtherDevice(t *testing.T) {
	f := &benchACS{informAt: benchTime, reboots: true}
	c := f.setup(t)
	// bench entry names the production device's id but the bench serial: identity mismatch, nothing sent
	for _, bad := range []BenchDevice{
		{DeviceID: prodID, OUI: "00259E", ProductClass: "EG8145V5", Serial: "48575443E2247AA5"},
		{DeviceID: benchID, OUI: "00259E", ProductClass: "EG8145V5", Serial: "48575443AAAAAAAA"},
		{DeviceID: benchID, OUI: "FFFFFF", ProductClass: "EG8145V5", Serial: "48575443E2247AA5"},
		{DeviceID: benchID, OUI: "00259E", ProductClass: "OTHER", Serial: "48575443E2247AA5"},
		{DeviceID: "", OUI: "00259E", ProductClass: "EG8145V5", Serial: "48575443E2247AA5"},
		{DeviceID: benchID, OUI: "", ProductClass: "EG8145V5", Serial: "48575443E2247AA5"},
	} {
		if _, err := c.RebootBench(context.Background(), bad, farFuture, time.Second, 10*time.Millisecond, fixedNow); err == nil {
			t.Fatalf("%+v: must be refused", bad)
		}
	}
	if len(f.wrote()) != 0 {
		t.Fatalf("no write may happen on identity failure: %v", f.wrote())
	}
}

func TestBenchRefusals(t *testing.T) {
	t.Run("duplicate ACS match", func(t *testing.T) {
		f := &benchACS{informAt: benchTime, dup: true}
		c := f.setup(t)
		if _, err := c.RebootBench(context.Background(), benchDev, farFuture, time.Second, 10*time.Millisecond, fixedNow); !errors.Is(err, ErrBenchIdentity) {
			t.Fatalf("got %v", err)
		}
		if len(f.wrote()) != 0 {
			t.Fatal("wrote")
		}
	})
	t.Run("offline", func(t *testing.T) {
		f := &benchACS{informAt: "2026-10-30T09:00:00Z"}
		c := f.setup(t)
		if _, err := c.RebootBench(context.Background(), benchDev, farFuture, time.Second, 10*time.Millisecond, fixedNow); !errors.Is(err, ErrBenchOffline) {
			t.Fatalf("got %v", err)
		}
		if len(f.wrote()) != 0 {
			t.Fatal("wrote")
		}
	})
	t.Run("an ssid task pending blocks the reboot", func(t *testing.T) {
		f := &benchACS{informAt: benchTime, tasks: []map[string]any{{"_id": "old000002", "name": "setParameterValues", "device": benchID, "timestamp": benchTime}}}
		c := f.setup(t)
		if _, err := c.RebootBench(context.Background(), benchDev, farFuture, time.Second, 10*time.Millisecond, fixedNow); !errors.Is(err, ErrBenchPending) {
			t.Fatalf("got %v", err)
		}
		if len(f.wrote()) != 0 {
			t.Fatal("wrote")
		}
	})
	t.Run("reboot already pending", func(t *testing.T) {
		f := &benchACS{informAt: benchTime, tasks: []map[string]any{{"_id": "old000001", "name": "reboot", "device": benchID, "timestamp": benchTime}}}
		c := f.setup(t)
		if _, err := c.RebootBench(context.Background(), benchDev, farFuture, time.Second, 10*time.Millisecond, fixedNow); !errors.Is(err, ErrBenchPending) {
			t.Fatalf("got %v", err)
		}
		if len(f.wrote()) != 0 {
			t.Fatal("wrote")
		}
	})
}

func TestBenchQueuedIsRemoved(t *testing.T) {
	f := &benchACS{informAt: benchTime, postCode: 202}
	c := f.setup(t)
	_, err := c.RebootBench(context.Background(), benchDev, farFuture, time.Second, 10*time.Millisecond, fixedNow)
	if !IsNotDelivered(err) {
		t.Fatalf("got %v", err)
	}
	if len(f.tasks) != 0 {
		t.Fatalf("queued reboot must be deleted, left %v", f.tasks)
	}
}

func TestBenchQueuedAndCannotRemove(t *testing.T) {
	f := &benchACS{informAt: benchTime, postCode: 202, delCode: 500}
	c := f.setup(t)
	_, err := c.RebootBench(context.Background(), benchDev, farFuture, time.Second, 10*time.Millisecond, fixedNow)
	if !errors.Is(err, ErrBenchUncleaned) {
		t.Fatalf("got %v", err)
	}
}

func TestBenchAmbiguousIsNotRetried(t *testing.T) {
	f := &benchACS{hangup: true}
	c := f.setup(t)
	real := func() time.Time { return time.Now().UTC().Add(-time.Second) }
	f.informAt = real().Format(time.RFC3339)
	out, err := c.RebootBench(context.Background(), benchDev, farFuture, time.Second, 10*time.Millisecond, real)
	if err == nil || out.Accepted || IsNotDelivered(err) {
		t.Fatalf("ambiguous: out=%+v err=%v", out, err)
	}
	posts := 0
	for _, l := range f.log {
		if strings.HasPrefix(l, "POST ") {
			posts++
		}
	}
	if posts != 1 {
		t.Fatalf("exactly one POST, got %d", posts)
	}
	if len(f.tasks) != 0 {
		t.Fatalf("our task must be removed: %v", f.tasks)
	}
}

func TestBenchNoNewBootIsNotConfirmed(t *testing.T) {
	f := &benchACS{informAt: benchTime} // delivered but _lastBoot never advances
	c := f.setup(t)
	out, err := c.RebootBench(context.Background(), benchDev, farFuture, 200*time.Millisecond, 50*time.Millisecond, fixedNow)
	if err != nil || !out.Accepted || out.PostcheckOK {
		t.Fatalf("out=%+v err=%v", out, err)
	}
}

func TestBenchRejected(t *testing.T) {
	f := &benchACS{informAt: benchTime, postCode: 403}
	c := f.setup(t)
	if _, err := c.RebootBench(context.Background(), benchDev, farFuture, time.Second, 10*time.Millisecond, fixedNow); !IsNotDelivered(err) {
		t.Fatalf("got %v", err)
	}
}

func TestBenchSourceHasNoOtherWrites(t *testing.T) {
	b, err := os.ReadFile("bench.go")
	if err != nil {
		t.Fatal(err)
	}
	s := string(b)
	for _, bad := range []string{"setParameterValues", "factoryReset", "download", "addObject", "deleteObject", "MethodPut", "MethodPatch"} {
		if strings.Contains(s, bad) {
			t.Errorf("bench.go must not mention %q", bad)
		}
	}
	if strings.Count(s, `"name": "reboot"`) != 1 {
		t.Error("exactly one reboot task body")
	}
}

func TestBenchNothingIsSentAfterTheDeadline(t *testing.T) {
	f := &benchACS{informAt: benchTime, reboots: true}
	c := f.setup(t)
	// deadline already in the past relative to the injected clock: identity passes, the last check before the POST refuses
	past := fixedNow().Add(-time.Second)
	if _, err := c.RebootBench(context.Background(), benchDev, past.Add(24*time.Hour), time.Second, 10*time.Millisecond, func() time.Time { return past.Add(25 * time.Hour) }); err == nil {
		t.Fatal("must refuse")
	}
	if len(f.wrote()) != 0 {
		t.Fatalf("no write after the deadline: %v", f.wrote())
	}
}
