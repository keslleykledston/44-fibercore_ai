package queue

import (
	"context"
	"os"
	"path/filepath"
	"testing"
)

func TestPersistsAcrossRestartInOrderWith0600(t *testing.T) {
	ctx := context.Background()
	path := filepath.Join(t.TempDir(), "q.db")
	q, err := Open(path)
	if err != nil {
		t.Fatal(err)
	}
	for _, p := range []string{"a", "b", "c"} {
		if err := q.Enqueue(ctx, "cpe_snapshot", []byte(p)); err != nil {
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
	_ = q.Enqueue(ctx, "k", []byte("x"))
	_ = q.Enqueue(ctx, "k", []byte("y"))
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
