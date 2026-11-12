//go:build !unix

package credfile

import (
	"errors"
	"os"
)

// The Edge is only supported on unix hosts: without ownership checks, a lock and a directory sync the guarantees of this package cannot be kept, so it fails closed.
var errPlatform = errors.New("credfile: not supported on this platform")

func openNoFollow(string) (*os.File, error) { return nil, errPlatform }
func ownedByUs(os.FileInfo) bool            { return false }
func lockFile(string) (func(), error)       { return nil, errPlatform }
func lockFileShared(string) (func(), error) { return nil, errPlatform }
func syncDir(string) error                  { return errPlatform }
