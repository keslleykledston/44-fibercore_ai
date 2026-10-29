package nbi

import (
	"bytes"
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"net/http"
	"net/url"
	"regexp"
	"sort"
	"strings"
	"time"
)

// SD-001 / ADR-SD-002 item 4 (authorised by the owner on 2026-10-29): ask the ACS to read ALLOWLISTED leaves from ONE CPE.
//
// This is the only place the Edge speaks anything but GET to the NBI, and it can say exactly three things:
//   - POST /devices/<id>/tasks  with a getParameterValues task whose parameterNames are a subset of the allowlist (never a name from outside),
//   - GET  /devices?query=<id>  (data-model detection),
//   - DELETE /tasks/<id> for a task THIS call created and that did not complete (so a failing task cannot stay queued on a customer CPE).
// No other task name exists in this package (a test greps the source for the dangerous ones).

const (
	taskTimeoutMS = 5000
	maxTaskBody   = 1 << 20
	maxGroups     = 8
)

var (
	// deviceIDRe is the GenieACS _id form "OUI-ProductClass-Serial" (URL-encoded where needed); nothing else is ever put into a path.
	deviceIDRe = regexp.MustCompile(`^[A-Za-z0-9._%-]{3,200}$`)
	taskIDRe   = regexp.MustCompile(`^[A-Za-z0-9]{8,64}$`)

	ErrBadDeviceID = errors.New("nbi refresh: invalid device id")
	ErrNoDataModel = errors.New("nbi refresh: device exposes neither InternetGatewayDevice nor Device; nothing requested")
	// ErrRefreshUncleaned: a task that did not complete could not be removed, so it may still be queued on the ACS (and fire a connection to
	// the customer's CPE later). The caller must treat the refresh as FAILED and hold the device.
	ErrRefreshUncleaned = errors.New("nbi refresh: an unfinished task could not be removed from the ACS")
	// ErrRefreshUnproven: after an ambiguous request nothing of ours was found on the ACS, but absence cannot be proven (the task could still
	// become visible). Always wrapped together with ErrRefreshUncleaned; the caller holds the device for less time than for a proven leftover.
	ErrRefreshUnproven = errors.New("nbi refresh: could not prove that no task was created")
	// ErrRefreshPending: the device already has an unfinished getParameterValues task for allowlisted names (left by an earlier unproven
	// attempt, an operator or another process). Nothing new is created until it is gone; the check runs before every refresh.
	ErrRefreshPending = errors.New("nbi refresh: an unfinished allowlisted task already exists on this device")
	errNotAllowlisted = errors.New("nbi refresh: parameter outside the allowlist")
)

// refreshGroups are the objects asked for, one task each, instance 1 (and the 5 GHz radio). A task that targets an object the CPE does not
// have faults on its own without affecting the others. Every leaf must be in the allowlist (checked on every call and by the tests).
var refreshGroups = map[string][][]string{
	"InternetGatewayDevice": {
		{"InternetGatewayDevice.WANDevice.1.WANCommonInterfaceConfig.PhysicalLinkStatus"},
		groupOf("InternetGatewayDevice.WANDevice.1.WANConnectionDevice.1.WANPPPConnection.1.", "ConnectionStatus", "Uptime"),
		groupOf("InternetGatewayDevice.WANDevice.1.WANConnectionDevice.1.WANIPConnection.1.", "ConnectionStatus", "Uptime"),
		groupOf("InternetGatewayDevice.LANDevice.1.WLANConfiguration.1.", "Enable", "Channel"),
		groupOf("InternetGatewayDevice.LANDevice.1.WLANConfiguration.5.", "Enable", "Channel"),
	},
	"Device": {
		{"Device.PPP.Interface.1.Status"},
		groupOf("Device.WiFi.Radio.1.", "Enable", "Channel"),
		groupOf("Device.WiFi.Radio.2.", "Enable", "Channel"),
		{"Device.DeviceInfo.UpTime"},
	},
}

func groupOf(prefix string, leaves ...string) []string {
	out := make([]string, len(leaves))
	for i, l := range leaves {
		out[i] = prefix + l
	}
	return out
}

// RefreshReport says what happened, in counts only (no device data).
type RefreshReport struct {
	DataModel string
	Groups    int
	Completed int
	Faulted   int
	Queued    int
	Cleaned   int
	Uncleaned int // unfinished tasks that could NOT be removed (also counted when the ACS gave no usable task id)
}

