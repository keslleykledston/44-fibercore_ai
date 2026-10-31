package collector

import (
	"context"
	"encoding/json"
	"fmt"
	"os"
	"path/filepath"
	"sort"
	"strings"
	"sync"
	"time"

	"github.com/keslleykledston/44-fibercore_ai/agents/edge/internal/olt"
	"github.com/keslleykledston/44-fibercore_ai/agents/edge/internal/oltquery"
)

// Capture is the SUPERVISED capture of queries that are not validated yet (ADR-0032 item 3): each listed query runs once, in the CLI session the collection
// already holds (no login of its own), after the collection and the on-demand queries, and its RAW output is written to a file that never leaves this host.
// Nothing here is sent to the Cloud. The file is for the person who writes the sanitised fixture and the parser; the Edge deletes it by itself after 24 h.
type Capture struct {
	Dir   string                   // captures/ next to the Edge queue: 0700, files 0600
	Items map[string][]CaptureItem // by the OLT's cloud id
	Store *oltquery.Store
	// Run executes one catalog query on the open session, unparsed (olt.HuaweiR015.RunQueryInConfig on a driver that enables exactly the listed IDs).
	Run   func(ctx context.Context, s olt.Session, queryID string, p olt.Params) (olt.QueryResult, error)
	Lease LeaseChecker
	Now   func() time.Time
	mu    sync.Mutex // one capture writes at a time: capacity check, name choice and rename are one step
	// OnCapture is told how each capture ended: id, bytes, duration and a CATEGORY (never the content). The Edge log shows only this.
	OnCapture func(queryID string, bytes int, took time.Duration, outcome string)
}

// CaptureItem names one query and its parameters (a PON or ONU scope can only be the bench's; the configuration enforces it).
type CaptureItem struct {
	QueryID string
	Params  olt.Params
}

const (
	captureMaxFiles = 10
	captureMaxBytes = 20 << 20
	captureKeep     = 24 * time.Hour
	captureDoneFile = "done.json"
)

func (c *Capture) now() time.Time {
	if c.Now != nil {
		return c.Now()
	}
	return time.Now()
}

func (it CaptureItem) key(cloudID string) string {
	return fmt.Sprintf("%s|%s|%d|%d|%d", cloudID, it.QueryID, it.Params.Slot, it.Params.Port, it.Params.ONT)
}

// fileBase names the output so two OLTs, or two scopes of one query, never share a file.
func (it CaptureItem) fileBase(cloudID string, at time.Time) string {
	id := cloudID
	if len(id) > 8 {
		id = id[:8]
	}
	name := fmt.Sprintf("%s-%s-%s", at.UTC().Format("20060102T150405Z"), id, strings.ReplaceAll(it.QueryID, ".", "_"))
	if it.Params.Slot != 0 || it.Params.Port != 0 || it.Params.ONT != 0 {
		name += fmt.Sprintf("-%d-%d-%d", it.Params.Slot, it.Params.Port, it.Params.ONT)
	}
	return name
}

// sweep removes captures older than 24 h (and leftovers of failed writes) and reports what remains.
func (c *Capture) sweep() (files int, bytes int64, err error) {
	if err := os.MkdirAll(c.Dir, 0o700); err != nil {
		return 0, 0, err
	}
	if err := os.Chmod(c.Dir, 0o700); err != nil {
		return 0, 0, err
	}
	ents, err := os.ReadDir(c.Dir)
	if err != nil {
		return 0, 0, err
	}
	for _, e := range ents {
		if e.IsDir() || e.Name() == captureDoneFile {
			continue
		}
		fi, err := e.Info()
		if err != nil {
			continue
		}
		if c.now().Sub(fi.ModTime()) > captureKeep || strings.HasPrefix(e.Name(), ".tmp-") {
			_ = os.Remove(filepath.Join(c.Dir, e.Name()))
			continue
		}
		files++
		bytes += fi.Size()
	}
	return files, bytes, nil
}

// loadDone reads the one-shot markers. A missing file is a first run; an unreadable or malformed one is NOT: it would make every capture look pending and
// repeat them, so the batch waits until a person looks at it. A marker never expires on its own: a capture runs once per entry; to run it again the person
// deletes captures/done.json (or changes the entry's parameters), which is a deliberate act.
func (c *Capture) loadDone() (map[string]bool, error) {
	done := map[string]bool{}
	b, err := os.ReadFile(filepath.Join(c.Dir, captureDoneFile))
	if os.IsNotExist(err) {
		return done, nil
	}
	if err != nil {
		return nil, err
	}
	var keys []string
	if err := json.Unmarshal(b, &keys); err != nil {
		return nil, err
	}
	for _, k := range keys {
		done[k] = true
	}
	return done, nil
}

// writeSynced writes the file, flushes it to disk and renames it into place (then flushes the directory entry).
func writeSynced(dir, tmp, final string, data []byte) error {
	f, err := os.OpenFile(tmp, os.O_WRONLY|os.O_CREATE|os.O_TRUNC, 0o600)
	if err != nil {
		return err
	}
	if _, err := f.Write(data); err != nil {
		f.Close()
		return err
	}
	if err := f.Sync(); err != nil {
		f.Close()
		return err
	}
	if err := f.Close(); err != nil {
		return err
	}
	if err := os.Rename(tmp, final); err != nil {
		return err
	}
	if d, err := os.Open(dir); err == nil {
		_ = d.Sync()
		d.Close()
	}
	return nil
}

