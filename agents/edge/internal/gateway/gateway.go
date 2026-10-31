// Package gateway talks to the Cloud API (outbound only). Sprint-1 interim identity is an
// `edge_agent` service-account token bound to this edge; target is mTLS (ADR-0011).
package gateway

import (
	"bytes"
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"net/http"
	"regexp"
	"strings"
	"sync"
	"time"
)

var jobIDRe = regexp.MustCompile(`^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$`)

// Outcome classifies a delivery attempt.
type Outcome int

const (
	Delivered Outcome = iota // 2xx
	Retry                    // network error, 5xx, 408, 429, auth refresh failure
	Rejected                 // other 4xx: the Cloud will never accept this payload
)

type Client struct {
	base     string
	clientID string
	secret   string
	http     *http.Client
	mu       sync.Mutex
	token    string
}

func New(base, clientID, secret string, hc *http.Client) *Client {
	return &Client{base: strings.TrimRight(base, "/"), clientID: clientID, secret: secret, http: hc}
}

func (c *Client) login(ctx context.Context) error {
	body, _ := json.Marshal(map[string]string{"client_id": c.clientID, "client_secret": c.secret})
	req, _ := http.NewRequestWithContext(ctx, http.MethodPost, c.base+"/v1/auth/service-token", bytes.NewReader(body))
	req.Header.Set("Content-Type", "application/json")
	resp, err := c.http.Do(req)
	if err != nil {
		return err
	}
	defer resp.Body.Close()
	if resp.StatusCode != http.StatusOK {
		return fmt.Errorf("login failed: status %d", resp.StatusCode)
	}
	var out struct {
		AccessToken string `json:"access_token"`
	}
	if err := json.NewDecoder(io.LimitReader(resp.Body, 1<<16)).Decode(&out); err != nil || out.AccessToken == "" {
		return errors.New("login: bad response")
	}
	c.mu.Lock()
	c.token = out.AccessToken
	c.mu.Unlock()
	return nil
}

func (c *Client) post(ctx context.Context, path string, payload []byte) (Outcome, int, error) {
	reauthed := false
	for attempt := 0; attempt < 3; attempt++ {
		c.mu.Lock()
		tok := c.token
		c.mu.Unlock()
		if tok == "" { // login does not consume a send attempt
			if err := c.login(ctx); err != nil {
				return Retry, 0, err
			}
			c.mu.Lock()
			tok = c.token
			c.mu.Unlock()
		}
		req, _ := http.NewRequestWithContext(ctx, http.MethodPost, c.base+path, bytes.NewReader(payload))
		req.Header.Set("Content-Type", "application/json")
		req.Header.Set("Authorization", "Bearer "+tok)
		resp, err := c.http.Do(req)
		if err != nil {
			return Retry, 0, err
		}
		io.Copy(io.Discard, io.LimitReader(resp.Body, 1<<20))
		resp.Body.Close()
		switch {
		case resp.StatusCode >= 200 && resp.StatusCode < 300:
			return Delivered, resp.StatusCode, nil
		case resp.StatusCode == http.StatusUnauthorized && !reauthed:
			reauthed = true
			c.mu.Lock()
			c.token = ""
			c.mu.Unlock()
			continue // token expired: log in again once
		case resp.StatusCode == http.StatusUnauthorized, resp.StatusCode == http.StatusRequestTimeout,
			resp.StatusCode == http.StatusTooManyRequests, resp.StatusCode >= 500:
			return Retry, resp.StatusCode, fmt.Errorf("status %d", resp.StatusCode)
		default:
			return Rejected, resp.StatusCode, fmt.Errorf("rejected: status %d", resp.StatusCode)
		}
	}
	return Retry, 0, errors.New("auth retry exhausted")
}

type Heartbeat struct {
	EdgeID   string `json:"edge_id"`
	TenantID string `json:"tenant_id"`
	Version  string `json:"version"`
	SentAt   string `json:"sent_at"`
}