// RefreshParams asks the ACS to read the allowlisted groups from one device. Nothing is requested unless the data model is detected first.
func (c *Client) RefreshParams(ctx context.Context, deviceID string) (RefreshReport, error) {
	c.refreshMu.Lock() // one active read at a time through this client (the Edge runs one job at a time and is a single instance per state dir)
	defer c.refreshMu.Unlock()
	var rep RefreshReport
	if !deviceIDRe.MatchString(deviceID) || strings.HasPrefix(deviceID, "DISCOVERYSERVICE") { // placeholder identities are not inventory
		return rep, ErrBadDeviceID
	}
	root, err := c.dataModel(ctx, deviceID)
	if err != nil {
		return rep, err
	}
	groups := refreshGroups[root]
	if len(groups) == 0 || len(groups) > maxGroups {
		return rep, ErrNoDataModel
	}
	rep.DataModel = root
	for _, g := range groups {
		for _, p := range g {
			if _, ok := allowlist[p]; !ok {
				return rep, fmt.Errorf("%w: %s", errNotAllowlisted, p)
			}
		}
	}
	// Evidence instead of a timer: a task that became visible late (or was left by anyone) shows up here, and blocks, on the next attempt.
	pending, err := c.deviceTasks(ctx, deviceID)
	if err != nil {
		return rep, fmt.Errorf("nbi refresh: cannot check for pending tasks: %w", err)
	}
	for _, d := range pending {
		if d.Name == "getParameterValues" && allAllowlisted(d.Names) {
			return rep, ErrRefreshPending
		}
	}
	for _, g := range groups {
		rep.Groups++
		started := time.Now()
		status, taskID, faulted, err := c.postTask(ctx, deviceID, g)
		ambiguous := false
		if err != nil {
			// A lost response, a timeout, a 5xx or a proxy-style 4xx (408, 429...) does not prove the ACS did NOT create the task. Only the
			// statuses the NBI itself uses to refuse a request before creating anything do.
			var rej *rejectedError
			if errors.As(err, &rej) && definitelyNotCreated[rej.status] {
				return rep, err
			}
			ambiguous = true
		}
		if ambiguous || status != http.StatusOK || faulted { // never leave a queued/faulted/unknown task on a customer CPE
			if cerr := c.cleanupTasks(ctx, deviceID, g, started, taskID); cerr != nil {
				rep.Uncleaned++
				return rep, fmt.Errorf("%w: %w", ErrRefreshUncleaned, cerr) // stop: nothing new while a task may still be pending
			}
			rep.Cleaned++
			if ambiguous {
				return rep, fmt.Errorf("nbi refresh: request outcome unknown, no task of ours remains: %w", err)
			}
		}
		switch {
		case status == http.StatusOK && !faulted:
			rep.Completed++
		case faulted:
			rep.Faulted++
		default:
			rep.Queued++
		}
	}
	return rep, nil
}

func (c *Client) dataModel(ctx context.Context, deviceID string) (string, error) {
	q, _ := json.Marshal(map[string]string{"_id": deviceID})
	u := *c.base
	u.Path = strings.TrimRight(u.Path, "/") + "/devices"
	u.RawQuery = url.Values{"query": {string(q)}, "projection": {"_id,InternetGatewayDevice.DeviceInfo.SoftwareVersion,Device.DeviceInfo.SoftwareVersion"}}.Encode()
	body, status, err := c.do(ctx, http.MethodGet, u.String(), nil)
	if err != nil {
		return "", err
	}
	if status != http.StatusOK {
		return "", fmt.Errorf("nbi: unexpected status %d", status)
	}
	var docs []map[string]any
	if err := json.Unmarshal(body, &docs); err != nil {
		return "", fmt.Errorf("nbi: decode: %w", err)
	}
	if len(docs) != 1 {
		return "", ErrBadDeviceID // unknown device: never create a task for an id the ACS does not list
	}
	roots := make([]string, 0, 2)
	for r := range refreshGroups {
		if _, ok := docs[0][r]; ok {
			roots = append(roots, r)
		}
	}
	sort.Strings(roots)
	if len(roots) != 1 {
		return "", ErrNoDataModel
	}
	return roots[0], nil
}

