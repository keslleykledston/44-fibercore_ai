// Package collector turns read-only observations into Cloud snapshot payloads.
package collector

import (
	"context"
	"encoding/json"
	"regexp"
	"strings"
	"time"

	"github.com/keslleykledston/44-fibercore_ai/agents/edge/internal/nbi"
)

// Item is a ready-to-queue payload.
type Item struct {
	Kind    string
	Key     string // logical stream; a newer complete round of the same Key supersedes older queued items
	Payload []byte
	// Gauge marks an item that is the CURRENT value of something (the ACS status): once it is persisted it supersedes the older queued items of its Key even when the round that made it was
	// incomplete. Without it a long ACS outage would queue one failure report per round and replay stale ones, in order, when the Cloud came back.
	Gauge bool
}

// Collector gathers one read-only observation round. Implementations MUST NOT write to devices.
type Collector interface {
	Name() string
	Collect(ctx context.Context) ([]Item, error)
}

type DeviceLister interface {
	Devices(ctx context.Context) ([]nbi.Device, error)
}

// ParamReader reads the validated CPE state the ACS already has cached (GET only; see nbi.CachedParams). Optional: without it only inventory is sent.
type ParamReader interface {
	CachedParams(ctx context.Context, ids []string) ([]nbi.DeviceParams, error)
}

type GenieACS struct {
	// Params, when set, adds a cpe_state item per round for the devices that were kept in the inventory snapshot.
	Params ParamReader

	// OnSkip, when set, receives how many devices were left out and why ("no_serial", "placeholder_identity"); nothing identifying.
	OnSkip func(reason string, n int)

	// ACSID (ADR-0046 D2) is `nbi_cloud_id`: the id of THIS Edge's ACS in the Cloud registry. When set, every round also queues ONE `acs_status` item (did the NBI answer, how many devices,
	// a closed error code). It rides on the read the round already makes: nothing extra is asked of the ACS. Empty = the Cloud is not told (an Edge with an old config is unchanged).
	ACSID string

	EdgeID      string
	ConnectorID string
	Client      DeviceLister
	Now         func() time.Time
}

// ACSKind is the registry kind this collector speaks (the Cloud checks it against the registered kind).
const ACSKind = "genieacs"

type acsStatus struct {
	ACSID       string  `json:"acs_id"`
	Kind        string  `json:"kind"`
	OK          bool    `json:"ok"`
	DeviceCount *int    `json:"device_count"`
	ErrorCode   *string `json:"error_code"`
}

// statusItem is the closed report the Cloud accepts: ok carries the device count and no error code, a failure the reverse. Superseded by the next round of the same ACS.
func (g *GenieACS) statusItem(devices int, errCode string) Item {
	st := acsStatus{ACSID: g.ACSID, Kind: ACSKind, OK: errCode == ""}
	if st.OK {
		st.DeviceCount = &devices
	} else {
		st.ErrorCode = &errCode
	}
	b, _ := json.Marshal(st) // plain types: cannot fail
	return Item{Kind: "acs_status", Key: "acs_status:" + g.ACSID, Payload: b, Gauge: true}
}

func (g *GenieACS) Name() string { return "genieacs" }

type cpeBinding struct {
	Protocol    string `json:"protocol"`
	ExternalID  string `json:"external_id"`
	ConnectorID string `json:"connector_id"`
}
type cpeIn struct {
	CanonicalSerial string `json:"canonical_serial"`
	Vendor          string `json:"vendor,omitempty"`
	Model           string `json:"model,omitempty"`
	Firmware        string `json:"firmware,omitempty"`
	// LastInformAt is the ACS's own `_lastInform` for this device (R-D004), distinct from the collection time. Omitted when the ACS
	// gave none, when it does not parse, or when it lies in the future: the cloud then knows nothing about the last Inform.
	LastInformAt string     `json:"last_inform_at,omitempty"`
	Binding      cpeBinding `json:"binding"`
}
type cpeStateIn struct {
	Binding cpeBinding   `json:"binding"`
	Metrics []nbi.Metric `json:"metrics"`
}
type cpeStateSnapshot struct {
	EdgeID     string       `json:"edge_id"`
	ObservedAt string       `json:"observed_at"`
	States     []cpeStateIn `json:"states"`
}
type cpeSnapshot struct {
	EdgeID     string  `json:"edge_id"`
	ObservedAt string  `json:"observed_at"`
	CPEs       []cpeIn `json:"cpes"`
}

