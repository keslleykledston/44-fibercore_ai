package nbi

import (
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"net/http"
	"net/url"
	"strings"
	"time"
)

// ADR-0030 (bench homologation). This file holds the ONLY write the Edge can send to the ACS: a `reboot` task for ONE device that is on the
// closed bench list, whose identity (OUI / product class / serial) was just read back from the ACS and matches that list exactly.
// Nothing here chooses a device: the caller passes the id the Cloud signed and the bench entry from local configuration, and both are checked.

const (
	benchTaskTimeoutMS = 10000
	// MaxInformAge: the CPE must have informed the ACS recently, otherwise it is not proven reachable and nothing is sent.
	MaxInformAge = 30 * time.Minute
)

var (
	ErrBenchIdentity  = errors.New("nbi bench: ACS device does not match the configured bench identity")
	ErrBenchOffline   = errors.New("nbi bench: device has not informed the ACS recently")
	ErrBenchPending   = errors.New("nbi bench: a reboot task is already pending on this device")
	ErrBenchUncleaned = errors.New("nbi bench: an unfinished reboot task could not be removed from the ACS")
)

// BenchDevice is one entry of the local closed list (copied from configuration by the caller).
type BenchDevice struct {
	DeviceID, OUI, ProductClass, Serial string
}

type benchDoc struct {
	ID       string `json:"_id"`
	LastBoot string `json:"_lastBoot"`
	Inform   string `json:"_lastInform"`
	DeviceID struct {
		OUI    string `json:"_OUI"`
		Class  string `json:"_ProductClass"`
		Serial string `json:"_SerialNumber"`
	} `json:"_deviceId"`
}

// BenchOutcome is what the caller reports to the Cloud. Accepted: the ACS delivered the reboot to the CPE. PostcheckOK: the CPE came back
// with a boot later than the request. Anything else is reported UNKNOWN by the caller (never a retry).
type BenchOutcome struct {
	Attempted   bool // the reboot task was POSTed: from here on the outcome can be unknown
	Accepted    bool
	PostcheckOK bool
	Detail      string
}

// BenchDeviceDoc reads the device document, requiring exactly one match whose _id and identity equal the bench entry. A duplicate, missing or
// placeholder value anywhere refuses.
func (c *Client) benchDevice(ctx context.Context, d BenchDevice) (benchDoc, error) {
	if !deviceIDRe.MatchString(d.DeviceID) || d.OUI == "" || d.ProductClass == "" || d.Serial == "" {
		return benchDoc{}, ErrBadDeviceID
	}
	q, _ := json.Marshal(map[string]string{"_id": d.DeviceID})
	u := *c.base
	u.Path = strings.TrimRight(u.Path, "/") + "/devices"
	u.RawQuery = url.Values{"query": {string(q)}, "projection": {"_id,_lastBoot,_lastInform,_deviceId"}}.Encode()
	body, st, err := c.doLimit(ctx, http.MethodGet, u.String(), nil, maxTaskListBody)
	if err != nil {
		return benchDoc{}, err
	}
	if st != http.StatusOK {
		return benchDoc{}, fmt.Errorf("nbi: device lookup status %d", st)
	}
	var docs []benchDoc
	if err := json.Unmarshal(body, &docs); err != nil {
		return benchDoc{}, fmt.Errorf("nbi: decode device: %w", err)
	}
	if len(docs) != 1 {
		return benchDoc{}, fmt.Errorf("%w: %d matches", ErrBenchIdentity, len(docs))
	}
	g := docs[0]
	if g.ID != d.DeviceID || g.DeviceID.OUI != d.OUI || g.DeviceID.Class != d.ProductClass || g.DeviceID.Serial != d.Serial {
		return benchDoc{}, ErrBenchIdentity
	}
	return g, nil
}

// BenchIdentity confirms, against the ACS right now, that the device is the configured bench device and that it is recently online.
func (c *Client) BenchIdentity(ctx context.Context, d BenchDevice, now time.Time) error {
	g, err := c.benchDevice(ctx, d)
	if err != nil {
		return err
	}
	return informFresh(g, now)
}

func informFresh(g benchDoc, now time.Time) error {
	t, err := time.Parse(time.RFC3339, g.Inform)
	if err != nil || now.Sub(t) > MaxInformAge || t.After(now.Add(5*time.Minute)) {
		return ErrBenchOffline
	}
	return nil
}

