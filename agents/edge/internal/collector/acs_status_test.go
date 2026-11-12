package collector

import (
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"
	"time"

	"github.com/keslleykledston/44-fibercore_ai/agents/edge/internal/nbi"
)

const acsID = "5f0c1d52-1b5e-4c36-9a3e-0f6a3f0d8c11"

type failingLister struct{ err error }

func (f failingLister) Devices(context.Context) ([]nbi.Device, error) { return nil, f.err }

func statusOf(t *testing.T, items []Item) map[string]any {
	t.Helper()
	var found []map[string]any
	for _, it := range items {
		if it.Kind != "acs_status" {
			continue
		}
		if it.Key != "acs_status:"+acsID {
			t.Fatalf("key=%q", it.Key)
		}
		var m map[string]any
		if err := json.Unmarshal(it.Payload, &m); err != nil {
			t.Fatal(err)
		}
		found = append(found, m)
	}
	if len(found) != 1 {
		t.Fatalf("want exactly one acs_status item, got %d", len(found))
	}
	return found[0]
}

func TestWithoutNBICloudIDNothingIsReportedAndNothingChanges(t *testing.T) {
	g := &GenieACS{EdgeID: "e", ConnectorID: "c", Client: fakeLister{[]nbi.Device{dev(1, "SER00001")}}}
	items, err := g.Collect(context.Background())
	if err != nil || len(items) != 1 || items[0].Kind != "cpe_snapshot" {
		t.Fatalf("items=%v err=%v", items, err)
	}
	items, err = (&GenieACS{EdgeID: "e", ConnectorID: "c", Client: failingLister{errors.New("boom")}}).Collect(context.Background())
	if err == nil || items != nil {
		t.Fatalf("a failure with no nbi_cloud_id keeps the old behaviour (no items, the error): %v %v", items, err)
	}
}

func TestAnOkRoundReportsTheDeviceCountOfWhatTheACSAnsweredIncludingWhatIsLeftOut(t *testing.T) {
	devs := []nbi.Device{dev(1, "SER00001"), dev(2, "SER00002"), dev(3, ""), {ID: "x", DeviceID: nbi.DeviceID{OUI: placeholderID, SerialNumber: "R4ND0M01"}}}
	g := &GenieACS{ACSID: acsID, EdgeID: "e", ConnectorID: "c", Client: fakeLister{devs}}
	items, err := g.Collect(context.Background())
	if err != nil {
		t.Fatal(err)
	}
	st := statusOf(t, items)
	if st["acs_id"] != acsID || st["kind"] != "genieacs" || st["ok"] != true || st["device_count"] != float64(4) {
		t.Fatalf("st=%v", st)
	}
	if v, present := st["error_code"]; !present || v != nil {
		t.Fatalf("an ok report carries an explicit null error_code: %v", st)
	}
	if len(st) != 5 {
		t.Fatalf("closed shape (acs_id, kind, ok, device_count, error_code): %v", st)
	}
	if items[0].Kind != "cpe_snapshot" {
		t.Fatalf("the inventory comes first: %v", items[0].Kind)
	}
}

func TestZeroDevicesIsAnOkReportWithCountZero(t *testing.T) {
	items, err := (&GenieACS{ACSID: acsID, EdgeID: "e", ConnectorID: "c", Client: fakeLister{nil}}).Collect(context.Background())
	if err != nil {
		t.Fatal(err)
	}
	st := statusOf(t, items)
	if st["ok"] != true || st["device_count"] != float64(0) {
		t.Fatalf("st=%v", st)
	}
}

