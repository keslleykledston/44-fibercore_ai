package nbi

import (
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"net/http"
	"net/http/httptest"
	"os"
	"path/filepath"
	"strings"
	"sync"
	"testing"
	"time"
)

type fakeACS struct {
	mu         sync.Mutex
	devices    string // JSON array returned by GET /devices
	taskCode   int    // status of POST .../tasks
	taskBody   string // when set, replaces the body of the POST response (e.g. to hide the id)
	faultBody  bool   // answer 200 with a fault object
	dropCreate bool   // the POST fails WITHOUT creating a task
	hangup     bool   // the POST creates the task and then closes the connection (what the real ACS did)
	listCode   int    // status of GET /tasks (0 = 200)
	deleteCode int    // status of DELETE (0 = 200); a non-2xx deletes nothing
	deleteNoop bool   // DELETE answers 200 but deletes nothing
	methods    []string
	taskPaths  []string
	posted     []map[string]any
	db         []map[string]any // tasks currently on the ACS
	deleted    []string
	query      string
	seq        int
	listCalls  int
	now        func() time.Time
}

func (f *fakeACS) clock() time.Time {
	if f.now != nil {
		return f.now()
	}
	return time.Now()
}

func (f *fakeACS) handler() http.Handler {
	return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		f.mu.Lock()
		defer f.mu.Unlock()
		f.methods = append(f.methods, r.Method+" "+r.URL.EscapedPath())
		switch {
		case r.Method == http.MethodGet && r.URL.Path == "/devices":
			_, _ = w.Write([]byte(f.devices))
		case r.Method == http.MethodGet && r.URL.Path == "/tasks":
			f.listCalls++
			if f.listCode != 0 {
				w.WriteHeader(f.listCode)
				return
			}
			b, _ := json.Marshal(f.db)
			_, _ = w.Write(b)
		case r.Method == http.MethodPost && strings.HasSuffix(r.URL.Path, "/tasks"):
			var m map[string]any
			b, _ := io.ReadAll(r.Body)
			_ = json.Unmarshal(b, &m)
			f.posted = append(f.posted, m)
			f.taskPaths = append(f.taskPaths, r.URL.EscapedPath())
			f.query = r.URL.RawQuery
			f.seq++
			id := fmt.Sprintf("task%08d", f.seq)
			dev := strings.TrimSuffix(strings.TrimPrefix(r.URL.Path, "/devices/"), "/tasks")
			if !f.dropCreate {
				f.db = append(f.db, map[string]any{"_id": id, "name": m["name"], "device": dev, "parameterNames": m["parameterNames"],
					"timestamp": f.clock().UTC().Format("2006-01-02T15:04:05.000Z")})
			}
			if f.hangup {
				if hj, ok := w.(http.Hijacker); ok {
					conn, _, _ := hj.Hijack()
					conn.Close()
				}
				return
			}
			w.WriteHeader(f.taskCode)
			switch {
			case f.taskBody != "":
				_, _ = w.Write([]byte(f.taskBody))
			case f.faultBody:
				_, _ = w.Write([]byte(`{"_id":"` + id + `","fault":{"code":"9005"}}`))
			default:
				_, _ = w.Write([]byte(`{"_id":"` + id + `"}`))
			}
		case r.Method == http.MethodDelete && strings.HasPrefix(r.URL.Path, "/tasks/"):
			id := strings.TrimPrefix(r.URL.Path, "/tasks/")
			f.deleted = append(f.deleted, id)
			if f.deleteCode != 0 {
				w.WriteHeader(f.deleteCode)
				return
			}
			if !f.deleteNoop {
				keep := f.db[:0:0]
				for _, t := range f.db {
					if t["_id"] != id {
						keep = append(keep, t)
					}
				}
				f.db = keep
			}
			w.WriteHeader(200)
		default:
			w.WriteHeader(404)
		}
	})
}

func newACS(t *testing.T, f *fakeACS) *Client {
	srv := httptest.NewServer(f.handler())
	t.Cleanup(srv.Close)
	c, err := New(srv.URL, srv.Client(), "")
	if err != nil {
		t.Fatal(err)
	}
	return c
}

const igd = `[{"_id":"AAAA00-ONT-SN1","InternetGatewayDevice":{"DeviceInfo":{"SoftwareVersion":{"_value":"1"}}}}]`

