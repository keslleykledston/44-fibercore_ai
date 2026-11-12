package managedolts

import (
	"errors"
	"fmt"
	"testing"
)

func TestAPendingRemovalIsNeverDroppedToMakeRoom(t *testing.T) {
	old := tombstoneCap
	tombstoneCap = 3
	defer func() { tombstoneCap = old }()
	s := newStore(t)
	mk := func(i int) Entry {
		e := entry(fmt.Sprintf("OLT-%d", i))
		e.Address = fmt.Sprintf("10.20.%d.1", i)
		e.CloudID = fmt.Sprintf("5a1f3c52-0b6e-4f0e-9a52-%012d", i)
		return e
	}
	for i := 0; i < 5; i++ {
		if _, err := s.Upsert(mk(i)); err != nil {
			t.Fatal(err)
		}
	}
	for i := 0; i < 3; i++ {
		if _, err := s.Remove(fmt.Sprintf("OLT-%d", i)); err != nil {
			t.Fatal(err)
		}
	}
	// the fourth pending removal is REFUSED before anything is written or deleted: no tombstone was evicted, the entry is still there, trust and credentials untouched
	if err := s.Trust("OLT-3", mk(3).Digest()); err != nil {
		t.Fatal(err)
	}
	if _, err := s.Remove("OLT-3"); !errors.Is(err, ErrTooManyRemovals) {
		t.Fatalf("err=%v", err)
	}
	tomb, err := s.Tombstones()
	if err != nil || len(tomb) != 3 {
		t.Fatalf("%v %v", tomb, err)
	}
	if it, ok, _ := s.Get("OLT-3"); !ok || !it.Trusted {
		t.Fatal("a refused removal must leave the OLT exactly as it was")
	}
	// once the Cloud has taken some, there is room again, and a repeated removal of the same id never needs room
	if err := s.ClearTombstones([]string{mk(0).CloudID}); err != nil {
		t.Fatal(err)
	}
	if _, err := s.Remove("OLT-3"); err != nil {
		t.Fatal(err)
	}
	if _, err := s.Remove("OLT-3"); err != nil { // already gone: nothing new to record
		t.Fatal(err)
	}
	if tomb, _ := s.Tombstones(); len(tomb) != 3 {
		t.Fatalf("%v", tomb)
	}
}
