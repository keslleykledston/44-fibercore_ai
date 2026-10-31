package nbi

import (
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"net/http"
	"net/url"
	"regexp"
	"strconv"
	"strings"
	"time"
)

// ADR-0038 (bench only): the TR-143 throughput test of the bench CPE. This file writes exactly ONE task shape (a setParameterValues that sets the
// interface, the one URL, [TestFileLength for the upload] and DiagnosticsState=Requested of the Download/Upload diagnostics object), reads back only
// leaves of that same object, and never repeats the request. The device was already identified against the closed bench list by the caller's
// BenchDevice and is confirmed against the ACS here; the destination URL comes from the Edge's own validated catalog (internal/speed), never from the Cloud.

const (
	speedTR181Download = "Device.IP.Diagnostics.DownloadDiagnostics"
	speedTR181Upload   = "Device.IP.Diagnostics.UploadDiagnostics"
	speedTR098Download = "InternetGatewayDevice.DownloadDiagnostics"
	speedTR098Upload   = "InternetGatewayDevice.UploadDiagnostics"
	speedStateLeaf     = "DiagnosticsState"
	speedRequested     = "Requested"
	speedCompleted     = "Completed"
	maxSpeedCounter    = int64(1_000_000_000_000)
)

var (
	ErrSpeedUnsupported = errors.New("nbi speed: the CPE does not expose a writable TR-143 diagnostics object in the interface's data model")
	ErrSpeedBusy        = errors.New("nbi speed: a diagnostic is already requested on this CPE")
	ErrSpeedInvalid     = errors.New("nbi speed: request outside the accepted shape")
	ErrSpeedRead        = errors.New("nbi speed: could not read the diagnostics object from the CPE")
	ErrSpeedTimeout     = errors.New("nbi speed: the diagnostic did not finish inside the wait; the CPE may still be generating traffic")
)

// SpeedRequest is everything the caller decides. Root is "tr181" or "tr098" (the data model of the configured WAN interface); URL is built by
// internal/speed from a fixed template over a pinned IP literal.
type SpeedRequest struct {
	Direction  string // download | upload
	Root       string
	Interface  string
	URL        string
	FileLength int64 // upload only
}

// SpeedCounters are the raw leaves of the finished diagnostic. A nil field is a leaf the CPE did not report (or reported out of range): the Cloud
// computes nothing from what is not there.
type SpeedCounters struct {
	State                                                                string
	BOM, EOM                                                             string // RFC 3339 with a zone, or "" when absent/unusable
	TestBytesReceived, TotalBytesReceived, TestBytesSent, TotalBytesSent *int64
}

// SpeedOutcome: Attempted = the request task was POSTed (from here on the outcome can be unknown). Counters is set only for a finished diagnostic
// (Completed or an Error_ state) read after the request.
type SpeedOutcome struct {
	Attempted bool
	Counters  *SpeedCounters
	Detail    string
}

var speedURLRe = regexp.MustCompile(`^http://(\[[0-9a-f:]+\]|[0-9.]+):[0-9]{1,5}/(dl|ul)/(10mb|50mb|200mb)$`)

func speedObject(root, direction string) (string, error) {
	switch {
	case root == "tr181" && direction == "download":
		return speedTR181Download, nil
	case root == "tr181" && direction == "upload":
		return speedTR181Upload, nil
	case root == "tr098" && direction == "download":
		return speedTR098Download, nil
	case root == "tr098" && direction == "upload":
		return speedTR098Upload, nil
	}
	return "", ErrSpeedInvalid
}

func (r SpeedRequest) valid() (string, error) {
	obj, err := speedObject(r.Root, r.Direction)
	if err != nil {
		return "", err
	}
	want := map[string]string{"download": "/dl/", "upload": "/ul/"}[r.Direction]
	if !speedURLRe.MatchString(r.URL) || !strings.Contains(r.URL, want) || r.Interface == "" || strings.ContainsAny(r.Interface, " \t\r\n;,") {
		return "", ErrSpeedInvalid
	}
	if (r.Direction == "upload") != (r.FileLength > 0) || r.FileLength > 200_000_000 {
		return "", ErrSpeedInvalid
	}
	return obj, nil
}

type speedLeaf struct {
	Value any
	At    time.Time
}

