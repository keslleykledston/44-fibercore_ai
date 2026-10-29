//go:build !unix

package singleton

import (
	"errors"
	"os"
)

var ErrHeld = errors.New("another fibercore-edge process holds the lock")

// Acquire fails closed: without a lock the OLT guard cannot be trusted, and the Edge is only supported on unix hosts.
func Acquire(string) (*os.File, error) {
	return nil, errors.New("single-instance lock is not supported on this platform")
}
