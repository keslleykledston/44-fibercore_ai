package nbi

import (
	"context"
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
	if gotMethod != "GET" || gotProj != "_id,_lastInform,_deviceId" || gotUser != "svc" {
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
