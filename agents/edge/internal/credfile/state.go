package credfile

import (
	"errors"
	"fmt"
	"io"
	"os"
	"path/filepath"
)

// OwnedByUs: the file belongs to the user this process runs as.
func OwnedByUs(fi os.FileInfo) bool { return ownedByUs(fi) }

// CheckStateDir is the rule for a directory that holds INTEGRITY-critical state (not a secret): it is ours and nobody else can write in it (no group/other write bit),
// so another user cannot replace or delete what is inside. Reading by others is not a concern for ids and times (the files themselves are 0600 anyway).
func CheckStateDir(dir string) error {
	fi, err := os.Stat(dir)
	if err != nil {
		return err
	}
	if !fi.IsDir() || fi.Mode().Perm()&0o022 != 0 || !ownedByUs(fi) {
		return fmt.Errorf("%s (directory must be owned by the Edge user and not writable by group/others): %w", dir, ErrInsecure)
	}
	return nil
}

// ReadStateFile reads a state file: the directory passes CheckStateDir, the file is a regular file (a symlink is never followed), owned by this user, mode 0600 with no
// group/other bit, checked on the OPEN descriptor, at most max bytes. A missing file is os.ErrNotExist (wrapped); every other problem is an ErrInsecure error.
func ReadStateFile(path string, max int64) ([]byte, error) {
	if err := CheckStateDir(filepath.Dir(path)); err != nil {
		return nil, err
	}
	li, err := os.Lstat(path)
	if err != nil {
		return nil, err
	}
	if !li.Mode().IsRegular() {
		return nil, fmt.Errorf("%s (not a regular file): %w", path, ErrInsecure)
	}
	f, err := openNoFollow(path)
	if err != nil {
		return nil, err
	}
	defer f.Close()
	fi, err := f.Stat()
	if err != nil {
		return nil, err
	}
	if !fi.Mode().IsRegular() || fi.Mode().Perm()&0o077 != 0 || !ownedByUs(fi) {
		return nil, fmt.Errorf("%s (file must be mode 0600 and owned by the Edge user): %w", path, ErrInsecure)
	}
	if fi.Size() > max {
		return nil, fmt.Errorf("%s (too big): %w", path, ErrInvalid)
	}
	b, err := io.ReadAll(io.LimitReader(f, max+1))
	if err != nil {
		return nil, err
	}
	if int64(len(b)) > max {
		return nil, fmt.Errorf("%s (too big): %w", path, ErrInvalid)
	}
	return b, nil
}

// IsNotExist reports a missing file from ReadStateFile.
func IsNotExist(err error) bool { return errors.Is(err, os.ErrNotExist) }

// CheckPrivateDir is the rule for the directory of a credentials file: ours, mode 0700 (no group/other bit).
func CheckPrivateDir(dir string) error { return checkDir(dir) }

// Lock takes the exclusive process lock named by path+".lock" (shared by every process and every handle in this process) and returns its release function. It lets
// other state files of the Edge (managed_olts.json, trust.json) follow the same read-modify-write discipline as the credentials file.
func Lock(path string) (func(), error) { return lockFile(path) }

// RLock takes the SHARED side of the same lock: it is granted while nobody holds the exclusive side (Lock), and an exclusive holder waits until every shared one is released.
// The managed OLTs use it to make a revocation a barrier for the connections that were authorised just before it.
func RLock(path string) (func(), error) { return lockFileShared(path) }
