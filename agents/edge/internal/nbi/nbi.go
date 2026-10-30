// Package nbi is a READ-ONLY GenieACS NBI client: the type exposes no write method and the HTTP
// verb is hard-coded to GET. Tasks/provisions/presets/files endpoints are unreachable by design.
package nbi

import (
	"context"
	"encoding/json"
	"fmt"
	"io"
	"net/http"
	"net/url"
	"regexp"
	"strings"
	"sync"
)

const maxBody = 16 << 20 // 16 MiB

type Client struct {
	refreshMu sync.Mutex // serialises RefreshParams: pre-flight check, POSTs and cleanup of one call never interleave with another call's
	base      *url.URL
	http      *http.Client
	authUser  string
	authPass  string
}

func New(base string, hc *http.Client, basicAuth string) (*Client, error) {
	u, err := url.Parse(base)
	if err != nil {
		return nil, err
	}
	c := &Client{base: u, http: hc}
	if basicAuth != "" {
		user, pass, ok := strings.Cut(basicAuth, ":")
		if !ok {
			return nil, fmt.Errorf("nbi credentials must be user:pass")
		}
		c.authUser, c.authPass = user, pass
	}
	return c, nil
}

type DeviceID struct {
	Manufacturer string `json:"_Manufacturer"`
	OUI          string `json:"_OUI"`
	ProductClass string `json:"_ProductClass"`
	SerialNumber string `json:"_SerialNumber"`
}

type Device struct {
	ID         string   `json:"_id"`
	LastInform string   `json:"_lastInform"`
	DeviceID   DeviceID `json:"_deviceId"`
	// The firmware the CPE reported at its last bootstrap, from the ACS cache (GET only). TR-098 or TR-181 root, whichever the CPE has.
	IGD  deviceInfoRoot `json:"InternetGatewayDevice"`
	Root deviceInfoRoot `json:"Device"`
}

type deviceInfoRoot struct {
	DeviceInfo struct {
		SoftwareVersion struct {
			Value any `json:"_value"`
		} `json:"SoftwareVersion"`
	} `json:"DeviceInfo"`
}

// Only two shapes of firmware identifier are forwarded (this field is written by the device itself, like its serial and model, and nothing
// else makes it trustworthy): a vendor build token in capitals with letters AND digits ("V5R019C10S350"), or a dotted numeric version
// ("1.2.3", "V2.0.1-b12"). Free text, lower-case words and anything with spaces or punctuation beyond that are dropped, so the field cannot
// carry a password-like string; the registry still matches the exact value, so an odd one only fails to match.
var (
	firmwareToken   = regexp.MustCompile(`^[A-Z][A-Z0-9]{3,31}$`)
	firmwareVersion = regexp.MustCompile(`^[Vv]?[0-9]{1,4}(\.[0-9]{1,4}){1,5}([-_][A-Za-z0-9]{1,12})?$`)
	hasDigit        = regexp.MustCompile(`[0-9]`)
	hasLetter       = regexp.MustCompile(`[A-Z]`)
)

// Firmware is the CPE's SoftwareVersion when it has one of the accepted shapes, else "".
func (d Device) Firmware() string {
	for _, v := range []any{d.IGD.DeviceInfo.SoftwareVersion.Value, d.Root.DeviceInfo.SoftwareVersion.Value} {
		s, ok := v.(string)
		if !ok {
			continue
		}
		s = strings.TrimSpace(s)
		if firmwareVersion.MatchString(s) || (firmwareToken.MatchString(s) && hasDigit.MatchString(s) && hasLetter.MatchString(s)) {
			return s
		}
	}
	return ""
}

// Devices lists devices with a fixed minimal projection (no parameter tree, so no PSK/PPPoE secrets leave the site).
func (c *Client) Devices(ctx context.Context) ([]Device, error) {
	u := *c.base
	u.Path = strings.TrimRight(u.Path, "/") + "/devices"
	q := url.Values{"projection": {"_id,_lastInform,_deviceId,InternetGatewayDevice.DeviceInfo.SoftwareVersion,Device.DeviceInfo.SoftwareVersion"}}
	u.RawQuery = q.Encode()
	req, err := http.NewRequestWithContext(ctx, http.MethodGet, u.String(), nil)
	if err != nil {
		return nil, err
	}
	if c.authUser != "" {
		req.SetBasicAuth(c.authUser, c.authPass)
	}
	resp, err := c.http.Do(req)
	if err != nil {
		return nil, err
	}
	defer resp.Body.Close()
	if resp.StatusCode != http.StatusOK {
		return nil, fmt.Errorf("nbi: unexpected status %d", resp.StatusCode)
	}
	body, err := io.ReadAll(io.LimitReader(resp.Body, maxBody+1))
	if err != nil {
		return nil, err
	}
	if len(body) > maxBody {
		return nil, fmt.Errorf("nbi: response exceeds %d bytes", maxBody)
	}
	var out []Device
	if err := json.Unmarshal(body, &out); err != nil {
		return nil, fmt.Errorf("nbi: invalid json: %w", err)
	}
	return out, nil
}
