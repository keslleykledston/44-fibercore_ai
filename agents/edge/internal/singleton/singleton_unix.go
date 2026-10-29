//go:build unix

// Package singleton makes sure only ONE Edge process runs per state directory. The OLT guard (interval, cooldown, lock) lives in a
// file, and two processes reading it independently would both find the device "due" and log into it at once.
package singleton

import (
	"errors"
	"fmt"
	"os"
	"syscall"
)

var ErrHeld = errors.New("another fibercore-edge process holds the lock")

// Acquire takes an exclusive, non-blocking advisory lock on path (created 0600). The lock lives as long as the returned file
// stays open, i.e. until the process exits (a crash releases it).
func Acquire(path string) (*os.File, error) {
	f, err := os.OpenFile(path, os.O_CREATE|os.O_RDWR, 0o600)
	if err != nil {
		return nil, err
	}
	if err := syscall.Flock(int(f.Fd()), syscall.LOCK_EX|syscall.LOCK_NB); err != nil {
		f.Close()
		if errors.Is(err, syscall.EWOULDBLOCK) {
			return nil, ErrHeld
		}
		return nil, fmt.Errorf("lock %s: %w", path, err)
	}
	return f, nil
}
