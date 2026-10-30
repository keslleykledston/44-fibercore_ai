package nbi

import (
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"net/http"
	"net/url"
	"os"
	"path/filepath"
	"strings"
	"time"
)

// ADR-0030 H3 (bench only): change the 2.4 GHz SSID of the bench CPE to the catalog value, read it back, then RESTORE the value read before and read
// that back too. Exactly one leaf is ever written (below). The original value stays on this host (restore file); only booleans leave it.

const (
	ssidLeaf      = "InternetGatewayDevice.LANDevice.1.WLANConfiguration.1.SSID" // TR-098, WLANConfiguration.1 = 2.4 GHz on the bench model (checked at H3)
	taskSetValues = "setParameterValues"                                         // the one write task name of this file (the reboot file only watches for it)
	ssidMaxBytes  = 32
	restoreTries  = 3
)

var restorePause = 2 * time.Second

var (
	ErrBenchSSIDRead    = errors.New("nbi bench: could not read the current SSID from the CPE")
	ErrBenchSSIDInvalid = errors.New("nbi bench: ssid outside the bench shape")
	ErrBenchRestore     = errors.New("nbi bench: the original SSID could not be restored; operator must restore it (restore file kept)")
)

// SSIDOutcome: Applied = the CPE acknowledged the set; Verified = it read back as requested; Restored = the original was set and read back.
type SSIDOutcome struct {
	Attempted, Applied, Verified, Restored bool
	Detail                                 string
}

type restoreRecord struct {
	Leaf     string `json:"leaf"`
	Original string `json:"original"`
	Target   string `json:"target"`
	At       string `json:"at"`
}

// SetBenchSSID runs the whole H3 maneuver for one identified bench device. `valid` is the bench SSID shape check (injected: the nbi package does
// not know the catalog). It never retries the change; only the restore (a return to the value read before) is repeated.
func (c *Client) SetBenchSSID(parent context.Context, d BenchDevice, ssid string, valid func(string) bool, notAfter time.Time, restoreFile string, now func() time.Time) (SSIDOutcome, error) {
	if valid == nil || !valid(ssid) {
		return SSIDOutcome{}, ErrBenchSSIDInvalid
	}
	c.refreshMu.Lock()
	defer c.refreshMu.Unlock()
	ctx, cancel := context.WithDeadline(parent, notAfter) // pre-send phase only
	defer cancel()
	g, err := c.benchDevice(ctx, d)
	if err != nil {
		return SSIDOutcome{}, err
	}
	if err := informFresh(g, now()); err != nil {
		return SSIDOutcome{}, err
	}
	docs, err := c.deviceTasks(ctx, d.DeviceID)
	if err != nil {
		return SSIDOutcome{}, err
	}
	for _, t := range docs {
		if t.Name == taskSetValues || t.Name == "reboot" {
			return SSIDOutcome{}, ErrBenchPending
		}
	}
	original, err := c.readSSID(ctx, d.DeviceID)
	if err != nil {
		return SSIDOutcome{}, err
	}
	if original == "" || len(original) > ssidMaxBytes || strings.ContainsFunc(original, func(r rune) bool { return r < 0x20 || r == 0x7f }) {
		return SSIDOutcome{}, fmt.Errorf("%w: unusable value", ErrBenchSSIDRead)
	}
	if original == ssid {
		return SSIDOutcome{}, fmt.Errorf("%w: the CPE already has that SSID", ErrBenchSSIDInvalid) // nothing to change, nothing to prove
	}
	// the way back is written to disk BEFORE anything changes: a crash from here on leaves a file saying what to restore
	rec, _ := json.Marshal(restoreRecord{Leaf: ssidLeaf, Original: original, Target: ssid, At: now().UTC().Format(time.RFC3339)})
	if err := writeFile0600(restoreFile, rec); err != nil {
		return SSIDOutcome{}, fmt.Errorf("nbi bench: cannot persist the restore record: %w", err)
	}
	since := now()
	if !since.Before(notAfter) {
		_ = os.Remove(restoreFile)
		return SSIDOutcome{}, ErrBenchExpired
	}
	status, taskID, err := c.postSetSSID(ctx, d.DeviceID, ssid)
	out := SSIDOutcome{Attempted: true}
	ctx = parent
	switch {
	case err == nil && status == http.StatusOK:
		out.Applied = true
	case err == nil && status == http.StatusAccepted:
		// queued: the CPE did not answer. Nothing changed; remove our task so it cannot fire later.
		if cerr := c.removeOwnTask(ctx, d.DeviceID, taskSetValues, taskID, since); cerr != nil {
			out.Detail = "ssid task queued and not removed"
			return out, fmt.Errorf("%w: %v", ErrBenchUncleaned, cerr)
		}
		_ = os.Remove(restoreFile)
		out.Detail = "device unreachable; ssid not changed"
		return out, errNotDelivered
	default:
		var rj *rejectedError
		if errors.As(err, &rj) && definitelyNotCreated[rj.status] {
			_ = os.Remove(restoreFile)
			out.Detail = fmt.Sprintf("ACS refused the task (%d)", rj.status)
			return out, errNotDelivered
		}
		// ambiguous: it may have been applied. Remove what is ours and fall through to the restore, which is safe either way.
		if cerr := c.removeOwnTask(ctx, d.DeviceID, taskSetValues, taskID, since); cerr != nil {
			out.Detail = "ambiguous ssid request and cleanup failed"
			return out, fmt.Errorf("%w: %v", ErrBenchUncleaned, cerr)
		}
	}
	if out.Applied {
		if v, rerr := c.readSSID(ctx, d.DeviceID); rerr == nil && v == ssid {
			out.Verified = true
		}
	}
	// restore: the value read before, set and read back; repeated (it is the return to the safe state), never the change itself
	var uncleaned error
restore:
	for i := 0; i < restoreTries && !out.Restored; i++ {
		if i > 0 {
			select {
			case <-ctx.Done():
				break restore
			case <-time.After(restorePause):
			}
		}
		st, id, perr := c.postSetSSID(ctx, d.DeviceID, original)
		if st == http.StatusAccepted && perr == nil {
			// queued: the CPE did not answer. A queued restore must not survive to overwrite a newer value later: remove it now, or stop.
			if cerr := c.removeOwnTask(ctx, d.DeviceID, taskSetValues, id, since); cerr != nil {
				uncleaned = cerr
				break restore
			}
			continue
		}
		if perr != nil || st != http.StatusOK {
			continue
		}
		if v, rerr := c.readSSID(ctx, d.DeviceID); rerr == nil && v == original {
			out.Restored = true
		}
	}
	if !out.Restored {
		// whatever we sent and could not attribute must not stay queued on the ACS: prove none is left, else say so
		if uncleaned == nil {
			uncleaned = c.removeOwnTask(ctx, d.DeviceID, taskSetValues, "", since)
		}
		out.Detail = "restore not confirmed"
		if uncleaned != nil {
			out.Detail = "restore not confirmed and a queued ssid task may remain on the ACS"
			return out, errors.Join(ErrBenchRestore, ErrBenchUncleaned)
		}
		return out, ErrBenchRestore
	}
	_ = os.Remove(restoreFile)
	switch {
	case out.Applied && out.Verified:
		out.Detail = "ssid changed, read back, and the original restored and read back"
	case out.Applied:
		out.Detail = "ssid acknowledged but not read back as requested; the original restored"
	default:
		out.Detail = "outcome of the change unknown; the original restored and read back"
	}
	return out, nil
}

