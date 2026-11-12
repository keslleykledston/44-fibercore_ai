package oltsecrets

import (
	"errors"
	"os"
	"path/filepath"
	"testing"

	"github.com/keslleykledston/44-fibercore_ai/agents/edge/internal/config"
)

// The applied store is integrity-critical state: a directory others can write in, or a link in place of the file, makes it unreadable (fail closed, nothing written).
func TestAppliedStoreInAnInsecureDirectoryOrBehindALinkFailsClosed(t *testing.T) {
	e := newEnv(t)
	dir := filepath.Dir(e.store.Path)
	if err := os.Chmod(dir, 0o770); err != nil { // writable by the group
		t.Fatal(err)
	}
	e.wantFail(e.build(spec{}), CodeStateUnreadable)
	if e.fileExists(e.credPath) {
		t.Fatal("no credential may be written while the store cannot be trusted")
	}
	if err := os.Chmod(dir, 0o700); err != nil {
		t.Fatal(err)
	}
	real := filepath.Join(dir, "real.json")
	if err := os.WriteFile(real, []byte(`{"v":1,"applied":[],"last":[]}`), 0o600); err != nil {
		t.Fatal(err)
	}
	if err := os.Symlink(real, e.store.Path); err != nil {
		t.Fatal(err)
	}
	e.wantFail(e.build(spec{id: "33333333-3333-4333-8333-333333333398"}), CodeStateUnreadable)
	if e.fileExists(e.credPath) {
		t.Fatal("no credential may be written behind a linked store")
	}
	// writing is refused in an insecure directory too
	_ = os.Remove(e.store.Path)
	_ = os.Chmod(dir, 0o770)
	if err := e.store.Record("33333333-3333-4333-8333-333333333397", tOLT, config.KindSSHLogin, e.exp); !errors.Is(err, ErrStateUnreadable) {
		t.Fatalf("%v", err)
	}
}

func TestAppliedStoreMissingDirectoryIsEmptyAndGetsCreated(t *testing.T) {
	e := newEnv(t)
	e.store.Path = filepath.Join(t.TempDir(), "novo", "applied.json")
	e.wantApplied(e.build(spec{}))
	if fi, err := os.Stat(filepath.Dir(e.store.Path)); err != nil || fi.Mode().Perm() != 0o700 {
		t.Fatalf("%v %v", fi, err)
	}
}
