package managedolts

import (
	"errors"
	"testing"
	"time"
)

func TestARevocationWaitsForWhoeverHoldsTheSharedLock(t *testing.T) {
	s := newStore(t)
	e := entry("A")
	s.Upsert(e)
	release, err := s.RLock()
	if err != nil {
		t.Fatal(err)
	}
	done := make(chan error, 1)
	go func() { _, err := s.Remove("A", e.CloudID); done <- err }()
	select {
	case <-done:
		t.Fatal("the removal must wait for the connection that was authorised before it")
	case <-time.After(300 * time.Millisecond):
	}
	if it, ok, _ := s.Get("A"); !ok || it.Entry.Name != "A" {
		t.Fatal("nothing may change while the shared lock is held")
	}
	release()
	select {
	case err := <-done:
		if err != nil {
			t.Fatal(err)
		}
	case <-time.After(5 * time.Second):
		t.Fatal("the removal must proceed once the shared lock is released")
	}
	if l, _ := s.List(); len(l) != 0 {
		t.Fatalf("%+v", l)
	}
	// shared holders do not exclude each other
	r1, err1 := s.RLock()
	r2, err2 := s.RLock()
	if err1 != nil || err2 != nil {
		t.Fatal(err1, err2)
	}
	r1()
	r2()
}

func TestANameKeepsItsCloudID(t *testing.T) {
	s := newStore(t)
	e := entry("A")
	s.Upsert(e)
	if err := s.Trust("A", e.Digest()); err != nil {
		t.Fatal(err)
	}
	other := "5a1f3c52-0b6e-4f0e-9a52-00000000beef"
	// a remove for another Cloud id (an old delivery, a recreated name) touches nothing
	if _, err := s.Remove("A", other); !errors.Is(err, ErrCloudIDMismatch) {
		t.Fatalf("err=%v", err)
	}
	if it, ok, _ := s.Get("A"); !ok || !it.Trusted {
		t.Fatal("the entry must be exactly as it was")
	}
	if tomb, _ := s.Tombstones(); len(tomb) != 0 {
		t.Fatalf("no tombstone for a refused removal: %v", tomb)
	}
	// and a set under the same name with another Cloud id is another OLT: refused until the old one is removed
	x := e
	x.CloudID = other
	if _, err := s.Upsert(x); !errors.Is(err, ErrCloudIDMismatch) {
		t.Fatalf("err=%v", err)
	}
	if it, _, _ := s.Get("A"); it.Entry.CloudID != e.CloudID || !it.Trusted {
		t.Fatal("the entry must be exactly as it was")
	}
	if _, err := s.Remove("A", e.CloudID); err != nil {
		t.Fatal(err)
	}
	if _, err := s.Upsert(x); err != nil {
		t.Fatalf("after the remove the name is free for the new Cloud id: %v", err)
	}
}