func TestRefreshGroupsAreSubsetsOfTheAllowlist(t *testing.T) {
	for root, groups := range refreshGroups {
		if len(groups) == 0 || len(groups) > maxGroups {
			t.Fatalf("%s: %d groups", root, len(groups))
		}
		for _, g := range groups {
			for _, p := range g {
				if _, ok := allowlist[p]; !ok || !strings.HasPrefix(p, root+".") {
					t.Fatalf("%s is not an allowlisted %s leaf", p, root)
				}
			}
		}
	}
}

func TestRefreshOnlyPostsGetParameterValuesOfAllowlistedLeaves(t *testing.T) {
	f := &fakeACS{devices: igd, taskCode: 200}
	c := newACS(t, f)
	rep, err := c.RefreshParams(context.Background(), "AAAA00-ONT-SN1")
	if err != nil || rep.DataModel != "InternetGatewayDevice" || rep.Groups != 5 || rep.Completed != 5 || rep.Queued+rep.Faulted+rep.Cleaned != 0 {
		t.Fatalf("%+v %v", rep, err)
	}
	if len(f.deleted) != 0 || f.listCalls != 0 {
		t.Fatalf("completed tasks need no cleanup: deleted=%v lists=%d", f.deleted, f.listCalls)
	}
	for _, task := range f.posted {
		if task["name"] != "getParameterValues" || len(task) != 2 {
			t.Fatalf("only getParameterValues with parameterNames may be posted: %v", task)
		}
		names, _ := task["parameterNames"].([]any)
		if len(names) == 0 {
			t.Fatal("empty task")
		}
		for _, n := range names {
			if _, ok := allowlist[n.(string)]; !ok {
				t.Fatalf("posted a name outside the allowlist: %v", n)
			}
		}
	}
	if !strings.Contains(f.query, "connection_request") || !strings.Contains(f.query, "timeout=5000") {
		t.Fatalf("query=%s", f.query)
	}
	for _, m := range f.methods {
		if !strings.HasPrefix(m, "GET ") && !strings.HasPrefix(m, "POST ") && !strings.HasPrefix(m, "DELETE ") {
			t.Fatalf("unexpected request %s", m)
		}
	}
}

func TestRefreshEscapesTheLiteralPercentOfAnACSIDExactlyOnce(t *testing.T) {
	f := &fakeACS{devices: strings.Replace(igd, "AAAA00-ONT-SN1", "CCCC22-hAP%20lite-SN3", 1), taskCode: 200, taskBody: `{}`}
	c := newACS(t, f)
	if _, err := c.RefreshParams(context.Background(), "CCCC22-hAP%20lite-SN3"); err != nil {
		t.Fatal(err)
	}
	if f.taskPaths[0] != "/devices/CCCC22-hAP%2520lite-SN3/tasks" {
		t.Fatalf("path=%s", f.taskPaths[0])
	}
}

func TestRefreshLeavesNoTaskBehindWhateverTheOutcome(t *testing.T) {
	for name, f := range map[string]*fakeACS{
		"queued (202)":         {devices: igd, taskCode: 202},
		"fault":                {devices: igd, taskCode: 200, faultBody: true},
		"id hidden by the ACS": {devices: igd, taskCode: 202, taskBody: `{}`},
		"invented id":          {devices: igd, taskCode: 202, taskBody: `{"_id":"../devices"}`},
		"unparsable body":      {devices: igd, taskCode: 202, taskBody: `not json`},
	} {
		rep, err := newACS(t, f).RefreshParams(context.Background(), "AAAA00-ONT-SN1")
		if err != nil || rep.Cleaned != 5 || rep.Uncleaned != 0 || len(f.db) != 0 {
			t.Fatalf("%s: %+v %v left=%d", name, rep, err, len(f.db))
		}
		for _, id := range f.deleted {
			if !taskIDRe.MatchString(id) {
				t.Fatalf("%s: DELETE for an id that is not well formed: %q", name, id)
			}
		}
	}
}

func TestRefreshReconcilesWhenTheConnectionDropsAfterTheTaskWasCreated(t *testing.T) {
	// what the real ACS did on 2026-10-29: it created the task and closed the connection (EOF) while it waited for the CPE
	f := &fakeACS{devices: igd, hangup: true}
	rep, err := newACS(t, f).RefreshParams(context.Background(), "AAAA00-ONT-SN1")
	if err == nil || errors.Is(err, ErrRefreshUncleaned) || len(f.db) != 0 || rep.Cleaned != 1 || len(f.posted) != 1 {
		t.Fatalf("%+v %v left=%d posted=%d (the failure is reported, the task is gone, no hold is needed)", rep, err, len(f.db), len(f.posted))
	}
	// the POST failed without creating anything: also clean, also reported
	f = &fakeACS{devices: igd, taskCode: 504, dropCreate: true}
	rep, err = newACS(t, f).RefreshParams(context.Background(), "AAAA00-ONT-SN1")
	if err == nil || errors.Is(err, ErrRefreshUncleaned) || len(f.db) != 0 {
		t.Fatalf("%+v %v", rep, err)
	}
}

