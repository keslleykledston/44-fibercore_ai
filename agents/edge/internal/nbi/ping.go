package nbi

import (
	"context"
	"errors"
	"net/http"
	"net/netip"
	"strconv"
	"strings"
	"time"
)

// ADR-0030 amendment (2026-10-31, line Q1) and ADR-0039 (bench only): the TR-143 IPPing test of the bench CPE. Like the throughput test, this file writes exactly ONE
// task shape (a setParameterValues that sets the interface, the host, the number of repetitions, the timeout and DiagnosticsState=Requested of the IPPing
// object), reads back only leaves of that same object, and never repeats the request. The destination is an IP literal from the Edge's own validated catalog
// (internal/ping), the repetitions and the timeout are fixed by the Edge, and the interface is the SERVICE WAN the owner wrote for the device: the ping measures
// the path the ISP delivers to the customer, exactly as the throughput test does.

const (
	pingTR181 = "Device.IP.Diagnostics.IPPing"
	pingTR098 = "InternetGatewayDevice.IPPingDiagnostics"
)

var (
	ErrPingInvalid = errors.New("nbi ping: request outside the accepted shape")
	ErrPingTimeout = errors.New("nbi ping: the diagnostic did not finish inside the wait")
)

// PingRequest is everything the caller decides. Root is "tr181" or "tr098" (the data model of the configured WAN interface); Host is an IP literal from the
// Edge's catalog; Repetitions and TimeoutMS are fixed by the Edge (internal/ping) and only bounded here.
type PingRequest struct {
	Root        string
	Interface   string
	Host        string
	Repetitions int
	TimeoutMS   int
}

// PingCounters are the raw leaves of the finished diagnostic. A nil field is a leaf the CPE did not report (or reported out of range): the Cloud computes
// nothing from what is not there. The times are milliseconds as TR-143 defines them.
type PingCounters struct {
	State               string
	Success, Failure    *int64
	AvgMS, MinMS, MaxMS *int64
}

// PingOutcome: Attempted = the request task was POSTed (from here on the outcome can be unknown). Counters is set only for a finished diagnostic
// (Completed or an Error_ state the CPE itself reported) read after the request.
type PingOutcome struct {
	Attempted bool
	Counters  *PingCounters
	Detail    string
}

func pingObject(root string) (string, error) {
	switch root {
	case "tr181":
		return pingTR181, nil
	case "tr098":
		return pingTR098, nil
	}
	return "", ErrPingInvalid
}

func (r PingRequest) valid() (string, error) {
	obj, err := pingObject(r.Root)
	if err != nil {
		return "", err
	}
	ip, perr := netip.ParseAddr(r.Host)
	if perr != nil || ip.Zone() != "" || ip.Is4In6() || r.Interface == "" || strings.ContainsAny(r.Interface, " \t\r\n;,") ||
		r.Repetitions < 1 || r.Repetitions > 10 || r.TimeoutMS < 100 || r.TimeoutMS > 10_000 {
		return "", ErrPingInvalid
	}
	return obj, nil
}

// pingRequired are the leaves a CPE must list in its cached object for the test to be attempted at all (a missing one means "unsupported", decided BEFORE
// anything is written).
func pingRequired() []string {
	return []string{speedStateLeaf, "SuccessCount", "FailureCount", "AverageResponseTime", "MinimumResponseTime", "MaximumResponseTime"}
}

