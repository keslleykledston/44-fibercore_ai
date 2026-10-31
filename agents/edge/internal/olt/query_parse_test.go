package olt

import (
	"encoding/json"
	"errors"
	"os"
	"strings"
	"testing"
)

func TestParseVersionFromTheRealCapture(t *testing.T) {
	b, err := os.ReadFile(r015Dir + "display_version.txt")
	if err != nil {
		t.Fatal(err)
	}
	raw, err := ParseResult("olt.version", string(b))
	if err != nil {
		t.Fatal(err)
	}
	var got map[string]any
	_ = json.Unmarshal(raw, &got)
	want := 1028*86400 + 9*3600 + 5*60 + 45
	if got["product"] != "MA5608T" || got["version"] != "MA5600V800R015C00" || got["patch"] != "SPC100 HP1013" || int(got["uptime_seconds"].(float64)) != want || len(got) != 4 {
		t.Fatalf("%v", got)
	}
}

func TestParseBoardFromTheRealCapture(t *testing.T) {
	b, err := os.ReadFile(r015Dir + "board_0.txt")
	if err != nil {
		t.Fatal(err)
	}
	raw, err := ParseResult("olt.board", string(b))
	if err != nil {
		t.Fatal(err)
	}
	var got struct {
		Boards []boardRow `json:"boards"`
		Empty  []int      `json:"empty_slots"`
	}
	if err := json.Unmarshal(raw, &got); err != nil {
		t.Fatal(err)
	}
	if len(got.Boards) != 5 || got.Boards[2] != (boardRow{Slot: 2, Name: "H801MCUD1", Status: "Active_normal"}) || len(got.Empty) != 1 || got.Empty[0] != 3 {
		t.Fatalf("%+v", got)
	}
	if strings.Contains(string(raw), "OLT-TEST") || strings.Contains(string(raw), "CPCB") {
		t.Fatalf("nothing but the closed fields may leave: %s", raw)
	}
}

func TestParsersFailClosed(t *testing.T) {
	for _, tc := range []struct{ id, out string }{
		{"olt.version", ""}, {"olt.version", "PRODUCT : MA5608T\nVERSION : x\n"},
		{"olt.version", "PRODUCT : <script>\nVERSION : MA5600V800R015C00\nPATCH : SPC100\nUptime is 1 day(s), 99 hour(s), 5 minute(s), 45 second(s)"},
		{"olt.version", "PRODUCT : MA5608T\nVERSION : MA5600V800R015C00; reload\nPATCH : SPC100\nUptime is 1 day(s), 1 hour(s), 5 minute(s), 45 second(s)"},
		{"olt.board", ""}, {"olt.board", "SlotID BoardName Status\n---\n"}, {"olt.board", "SlotID BoardName Status\n0 H805GPFD Normal\n0 H805GPFD Normal\n"},
		{"olt.board", "SlotID BoardName Status\n99 H805GPFD Normal\n"}, {"olt.board", "SlotID BoardName Status\n0 H805GPFD Normal\nfree text from the device\n"},
	} {
		if _, err := ParseResult(tc.id, tc.out); !errors.Is(err, ErrBadOutput) {
			t.Errorf("%s %q: %v", tc.id, tc.out, err)
		}
	}
	if _, err := ParseResult("onu.info", "x"); !errors.Is(err, ErrNoParser) || HasParser("onu.info") {
		t.Fatal("a query without parser must say so")
	}
	for _, q := range Queries() { // a parser exists only for validated queries
		if HasParser(q.ID) && !q.Validated {
			t.Fatalf("%s has a parser but is not validated", q.ID)
		}
	}
}

func TestParseLot1FromTheRealCaptures(t *testing.T) {
	read := func(n string) string {
		b, err := os.ReadFile(r015Dir + n)
		if err != nil {
			t.Fatal(err)
		}
		return string(b)
	}
	raw, err := ParseResult("olt.time", read("display_time.txt"))
	if err != nil || string(raw) != `{"time":"2026-10-30T20:42:45-04:00"}` {
		t.Fatalf("%s %v", raw, err)
	}
	raw, err = ParseResult("olt.sync", read("display_data_sync_state.txt"))
	if err != nil || string(raw) != `{"standby":"absent_or_fault"}` {
		t.Fatalf("%s %v", raw, err)
	}
	raw, err = ParseResult("olt.temperature", read("display_temperature_0.txt"))
	want := `{"boards":[{"slot":0,"name":"H805GPFD","celsius":45},{"slot":1,"name":"H805GPFD","celsius":45},{"slot":2,"name":"H801MCUD1","celsius":43}]}`
	if err != nil || string(raw) != want {
		t.Fatalf("%s %v", raw, err)
	}
	for _, id := range []string{"olt.time", "olt.sync", "olt.temperature"} {
		if !HasParser(id) {
			t.Fatalf("%s has a parser", id)
		}
	}
}