func (c *Client) postSetSSID(ctx context.Context, deviceID, value string) (status int, taskID string, err error) {
	body, _ := json.Marshal(map[string]any{"name": "setParameterValues", "parameterValues": [][]string{{ssidLeaf, value, "xsd:string"}}})
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

// readSSID asks the CPE for the leaf (a getParameterValues task for ONE fixed leaf) and returns the value the ACS then holds.
func (c *Client) readSSID(ctx context.Context, deviceID string) (string, error) {
	st, taskID, faulted, err := c.postTask(ctx, deviceID, []string{ssidLeaf})
	if err != nil || st != http.StatusOK || faulted {
		if st == http.StatusAccepted && taskID != "" {
			_ = c.deleteTask(ctx, taskID) // our read, queued because the CPE did not answer
		}
		return "", fmt.Errorf("%w", ErrBenchSSIDRead)
	}
	q, _ := json.Marshal(map[string]string{"_id": deviceID})
	u := *c.base
	u.Path = strings.TrimRight(u.Path, "/") + "/devices"
	u.RawQuery = url.Values{"query": {string(q)}, "projection": {ssidLeaf}}.Encode()
	body, st, err := c.do(ctx, http.MethodGet, u.String(), nil)
	if err != nil || st != http.StatusOK {
		return "", ErrBenchSSIDRead
	}
	var docs []map[string]any
	if json.Unmarshal(body, &docs) != nil || len(docs) != 1 {
		return "", ErrBenchSSIDRead
	}
	var cur any = docs[0]
	for _, k := range strings.Split(ssidLeaf, ".") {
		m, ok := cur.(map[string]any)
		if !ok {
			return "", ErrBenchSSIDRead
		}
		cur = m[k]
	}
	leaf, ok := cur.(map[string]any)
	if !ok {
		return "", ErrBenchSSIDRead
	}
	v, ok := leaf["_value"].(string)
	if !ok {
		return "", ErrBenchSSIDRead
	}
	return v, nil
}

func writeFile0600(path string, data []byte) error {
	tmp, err := os.CreateTemp(filepath.Dir(path), ".bench-restore-*")
	if err != nil {
		return err
	}
	defer os.Remove(tmp.Name())
	if err := tmp.Chmod(0o600); err != nil {
		tmp.Close()
		return err
	}
	if _, err := tmp.Write(data); err != nil {
		tmp.Close()
		return err
	}
	if err := tmp.Sync(); err != nil {
		tmp.Close()
		return err
	}
	if err := tmp.Close(); err != nil {
		return err
	}
	return os.Rename(tmp.Name(), path)
}