// RunBenchPing runs the whole bench ping test for one identified bench device: confirm the identity and the recent inform, refuse when a bench write is pending
// or a diagnostic is already requested, verify the service WAN is connected, set the diagnostic ONCE, then poll its result until it finishes or `wait` runs out.
// It never re-sends the request and never leaves its own queued task on the ACS. notAfter bounds everything up to and including the single send.
func (c *Client) RunBenchPing(parent context.Context, d BenchDevice, req PingRequest, notAfter time.Time, wait, poll time.Duration, now func() time.Time) (PingOutcome, error) {
	obj, err := req.valid()
	if err != nil {
		return PingOutcome{}, err
	}
	c.refreshMu.Lock()
	defer c.refreshMu.Unlock()
	ctx, cancel := context.WithDeadline(parent, notAfter)
	defer cancel()
	g, err := c.benchDevice(ctx, d)
	if err != nil {
		return PingOutcome{}, err
	}
	if err := informFresh(g, now()); err != nil {
		return PingOutcome{}, err
	}
	docs, err := c.deviceTasks(ctx, d.DeviceID)
	if err != nil {
		return PingOutcome{}, err
	}
	for _, t := range docs {
		if t.Name == taskSetValues || t.Name == "reboot" {
			return PingOutcome{}, ErrBenchPending
		}
	}
	other := pingTR098
	if req.Root == "tr098" {
		other = pingTR181
	}
	listed, err := c.diagCacheLeaves(ctx, d.DeviceID, obj, other)
	if err != nil {
		return PingOutcome{}, err
	}
	for _, n := range pingRequired() {
		if !listed[n] {
			return PingOutcome{}, ErrSpeedUnsupported
		}
	}
	cur, err := c.readSpeedLeaves(ctx, d.DeviceID, obj, []string{speedStateLeaf})
	if err != nil {
		return PingOutcome{}, err
	}
	if s, _ := cur[speedStateLeaf].Value.(string); s == speedRequested {
		return PingOutcome{}, ErrSpeedBusy
	}
	if err := c.checkServiceWAN(ctx, d.DeviceID, req.Root, req.Interface, now); err != nil {
		return PingOutcome{}, err
	}
	since := now()
	if !since.Before(notAfter) {
		return PingOutcome{}, ErrBenchExpired
	}
	values := [][]string{
		{obj + ".Interface", req.Interface, "xsd:string"},
		{obj + ".Host", req.Host, "xsd:string"},
		{obj + ".NumberOfRepetitions", strconv.Itoa(req.Repetitions), "xsd:unsignedInt"},
		{obj + ".Timeout", strconv.Itoa(req.TimeoutMS), "xsd:unsignedInt"},
		{obj + "." + speedStateLeaf, speedRequested, "xsd:string"},
	}
	status, taskID, err := c.postSetValues(ctx, d.DeviceID, values)
	out := PingOutcome{Attempted: true}
	ctx = parent
	switch {
	case err == nil && status == http.StatusOK:
		// the CPE acknowledged the RPC: the diagnostic is running (or already finished)
	case err == nil && status == http.StatusAccepted:
		// queued: the CPE did not answer the connection request. Nothing started; remove our task so it cannot fire later.
		if cerr := c.removeOwnTask(ctx, d.DeviceID, taskSetValues, taskID, since); cerr != nil {
			out.Detail = "ping task queued and not removed"
			return out, errors.Join(ErrBenchUncleaned, cerr)
		}
		out.Detail = "device unreachable; test not started"
		return out, errNotDelivered
	default:
		var rj *rejectedError
		if errors.As(err, &rj) && definitelyNotCreated[rj.status] {
			out.Detail = "ACS refused the task"
			return out, errNotDelivered
		}
		// ambiguous: the task may exist and the test may be running. Remove what is ours; the outcome stays unknown (the caller locks the target).
		if cerr := c.removeOwnTask(ctx, d.DeviceID, taskSetValues, taskID, since); cerr != nil {
			out.Detail = "ambiguous ping request and cleanup failed"
			return out, errors.Join(ErrBenchUncleaned, cerr)
		}
		out.Detail = "ambiguous ping request"
		return out, errAmbiguous
	}
	names := pingRequired()
	deadline := time.Now().Add(wait)
	for {
		select {
		case <-ctx.Done():
			out.Detail = "polling interrupted"
			return out, ErrPingTimeout
		case <-time.After(poll):
		}
		leaves, rerr := c.readSpeedLeaves(ctx, d.DeviceID, obj, names)
		if rerr == nil {
			if cn := finishedPing(leaves, since); cn != nil {
				out.Counters = cn
				out.Detail = "diagnostic finished"
				return out, nil
			}
		}
		if time.Now().After(deadline) {
			out.Detail = "no finished result inside the wait"
			return out, ErrPingTimeout
		}
	}
}

// pingStateComplete is how the IPPing diagnostic names a finished test (see finishedPing).
const pingStateComplete = "Complete"

// finishedPing returns the counters when the state is terminal (Complete/Completed or Error_*) AND was read after the request (a leaf older than the request is the
// result of an earlier test and is ignored).
func finishedPing(l map[string]speedLeaf, since time.Time) *PingCounters {
	st, ok := l[speedStateLeaf]
	state, _ := st.Value.(string)
	// the IPPing object ends in "Complete" (TR-098/TR-181); the throughput objects end in "Completed". A ZTE F670L was measured ending in "Complete" (2026-11-01):
	// both mean a finished test and the report carries the one name the Cloud's closed shape knows.
	if state == pingStateComplete {
		state = speedCompleted
	}
	if !ok || (state != speedCompleted && !strings.HasPrefix(state, "Error_")) || st.At.Before(since.Add(-taskClockSkew)) {
		return nil
	}
	return &PingCounters{
		State:   state,
		Success: pingInt(freshValue(l, "SuccessCount", since)), Failure: pingInt(freshValue(l, "FailureCount", since)),
		AvgMS: pingInt(freshValue(l, "AverageResponseTime", since)), MinMS: pingInt(freshValue(l, "MinimumResponseTime", since)), MaxMS: pingInt(freshValue(l, "MaximumResponseTime", since)),
	}
}

// freshValue is a leaf's value only when the leaf itself was read STRICTLY after the request: a leaf the CPE did not return keeps its old value AND its old
// timestamp in the ACS, and an old counter is never presented as the result of this test. Unlike the state leaf (which tolerates the clock difference between
// the ACS and this host), a counter fails closed: a leaf left out makes the result inconclusive, a stale one would make it wrong.
func freshValue(l map[string]speedLeaf, name string, since time.Time) any {
	leaf, ok := l[name]
	if !ok || !leaf.At.After(since) {
		return nil
	}
	return leaf.Value
}

// pingInt is speedInt with the bound of a ping leaf: a count or a time in ms of at most a day; anything else is "not reported".
func pingInt(v any) *int64 {
	n := speedInt(v)
	if n == nil || *n > 86_400_000 {
		return nil
	}
	return n
}
