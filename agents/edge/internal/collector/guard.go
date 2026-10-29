package collector

import (
	"encoding/json"
	"errors"
	"fmt"
	"os"
	"path/filepath"
	"time"
)

// GuardState is what the OLT guard remembers per physical device. It outlives the process: a restart (or a crash loop under
// cron) must not reopen the window that the interval and the failure cooldown are there to keep closed.
type GuardState struct {
	Last      time.Time `json:"last"`       // start of the last attempt (success or failure)
	CoolUntil time.Time `json:"cool_until"` // do not touch the device before this instant
}

// ErrGuardCorrupt: the state file exists but cannot be trusted. The guard then assumes every device was just touched.
var ErrGuardCorrupt = errors.New("olt guard state file is unreadable")

type GuardStore interface {
	Load() (map[string]GuardState, error)
	Save(map[string]GuardState) error
}

// FileGuard keeps the state in one small JSON file (0600), replaced atomically so a crash never leaves a half-written file.
type FileGuard struct{ Path string }

func (f FileGuard) Load() (map[string]GuardState, error) {
	b, err := os.ReadFile(f.Path)
	if errors.Is(err, os.ErrNotExist) {
		return map[string]GuardState{}, nil
	}
	if err != nil {
		return nil, fmt.Errorf("%w: %v", ErrGuardCorrupt, err)
	}
	m := map[string]GuardState{}
	if err := json.Unmarshal(b, &m); err != nil {
		return nil, fmt.Errorf("%w: %v", ErrGuardCorrupt, err)
	}
	return m, nil
}

func (f FileGuard) Save(m map[string]GuardState) error {
	b, err := json.Marshal(m)
	if err != nil {
		return err
	}
	tmp, err := os.CreateTemp(filepath.Dir(f.Path), ".olt-guard-*")
	if err != nil {
		return err
	}
	name := tmp.Name()
	defer os.Remove(name) // no-op after a successful rename
	if err := tmp.Chmod(0o600); err != nil {
		tmp.Close()
		return err
	}
	if _, err := tmp.Write(b); err != nil {
		tmp.Close()
		return err
	}
	if err := tmp.Sync(); err != nil {
		tmp.Close()
		return err
	}
	if err := tmp.Close(); err != nil {
		return err
	}
	return os.Rename(name, f.Path)
}
