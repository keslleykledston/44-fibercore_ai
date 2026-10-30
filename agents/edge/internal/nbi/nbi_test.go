package nbi

import (
	"context"
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"
)

func TestDevicesIsGETWithMinimalProjectionAndAuth(t *testing.T) {
	var gotMethod, gotProj, gotUser string
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		gotMethod, gotProj = r.Method, r.URL.Query().Get("projection")
		gotUser, _, _ = r.BasicAuth()
		w.Write([]byte(`[{"_id":"X-1","_lastInform":"2026-10-28T00:00:00Z","_deviceId":{"_Manufacturer":"Huawei","_OUI":"00259E","_ProductClass":"HG8245H","_SerialNumber":"S1"}}]`))
	}))
	defer srv.Close()
	c, _ := New(srv.URL, srv.Client(), "svc:pw")
	devs, err := c.Devices(context.Background())
	if err != nil || len(devs) != 1 || devs[0].DeviceID.SerialNumber != "S1" {
		t.Fatalf("devs=%v err=%v", devs, err)
	}
	if gotMethod != "GET" || gotProj != "_id,_lastInform,_deviceId,InternetGatewayDevice.DeviceInfo.SoftwareVersion,Device.DeviceInfo.SoftwareVersion" || gotUser != "svc" {
		t.Fatalf("method=%s projection=%s user=%s", gotMethod, gotProj, gotUser)
	}
}

func TestDevicesErrors(t *testing.T) {
	cases := map[string]func(http.ResponseWriter, *http.Request){
		"status": func(w http.ResponseWriter, r *http.Request) { w.WriteHeader(500) },
		"json":   func(w http.ResponseWriter, r *http.Request) { w.Write([]byte("not json")) },
		"huge": func(w http.ResponseWriter, r *http.Request) {
			w.Write([]byte("[" + strings.Repeat(" ", maxBody+10) + "]"))
		},
	}
	for name, h := range cases {
		srv := httptest.NewServer(http.HandlerFunc(h))
		c, _ := New(srv.URL, srv.Client(), "")
		if _, err := c.Devices(context.Background()); err == nil {
			t.Errorf("%s: expected error", name)
		}
		srv.Close()
	}
}

func TestBadCredentialsFormat(t *testing.T) {
	if _, err := New("http://x", http.DefaultClient, "nocolon"); err == nil {
		t.Fatal("expected error")
	}
}

func TestDeviceFirmwareComesFromTheCachedSoftwareVersionAndIsSanitised(t *testing.T) {
	cases := map[string]string{
		`{"InternetGatewayDevice":{"DeviceInfo":{"SoftwareVersion":{"_value":"V5R019C10S350"}}}}`: "V5R019C10S350",
		`{"Device":{"DeviceInfo":{"SoftwareVersion":{"_value":"V2.0.1-b12"}}}}`:                   "V2.0.1-b12",
		`{"Device":{"DeviceInfo":{"SoftwareVersion":{"_value":"Admin1234"}}}}`:                    "",
		`{"Device":{"DeviceInfo":{"SoftwareVersion":{"_value":"MySecret-2026"}}}}`:                "",
		`{"Device":{"DeviceInfo":{"SoftwareVersion":{"_value":"hunter2hunter2"}}}}`:               "",
		`{"Device":{"DeviceInfo":{"SoftwareVersion":{"_value":"123456789"}}}}`:                    "",
		`{"Device":{"DeviceInfo":{"SoftwareVersion":{"_value":"ABCDEFGH"}}}}`:                     "",
		`{"InternetGatewayDevice":{"DeviceInfo":{"SoftwareVersion":{"_value":"x; DROP TABLE"}}}}`: "",
		`{"InternetGatewayDevice":{"DeviceInfo":{"SoftwareVersion":{"_value":7}}}}`:               "",
		`{}`: "",
	}
	for body, want := range cases {
		var d Device
		if err := json.Unmarshal([]byte(body), &d); err != nil {
			t.Fatal(err)
		}
		if got := d.Firmware(); got != want {
			t.Errorf("%s: got %q want %q", body, got, want)
		}
	}
}