const maxPerSnapshot = 5000 // keep in sync with the Cloud limit
// stateReadBatch is how many devices one cache read covers (the NBI client's own per-request size): a failed read costs only its own devices,
// never the rest of the round, and never trips the client's ceiling per call.
const stateReadBatch = 25
const maxStatesPerItem = 200     // Cloud accepts 500 per call; smaller items keep one bad batch from costing many CPEs
const maxStateSkew = time.Minute // a timestamp further ahead than this (the Cloud allows 5 min) is dropped here so one clock cannot poison a batch

// placeholderID is the identity GenieACS/CPEs use BEFORE a device is really known (observed on the real server: Huawei ONTs informing
// as DISCOVERYSERVICE with a fresh random serial each time). It is not an inventory identity: ingesting it would create a new fake CPE
// per Inform. Counts of what was dropped are reported through OnSkip, never the identifiers.
const placeholderID = "DISCOVERYSERVICE"

// A serial is a CLAIM made by the device itself (CWMP is reachable by anyone who finds the port). Only a plain identifier is accepted; the
// rest (control characters, huge strings, markup) is dropped and counted.
var serialRe = regexp.MustCompile(`^[A-Z0-9][A-Z0-9._-]{3,63}$`)

// canonicalSerial is the ONE form the Cloud stores (trimmed, upper case); grouping and validation use it so case/space variants of a
// serial collapse into the same claim instead of looking like two devices.
func canonicalSerial(s string) string { return strings.ToUpper(strings.TrimSpace(s)) }

// lastInform normalises the ACS `_lastInform` to RFC 3339 UTC. Anything that does not parse, or that is in the future, becomes "" (omitted).
func lastInform(raw string, now time.Time) string {
	raw = strings.TrimSpace(raw)
	if raw == "" {
		return ""
	}
	t, err := time.Parse(time.RFC3339Nano, raw)
	if err != nil || t.After(now.Add(5*time.Minute)) {
		return ""
	}
	return t.UTC().Format(time.RFC3339)
}

func isPlaceholder(d nbi.Device) bool {
	return d.DeviceID.OUI == placeholderID || d.DeviceID.Manufacturer == placeholderID || d.DeviceID.ProductClass == placeholderID
}