func TestRefreshOnlyDeletesTasksThisCallCreated(t *testing.T) {
	old := time.Now().Add(-48 * time.Hour).UTC().Format("2006-01-02T15:04:05.000Z")
	names := refreshGroups["InternetGatewayDevice"][0]
	other := func(id, dev, name string, pn []string, ts string) map[string]any {
		return map[string]any{"_id": id, "name": name, "device": dev, "parameterNames": pn, "timestamp": ts}
	}
	f := &fakeACS{devices: igd, taskCode: 202, db: []map[string]any{
		other("oldtask0001", "AAAA00-ONT-SN1", "getParameterValues", toAny(names), old),                                   // same shape, but old
		other("othernames1", "AAAA00-ONT-SN1", "getParameterValues", []string{"Device.DeviceInfo.UpTime"}, old),           // different names
		other("otherdevice", "BBBB00-ONT-SN2", "getParameterValues", toAny(names), time.Now().UTC().Format(time.RFC3339)), // other device
		other("othername01", "AAAA00-ONT-SN1", "reboot", nil, time.Now().UTC().Format(time.RFC3339)),                      // other task kind
	}}
	rep, err := newACS(t, f).RefreshParams(context.Background(), "AAAA00-ONT-SN1")
	if err != nil || rep.Cleaned != 5 {
		t.Fatalf("%+v %v", rep, err)
	}
	if len(f.db) != 4 {
		t.Fatalf("tasks that were not ours must stay untouched: %d left", len(f.db))
	}
	for _, id := range f.deleted {
		if !strings.HasPrefix(id, "task0000") {
			t.Fatalf("deleted a task that this call did not create: %s", id)
		}
	}
}

func toAny(s []string) []string { return s }

func TestRefreshFailsAndStopsWhenCleanupCannotBeProven(t *testing.T) {
	cases := map[string]*fakeACS{
		"delete 500":       {devices: igd, taskCode: 202, deleteCode: 500},
		"delete 404":       {devices: igd, taskCode: 202, deleteCode: 404},
		"delete is a noop": {devices: igd, taskCode: 202, deleteNoop: true}, // 200 but the task is still there: verification catches it
		"list 500":         {devices: igd, taskCode: 202, listCode: 500},
		"list 403":         {devices: igd, taskCode: 202, listCode: 403},
	}
	for name, f := range cases {
		rep, err := newACS(t, f).RefreshParams(context.Background(), "AAAA00-ONT-SN1")
		if !errors.Is(err, ErrRefreshUncleaned) || rep.Uncleaned != 1 || len(f.posted) != 1 {
			t.Fatalf("%s: %+v %v posted=%d (no further task while one may be pending)", name, rep, err, len(f.posted))
		}
	}
}

func TestRefreshRefusesBeforeAnyTaskWhenTheDeviceOrModelIsNotClear(t *testing.T) {
	c := func(f *fakeACS) *Client { return newACS(t, f) }
	for name, tc := range map[string]struct {
		id, devices string
		want        error
	}{
		"unknown to the acs":   {"AAAA00-ONT-SN1", `[]`, ErrBadDeviceID},
		"two docs":             {"AAAA00-ONT-SN1", `[{"_id":"a"},{"_id":"b"}]`, ErrBadDeviceID},
		"no data model":        {"AAAA00-ONT-SN1", `[{"_id":"AAAA00-ONT-SN1"}]`, ErrNoDataModel},
		"both data models":     {"AAAA00-ONT-SN1", `[{"_id":"x","Device":{},"InternetGatewayDevice":{}}]`, ErrNoDataModel},
		"placeholder identity": {"DISCOVERYSERVICE-DISCOVERYSERVICE-X1", igd, ErrBadDeviceID},
		"slash":                {"a/../b", igd, ErrBadDeviceID},
		"empty":                {"", igd, ErrBadDeviceID},
		"too long":             {strings.Repeat("A", 201), igd, ErrBadDeviceID},
		"query injection":      {`x","$or":[{}]`, igd, ErrBadDeviceID},
	} {
		f := &fakeACS{devices: tc.devices, taskCode: 200, taskBody: `{}`}
		if _, err := c(f).RefreshParams(context.Background(), tc.id); !errors.Is(err, tc.want) || len(f.posted) != 0 {
			t.Fatalf("%s: err=%v tasks=%d", name, err, len(f.posted))
		}
	}
}

