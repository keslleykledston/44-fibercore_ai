package collector

import (
	"context"
	"encoding/json"
	"fmt"
	"os"
	"path/filepath"
	"sort"
	"strings"
	"time"

	"github.com/keslleykledston/44-fibercore_ai/agents/edge/internal/olt"
	"github.com/keslleykledston/44-fibercore_ai/agents/edge/internal/oltquery"
)

// Capture is the SUPERVISED capture of queries that are not validated yet (ADR-0032 item 3): each listed query runs once, in the CLI session the collection
// already holds (no login of its own), after the collection and the on-demand queries, and its RAW output is written to a file that never leaves this host.
// Nothing here is sent to the Cloud. The file is for the person who writes the sanitised fixture and the parser; the Edge deletes it by itself after 24 h.
type Capture struct {
	Dir   string // captures/ next to the Edge queue: 0700, files 0600
	Items []CaptureItem
	Store *oltquery.Store
	// Run executes one catalog query on the open session, unparsed (olt.HuaweiR015.RunQueryInConfig on a driver that enables exactly the listed IDs).
	Run   func(ctx context.Context, s olt.Session, queryID string, p olt.Params) (olt.QueryResult, error)
	Lease LeaseChecker
	Now   func() time.Time
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

func (it CaptureItem) key() string {
	return fmt.Sprintf("%s|%d|%d|%d", it.QueryID, it.Params.Slot, it.Params.Port, it.Params.ONT)
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

func (c *Capture) loadDone() map[string]bool {
	done := map[string]bool{}
	b, err := os.ReadFile(filepath.Join(c.Dir, captureDoneFile))
	if err == nil {
		var keys []string
		if json.Unmarshal(b, &keys) == nil {
			for _, k := range keys {
				done[k] = true
			}
		}
	}
	return done
}

func (c *Capture) saveDone(done map[string]bool) error {
	keys := make([]string, 0, len(done))
	for k := range done {
		keys = append(keys, k)
	}
	sort.Strings(keys)
	b, _ := json.Marshal(keys)
	tmp := filepath.Join(c.Dir, ".tmp-done")
	if err := os.WriteFile(tmp, b, 0o600); err != nil {
		return err
	}
	return os.Rename(tmp, filepath.Join(c.Dir, captureDoneFile))
}

func categoryOf(err error) string {
	if err == nil {
		return "ok"
	}
	return failureReason(err)
}

// Do runs the pending captures of this OLT. It returns how many reached the device. The first anomaly (device refusal, pagination, timeout, no lease, no
// room) ends the batch: the rest waits for another window. A capture that was attempted is marked done BEFORE its output is written, so a crash never repeats it.
func (c *Capture) Do(ctx context.Context, src OLTSource, raw olt.Session, cloudID, session string) (ran int) {
	if c == nil || c.Store == nil || c.Run == nil || c.Lease == nil || cloudID == "" || len(c.Items) == 0 {
		return 0
	}
	files, size, err := c.sweep()
	if err != nil {
		return 0
	}
	done := c.loadDone()
	var pending []CaptureItem
	for _, it := range c.Items {
		if !done[it.key()] {
			pending = append(pending, it)
		}
	}
	if len(pending) == 0 {
		return 0
	}
	sess := olt.NewBudget(olt.ReadOnlySession{Inner: raw, Allowed: src.Driver.Allowed}, queryCommandsEach*oltquery.CapturesPerSession, queryMaxBytes)
	for _, it := range pending {
		if files >= captureMaxFiles || size >= captureMaxBytes {
			return ran // too much raw output on disk: the person has to collect and delete it first
		}
		if !windowLeft(ctx) {
			return ran
		}
		epoch, ok := c.Lease.Epoch(cloudID)
		if !ok {
			return ran
		}
		leaseLeft, err := c.Lease.Grant(cloudID, epoch)
		if err != nil || leaseLeft < minQueryWindow {
			return ran
		}
		leaseEnd := time.Now().Add(leaseLeft)
		if err := c.Store.ReserveCapture(cloudID, session); err != nil { // on disk before anything is sent
			return ran
		}
		done[it.key()] = true // attempted = done: never repeated, even if the output below fails
		if err := c.saveDone(done); err != nil {
			return ran
		}
		ran++
		runCtx, stop := context.WithDeadline(ctx, leaseEnd)
		started := time.Now()
		res, err := c.Run(runCtx, sess, it.QueryID, it.Params)
		stop()
		took := time.Since(started)
		if err != nil {
			if c.OnCapture != nil {
				c.OnCapture(it.QueryID, 0, took, categoryOf(err))
			}
			return ran
		}
		name := fmt.Sprintf("%s-%s", c.now().UTC().Format("20060102T150405Z"), strings.ReplaceAll(it.QueryID, ".", "_"))
		if res.Truncated {
			name += ".trunc"
		}
		tmp := filepath.Join(c.Dir, ".tmp-"+name)
		if err := os.WriteFile(tmp, []byte(res.Output), 0o600); err != nil || os.Rename(tmp, filepath.Join(c.Dir, name+".txt")) != nil {
			_ = os.Remove(tmp)
			if c.OnCapture != nil {
				c.OnCapture(it.QueryID, 0, took, "persist_error")
			}
			return ran
		}
		files++
		size += int64(len(res.Output))
		if c.OnCapture != nil {
			c.OnCapture(it.QueryID, len(res.Output), took, map[bool]string{true: "truncated", false: "ok"}[res.Truncated])
		}
	}
	return ran
}