func (c *Client) postTask(ctx context.Context, deviceID string, names []string) (status int, taskID string, faulted bool, err error) {
	body, err := json.Marshal(map[string]any{"name": "getParameterValues", "parameterNames": names})
	if err != nil {
		return 0, "", false, err
	}
	u := *c.base
	u.Path = strings.TrimRight(u.Path, "/") + "/devices/" + deviceID + "/tasks"
	// GenieACS _id values contain literal '%' (e.g. "hAP%20lite"); u.Path is escaped once more on the wire, which is what the NBI expects.
	u.RawQuery = url.Values{"timeout": {fmt.Sprint(taskTimeoutMS)}, "connection_request": {""}}.Encode()
	resp, st, err := c.do(ctx, http.MethodPost, u.String(), body)
	if err != nil {
		return 0, "", false, err
	}
	if st != http.StatusOK && st != http.StatusAccepted {
		return st, "", false, &rejectedError{status: st}
	}
	var t struct {
		ID    string          `json:"_id"`
		Fault json.RawMessage `json:"fault"`
	}
	_ = json.Unmarshal(resp, &t) // tolerant: an unparsable body just means there is no id to clean up
	if !taskIDRe.MatchString(t.ID) {
		t.ID = ""
	}
	return st, t.ID, len(t.Fault) > 0 && string(t.Fault) != "null", nil
}

// definitelyNotCreated lists the statuses that mean "refused before creating a task": malformed request, no/bad credentials, forbidden,
// unknown device, wrong method, invalid body. Everything else (timeouts, rate limits, gateway errors, 5xx) is ambiguous.
var definitelyNotCreated = map[int]bool{400: true, 401: true, 403: true, 404: true, 405: true, 422: true}

type rejectedError struct{ status int }

func (e *rejectedError) Error() string {
	return fmt.Sprintf("nbi: task rejected with status %d", e.status)
}

// cleanupTasks removes the task(s) THIS call created on deviceID and proves nothing of ours is left. Ownership rules, strictest first:
//   - the ACS returned a well-formed task id: only that id is deleted, and only if the device's task list shows it; a look-alike next to it
//     (same shape, same window) cannot be attributed, so the call fails closed without touching either;
//   - no usable id: a task is ours only if it is the ONLY one on the device with getParameterValues + exactly the posted names + a stamp not
//     older than the call (small skew). Two or more candidates cannot be attributed, so the call fails closed (the caller holds the device).
//
// Residual risk (accepted, ADR-SD-002): with no id and exactly one look-alike created within the skew window by someone else, that one
// read-only task of the same allowlisted leaves would be removed.
func (c *Client) cleanupTasks(ctx context.Context, deviceID string, names []string, since time.Time, knownID string) error {
	docs, err := c.deviceTasks(ctx, deviceID)
	if err != nil {
		return err
	}
	var cand []string
	for _, d := range docs {
		if looksLikeOurs(d, names, since) {
			cand = append(cand, d.ID)
		}
	}
	var target string
	if knownID != "" {
		// The id is the proof of WHICH task is ours, but the listing must show it (with this device) before anything is deleted, and no other
		// same-shape task from the same window may exist: a duplicate cannot be attributed, so we fail closed instead of guessing.
		found := hasID(docs, knownID)
		for i := 1; i < settleChecks && !found; i++ { // the task we were told about may not be listed yet: look again, bounded
			select {
			case <-ctx.Done():
				return ctx.Err()
			case <-time.After(settleDelay):
			}
			if docs, err = c.deviceTasks(ctx, deviceID); err != nil {
				return err
			}
			cand = cand[:0]
			for _, d := range docs {
				if looksLikeOurs(d, names, since) {
					cand = append(cand, d.ID)
				}
			}
			found = hasID(docs, knownID)
		}
		if !found {
			return errors.New("nbi: the task the ACS returned is not in the device's task list")
		}
		for _, id := range cand {
			if id != knownID {
				return errors.New("nbi: another look-alike task exists next to ours, cannot attribute")
			}
		}
		target = knownID
	} else {
		// No id and nothing listed yet is NOT proof that nothing was created (the task may become visible a moment later): look again
		// over a short, bounded window before accepting "nothing of ours exists".
		for i := 1; i < settleChecks && len(cand) == 0; i++ {
			select {
			case <-ctx.Done():
				return ctx.Err()
			case <-time.After(settleDelay):
			}
			if docs, err = c.deviceTasks(ctx, deviceID); err != nil {
				return err
			}
			for _, d := range docs {
				if looksLikeOurs(d, names, since) {
					cand = append(cand, d.ID)
				}
			}
		}
		if len(cand) > 1 {
			return errors.New("nbi: several look-alike tasks, cannot attribute ours")
		}
		if len(cand) == 1 {
			target = cand[0]
		}
	}
	if target == "" {
		// Nothing of ours was seen, but with no task id from the ACS that is not proof that nothing was created.
		return ErrRefreshUnproven
	}
	if err := c.deleteTask(ctx, target); err != nil {
		return err
	}
	after, err := c.deviceTasks(ctx, deviceID)
	if err != nil {
		return err
	}
	for _, d := range after {
		if d.ID == target || looksLikeOurs(d, names, since) {
			return errors.New("nbi: task still present after delete")
		}
	}
	return nil
}