func (c *Capture) saveDone(done map[string]bool) error {
	keys := make([]string, 0, len(done))
	for k := range done {
		keys = append(keys, k)
	}
	sort.Strings(keys)
	b, _ := json.Marshal(keys)
	return writeSynced(c.Dir, filepath.Join(c.Dir, ".tmp-done"), filepath.Join(c.Dir, captureDoneFile), b)
}

func categoryOf(err error) string {
	if err == nil {
		return "ok"
	}
	return failureReason(err)
}

// Do runs the pending captures of this OLT. It returns how many reached the device. The first anomaly (device refusal, pagination, timeout, no lease, no
// room) ends the batch: the rest waits for another window. A capture that was attempted is marked done BEFORE its output is written, so a crash never repeats it.
// Every early stop is reported through OnCapture with a category (never content), so a capture that did not run is distinguishable from one that was not due.
func (c *Capture) Do(ctx context.Context, src OLTSource, raw olt.Session, cloudID, session string) (ran int) {
	if c == nil || c.Store == nil || c.Run == nil || c.Lease == nil || cloudID == "" || len(c.Items[cloudID]) == 0 {
		return 0
	}
	report := func(it CaptureItem, n int, took time.Duration, outcome string) {
		if c.OnCapture != nil {
			c.OnCapture(it.QueryID, n, took, outcome)
		}
	}
	first := c.Items[cloudID][0]
	files, size, err := c.sweep()
	if err != nil {
		report(first, 0, 0, "storage_error")
		return 0
	}
	done, err := c.loadDone()
	if err != nil {
		report(first, 0, 0, "done_unreadable") // fail closed: a damaged marker file must not make every capture look pending
		return 0
	}
	var pending []CaptureItem
	for _, it := range c.Items[cloudID] {
		if !done[it.key(cloudID)] {
			pending = append(pending, it)
		}
	}
	if len(pending) == 0 {
		return 0
	}
	sess := olt.NewBudget(olt.ReadOnlySession{Inner: raw, Allowed: src.Driver.Allowed}, queryCommandsEach*oltquery.CapturesPerSession, queryMaxBytes)
	for _, it := range pending {
		if files >= captureMaxFiles || size >= captureMaxBytes {
			report(it, 0, 0, "captures_dir_full") // too much raw output on disk: the person has to collect and delete it first
			return ran
		}
		if !windowLeft(ctx) {
			report(it, 0, 0, "no_window")
			return ran
		}
		epoch, ok := c.Lease.Epoch(cloudID)
		if !ok {
			report(it, 0, 0, "no_lease")
			return ran
		}
		leaseLeft, err := c.Lease.Grant(cloudID, epoch)
		if err != nil || leaseLeft < minQueryWindow {
			report(it, 0, 0, "no_lease")
			return ran
		}
		leaseEnd := time.Now().Add(leaseLeft)
		if err := c.Store.ReserveCapture(cloudID, session); err != nil { // on disk before anything is sent
			report(it, 0, 0, "budget")
			return ran
		}
		done[it.key(cloudID)] = true // attempted = done: never repeated, even if the output below fails
		if err := c.saveDone(done); err != nil {
			report(it, 0, 0, "persist_error") // the reservation is spent; nothing was sent
			return ran
		}
		ran++
		runCtx, stop := context.WithDeadline(ctx, leaseEnd)
		started := time.Now()
		res, err := c.Run(runCtx, sess, it.QueryID, it.Params)
		stop()
		took := time.Since(started)
		if err != nil {
			report(it, 0, took, categoryOf(err))
			return ran
		}
		n, werr := c.store(it, cloudID, res)
		if werr != nil {
			report(it, 0, took, "persist_error")
			return ran
		}
		files++
		size += int64(n)
		report(it, n, took, map[bool]string{true: "truncated", false: "ok"}[res.Truncated])
	}
	return ran
}

// store writes the raw output under a name that is not taken yet (never overwrites), serialised across OLTs so the capacity check and the write are one step.
func (c *Capture) store(it CaptureItem, cloudID string, res olt.QueryResult) (int, error) {
	c.mu.Lock()
	defer c.mu.Unlock()
	files, _, err := c.sweep() // the size cap is checked before each run; one capture is at most queryMaxBytes, so the directory stays within cap + one capture
	if err != nil {
		return 0, err
	}
	if files >= captureMaxFiles {
		return 0, fmt.Errorf("captures directory full")
	}
	base := it.fileBase(cloudID, c.now())
	if res.Truncated {
		base += ".trunc"
	}
	final := filepath.Join(c.Dir, base+".txt")
	for i := 2; ; i++ {
		if _, err := os.Lstat(final); os.IsNotExist(err) {
			break
		}
		if i > 99 {
			return 0, fmt.Errorf("no free name")
		}
		final = filepath.Join(c.Dir, fmt.Sprintf("%s-%d.txt", base, i))
	}
	tmp := filepath.Join(c.Dir, ".tmp-"+filepath.Base(final))
	if err := writeSynced(c.Dir, tmp, final, []byte(res.Output)); err != nil {
		_ = os.Remove(tmp)
		return 0, err
	}
	return len(res.Output), nil
}
