package queue

import (
	"context"
	"os"
	"path/filepath"
	"testing"
	"time"
)

func TestPersistsAcrossRestartInOrderWith0600(t *testing.T) {
	ctx := context.Background()
	path := filepath.Join(t.TempDir(), "q.db")
	q, err := Open(path)
	if err != nil {
		t.Fatal(err)
	}
	for _, p := range []string{"a", "b", "c"} {
		if err := q.Enqueue(ctx, "cpe_snapshot", "", 0, []byte(p)); err != nil {
			t.Fatal(err)
		}
	}
	q.Close()
	q2, err := Open(path)
	if err != nil {
		t.Fatal(err)
	}
	defer q2.Close()
	items, _ := q2.Next(ctx, 10)
	if len(items) != 3 || string(items[0].Payload) != "a" || string(items[2].Payload) != "c" {
		t.Fatalf("items=%v", items)
	}
	_ = q2.Ack(ctx, items[0].ID)
	if rest, _ := q2.Next(ctx, 10); len(rest) != 2 {
		t.Fatalf("after ack: %d", len(rest))
	}
	if fi, _ := os.Stat(path); fi.Mode().Perm() != 0o600 {
		t.Fatalf("mode=%v", fi.Mode().Perm())
	}
}

func TestDeadLetterAfterMaxAttemptsAndOnReject(t *testing.T) {
	ctx := context.Background()
	q, _ := Open(filepath.Join(t.TempDir(), "q.db"))
	defer q.Close()
	q.MaxAttempts = 3
	_ = q.Enqueue(ctx, "k", "", 0, []byte("x"))
	_ = q.Enqueue(ctx, "k", "", 0, []byte("y"))
	for i := 0; i < 3; i++ {
		items, _ := q.Next(ctx, 1)
		dead, err := q.Retry(ctx, items[0], "boom")
		if err != nil {
			t.Fatal(err)
		}
		if dead != (i == 2) {
			t.Fatalf("attempt %d dead=%v", i, dead)
		}
	}
	items, _ := q.Next(ctx, 5)
	if len(items) != 1 || string(items[0].Payload) != "y" {
		t.Fatalf("expected only y pending, got %v", items)
	}
	_ = q.Dead(ctx, items[0], "rejected")
	p, d, _ := q.Counts(ctx)
	if p != 0 || d != 2 {
		t.Fatalf("pending=%d dead=%d", p, d)
	}
}

func TestBackpressureDropsOldestAndRespectsLimits(t *testing.T) {
	ctx := context.Background()
	q, _ := Open(filepath.Join(t.TempDir(), "q.db"))
	defer q.Close()
	q.MaxPending = 3
	for _, p := range []string{"1", "2", "3", "4", "5"} {
		if err := q.Enqueue(ctx, "k", "", 0, []byte(p)); err != nil {
			t.Fatal(err)
		}
	}
	items, _ := q.Next(ctx, 10)
	if len(items) != 3 || string(items[0].Payload) != "3" || string(items[2].Payload) != "5" || q.Dropped != 2 {
		t.Fatalf("items=%v dropped=%d", items, q.Dropped)
	}
	q.MaxBytes = 10
	if err := q.Enqueue(ctx, "k", "", 0, make([]byte, 11)); err == nil {
		t.Fatal("oversized payload must be refused")
	}
	for i := 0; i < 5; i++ {
		_ = q.Enqueue(ctx, "k", "", 0, make([]byte, 4))
	}
	var total int
	items, _ = q.Next(ctx, 100)
	for _, it := range items {
		total += len(it.Payload)
	}
	if total > 10 || len(items) == 0 {
		t.Fatalf("byte limit violated: total=%d items=%d", total, len(items))
	}
}

func TestDeadLetterRetention(t *testing.T) {
	ctx := context.Background()
	q, _ := Open(filepath.Join(t.TempDir(), "q.db"))
	defer q.Close()
	q.MaxDead = 2
	for i := 0; i < 5; i++ {
		_ = q.Enqueue(ctx, "k", "", 0, []byte{byte(i)})
		items, _ := q.Next(ctx, 1)
		_ = q.Dead(ctx, items[0], "r")
	}
	if _, d, _ := q.Counts(ctx); d != 2 {
		t.Fatalf("dead=%d want 2", d)
	}
}

func TestBackpressureNeverEvictsAnotherKind(t *testing.T) {
	ctx := context.Background()
	q, _ := Open(filepath.Join(t.TempDir(), "q.db"))
	defer q.Close()
	q.MaxPending = 2
	_ = q.Enqueue(ctx, "olt_snapshot", "olt:A", 1, []byte("olt-old"))
	for i := 0; i < 10; i++ { // flood of CPE snapshots
		_ = q.Enqueue(ctx, "cpe_snapshot", "cpe:c", int64(i), []byte{byte(i)})
	}
	items, _ := q.Next(ctx, 100)
	var olt, cpe int
	for _, it := range items {
		if it.Kind == "olt_snapshot" {
			olt++
		} else {
			cpe++
		}
	}
	if olt != 1 || cpe != 2 {
		t.Fatalf("olt=%d cpe=%d (OLT snapshot must survive a CPE flood)", olt, cpe)
	}
}

func TestPruneSupersededOnlyOlderRoundsOfSameKey(t *testing.T) {
	ctx := context.Background()
	q, _ := Open(filepath.Join(t.TempDir(), "q.db"))
	defer q.Close()
	_ = q.Enqueue(ctx, "cpe_snapshot", "cpe:c", 1, []byte("r1a"))
	_ = q.Enqueue(ctx, "cpe_snapshot", "cpe:c", 1, []byte("r1b"))
	_ = q.Enqueue(ctx, "cpe_snapshot", "cpe:c", 2, []byte("r2a"))
	_ = q.Enqueue(ctx, "cpe_snapshot", "cpe:other", 1, []byte("o1"))
	_ = q.PruneSuperseded(ctx, "cpe:c", 2)
	items, _ := q.Next(ctx, 10)
	got := ""
	for _, it := range items {
		got += string(it.Payload) + ","
	}
	if got != "r2a,o1," {
		t.Fatalf("got %s", got)
	}
}

func TestNonceStorePersistsAcrossRestartAndExpires(t *testing.T) {
	ctx := context.Background()
	path := filepath.Join(t.TempDir(), "q.db")
	q, _ := Open(path)
	if ok, _ := q.Remember(ctx, "n1", time.Now().Add(time.Hour)); !ok {
		t.Fatal("first use must be fresh")
	}
	q.Close()
	q2, _ := Open(path)
	defer q2.Close()
	if ok, _ := q2.Remember(ctx, "n1", time.Now().Add(time.Hour)); ok {
		t.Fatal("replay after restart must be detected")
	}
	_, _ = q2.Remember(ctx, "old", time.Now().Add(-time.Hour))
	if ok, _ := q2.Remember(ctx, "old", time.Now().Add(time.Hour)); !ok {
		t.Fatal("expired nonce is pruned and may be reused")
	}
}
