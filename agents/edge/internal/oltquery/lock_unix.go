//go:build unix

package oltquery

import (
	"os"
	"syscall"
)

// lockFile takes a BLOCKING exclusive advisory lock on path+".lock" (created 0600), held for the whole load-modify-save: any two Store values, in this
// process or another, that share the file are serialised by the kernel (flock locks belong to the open file description, so two opens in one process
// also exclude each other). The returned func releases it.
func lockFile(path string) (func(), error) {
	f, err := os.OpenFile(path+".lock", os.O_CREATE|os.O_RDWR, 0o600)
	if err != nil {
		return nil, err
	}
	if err := syscall.Flock(int(f.Fd()), syscall.LOCK_EX); err != nil {
		f.Close()
		return nil, err
	}
	return func() { _ = syscall.Flock(int(f.Fd()), syscall.LOCK_UN); f.Close() }, nil
}

// syncDir makes a rename durable: the directory entry is flushed too.
func syncDir(dir string) error {
	d, err := os.Open(dir)
	if err != nil {
		return err
	}
	defer d.Close()
	return d.Sync()
}