// RebootBench asks the ACS to reboot the bench device `d` (already identified) and checks, within `wait`, that the CPE booted again.
// The caller has already durably claimed the authorization and reserved the pacing slot: this function never retries a reboot.
func (c *Client) RebootBench(ctx context.Context, d BenchDevice, wait, poll time.Duration, now func() time.Time) (BenchOutcome, error) {
	c.refreshMu.Lock() // never interleaves with an active read of the same ACS client
	defer c.refreshMu.Unlock()
	g, err := c.benchDevice(ctx, d)
	if err != nil {
		return BenchOutcome{}, err
	}
	if err := informFresh(g, now()); err != nil {
		return BenchOutcome{}, err
	}
	docs, err := c.deviceTasks(ctx, d.DeviceID)
	if err != nil {
		return BenchOutcome{}, err
	}
	for _, t := range docs {
		if t.Name == "reboot" {
			return BenchOutcome{}, ErrBenchPending
		}
	}
	before, _ := time.Parse(time.RFC3339, g.LastBoot)
	since := now()
	status, taskID, err := c.postReboot(ctx, d.DeviceID)
	attempted := true
	switch {
	case err == nil && status == http.StatusOK:
		// the CPE acknowledged the RPC; the task is gone from the ACS
	case err == nil && status == http.StatusAccepted:
		// queued: the CPE did not answer the connection request. Not delivered; remove our task so it cannot fire later.
		if cerr := c.removeReboot(ctx, d.DeviceID, taskID, since); cerr != nil {
			return BenchOutcome{Attempted: attempted, Detail: "reboot queued and not removed"}, fmt.Errorf("%w: %v", ErrBenchUncleaned, cerr)
		}
		return BenchOutcome{Attempted: attempted, Detail: "device unreachable; reboot not delivered"}, errNotDelivered
	default:
		var rj *rejectedError
		if errors.As(err, &rj) && definitelyNotCreated[rj.status] {
			return BenchOutcome{Attempted: attempted, Detail: fmt.Sprintf("ACS refused the task (%d)", rj.status)}, errNotDelivered
		}
		// ambiguous: the task may exist and may have reached the CPE. Remove what is ours; the outcome stays unknown.
		if cerr := c.removeReboot(ctx, d.DeviceID, taskID, since); cerr != nil {
			return BenchOutcome{Attempted: attempted, Detail: "ambiguous reboot request and cleanup failed"}, fmt.Errorf("%w: %v", ErrBenchUncleaned, cerr)
		}
		return BenchOutcome{Attempted: attempted, Detail: "ambiguous reboot request"}, errAmbiguous
	}
	out := BenchOutcome{Attempted: attempted, Accepted: true, Detail: "reboot delivered"}
	deadline := time.Now().Add(wait)
	for {
		select {
		case <-ctx.Done():
			out.Detail = "reboot delivered; postcheck interrupted"
			return out, nil
		case <-time.After(poll):
		}
		if cur, err := c.benchDevice(ctx, d); err == nil {
			if t, perr := time.Parse(time.RFC3339, cur.LastBoot); perr == nil && !t.Before(since.Add(-taskClockSkew)) && t.After(before) {
				out.PostcheckOK, out.Detail = true, "device rebooted and informed again"
				return out, nil
			}
		}
		if time.Now().After(deadline) {
			out.Detail = "reboot delivered; no new boot seen within the wait"
			return out, nil
		}
	}
}

// errNotDelivered: nothing reached the CPE (known, cleaned up). errAmbiguous: it may have.
var (
	errNotDelivered = errors.New("nbi bench: reboot not delivered")
	errAmbiguous    = errors.New("nbi bench: reboot outcome ambiguous")
)

// IsNotDelivered reports a failure known to have had no effect on the device.
func IsNotDelivered(err error) bool { return errors.Is(err, errNotDelivered) }

func (c *Client) postReboot(ctx context.Context, deviceID string) (status int, taskID string, err error) {
	body, _ := json.Marshal(map[string]any{"name": "reboot"})
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
		ID string `json:"_id"`
	}
	_ = json.Unmarshal(resp, &t)
	if !taskIDRe.MatchString(t.ID) {
		t.ID = ""
	}
	return st, t.ID, nil
}

// removeReboot deletes the reboot task(s) this call created and proves none is left. With a known id only that id; without one, the single
// reboot task stamped not before the call (two or more cannot be attributed: fail closed).
func (c *Client) removeReboot(ctx context.Context, deviceID, knownID string, since time.Time) error {
	docs, err := c.deviceTasks(ctx, deviceID)
	if err != nil {
		return err
	}
	var cand []string
	for _, t := range docs {
		if t.Name != "reboot" {
			continue
		}
		if knownID != "" {
			if t.ID == knownID {
				cand = append(cand, t.ID)
			}
			continue
		}
		if ts, perr := time.Parse(time.RFC3339, t.Timestamp); perr == nil && !ts.Before(since.Add(-taskClockSkew)) {
			cand = append(cand, t.ID)
		}
	}
	if knownID == "" && len(cand) > 1 {
		return errors.New("cannot attribute the reboot task")
	}
	for _, id := range cand {
		if err := c.deleteTask(ctx, id); err != nil {
			return err
		}
	}
	left, err := c.deviceTasks(ctx, deviceID)
	if err != nil {
		return err
	}
	for _, t := range left {
		if t.Name == "reboot" && (knownID == "" || t.ID == knownID) {
			if knownID != "" || func() bool {
				ts, e := time.Parse(time.RFC3339, t.Timestamp)
				return e == nil && !ts.Before(since.Add(-taskClockSkew))
			}() {
				return errors.New("reboot task still listed")
			}
		}
	}
	return nil
}
