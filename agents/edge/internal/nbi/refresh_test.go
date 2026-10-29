package nbi

import (
	"context"
	"encoding/json"
	"errors"
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
	taskCode   int
	taskBody   string
	methods    []string
	taskPaths  []string
	tasks      []map[string]any
	deleted    []string
	deleteCode int
	query      string
}

func (f *fakeACS) handler() http.Handler {
	return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		f.mu.Lock()
		defer f.mu.Unlock()
		f.methods = append(f.methods, r.Method+" "+r.URL.EscapedPath())
		switch {
		case r.Method == http.MethodGet && r.URL.Path == "/devices":
			_, _ = w.Write([]byte(f.devices))
		case r.Method == http.MethodPost && strings.HasSuffix(r.URL.Path, "/tasks"):
			var m map[string]any
			b, _ := io.ReadAll(r.Body)
			_ = json.Unmarshal(b, &m)
			f.tasks = append(f.tasks, m)
			f.taskPaths = append(f.taskPaths, r.URL.EscapedPath())
			f.query = r.URL.RawQuery
			w.WriteHeader(f.taskCode)
			_, _ = w.Write([]byte(f.taskBody))
		case r.Method == http.MethodDelete && strings.HasPrefix(r.URL.Path, "/tasks/"):
			f.deleted = append(f.deleted, strings.TrimPrefix(r.URL.Path, "/tasks/"))
			if f.deleteCode != 0 {
				w.WriteHeader(f.deleteCode)
				return
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
	f := &fakeACS{devices: igd, taskCode: 200, taskBody: `{"_id":"abc12345"}`}
	c := newACS(t, f)
	rep, err := c.RefreshParams(context.Background(), "AAAA00-ONT-SN1")
	if err != nil || rep.DataModel != "InternetGatewayDevice" || rep.Groups != 5 || rep.Completed != 5 || rep.Queued+rep.Faulted+rep.Cleaned != 0 {
		t.Fatalf("%+v %v", rep, err)
	}
	if len(f.deleted) != 0 {
		t.Fatalf("completed tasks must not be deleted: %v", f.deleted)
	}
	for _, task := range f.tasks {
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

func TestRefreshCleansUpQueuedAndFaultedTasksButOnlyThoseItCreated(t *testing.T) {
	f := &fakeACS{devices: igd, taskCode: 202, taskBody: `{"_id":"task1234abcd"}`}
	c := newACS(t, f)
	rep, err := c.RefreshParams(context.Background(), "AAAA00-ONT-SN1")
	if err != nil || rep.Queued != 5 || rep.Cleaned != 5 || len(f.deleted) != 5 {
		t.Fatalf("%+v %v deleted=%v", rep, err, f.deleted)
	}
	f2 := &fakeACS{devices: igd, taskCode: 200, taskBody: `{"_id":"task1234abcd","fault":{"code":"9005"}}`}
	rep, err = newACS(t, f2).RefreshParams(context.Background(), "AAAA00-ONT-SN1")
	if err != nil || rep.Faulted != 5 || rep.Completed != 0 || len(f2.deleted) != 5 {
		t.Fatalf("%+v %v", rep, err)
	}
	// an id the ACS invents (path traversal, oversized) is never turned into a DELETE: the refresh FAILS instead of claiming a clean state
	for _, bad := range []string{`{"_id":"../devices"}`, `{"_id":"a/b"}`, `{"_id":""}`, `not json`} {
		f3 := &fakeACS{devices: igd, taskCode: 202, taskBody: bad}
		rep, err = newACS(t, f3).RefreshParams(context.Background(), "AAAA00-ONT-SN1")
		if !errors.Is(err, ErrRefreshUncleaned) || len(f3.deleted) != 0 || rep.Cleaned != 0 || rep.Uncleaned != 1 || len(f3.tasks) != 1 {
			t.Fatalf("%s: %+v %v deleted=%v tasks=%d", bad, rep, err, f3.deleted, len(f3.tasks))
		}
	}
}

func TestRefreshFailsAndStopsWhenAnUnfinishedTaskCannotBeRemoved(t *testing.T) {
	for _, code := range []int{500, 404, 403} {
		f := &fakeACS{devices: igd, taskCode: 202, taskBody: `{"_id":"task1234abcd"}`, deleteCode: code}
		rep, err := newACS(t, f).RefreshParams(context.Background(), "AAAA00-ONT-SN1")
		if !errors.Is(err, ErrRefreshUncleaned) || rep.Uncleaned != 1 || rep.Cleaned != 0 || len(f.tasks) != 1 {
			t.Fatalf("delete=%d: %+v %v tasks=%d (no further task may be created while one may be pending)", code, rep, err, len(f.tasks))
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
		if _, err := c(f).RefreshParams(context.Background(), tc.id); !errors.Is(err, tc.want) || len(f.tasks) != 0 {
			t.Fatalf("%s: err=%v tasks=%d", name, err, len(f.tasks))
		}
	}
}

func TestRefreshAmbiguousPostOutcomesAreTreatedAsPossiblyUncleanButExplicit4xxIsNot(t *testing.T) {
	for _, code := range []int{500, 502, 503, 504, 408, 429, 409, 413} {
		f := &fakeACS{devices: igd, taskCode: code, taskBody: `x`}
		rep, err := newACS(t, f).RefreshParams(context.Background(), "AAAA00-ONT-SN1")
		if !errors.Is(err, ErrRefreshUncleaned) || rep.Uncleaned != 1 || len(f.tasks) != 1 {
			t.Fatalf("%d: %+v %v tasks=%d (the ACS may have created the task)", code, rep, err, len(f.tasks))
		}
	}
	for _, code := range []int{400, 401, 403, 404, 405, 422} {
		f := &fakeACS{devices: igd, taskCode: code, taskBody: `x`}
		_, err := newACS(t, f).RefreshParams(context.Background(), "AAAA00-ONT-SN1")
		if err == nil || errors.Is(err, ErrRefreshUncleaned) || len(f.tasks) != 1 {
			t.Fatalf("%d: a refusal the NBI makes before creating anything: stop without a hold: %v tasks=%d", code, err, len(f.tasks))
		}
	}
	// transport failure on the POST (connection dropped after the request was sent)
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.Method == http.MethodGet {
			_, _ = w.Write([]byte(igd))
			return
		}
		if hj, ok := w.(http.Hijacker); ok {
			conn, _, _ := hj.Hijack()
			conn.Close()
		}
	}))
	defer srv.Close()
	c, _ := New(srv.URL, srv.Client(), "")
	rep, err := c.RefreshParams(context.Background(), "AAAA00-ONT-SN1")
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
