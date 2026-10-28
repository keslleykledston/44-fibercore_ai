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

// Defaults bound disk use on the ISP site. Backpressure is applied PER KIND (a flood of one snapshot kind never
// evicts another kind), oldest first. Within one (kind,key) a completed newer round supersedes older rounds
// (PruneSuperseded) because snapshots are full-state observations.
const (
	DefaultMaxPending = 2000
	DefaultMaxBytes   = 256 << 20
	DefaultMaxDead    = 500
)

type Queue struct {
	db          *sql.DB
	MaxAttempts int
	MaxPending  int // per kind
	MaxBytes    int64
	MaxDead     int
	Dropped     int64            // pending items dropped by backpressure since start (exposed for logs/metrics)
	Now         func() time.Time // clock for nonce expiry; nil => time.Now. Must be the same clock the job verifier uses.
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
		`CREATE TABLE IF NOT EXISTS pending (id INTEGER PRIMARY KEY AUTOINCREMENT, kind TEXT NOT NULL, key TEXT NOT NULL DEFAULT '', round INTEGER NOT NULL DEFAULT 0, payload BLOB NOT NULL, attempts INTEGER NOT NULL DEFAULT 0, created_at TEXT NOT NULL)`,
		`CREATE TABLE IF NOT EXISTS seen_nonces (nonce TEXT PRIMARY KEY, until TEXT NOT NULL)`,
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

// Enqueue stores a payload. key identifies the logical stream it belongs to (e.g. "cpe:<connector>") and round
// the collection round; both are used only by PruneSuperseded.
func (q *Queue) Enqueue(ctx context.Context, kind, key string, round int64, payload []byte) error {
	if int64(len(payload)) > q.MaxBytes {
		return fmt.Errorf("payload of %d bytes exceeds queue byte limit", len(payload))
	}
	tx, err := q.db.BeginTx(ctx, nil)
	if err != nil {
		return err
	}
	defer tx.Rollback()
	res, err := tx.ExecContext(ctx, `INSERT INTO pending (kind, key, round, payload, created_at) VALUES (?,?,?,?,?)`, kind, key, round, payload, time.Now().UTC().Format(time.RFC3339Nano))
	if err != nil {
		return err
	}
	newID, _ := res.LastInsertId()
	// Per-kind item limit: evict the oldest of THIS kind only.
	r, err := tx.ExecContext(ctx, `DELETE FROM pending WHERE kind = ? AND id IN (
		SELECT id FROM pending WHERE kind = ? ORDER BY id DESC LIMIT -1 OFFSET ?)`, kind, kind, q.MaxPending)
	if err != nil {
		return err
	}
	dropped, _ := r.RowsAffected()
	// Global byte limit: evict the oldest item of the kind holding the most bytes (never the one just inserted).
	for {
		var total int64
		if err := tx.QueryRowContext(ctx, `SELECT COALESCE(SUM(length(payload)),0) FROM pending`).Scan(&total); err != nil {
			return err
		}
		if total <= q.MaxBytes {
			break
		}
		r, err := tx.ExecContext(ctx, `DELETE FROM pending WHERE id = (
			SELECT MIN(id) FROM pending WHERE id <> ? AND kind = (
				SELECT kind FROM pending GROUP BY kind ORDER BY SUM(length(payload)) DESC LIMIT 1))`, newID)
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

// PruneSuperseded removes pending items of a stream that belong to rounds older than `round`. Call it only after
// the whole round was persisted, so an incomplete round never discards the previous complete one.
func (q *Queue) PruneSuperseded(ctx context.Context, key string, round int64) error {
	_, err := q.db.ExecContext(ctx, `DELETE FROM pending WHERE key = ? AND round < ?`, key, round)
	return err
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

// Remember implements jobs.NonceStore: true if the nonce is new. Expired nonces are pruned opportunistically.
func (q *Queue) Remember(ctx context.Context, nonce string, until time.Time) (bool, error) {
	clock := time.Now
	if q.Now != nil {
		clock = q.Now
	}
	now := clock().UTC().Format(time.RFC3339Nano)
	if _, err := q.db.ExecContext(ctx, `DELETE FROM seen_nonces WHERE until < ?`, now); err != nil {
		return false, err
	}
	res, err := q.db.ExecContext(ctx, `INSERT OR IGNORE INTO seen_nonces (nonce, until) VALUES (?,?)`, nonce, until.UTC().Format(time.RFC3339Nano))
	if err != nil {
		return false, err
	}
	n, _ := res.RowsAffected()
	return n == 1, nil
}