func TestAFailedRoundReportsOnlyAClosedCodeAndStillReturnsTheError(t *testing.T) {
	secretURL := "http://admin:hunter2@10.9.8.7:7557/devices"
	cases := map[string]struct {
		err  error
		code string
	}{
		"status 500":     {&nbi.StatusError{Code: 500}, "unexpected_status"},
		"status 401":     {&nbi.StatusError{Code: 401}, "unauthorized"},
		"status 403":     {fmt.Errorf("wrapped: %w", &nbi.StatusError{Code: 403}), "unauthorized"},
		"too large":      {fmt.Errorf("x: %w", nbi.ErrTooLarge), "too_large"},
		"bad response":   {fmt.Errorf("x: %w: %w", nbi.ErrBadResponse, errors.New("invalid character")), "bad_response"},
		"deadline":       {context.DeadlineExceeded, "timeout"},
		"unreachable":    {fmt.Errorf("Get %q: %w", secretURL, nbi.ErrUnreachable), "unreachable"},
		"something else": {errors.New("totally unexpected " + secretURL), "unknown"},
	}
	for name, c := range cases {
		g := &GenieACS{ACSID: acsID, EdgeID: "e", ConnectorID: "c", Client: failingLister{c.err}}
		items, err := g.Collect(context.Background())
		if err == nil {
			t.Fatalf("%s: the error must still be returned (the round is incomplete)", name)
		}
		st := statusOf(t, items)
		if st["ok"] != false || st["error_code"] != c.code {
			t.Errorf("%s: st=%v", name, st)
		}
		if v, present := st["device_count"]; !present || v != nil {
			t.Errorf("%s: a failed report carries an explicit null device_count: %v", name, st)
		}
		raw := string(items[0].Payload)
		for _, leak := range []string{"hunter2", "10.9.8.7", "admin", "http", "invalid character"} {
			if strings.Contains(raw, leak) {
				t.Errorf("%s: %q leaked into the report: %s", name, leak, raw)
			}
		}
	}
}

func TestANetworkErrorFromTheRealClientIsUnreachableAndATimeoutIsATimeout(t *testing.T) {
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {}))
	url := srv.URL
	srv.Close() // nothing listens any more
	c, _ := nbi.New(url, &http.Client{Timeout: 2 * time.Second}, "")
	_, err := c.Devices(context.Background())
	if got := nbi.ErrorCode(err); got != "unreachable" {
		t.Fatalf("refused connection: %q (%v)", got, err)
	}
	slow := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) { time.Sleep(300 * time.Millisecond) }))
	defer slow.Close()
	c2, _ := nbi.New(slow.URL, &http.Client{Timeout: 50 * time.Millisecond}, "")
	_, err = c2.Devices(context.Background())
	if got := nbi.ErrorCode(err); got != "timeout" {
		t.Fatalf("slow ACS: %q (%v)", got, err)
	}
	denied := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) { w.WriteHeader(401) }))
	defer denied.Close()
	c3, _ := nbi.New(denied.URL, denied.Client(), "u:p")
	_, err = c3.Devices(context.Background())
	if got := nbi.ErrorCode(err); got != "unauthorized" {
		t.Fatalf("401: %q (%v)", got, err)
	}
}

func TestACancelledRoundIsNotAnACSFailure(t *testing.T) {
	ctx, cancel := context.WithCancel(context.Background())
	cancel()
	g := &GenieACS{ACSID: acsID, EdgeID: "e", ConnectorID: "c", Client: failingLister{context.Canceled}}
	items, err := g.Collect(ctx)
	if err == nil || items != nil {
		t.Fatalf("a shutdown is not news about the ACS: %v %v", items, err)
	}
}

func TestEveryErrorCodeTheEdgeCanSendIsInTheCloudsClosedList(t *testing.T) {
	cloud := map[string]bool{"unreachable": true, "timeout": true, "unauthorized": true, "unexpected_status": true, "bad_response": true, "too_large": true, "unknown": true} // app/core/acs.py ACS_ERROR_CODES
	for _, err := range []error{&nbi.StatusError{Code: 500}, &nbi.StatusError{Code: 401}, nbi.ErrTooLarge, nbi.ErrBadResponse, nbi.ErrUnreachable, context.DeadlineExceeded, errors.New("x")} {
		if c := nbi.ErrorCode(err); !cloud[c] {
			t.Errorf("%v -> %q is not in the Cloud list", err, c)
		}
	}
	if nbi.ErrorCode(nil) != "" {
		t.Fatal("nil is no error")
	}
}
