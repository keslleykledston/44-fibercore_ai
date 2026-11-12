package gateway

import (
	"bytes"
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"net/http"
	"strings"
	"time"
)

// Client side of ADR-0045 (OLT credentials sealed to this Edge). Three routes, all authenticated like every Edge route:
//
//	POST /v1/edge/seal-key                       {public_key}
//	GET  /v1/edge/secret-deliveries/next         200 {delivery} | 204
//	POST /v1/edge/secret-deliveries/{id}/result  {lease_token, outcome, code}
//
// These calls keep their OWN wait window for a 429 (secretUntil): a Cloud that asks this slow, optional channel to wait never holds back the delivery of snapshots. They
// also respect the existing one: while the intake budget wait (`until`) is open, SecretsWaitUntil says so and the caller does not call at all. The ingestion header
// X-Edge-Backoff is NOT sent here: it opts the request in to the per-agent intake budget, and this channel is not ingestion.

// ErrSecretsThrottled is a 429 from the secrets routes (the wait is recorded in SecretsWaitUntil). Never a failure of the delivery.
var ErrSecretsThrottled = errors.New("secret deliveries: the Cloud asked this Edge to wait")

// ErrStaleLease is a 409 on a result: the lease_token is not the current attempt's. Nothing changed in the Cloud; the caller asks for the next delivery again.
var ErrStaleLease = errors.New("secret delivery result: stale lease")

// SecretDelivery is the `next` answer. Nothing in it is trusted before the signature is verified (package oltsecrets).
type SecretDelivery struct {
	ID         string          `json:"id"`
	LeaseToken string          `json:"lease_token"`
	OLTName    string          `json:"olt_name"`
	Kind       string          `json:"kind"`
	KeyID      string          `json:"key_id"`
	ExpiresAt  json.RawMessage `json:"expires_at"` // unix seconds (number) or an RFC 3339 string: ADR-0045 does not fix the JSON form
	Sealed     string          `json:"sealed"`
	Signature  string          `json:"signature"`
	// Optional identity the Cloud may echo; when present it must match this Edge (ADR-0045 AAD). Never required.
	TenantID string `json:"tenant_id,omitempty"`
	EdgeID   string `json:"edge_id,omitempty"`
	AAD      string `json:"aad,omitempty"`
}

// SecretsWaitUntil is the later of the intake-budget wait and the secrets wait (zero or past: a call may go out now).
func (c *Client) SecretsWaitUntil() time.Time {
	c.mu.Lock()
	defer c.mu.Unlock()
	if c.secretUntil.After(c.until) {
		return c.secretUntil
	}
	return c.until
}

func (c *Client) secretThrottle(h string) {
	d := minThrottle
	if n, ok := atoiPositive(h); ok {
		d = time.Duration(n) * time.Second
	}
	if d < minThrottle {
		d = minThrottle
	}
	if d > maxThrottle {
		d = maxThrottle
	}
	c.mu.Lock()
	c.secretUntil = time.Now().Add(d)
	c.mu.Unlock()
}

func atoiPositive(h string) (int, bool) {
	h = strings.TrimSpace(h)
	if h == "" || len(h) > 9 {
		return 0, false
	}
	n := 0
	for _, r := range h {
		if r < '0' || r > '9' {
			return 0, false
		}
		n = n*10 + int(r-'0')
	}
	return n, n > 0
}

// bearer returns the access token, logging in when there is none.
func (c *Client) bearer(ctx context.Context) (string, error) {
	c.mu.Lock()
	tok := c.token
	c.mu.Unlock()
	if tok != "" {
		return tok, nil
	}
	if err := c.login(ctx); err != nil {
		return "", err
	}
	c.mu.Lock()
	defer c.mu.Unlock()
	return c.token, nil
}

