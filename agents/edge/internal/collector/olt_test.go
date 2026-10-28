package collector

import (
	"context"
	"encoding/json"
	"errors"
	"os"
	"path/filepath"
	"reflect"
	"testing"
	"time"

	"github.com/keslleykledston/44-fibercore_ai/agents/edge/internal/olt"
)

type fileSession struct{ dir string }

func (f fileSession) Run(_ context.Context, cmd string) (string, error) {
	m := map[string]string{
		"display version": "display_version.txt", "display ont info summary 0/1/0": "ont_info_summary_0_1_0.txt",
		"display ont optical-info 0/1/0 all": "ont_optical_0_1_0.txt",
	}
	n, ok := m[cmd]
	if !ok {
		return "", errors.New("unexpected " + cmd)
	}
	b, err := os.ReadFile(filepath.Join("..", "olt", "testdata", f.dir, n))
	return string(b), err
}

func src(name, dir string, unverified bool) OLTSource {
	return OLTSource{Name: name, Driver: olt.Huawei{}, Ports: []string{"0/1/0"}, AllowUnverified: unverified,
		Open: func(context.Context) (olt.Session, func(), error) { return fileSession{dir}, func() {}, nil }}
}

func TestOLTSnapshotPayloadMatchesCloudContractAndNeverClaimsObserved(t *testing.T) {
	c := &OLT{EdgeID: "e1", Sources: []OLTSource{src("OLT-A", "huawei_ma5800/R018", false)},
		Now: func() time.Time { return time.Date(2026, 10, 28, 1, 0, 0, 0, time.UTC) }}
	items, err := c.Collect(context.Background())
	if err != nil || len(items) != 1 || items[0].Kind != "olt_snapshot" || items[0].Key != "olt:OLT-A" {
		t.Fatalf("items=%v err=%v", items, err)
	}
	golden := filepath.Join("..", "..", "..", "..", "tests", "fixtures", "edge", "olt_snapshot_huawei.golden.json")
	if os.Getenv("UPDATE_GOLDEN") == "1" {
		var pretty map[string]any
		_ = json.Unmarshal(items[0].Payload, &pretty)
		b, _ := json.MarshalIndent(pretty, "", "  ")
		_ = os.MkdirAll(filepath.Dir(golden), 0o755)
		_ = os.WriteFile(golden, append(b, '\n'), 0o644)
	}
	want, err := os.ReadFile(golden)
	if err != nil {
		t.Fatal(err)
	}
	var wantV, gotV any
	_ = json.Unmarshal(want, &wantV)
	_ = json.Unmarshal(items[0].Payload, &gotV)
	if !reflect.DeepEqual(wantV, gotV) {
		t.Fatalf("payload differs from golden consumed by the Python contract test:\n%s", items[0].Payload)
	}
	var p map[string]any
	_ = json.Unmarshal(items[0].Payload, &p)
	if p["driver_level"] != "identified" || p["name"] != "OLT-A" || p["vendor"] != "huawei" || p["firmware"] != "R018" || p["edge_id"] != "e1" {
		t.Fatalf("payload=%v", p)
	}
	if len(p["onus"].([]any)) != 3 || len(p["pons"].([]any)) != 1 {
		t.Fatalf("payload=%v", p)
	}
}

func TestUnknownFirmwareRefusedUnlessExplicitlyAllowed(t *testing.T) {
	bad := src("OLT-B", "huawei_ma5800/R018", false)
	bad.Open = func(context.Context) (olt.Session, func(), error) {
		return versionOverride{fileSession{"huawei_ma5800/R018"}}, func() {}, nil
	}
	items, err := (&OLT{EdgeID: "e", Sources: []OLTSource{bad}}).Collect(context.Background())
	if !errors.Is(err, olt.ErrUnsupportedFirmware) || len(items) != 0 {
		t.Fatalf("items=%v err=%v", items, err)
	}
	bad.AllowUnverified = true
	items, err = (&OLT{EdgeID: "e", Sources: []OLTSource{bad}}).Collect(context.Background())
	if err != nil || len(items) != 1 {
		t.Fatalf("items=%v err=%v", items, err)
	}
	var p map[string]any
	_ = json.Unmarshal(items[0].Payload, &p)
	if p["driver_level"] != "identified" {
		t.Fatalf("unverified must stay identified: %v", p["driver_level"])
	}
}

type versionOverride struct{ fileSession }

func (v versionOverride) Run(ctx context.Context, cmd string) (string, error) {
	if cmd == "display version" {
		return "  VERSION : R999\n  PRODUCT : MA5800-X7\n", nil
	}
	return v.fileSession.Run(ctx, cmd)
}

func TestOneOLTFailureKeepsOthers(t *testing.T) {
	broken := OLTSource{Name: "OLT-X", Driver: olt.Huawei{}, Ports: []string{"0/1/0"},
		Open: func(context.Context) (olt.Session, func(), error) { return nil, nil, errors.New("unreachable") }}
	items, err := (&OLT{EdgeID: "e", Sources: []OLTSource{broken, src("OLT-A", "huawei_ma5800/R018", false)}}).Collect(context.Background())
	if err == nil || len(items) != 1 {
		t.Fatalf("items=%d err=%v", len(items), err)
	}
}
