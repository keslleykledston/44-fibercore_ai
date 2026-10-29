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
	errNotAllowlisted   = errors.New("nbi refresh: parameter outside the allowlist")
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
	for _, g := range groups {
		rep.Groups++
		status, taskID, faulted, err := c.postTask(ctx, deviceID, g)
		if err != nil {
			// A lost response, a timeout or a 5xx does not prove the ACS did NOT create the task. Only an explicit 4xx rejection does.
			var rej *rejectedError
			if errors.As(err, &rej) && rej.status >= 400 && rej.status < 500 {
				return rep, err
			}
			rep.Uncleaned++
			return rep, fmt.Errorf("%w: %v", ErrRefreshUncleaned, err)
		}
		switch {
		case status == http.StatusOK && !faulted:
			rep.Completed++
		case faulted:
			rep.Faulted++
		default:
			rep.Queued++
		}
		if status != http.StatusOK || faulted { // never leave a queued/faulted task retrying on a customer CPE
			if taskID != "" && c.deleteTask(ctx, taskID) == nil {
				rep.Cleaned++
			} else {
				rep.Uncleaned++
				return rep, ErrRefreshUncleaned // stop: no further task is created while one may still be pending
			}
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

type rejectedError struct{ status int }

func (e *rejectedError) Error() string {
	return fmt.Sprintf("nbi: task rejected with status %d", e.status)
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
	b, err := io.ReadAll(io.LimitReader(resp.Body, maxTaskBody+1))
	if err != nil {
		return nil, resp.StatusCode, err
	}
	if len(b) > maxTaskBody {
		return nil, resp.StatusCode, fmt.Errorf("nbi: response exceeds %d bytes", maxTaskBody)
	}
	return b, resp.StatusCode, nil
}