func (c *Client) Heartbeat(ctx context.Context, edgeID, tenantID, version string) (Outcome, error) {
	b, _ := json.Marshal(Heartbeat{edgeID, tenantID, version, time.Now().UTC().Format(time.RFC3339)})
	o, _, err := c.post(ctx, "/v1/edge/heartbeat", b)
	return o, err
}

// Deliver sends a queued payload to the endpoint mapped from its kind.
func (c *Client) Deliver(ctx context.Context, kind string, payload []byte) (Outcome, error) {
	if kind == "job_result" { // durable job outcome: {"job_id":..., "state":..., "detail":..., "postcheck_ok":...}
		var m map[string]any
		if err := json.Unmarshal(payload, &m); err != nil {
			return Rejected, err
		}
		id, _ := m["job_id"].(string)
		if !jobIDRe.MatchString(id) {
			return Rejected, fmt.Errorf("job_result without valid job_id")
		}
		delete(m, "job_id")
		b, _ := json.Marshal(m)
		o, _, err := c.post(ctx, "/v1/edge/jobs/"+id+"/result", b)
		return o, err
	}
	path, ok := map[string]string{"olt_snapshot": "/v1/edge/olt-snapshots", "cpe_snapshot": "/v1/edge/cpe-snapshots", "cpe_state": "/v1/edge/cpe-state", "speed_health": "/v1/edge/speed-health"}[kind]
	if !ok {
		return Rejected, fmt.Errorf("unknown kind %q", kind)
	}
	o, _, err := c.post(ctx, path, payload)
	return o, err
}

// LeaseHeader carries the Cloud's signed bench lease (ADR-0030) on every poll answer, with or without a job.
const LeaseHeader = "X-Bench-Lease"

// OLTLeaseHeader carries the Cloud's signed ownership lease of the OLTs (ADR-0029), on every poll answer too.
const OLTLeaseHeader = "X-OLT-Lease"

// Leases are the raw lease headers of one poll answer (empty = the Cloud sent none).
type Leases struct{ Bench, OLT string }

// NextJob polls for one approved job. Returns a nil body when none is available. The second value is the raw bench lease header
// (empty when the Cloud sent none); the caller verifies it, nothing is trusted here.
func (c *Client) NextJob(ctx context.Context) ([]byte, Leases, error) {
	for attempt := 0; attempt < 2; attempt++ {
		c.mu.Lock()
		tok := c.token
		c.mu.Unlock()
		if tok == "" {
			if err := c.login(ctx); err != nil {
				return nil, Leases{}, err
			}
			c.mu.Lock()
			tok = c.token
			c.mu.Unlock()
		}
		req, _ := http.NewRequestWithContext(ctx, http.MethodGet, c.base+"/v1/edge/jobs/next", nil)
		req.Header.Set("Authorization", "Bearer "+tok)
		resp, err := c.http.Do(req)
		if err != nil {
			return nil, Leases{}, err
		}
		body, _ := io.ReadAll(io.LimitReader(resp.Body, 1<<16))
		resp.Body.Close()
		lease := Leases{Bench: resp.Header.Get(LeaseHeader), OLT: resp.Header.Get(OLTLeaseHeader)}
		if len(lease.Bench) > 1<<15 {
			lease.Bench = "!oversize" // never parses: the caller withdraws the lease
		}
		if len(lease.OLT) > 1<<15 {
			lease.OLT = "!oversize"
		}
		switch resp.StatusCode {
		case http.StatusOK:
			return body, lease, nil
		case http.StatusNoContent:
			return nil, lease, nil
		case http.StatusUnauthorized:
			c.mu.Lock()
			c.token = ""
			c.mu.Unlock()
		default:
			return nil, Leases{}, fmt.Errorf("next job: status %d", resp.StatusCode)
		}
	}
	return nil, Leases{}, errors.New("next job: auth retry exhausted")
}