// secretsDo performs one request of the secrets routes with a single relogin on 401. It returns the status code and the body (at most maxBody bytes).
func (c *Client) secretsDo(ctx context.Context, method, path string, payload []byte, maxBody int64) (int, []byte, error) {
	for attempt := 0; attempt < 2; attempt++ {
		tok, err := c.bearer(ctx)
		if err != nil {
			return 0, nil, err
		}
		var body io.Reader
		if payload != nil {
			body = bytes.NewReader(payload)
		}
		req, err := http.NewRequestWithContext(ctx, method, c.base+path, body)
		if err != nil {
			return 0, nil, err
		}
		if payload != nil {
			req.Header.Set("Content-Type", "application/json")
		}
		req.Header.Set("Authorization", "Bearer "+tok)
		resp, err := c.http.Do(req)
		if err != nil {
			return 0, nil, err
		}
		b, rerr := io.ReadAll(io.LimitReader(resp.Body, maxBody+1))
		resp.Body.Close()
		if rerr != nil {
			return 0, nil, rerr
		}
		if int64(len(b)) > maxBody {
			return resp.StatusCode, nil, errors.New("secret deliveries: answer too large")
		}
		if resp.StatusCode == http.StatusUnauthorized && attempt == 0 {
			c.mu.Lock()
			c.token = ""
			c.mu.Unlock()
			continue
		}
		if resp.StatusCode == http.StatusTooManyRequests {
			c.secretThrottle(resp.Header.Get("Retry-After"))
			return resp.StatusCode, nil, ErrSecretsThrottled
		}
		return resp.StatusCode, b, nil
	}
	return 0, nil, errors.New("secret deliveries: auth retry exhausted")
}

// PublishSealKey sends the public key of this Edge (base64url, no padding). Idempotent in the Cloud (a new value makes it pending again). Delivered = 2xx; a 5xx or a
// network error is Retry; a 429 is Throttled; any other 4xx is Rejected (for example the feature is off for this provider).
func (c *Client) PublishSealKey(ctx context.Context, publicKey string) (Outcome, int, error) {
	b, _ := json.Marshal(map[string]string{"public_key": publicKey})
	code, _, err := c.secretsDo(ctx, http.MethodPost, "/v1/edge/seal-key", b, 1<<16)
	return classify(code, err)
}

func classify(code int, err error) (Outcome, int, error) {
	switch {
	case errors.Is(err, ErrSecretsThrottled):
		return Throttled, code, err
	case err != nil:
		return Retry, code, err
	case code >= 200 && code < 300:
		return Delivered, code, nil
	case code == http.StatusRequestTimeout || code == http.StatusUnauthorized || code >= 500:
		return Retry, code, fmt.Errorf("status %d", code)
	default:
		return Rejected, code, fmt.Errorf("rejected: status %d", code)
	}
}

// NextSecretDelivery asks for the delivery to apply. (nil, nil) = nothing to do (204). A 429 is ErrSecretsThrottled; a 5xx or network error is a plain error (the
// caller waits for the next cycle and counts nothing against any delivery).
func (c *Client) NextSecretDelivery(ctx context.Context) (*SecretDelivery, error) {
	code, b, err := c.secretsDo(ctx, http.MethodGet, "/v1/edge/secret-deliveries/next", nil, 16<<10)
	if err != nil {
		return nil, err
	}
	switch code {
	case http.StatusNoContent:
		return nil, nil
	case http.StatusOK:
		var d SecretDelivery
		if json.Unmarshal(b, &d) != nil || d.ID == "" {
			return nil, errors.New("secret deliveries: malformed answer") // never the decoder's text or the body
		}
		return &d, nil
	default:
		return nil, fmt.Errorf("secret deliveries next: status %d", code)
	}
}

// SecretDeliveryResult reports the outcome of ONE attempt (identified by its lease_token). `code` is empty for "applied". A 409 is ErrStaleLease.
func (c *Client) SecretDeliveryResult(ctx context.Context, id, leaseToken, outcome, code string) (Outcome, int, error) {
	if !jobIDRe.MatchString(id) {
		return Rejected, 0, errors.New("secret delivery result: bad delivery id")
	}
	m := map[string]string{"lease_token": leaseToken, "outcome": outcome}
	if code != "" {
		m["code"] = code
	}
	b, _ := json.Marshal(m)
	st, _, err := c.secretsDo(ctx, http.MethodPost, "/v1/edge/secret-deliveries/"+id+"/result", b, 1<<16)
	if err == nil && st == http.StatusConflict {
		return Rejected, st, ErrStaleLease
	}
	return classify(st, err)
}
