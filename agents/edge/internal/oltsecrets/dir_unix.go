//go:build unix

package oltsecrets

import (
	"fmt"
	"os"
	"syscall"
)

// checkPrivateDir: the directory exists, is ours and is closed to group and other (ADR-0045: 0700).
func checkPrivateDir(dir string) error {
	fi, err := os.Stat(dir)
	if err != nil {
		return err
	}
	st, ok := fi.Sys().(*syscall.Stat_t)
	if !fi.IsDir() || fi.Mode().Perm()&0o077 != 0 || !ok || int(st.Uid) != os.Geteuid() {
		return fmt.Errorf("%s (directory must be mode 0700 and owned by the Edge user): %w", dir, ErrKeyFile)
	}
	return nil
}