// settleChecks lists in total (the first plus settleChecks-1 more, settleDelay apart) before "no task of ours" is accepted. Variables so tests
// can shrink the wait; production keeps ~4 s.
var (
	settleChecks = 3
	settleDelay  = 2 * time.Second
)

const (
	taskClockSkew   = 5 * time.Second
	maxTaskListBody = 4 << 20
)

type taskDoc struct {
	ID        string   `json:"_id"`
	Name      string   `json:"name"`
	Device    string   `json:"device"`
	Names     []string `json:"parameterNames"`
	Timestamp string   `json:"timestamp"`
}

func looksLikeOurs(d taskDoc, names []string, since time.Time) bool {
	ts, err := time.Parse(time.RFC3339, d.Timestamp)
	return err == nil && d.Name == "getParameterValues" && sameNames(d.Names, names) && !ts.Before(since.Add(-taskClockSkew))
}

// deviceTasks lists the tasks of ONE device (query sent to the ACS and re-checked here). A list too large to read in full is an error:
// cleanup is never declared on a partial view.
func (c *Client) deviceTasks(ctx context.Context, deviceID string) ([]taskDoc, error) {
	q, _ := json.Marshal(map[string]string{"device": deviceID})
	u := *c.base
	u.Path = strings.TrimRight(u.Path, "/") + "/tasks"
	u.RawQuery = url.Values{"query": {string(q)}}.Encode()
	body, st, err := c.doLimit(ctx, http.MethodGet, u.String(), nil, maxTaskListBody)
	if err != nil {
		return nil, err
	}
	if st != http.StatusOK {
		return nil, fmt.Errorf("nbi: list tasks status %d", st)
	}
	var docs []taskDoc
	if err := json.Unmarshal(body, &docs); err != nil {
		return nil, fmt.Errorf("nbi: decode tasks: %w", err)
	}
	out := docs[:0]
	for _, d := range docs {
		if d.Device == deviceID && taskIDRe.MatchString(d.ID) {
			out = append(out, d)
		}
	}
	return out, nil
}

func allAllowlisted(names []string) bool {
	if len(names) == 0 {
		return false
	}
	for _, n := range names {
		if _, ok := allowlist[n]; !ok {
			return false
		}
	}
	return true
}

func hasID(docs []taskDoc, id string) bool {
	for _, d := range docs {
		if d.ID == id {
			return true
		}
	}
	return false
}

func sameNames(a, b []string) bool {
	if len(a) != len(b) {
		return false
	}
	x, y := append([]string(nil), a...), append([]string(nil), b...)
	sort.Strings(x)
	sort.Strings(y)
	for i := range x {
		if x[i] != y[i] {
			return false
		}
	}
	return true
}

func (c *Client) deleteTask(ctx context.Context, taskID string) error {
	if !taskIDRe.MatchString(taskID) {
		return errors.New("nbi: invalid task id")
	}
	u := *c.base
	u.Path = strings.TrimRight(u.Path, "/") + "/tasks/" + taskID
	_, st, err := c.do(ctx, http.MethodDelete, u.String(), nil)
	if err != nil {
		return err
	}
	if st != http.StatusOK && st != http.StatusNoContent {
		return fmt.Errorf("nbi: delete task status %d", st)
	}
	return nil
}

// do is the single request path of the refresh feature: the method is one of three literals chosen by the callers above.
func (c *Client) do(ctx context.Context, method, rawURL string, body []byte) ([]byte, int, error) {
	return c.doLimit(ctx, method, rawURL, body, maxTaskBody)
}

func (c *Client) doLimit(ctx context.Context, method, rawURL string, body []byte, limit int64) ([]byte, int, error) {
	var rd io.Reader
	if body != nil {
		rd = bytes.NewReader(body)
	}
	req, err := http.NewRequestWithContext(ctx, method, rawURL, rd)
	if err != nil {
		return nil, 0, err
	}
	if body != nil {
		req.Header.Set("Content-Type", "application/json")
	}
	if c.authUser != "" {
		req.SetBasicAuth(c.authUser, c.authPass)
	}
	resp, err := c.http.Do(req)
	if err != nil {
		return nil, 0, err
	}
	defer resp.Body.Close()
	b, err := io.ReadAll(io.LimitReader(resp.Body, limit+1))
	if err != nil {
		return nil, resp.StatusCode, err
	}
	if int64(len(b)) > limit {
		return nil, resp.StatusCode, fmt.Errorf("nbi: response exceeds %d bytes", limit)
	}
	return b, resp.StatusCode, nil
}
