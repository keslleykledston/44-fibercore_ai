//go:build unix

package singleton

import (
	"errors"
	"os"
	"path/filepath"
	"testing"
)

func TestSecondProcessCannotTakeTheLockUntilTheFirstReleasesIt(t *testing.T) {
	path := filepath.Join(t.TempDir(), "edge.lock")
	first, err := Acquire(path)
	if err != nil {
		t.Fatal(err)
	}
	if _, err := Acquire(path); !errors.Is(err, ErrHeld) {
		t.Fatalf("second holder must be refused: %v", err)
	}
	first.Close() // process exit / crash
	again, err := Acquire(path)
	if err != nil {
		t.Fatalf("lock must be free after the first holder is gone: %v", err)
	}
	again.Close()
	if fi, _ := os.Stat(path); fi.Mode().Perm() != 0o600 {
		t.Fatalf("lock file mode %v", fi.Mode().Perm())
	}
}