// RunBenchSpeed runs the whole bench test for one identified bench device: confirm the identity and the recent inform, refuse when a bench write is
// pending or a diagnostic is already requested, set the diagnostic ONCE, then poll its result until it finishes or `wait` runs out. It never re-sends
// the request, and never leaves its own queued task on the ACS.
//
// notAfter bounds everything up to and including the single send; the polling after it uses `parent`.
func (c *Client) RunBenchSpeed(parent context.Context, d BenchDevice, req SpeedRequest, notAfter time.Time, wait, poll time.Duration, now func() time.Time) (SpeedOutcome, error) {
	obj, err := req.valid()
	if err != nil {
		return SpeedOutcome{}, err
	}
	c.refreshMu.Lock()
	defer c.refreshMu.Unlock()
	ctx, cancel := context.WithDeadline(parent, notAfter)
	defer cancel()
	g, err := c.benchDevice(ctx, d)
	if err != nil {
		return SpeedOutcome{}, err
	}
	if err := informFresh(g, now()); err != nil {
		return SpeedOutcome{}, err
	}
	docs, err := c.deviceTasks(ctx, d.DeviceID)
	if err != nil {
		return SpeedOutcome{}, err
	}
	for _, t := range docs {
		if t.Name == taskSetValues || t.Name == "reboot" {
			return SpeedOutcome{}, ErrBenchPending
		}
	}
	extra, err := c.speedCacheLeaves(ctx, d.DeviceID, req.Root, req.Direction)
	if err != nil {
		return SpeedOutcome{}, err
	}
	for _, n := range speedRequired(req.Direction) {
		if !extra[n] {
			return SpeedOutcome{}, ErrSpeedUnsupported
		}
	}
	cur, err := c.readSpeedLeaves(ctx, d.DeviceID, obj, []string{speedStateLeaf})
	if err != nil {
		return SpeedOutcome{}, err
	}
	if s, _ := cur[speedStateLeaf].Value.(string); s == speedRequested {
		return SpeedOutcome{}, ErrSpeedBusy
	}
	since := now()
	if !since.Before(notAfter) {
		return SpeedOutcome{}, ErrBenchExpired
	}
	status, taskID, err := c.postSetSpeed(ctx, d.DeviceID, obj, req)
	out := SpeedOutcome{Attempted: true}
	ctx = parent
	switch {
	case err == nil && status == http.StatusOK:
		// the CPE acknowledged the RPC: the diagnostic is running (or already finished)
	case err == nil && status == http.StatusAccepted:
		// queued: the CPE did not answer the connection request. Nothing started; remove our task so it cannot fire later.
		if cerr := c.removeOwnTask(ctx, d.DeviceID, taskSetValues, taskID, since); cerr != nil {
			out.Detail = "speed task queued and not removed"
			return out, fmt.Errorf("%w: %v", ErrBenchUncleaned, cerr)
		}
		out.Detail = "device unreachable; test not started"
		return out, errNotDelivered
	default:
		var rj *rejectedError
		if errors.As(err, &rj) && definitelyNotCreated[rj.status] {
			out.Detail = fmt.Sprintf("ACS refused the task (%d)", rj.status)
			return out, errNotDelivered
		}
		// ambiguous: the task may exist and the test may be running. Remove what is ours; the outcome stays unknown (the caller locks the target).
		if cerr := c.removeOwnTask(ctx, d.DeviceID, taskSetValues, taskID, since); cerr != nil {
			out.Detail = "ambiguous speed request and cleanup failed"
			return out, fmt.Errorf("%w: %v", ErrBenchUncleaned, cerr)
		}
		out.Detail = "ambiguous speed request"
		return out, errAmbiguous
	}
	names := speedResultLeaves(req.Direction, extra)
	deadline := time.Now().Add(wait)
	for {
		select {
		case <-ctx.Done():
			out.Detail = "polling interrupted"
			return out, ErrSpeedTimeout
		case <-time.After(poll):
		}
		leaves, rerr := c.readSpeedLeaves(ctx, d.DeviceID, obj, names)
		if rerr == nil {
			if cn := finishedCounters(leaves, since); cn != nil {
				out.Counters = cn
				out.Detail = "diagnostic finished"
				return out, nil
			}
		}
		if time.Now().After(deadline) {
			out.Detail = "no finished result inside the wait"
			return out, ErrSpeedTimeout
		}
	}
}