func TestLot1ParsersFailClosed(t *testing.T) {
	for _, tc := range []struct{ id, out string }{
		{"olt.time", ""}, {"olt.time", "2026-13-40 20:42:45-04:00"}, {"olt.time", "2026-10-30 20:42:45-04:00\n2026-10-30 20:42:46-04:00"},
		{"olt.time", "2026-10-30 20:42:45-04:00\nfree text"}, {"olt.time", "1999-10-30 20:42:45-04:00"}, {"olt.time", "2026-10-30 20:42:45"},
		{"olt.sync", ""}, {"olt.sync", "Standby board fault or not exist\nsomething else"}, {"olt.sync", "Sync state: complete"},
		{"olt.temperature", ""}, {"olt.temperature", "SlotID:  0      BoardName: H805GPFD       Temperature:   45C( 113F)\nSlotID:  0      BoardName: H805GPFD       Temperature:   46C( 114F)"},
		{"olt.temperature", "SlotID:  99     BoardName: H805GPFD       Temperature:   45C( 113F)"}, {"olt.temperature", "SlotID:  0      BoardName: H805GPFD       Temperature:   900C( 113F)"},
		{"olt.temperature", "SlotID:  0      BoardName: H805GPFD       Temperature:   45C( 113F)\nnote: hot"},
	} {
		if _, err := ParseResult(tc.id, tc.out); !errors.Is(err, ErrBadOutput) {
			t.Errorf("%s %q: %v", tc.id, tc.out, err)
		}
	}
}

func TestParseLot2CpuAndMemFromTheRealCaptures(t *testing.T) {
	read := func(n string) string {
		b, err := os.ReadFile(r015Dir + n)
		if err != nil {
			t.Fatal(err)
		}
		return string(b)
	}
	for file, tc := range map[string]struct{ id, want string }{
		"display_cpu_0_0.txt": {"slot.cpu", `{"percent":15}`}, // line card: fixed "Send message ... board executing..." line first
		"display_cpu_0_2.txt": {"slot.cpu", `{"percent":51}`}, // control board: the occupancy alone
		"display_mem_0_0.txt": {"slot.mem", `{"percent":34}`},
		"display_mem_0_2.txt": {"slot.mem", `{"percent":30}`},
	} {
		raw, err := ParseResult(tc.id, read(file))
		if err != nil || string(raw) != tc.want {
			t.Fatalf("%s: %s %v", file, raw, err)
		}
	}
	for _, id := range []string{"slot.cpu", "slot.mem"} {
		q, _ := QueryByID(id)
		if !HasParser(id) || !q.Validated {
			t.Fatalf("%s needs a parser and the Validated flag together", id)
		}
	}
}

func TestLot2ParsersFailClosed(t *testing.T) {
	pre := "Send message for inquiring board cpu occupancy successfully, board executing...\n"
	for _, tc := range []struct{ id, out string }{
		{"slot.cpu", ""}, {"slot.cpu", pre}, {"slot.cpu", "CPU occupancy: 101%"}, {"slot.cpu", "CPU occupancy: 15"}, {"slot.cpu", "CPU occupancy: -1%"},
		{"slot.cpu", "CPU occupancy: 15%\nCPU occupancy: 16%"}, // two answers: ambiguous
		{"slot.cpu", "CPU occupancy: 15%\nnote: busy"},         // free text from the device is never forwarded
		{"slot.cpu", pre + pre + "CPU occupancy: 15%"},         // the preamble is accepted once only
		{"slot.cpu", "CPU occupancy: 15%\n" + pre},             // and only before the value
		{"slot.cpu", "Memory occupancy: 15%"},                  // wrong label for the query
		{"slot.mem", pre + "Memory occupancy: 34%"},            // the preamble belongs to the CPU query only
		{"slot.mem", "Memory occupancy: 34% <script>"}, {"slot.mem", "CPU occupancy: 34%"},
	} {
		if _, err := ParseResult(tc.id, tc.out); !errors.Is(err, ErrBadOutput) {
			t.Errorf("%s %q: %v", tc.id, tc.out, err)
		}
	}
}
