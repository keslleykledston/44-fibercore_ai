// Package queue is the Edge store-and-forward buffer (SQLite WAL). Items survive restarts and are
// delivered in order; permanently rejected items move to a dead-letter table instead of blocking.
package queue

import (
	"context"
	"database/sql"
	"fmt"
	"os"
	"time"

	_ "modernc.org/sqlite"
)

type Item struct {
	ID       int64
	Kind     string
	Payload  []byte
	Attempts int
}

// Defaults bound disk use on the ISP site. Snapshots are full-state observations that supersede older ones
// (the Cloud ignores out-of-order data), so when a limit is hit the OLDEST pending items are dropped first.
const (
	DefaultMaxPending = 2000
	DefaultMaxBytes   = 256 << 20
	DefaultMaxDead    = 500
)

type Queue struct {
	db          *sql.DB
	MaxAttempts int
	MaxPending  int
	MaxBytes    int64
	MaxDead     int
	Dropped     int64 // pending items dropped by backpressure since start (exposed for logs/metrics)
}

func Open(path string) (*Queue, error) {
	// Created 0600 up front: the queue holds inventory data of the ISP's customers.
	f, err := os.OpenFile(path, os.O_CREATE|os.O_RDWR, 0o600)
	if err != nil {
		return nil, err
	}
	f.Close()
	db, err := sql.Open("sqlite", fmt.Sprintf("file:%s?_pragma=journal_mode(WAL)&_pragma=busy_timeout(5000)&_pragma=synchronous(NORMAL)", path))
	if err != nil {
		return nil, err
	}
	db.SetMaxOpenConns(1)
	for _, ddl := range []string{
		`CREATE TABLE IF NOT EXISTS pending (id INTEGER PRIMARY KEY AUTOINCREMENT, kind TEXT NOT NULL, payload BLOB NOT NULL, attempts INTEGER NOT NULL DEFAULT 0, created_at TEXT NOT NULL)`,
		`CREATE TABLE IF NOT EXISTS dead (id INTEGER PRIMARY KEY, kind TEXT NOT NULL, payload BLOB NOT NULL, reason TEXT NOT NULL, dead_at TEXT NOT NULL)`,
	} {
		if _, err := db.Exec(ddl); err != nil {
			db.Close()
			return nil, err
		}
	}
	return &Queue{db: db, MaxAttempts: 20, MaxPending: DefaultMaxPending, MaxBytes: DefaultMaxBytes, MaxDead: DefaultMaxDead}, nil
}

func (q *Queue) Close() error { return q.db.Close() }

func (q *Queue) Enqueue(ctx context.Context, kind string, payload []byte) error {
	if int64(len(payload)) > q.MaxBytes {
		return fmt.Errorf("payload of %d bytes exceeds queue byte limit", len(payload))
	}
	tx, err := q.db.BeginTx(ctx, nil)
	if err != nil {
		return err
	}
	defer tx.Rollback()
	if _, err := tx.ExecContext(ctx, `INSERT INTO pending (kind, payload, created_at) VALUES (?,?,?)`, kind, payload, time.Now().UTC().Format(time.RFC3339Nano)); err != nil {
		return err
	}
	// Backpressure: evict oldest until both item and byte limits hold (never the item just inserted).
	res, err := tx.ExecContext(ctx, `DELETE FROM pending WHERE id IN (
		SELECT id FROM pending ORDER BY id DESC LIMIT -1 OFFSET ?)`, q.MaxPending)
	if err != nil {
		return err
	}
	dropped, _ := res.RowsAffected()
	for {
		var total int64
		if err := tx.QueryRowContext(ctx, `SELECT COALESCE(SUM(length(payload)),0) FROM pending`).Scan(&total); err != nil {
			return err
		}
		if total <= q.MaxBytes {
			break
		}
		r, err := tx.ExecContext(ctx, `DELETE FROM pending WHERE id = (SELECT MIN(id) FROM pending) AND (SELECT COUNT(*) FROM pending) > 1`)
		if err != nil {
			return err
		}
		n, _ := r.RowsAffected()
		if n == 0 {
			break
		}
		dropped += n
	}
	if err := tx.Commit(); err != nil {
		return err
	}
	q.Dropped += dropped
	return nil
}

// Next returns up to n oldest items.
func (q *Queue) Next(ctx context.Context, n int) ([]Item, error) {
	rows, err := q.db.QueryContext(ctx, `SELECT id, kind, payload, attempts FROM pending ORDER BY id LIMIT ?`, n)
	if err != nil {
		return nil, err
	}
	defer rows.Close()
	var out []Item
	for rows.Next() {
		var it Item
		if err := rows.Scan(&it.ID, &it.Kind, &it.Payload, &it.Attempts); err != nil {
			return nil, err
		}
		out = append(out, it)
	}
	return out, rows.Err()
}

func (q *Queue) Ack(ctx context.Context, id int64) error {
	_, err := q.db.ExecContext(ctx, `DELETE FROM pending WHERE id = ?`, id)
	return err
}

// Retry bumps attempts; past MaxAttempts the item is dead-lettered. Returns true if dead-lettered.
func (q *Queue) Retry(ctx context.Context, it Item, reason string) (bool, error) {
	if it.Attempts+1 >= q.MaxAttempts {
		return true, q.Dead(ctx, it, "max attempts: "+reason)
	}
	_, err := q.db.ExecContext(ctx, `UPDATE pending SET attempts = attempts + 1 WHERE id = ?`, it.ID)
	return false, err
}

// Dead moves an item out of the pending path (permanent rejection by the Cloud).
func (q *Queue) Dead(ctx context.Context, it Item, reason string) error {
	tx, err := q.db.BeginTx(ctx, nil)
	if err != nil {
		return err
	}
	defer tx.Rollback()
	if _, err := tx.ExecContext(ctx, `INSERT OR REPLACE INTO dead (id, kind, payload, reason, dead_at) VALUES (?,?,?,?,?)`, it.ID, it.Kind, it.Payload, reason, time.Now().UTC().Format(time.RFC3339Nano)); err != nil {
		return err
	}
	if _, err := tx.ExecContext(ctx, `DELETE FROM pending WHERE id = ?`, it.ID); err != nil {
		return err
	}
	// retention: keep only the newest MaxDead dead letters
	if _, err := tx.ExecContext(ctx, `DELETE FROM dead WHERE id IN (SELECT id FROM dead ORDER BY dead_at DESC, id DESC LIMIT -1 OFFSET ?)`, q.MaxDead); err != nil {
		return err
	}
	return tx.Commit()
}

func (q *Queue) Counts(ctx context.Context) (pending, dead int, err error) {
	if err = q.db.QueryRowContext(ctx, `SELECT count(*) FROM pending`).Scan(&pending); err != nil {
		return
	}
	err = q.db.QueryRowContext(ctx, `SELECT count(*) FROM dead`).Scan(&dead)
	return
}