// speedRequired are the result leaves a CPE must list in its cached object for the test to be attempted at all: asking a CPE for a parameter it does not
// have is a fault that would hide the whole read, so a missing one means "unsupported", decided BEFORE anything is written.
func speedRequired(direction string) []string {
	if direction == "download" {
		return []string{speedStateLeaf, "BOMTime", "EOMTime", "TestBytesReceived", "TotalBytesReceived"}
	}
	return []string{speedStateLeaf, "BOMTime", "EOMTime", "TotalBytesSent"}
}

// speedResultLeaves: the required leaves, plus TestBytesSent for the upload when the cached object lists it.
func speedResultLeaves(direction string, cached map[string]bool) []string {
	names := speedRequired(direction)
	if direction == "upload" && cached["TestBytesSent"] {
		names = append(names, "TestBytesSent")
	}
	return names
}

// finishedCounters returns the counters when the state is terminal (Completed or Error_*) AND was read after the request (a leaf older than the request
// is the result of an earlier test and is ignored).
func finishedCounters(l map[string]speedLeaf, since time.Time) *SpeedCounters {
	st, ok := l[speedStateLeaf]
	state, _ := st.Value.(string)
	if !ok || (state != speedCompleted && !strings.HasPrefix(state, "Error_")) || st.At.Before(since.Add(-taskClockSkew)) {
		return nil
	}
	return &SpeedCounters{
		State: state, BOM: speedTime(l["BOMTime"].Value), EOM: speedTime(l["EOMTime"].Value),
		TestBytesReceived: speedInt(l["TestBytesReceived"].Value), TotalBytesReceived: speedInt(l["TotalBytesReceived"].Value),
		TestBytesSent: speedInt(l["TestBytesSent"].Value), TotalBytesSent: speedInt(l["TotalBytesSent"].Value),
	}
}

// speedTime keeps a device time only when it carries a zone and is not the TR-143 "unset" value (year 1).
func speedTime(v any) string {
	s, _ := v.(string)
	t, err := time.Parse(time.RFC3339Nano, s)
	if err != nil || t.Year() < 2000 {
		return ""
	}
	return t.UTC().Format(time.RFC3339Nano)
}

func speedInt(v any) *int64 {
	var n int64
	switch x := v.(type) {
	case float64:
		if x != float64(int64(x)) {
			return nil
		}
		n = int64(x)
	case string:
		p, err := strconv.ParseInt(x, 10, 64)
		if err != nil {
			return nil
		}
		n = p
	default:
		return nil
	}
	if n < 0 || n > maxSpeedCounter {
		return nil
	}
	return &n
}

func (c *Client) postSetSpeed(ctx context.Context, deviceID, obj string, r SpeedRequest) (status int, taskID string, err error) {
	urlLeaf := "DownloadURL"
	values := [][]string{{obj + ".Interface", r.Interface, "xsd:string"}}
	if r.Direction == "upload" {
		urlLeaf = "UploadURL"
		values = append(values, []string{obj + "." + urlLeaf, r.URL, "xsd:string"}, []string{obj + ".TestFileLength", strconv.FormatInt(r.FileLength, 10), "xsd:unsignedInt"})
	} else {
		values = append(values, []string{obj + "." + urlLeaf, r.URL, "xsd:string"})
	}
	values = append(values, []string{obj + "." + speedStateLeaf, speedRequested, "xsd:string"})
	body, _ := json.Marshal(map[string]any{"name": "setParameterValues", "parameterValues": values})
	u := *c.base
	u.Path = strings.TrimRight(u.Path, "/") + "/devices/" + deviceID + "/tasks"
	u.RawQuery = url.Values{"timeout": {fmt.Sprint(benchTaskTimeoutMS)}, "connection_request": {""}}.Encode()
	resp, st, err := c.do(ctx, http.MethodPost, u.String(), body)
	if err != nil {
		return 0, "", err
	}
	if st != http.StatusOK && st != http.StatusAccepted {
		return st, "", &rejectedError{status: st}
	}
	var t struct {
		ID    string          `json:"_id"`
		Fault json.RawMessage `json:"fault"`
	}
	_ = json.Unmarshal(resp, &t)
	if len(t.Fault) > 0 && string(t.Fault) != "null" {
		return st, "", &rejectedError{status: http.StatusUnprocessableEntity} // the CPE faulted: not applied
	}
	if !taskIDRe.MatchString(t.ID) {
		t.ID = ""
	}
	return st, t.ID, nil
}