func (g *GenieACS) Collect(ctx context.Context) ([]Item, error) {
	devs, err := g.Client.Devices(ctx)
	if err != nil {
		if g.ACSID != "" && ctx.Err() == nil { // the failure is itself the news; a shutdown (cancelled context) is not an ACS failure
			return []Item{g.statusItem(0, nbi.ErrorCode(err))}, err
		}
		return nil, err
	}
	now := g.Now
	if now == nil {
		now = time.Now
	}
	observed := now().UTC().Format(time.RFC3339)
	var items []Item
	var batch []cpeIn
	flush := func() error {
		if len(batch) == 0 {
			return nil
		}
		b, err := json.Marshal(cpeSnapshot{EdgeID: g.EdgeID, ObservedAt: observed, CPEs: batch})
		if err != nil {
			return err
		}
		items = append(items, Item{Kind: "cpe_snapshot", Key: "cpe:" + g.ConnectorID, Payload: b})
		batch = nil
		return nil
	}
	skipped := map[string]int{}
	defer func() {
		if g.OnSkip != nil {
			for _, r := range []string{"no_serial", "invalid_serial", "placeholder_identity", "conflicting_serial", "state_read_failed", "state_future_timestamp"} {
				if skipped[r] > 0 {
					g.OnSkip(r, skipped[r])
				}
			}
		}
	}()
	// Two DIFFERENT devices claiming the same serial cannot both be true and nothing here can tell which one is: drop every claim.
	claims := map[string]map[string]bool{}
	for _, d := range devs {
		if !isPlaceholder(d) && d.ID != "" {
			k := canonicalSerial(d.DeviceID.SerialNumber)
			if claims[k] == nil {
				claims[k] = map[string]bool{}
			}
			claims[k][d.ID] = true
		}
	}
	var kept []nbi.Device // the devices that made it into the inventory snapshot: only these may carry state
	for _, d := range devs {
		if isPlaceholder(d) {
			skipped["placeholder_identity"]++
			continue
		}
		serial := canonicalSerial(d.DeviceID.SerialNumber)
		if serial == "" || d.ID == "" {
			skipped["no_serial"]++
			continue // cannot be keyed canonically; skip rather than invent identity
		}
		if !serialRe.MatchString(serial) {
			skipped["invalid_serial"]++
			continue
		}
		if len(claims[serial]) > 1 {
			skipped["conflicting_serial"]++
			continue
		}
		batch = append(batch, cpeIn{
			CanonicalSerial: serial, Vendor: d.DeviceID.Manufacturer, Model: d.DeviceID.ProductClass, Firmware: d.Firmware(),
			LastInformAt: lastInform(d.LastInform, now()),
			Binding:      cpeBinding{Protocol: "tr069", ExternalID: d.ID, ConnectorID: g.ConnectorID},
		})
		kept = append(kept, d)
		if len(batch) == maxPerSnapshot {
			if err := flush(); err != nil {
				return nil, err
			}
		}
	}
	if err := flush(); err != nil {
		return nil, err
	}
	if g.ACSID != "" {
		items = append(items, g.statusItem(len(devs), ""))
	}
	// State goes AFTER the inventory items of the same round (the Cloud resolves the CPE through the binding the snapshot just created).
	// Failing to read it never costs the inventory.
	if g.Params != nil && len(kept) > 0 {
		items = append(items, g.stateItems(ctx, kept, observed, now(), skipped)...)
	}
	return items, nil
}

func (g *GenieACS) stateItems(ctx context.Context, kept []nbi.Device, observed string, now time.Time, skipped map[string]int) []Item {
	known := map[string]bool{}
	var res []nbi.DeviceParams
	for i := 0; i < len(kept); i += stateReadBatch {
		end := min(i+stateReadBatch, len(kept))
		ids := make([]string, 0, end-i)
		for _, d := range kept[i:end] {
			ids = append(ids, d.ID)
			known[d.ID] = true
		}
		r, err := g.Params.CachedParams(ctx, ids)
		if err != nil {
			skipped["state_read_failed"]++ // counted per failed read; what the other reads returned is kept, and the Cloud keeps the older state
			if ctx.Err() != nil {
				break
			}
			continue
		}
		res = append(res, r...)
	}
	var items []Item
	var batch []cpeStateIn
	flush := func() {
		if len(batch) == 0 {
			return
		}
		if b, err := json.Marshal(cpeStateSnapshot{EdgeID: g.EdgeID, ObservedAt: observed, States: batch}); err != nil {
			skipped["state_read_failed"]++ // cannot happen with these plain types; if it ever does it is counted, not silent
		} else {
			items = append(items, Item{Kind: "cpe_state", Key: "cpe_state:" + g.ConnectorID, Payload: b})
		}
		batch = nil
	}
	for _, r := range res {
		if !known[r.ID] { // only what was asked for, and only devices that are in this round's inventory
			continue
		}
		var ms []nbi.Metric
		for _, m := range r.Metrics {
			if t, err := time.Parse(time.RFC3339, m.CapturedAt); err != nil || t.After(now.Add(maxStateSkew)) {
				skipped["state_future_timestamp"]++
				continue
			}
			ms = append(ms, m)
		}
		if len(ms) == 0 {
			continue
		}
		batch = append(batch, cpeStateIn{Binding: cpeBinding{Protocol: "tr069", ExternalID: r.ID, ConnectorID: g.ConnectorID}, Metrics: ms})
		if len(batch) == maxStatesPerItem {
			flush()
		}
	}
	flush()
	return items
}
