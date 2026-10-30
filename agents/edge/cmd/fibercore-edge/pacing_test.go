package main

import (
	"os"
	"strings"
	"testing"
)

// The guard must be built from the configured pacing, never from literals (a previous version logged the configured values and enforced the defaults).
func TestBenchGuardUsesTheConfiguredPacing(t *testing.T) {
	b, err := os.ReadFile("main.go")
	if err != nil {
		t.Fatal(err)
	}
	s := string(b)
	i := strings.Index(s, "config.BenchGuardFile(")
	if i < 0 {
		t.Fatal("bench guard not found")
	}
	line := s[i : i+strings.Index(s[i:], "\n")]
	if !strings.Contains(line, "MinPerDevice: minGap") || !strings.Contains(line, "MaxPerHour: perHour") || strings.Contains(line, "30 *") {
		t.Fatalf("bench guard must use the resolved pacing: %s", line)
	}
}