// speedCacheLeaves reads the ACS CACHE (no task): the diagnostics object of the interface's data model must be there with a writable state leaf, and it
// must not exist in the other data model too. It returns the optional leaves the cached object lists.
func (c *Client) speedCacheLeaves(ctx context.Context, deviceID, root, direction string) (map[string]bool, error) {
	other := "tr098"
	if root == "tr098" {
		other = "tr181"
	}
	mine, _ := speedObject(root, direction)
	theirs, _ := speedObject(other, direction)
	doc, err := c.deviceDoc(ctx, deviceID, []string{mine, theirs})
	if err != nil {
		return nil, ErrSpeedRead
	}
	if node, ok := walk(doc, theirs); ok && len(node) > 0 {
		return nil, ErrSpeedUnsupported // present in both data models: not a single, unambiguous root
	}
	node, ok := walk(doc, mine)
	if !ok {
		return nil, ErrSpeedUnsupported
	}
	st, _ := node[speedStateLeaf].(map[string]any)
	if w, _ := st["_writable"].(bool); !w {
		return nil, ErrSpeedUnsupported
	}
	out := map[string]bool{}
	for k, v := range node {
		if _, leaf := v.(map[string]any); leaf && !strings.HasPrefix(k, "_") {
			out[k] = true
		}
	}
	return out, nil
}

// readSpeedLeaves asks the CPE for leaves of the diagnostics object (a getParameterValues task) and returns the values the ACS then holds, with the time it
// captured each one.
func (c *Client) readSpeedLeaves(ctx context.Context, deviceID, obj string, names []string) (map[string]speedLeaf, error) {
	paths := make([]string, len(names))
	for i, n := range names {
		paths[i] = obj + "." + n
	}
	st, taskID, faulted, err := c.postTask(ctx, deviceID, paths)
	if err != nil || st != http.StatusOK || faulted {
		if st == http.StatusAccepted && taskID != "" {
			_ = c.deleteTask(ctx, taskID) // our read, queued because the CPE did not answer
		}
		return nil, ErrSpeedRead
	}
	doc, err := c.deviceDoc(ctx, deviceID, []string{obj})
	if err != nil {
		return nil, ErrSpeedRead
	}
	node, ok := walk(doc, obj)
	if !ok {
		return nil, ErrSpeedRead
	}
	out := map[string]speedLeaf{}
	for _, n := range names {
		leaf, ok := node[n].(map[string]any)
		if !ok {
			continue
		}
		ts, _ := leaf["_timestamp"].(string)
		at, _ := time.Parse(time.RFC3339, ts)
		out[n] = speedLeaf{Value: leaf["_value"], At: at}
	}
	return out, nil
}

// deviceDoc GETs ONE device with a projection of the given object paths.
func (c *Client) deviceDoc(ctx context.Context, deviceID string, projection []string) (map[string]any, error) {
	q, _ := json.Marshal(map[string]string{"_id": deviceID})
	u := *c.base
	u.Path = strings.TrimRight(u.Path, "/") + "/devices"
	u.RawQuery = url.Values{"query": {string(q)}, "projection": {strings.Join(projection, ",")}}.Encode()
	body, st, err := c.do(ctx, http.MethodGet, u.String(), nil)
	if err != nil || st != http.StatusOK {
		return nil, ErrSpeedRead
	}
	var docs []map[string]any
	if json.Unmarshal(body, &docs) != nil || len(docs) != 1 {
		return nil, ErrSpeedRead
	}
	return docs[0], nil
}

func walk(doc map[string]any, path string) (map[string]any, bool) {
	var cur any = doc
	for _, k := range strings.Split(path, ".") {
		m, ok := cur.(map[string]any)
		if !ok {
			return nil, false
		}
		if cur, ok = m[k]; !ok {
			return nil, false
		}
	}
	m, ok := cur.(map[string]any)
	return m, ok
}