func TestRefreshAmbiguousStatusesAreCleanedUpAndExplicitRefusalsAreNot(t *testing.T) {
	for _, code := range []int{500, 502, 503, 504, 408, 429, 409, 413} {
		f := &fakeACS{devices: igd, taskCode: code, taskBody: `x`}
		rep, err := newACS(t, f).RefreshParams(context.Background(), "AAAA00-ONT-SN1")
		if err == nil || errors.Is(err, ErrRefreshUncleaned) || f.listCalls == 0 || len(f.db) != 0 || len(f.posted) != 1 || rep.Cleaned != 1 {
			t.Fatalf("%d: %+v %v lists=%d left=%d", code, rep, err, f.listCalls, len(f.db))
		}
	}
	for _, code := range []int{400, 401, 403, 404, 405, 422} {
		f := &fakeACS{devices: igd, taskCode: code, taskBody: `x`, dropCreate: true}
		_, err := newACS(t, f).RefreshParams(context.Background(), "AAAA00-ONT-SN1")
		if err == nil || errors.Is(err, ErrRefreshUncleaned) || len(f.posted) != 1 || f.listCalls != 0 {
			t.Fatalf("%d: a refusal the NBI makes before creating anything needs no cleanup: %v lists=%d", code, err, f.listCalls)
		}
	}
	// ambiguous AND the cleanup is impossible => hold
	f := &fakeACS{devices: igd, taskCode: 503, listCode: 500}
	rep, err := newACS(t, f).RefreshParams(context.Background(), "AAAA00-ONT-SN1")
	if !errors.Is(err, ErrRefreshUncleaned) || rep.Uncleaned != 1 {
		t.Fatalf("%+v %v", rep, err)
	}
}

func TestRefreshHasNoOtherTaskNameInTheSource(t *testing.T) {
	b, err := os.ReadFile("refresh.go")
	if err != nil {
		t.Fatal(err)
	}
	for _, bad := range []string{"setParameterValues", "reboot", "factoryReset", "download", "addObject", "deleteObject", "refreshObject", "MethodPut", "MethodPatch"} {
		if strings.Contains(string(b), bad) {
			t.Fatalf("refresh.go mentions %q", bad)
		}
	}
}

func guard(t *testing.T, now *time.Time) *RefreshGuard {
	return &RefreshGuard{Path: filepath.Join(t.TempDir(), "g.json"), MinPerDevice: 10 * time.Minute, MaxPerHour: 3, Now: func() time.Time { return *now }}
}

func TestRefreshGuardPacesPerDeviceAndPerHourAndPersists(t *testing.T) {
	now := time.Date(2026, 10, 29, 12, 0, 0, 0, time.UTC)
	g := guard(t, &now)
	if err := g.Reserve("A"); err != nil {
		t.Fatal(err)
	}
	if err := g.Reserve("A"); !errors.Is(err, ErrRefreshTooSoon) {
		t.Fatalf("%v", err)
	}
	// a restart (new instance, same file) does not reopen the window
	g2 := &RefreshGuard{Path: g.Path, MinPerDevice: g.MinPerDevice, MaxPerHour: g.MaxPerHour, Now: g.Now}
	if err := g2.Reserve("A"); !errors.Is(err, ErrRefreshTooSoon) {
		t.Fatalf("restart reopened the window: %v", err)
	}
	if err := g2.Reserve("B"); err != nil {
		t.Fatal(err)
	}
	if err := g2.Reserve("C"); err != nil {
		t.Fatal(err)
	}
	if err := g2.Reserve("D"); !errors.Is(err, ErrRefreshBudget) {
		t.Fatalf("hourly budget not enforced: %v", err)
	}
	now = now.Add(11 * time.Minute)
	if err := g2.Reserve("A"); !errors.Is(err, ErrRefreshBudget) {
		t.Fatalf("budget is per hour, not per device window: %v", err)
	}
	now = now.Add(time.Hour)
	if err := g2.Reserve("A"); err != nil {
		t.Fatalf("after an hour it must admit again: %v", err)
	}
	if st, _ := os.Stat(g.Path); st.Mode().Perm() != 0o600 {
		t.Fatalf("mode %v", st.Mode())
	}
	if b, _ := os.ReadFile(g.Path); strings.Contains(string(b), `"A"`) {
		t.Fatal("device ids must not be stored in clear")
	}
}

