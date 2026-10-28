package olt

import (
	"context"
	"encoding/hex"
	"encoding/json"
	"fmt"
	"os"
	"strings"
	"testing"
	"time"
)

// Opt-in, read-only check against a real OLT (through whatever UDP path the operator has). It never runs in CI:
//
//	R015_SNMP_ADDR=127.0.0.1:1161 R015_SNMP_COMMUNITY_FILE=/path/0600 R015_SNMP_PONS=0/0/14 go test ./internal/olt -run LiveSNMP -v
//
// With R015_SNMP_DUMP=<file> it also writes the responses it saw as a sanitized MIB fixture (serials replaced).
type recorder struct {
	inner SNMPReader
	seen  map[string]SNMPValue
}

func (r *recorder) Get(ctx context.Context, oids []string) (map[string]SNMPValue, error) {
	out, err := r.inner.Get(ctx, oids)
	for k, v := range out {
		r.seen[k] = v
	}
	return out, err
}

func (r *recorder) Walk(ctx context.Context, root string, max int) ([]SNMPRow, error) {
	rows, err := r.inner.Walk(ctx, root, max)
	for _, row := range rows {
		r.seen[root+"."+row.Suffix] = row.Value
	}
	return rows, err
}

func TestLiveSNMPAgainstARealOLT(t *testing.T) {
	addr, file := os.Getenv("R015_SNMP_ADDR"), os.Getenv("R015_SNMP_COMMUNITY_FILE")
	if addr == "" || file == "" {
		t.Skip("set R015_SNMP_ADDR and R015_SNMP_COMMUNITY_FILE to run against a real OLT")
	}
	b, err := os.ReadFile(file)
	if err != nil {
		t.Fatal(err)
	}
	r, closeFn, err := DialSNMP(context.Background(), SNMPConfig{Addr: addr, Community: strings.TrimSpace(string(b)),
		Allowed: func(h string) bool { return h == addr }, Timeout: 8 * time.Second, Pace: 200 * time.Millisecond})
	if err != nil {
		t.Fatal(err)
	}
	defer closeFn()
	rec := &recorder{inner: r, seen: map[string]SNMPValue{}}
	ports := strings.Split(os.Getenv("R015_SNMP_PONS"), ",")
	ctx, cancel := context.WithTimeout(context.Background(), 4*time.Minute)
	defer cancel()
	snap, err := HuaweiSNMP{}.Snapshot(ctx, rec, ports)
	if err != nil {
		t.Fatal(err)
	}
	for i, p := range snap.PONs {
		on := 0
		for _, u := range snap.ONUs {
			if u.PonPath == p.Path && u.Status == "online" {
				on++
			}
		}
		t.Logf("%s: onus=%d online=%d verified=%v identity=%+v", p.Path, countPon(snap, p.Path), on, p.Verified, snap.Identity)
		_ = i
	}
	if dump := os.Getenv("R015_SNMP_DUMP"); dump != "" {
		type entry struct {
			OID   string `json:"oid"`
			Int   *int64 `json:"int,omitempty"`
			Bytes string `json:"bytes_hex,omitempty"`
		}
		fake := map[string]string{}
		var out []entry
		for oid, v := range rec.seen {
			e := entry{OID: oid}
			switch {
			case v.IsInt:
				n := v.Int
				e.Int = &n
			case v.IsBytes && len(v.Bytes) == 8 && strings.Contains(oid, ".43.1.3."): // a serial: replace, consistently
				key := hex.EncodeToString(v.Bytes)
				if _, ok := fake[key]; !ok {
					fake[key] = fmt.Sprintf("48575443%08x", 0x30000000+len(fake))
				}
				e.Bytes = fake[key]
			case v.IsBytes:
				e.Bytes = hex.EncodeToString(v.Bytes)
			default:
				continue
			}
			out = append(out, e)
		}
		j, _ := json.MarshalIndent(out, "", " ")
		if err := os.WriteFile(dump, j, 0o600); err != nil {
			t.Fatal(err)
		}
	}
}

func countPon(s Snapshot, path string) int {
	n := 0
	for _, u := range s.ONUs {
		if u.PonPath == path {
			n++
		}
	}
	return n
}
