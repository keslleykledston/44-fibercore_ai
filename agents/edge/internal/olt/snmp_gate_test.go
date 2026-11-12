package olt

import (
	"context"
	"errors"
	"strings"
	"sync"
	"testing"
	"time"
)

// The gate (ADR-0046) is asked before the socket is opened and before EVERY packet, retransmissions included, and released right after each one.
func TestSNMPGateIsHeldAroundTheConnectAndEveryPacketAndARefusalSendsNothing(t *testing.T) {
	addr, packets := silentAgent(t)
	var mu sync.Mutex
	held, asked, maxHeld := 0, 0, 0
	allow := true
	gate := func() (func(), error) {
		mu.Lock()
		defer mu.Unlock()
		asked++
		if !allow {
			return nil, errors.New("revoked")
		}
		held++
		if held > maxHeld {
			maxHeld = held
		}
		return func() { mu.Lock(); held--; mu.Unlock() }, nil
	}
	r := dialSilent(t, addr, func(c *SNMPConfig) { c.Retries = 2; c.Gate = gate })
	mu.Lock()
	if asked != 1 || held != 0 {
		t.Fatalf("the connect must ask once and release: asked=%d held=%d", asked, held)
	}
	mu.Unlock()
	if _, err := r.Get(context.Background(), []string{"1.3.6.1.2.1.1.3.0"}); err == nil {
		t.Fatal("a silent agent times out")
	}
	time.Sleep(50 * time.Millisecond)
	mu.Lock()
	if asked != 1+3 || held != 0 || maxHeld != 1 {
		t.Fatalf("every one of the 3 packets (1 request + 2 retransmissions) is its own gated exchange: asked=%d held=%d max=%d", asked, held, maxHeld)
	}
	allow = false
	mu.Unlock()
	before := packets()
	if _, err := r.Get(context.Background(), []string{"1.3.6.1.2.1.1.3.0"}); err == nil || !strings.Contains(err.Error(), "revoked") {
		t.Fatalf("a refused gate must stop the request: %v", err)
	}
	if _, err := r.Walk(context.Background(), "1.3.6.1.2.1.2", 10); err == nil {
		t.Fatal("and the walk")
	}
	time.Sleep(50 * time.Millisecond)
	if packets() != before {
		t.Fatalf("no packet may leave after the gate refuses: %d -> %d", before, packets())
	}
	// a refusing gate also stops the connection itself
	addr2, packets2 := silentAgent(t)
	_, _, err := DialSNMP(context.Background(), SNMPConfig{Addr: addr2, Community: "x", Allowed: func(string) bool { return true }, Gate: func() (func(), error) { return nil, errors.New("revoked") }})
	if !errors.Is(err, ErrSNMPDenied) || packets2() != 0 {
		t.Fatalf("%v %d", err, packets2())
	}
}