func TestRefreshGuardHoldBlocksOnlyThatDeviceAndSurvivesRestart(t *testing.T) {
	now := time.Date(2026, 10, 29, 12, 0, 0, 0, time.UTC)
	g := guard(t, &now)
	if err := g.Hold("A", 24*time.Hour); err != nil {
		t.Fatal(err)
	}
	g2 := &RefreshGuard{Path: g.Path, MinPerDevice: g.MinPerDevice, MaxPerHour: g.MaxPerHour, Now: g.Now}
	if err := g2.Reserve("A"); !errors.Is(err, ErrRefreshHeld) {
		t.Fatalf("%v", err)
	}
	if err := g2.Reserve("B"); err != nil {
		t.Fatalf("a hold is per device: %v", err)
	}
	now = now.Add(25 * time.Hour)
	if err := g2.Reserve("A"); err != nil {
		t.Fatalf("hold must expire: %v", err)
	}
	if err := (&RefreshGuard{}).Hold("A", time.Hour); !errors.Is(err, ErrRefreshNoReserve) {
		t.Fatalf("%v", err)
	}
}

func TestRefreshGuardHoldSurvivesAFailedWriteForTheLifeOfTheProcess(t *testing.T) {
	now := time.Date(2026, 10, 29, 12, 0, 0, 0, time.UTC)
	dir := t.TempDir()
	g := &RefreshGuard{Path: filepath.Join(dir, "g.json"), MinPerDevice: time.Minute, MaxPerHour: 5, Now: func() time.Time { return now }}
	if err := g.Reserve("A"); err != nil {
		t.Fatal(err)
	}
	if err := os.Chmod(dir, 0o500); err != nil { // the state can no longer be written
		t.Fatal(err)
	}
	defer os.Chmod(dir, 0o700)
	if os.Geteuid() == 0 {
		t.Skip("root ignores directory permissions")
	}
	if err := g.Hold("A", 24*time.Hour); err == nil {
		t.Fatal("the write was expected to fail")
	}
	now = now.Add(30 * time.Minute) // far past the per-device window
	if err := g.Reserve("A"); !errors.Is(err, ErrRefreshHeld) {
		t.Fatalf("a hold whose write failed must still be in force: %v", err)
	}
}

func TestRefreshGuardFailsClosed(t *testing.T) {
	now := time.Date(2026, 10, 29, 12, 0, 0, 0, time.UTC)
	g := guard(t, &now)
	for _, content := range []string{"{not json", "null", `{"devices":null}`} {
		if err := os.WriteFile(g.Path, []byte(content), 0o600); err != nil {
			t.Fatal(err)
		}
		if err := g.Reserve("A"); !errors.Is(err, ErrRefreshBudget) {
			t.Fatalf("%q: a corrupt state must block (budget spent), got %v", content, err)
		}
	}
	bad := &RefreshGuard{Path: filepath.Join(t.TempDir(), "missing-dir", "g.json"), MinPerDevice: time.Minute, MaxPerHour: 3, Now: func() time.Time { return now }}
	if err := bad.Reserve("A"); !errors.Is(err, ErrRefreshNoReserve) {
		t.Fatalf("unwritable state must refuse: %v", err)
	}
	for _, g := range []*RefreshGuard{{}, {Path: "x", MinPerDevice: time.Minute}, {Path: "x", MaxPerHour: 1}} {
		if err := g.Reserve("A"); !errors.Is(err, ErrRefreshNoReserve) {
			t.Fatalf("unconfigured guard must refuse: %v", err)
		}
	}
	// future-dated entries (clock jump) never block forever
	g3 := guard(t, &now)
	fut := now.Add(48 * time.Hour).Unix()
	_ = os.WriteFile(g3.Path, []byte(`{"devices":{},"recent":[`+itoa(fut)+`,`+itoa(fut)+`,`+itoa(fut)+`]}`), 0o600)
	if err := g3.Reserve("A"); err != nil {
		t.Fatalf("future entries must be ignored: %v", err)
	}
}

func itoa(n int64) string { b, _ := json.Marshal(n); return string(b) }
