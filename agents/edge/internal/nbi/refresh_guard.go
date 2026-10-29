package nbi

import (
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"errors"
	"fmt"
	"os"
	"path/filepath"
	"sync"
	"time"
)

var (
	ErrRefreshTooSoon   = errors.New("nbi refresh: this device was refreshed too recently")
	ErrRefreshBudget    = errors.New("nbi refresh: hourly refresh budget exhausted")
	ErrRefreshNoReserve = errors.New("nbi refresh: could not persist the reservation; refusing")
)

// RefreshGuard paces the active reads: at most one per device per MinPerDevice and MaxPerHour in total (all devices). The reservation is
// written to disk BEFORE anything is sent, so a crash or restart cannot reopen the window, and a failed write means no request at all.
// A corrupt or unreadable state file is treated as "budget just spent": it blocks for an hour instead of guessing.
type RefreshGuard struct {
	Path         string
	MinPerDevice time.Duration
	MaxPerHour   int
	Now          func() time.Time

	mu sync.Mutex
}

type refreshState struct {
	Devices map[string]int64 `json:"devices"` // sha256(device id) -> unix seconds of the last reservation
	Recent  []int64          `json:"recent"`  // unix seconds of reservations in the last hour
}

func (g *RefreshGuard) now() time.Time {
	if g.Now != nil {
		return g.Now()
	}
	return time.Now()
}

func (g *RefreshGuard) load(now time.Time) refreshState {
	b, err := os.ReadFile(g.Path)
	if errors.Is(err, os.ErrNotExist) {
		return refreshState{Devices: map[string]int64{}}
	}
	var st refreshState
	if err != nil || json.Unmarshal(b, &st) != nil || st.Devices == nil {
		st = refreshState{Devices: map[string]int64{}}
		for i := 0; i < g.MaxPerHour; i++ {
			st.Recent = append(st.Recent, now.Unix())
		}
	}
	return st
}

// Reserve admits (and records) one refresh of deviceID, or says why not.
func (g *RefreshGuard) Reserve(deviceID string) error {
	g.mu.Lock()
	defer g.mu.Unlock()
	if g.Path == "" || g.MinPerDevice <= 0 || g.MaxPerHour <= 0 {
		return ErrRefreshNoReserve
	}
	now := g.now()
	st := g.load(now)
	nowS := now.Unix()
	recent := st.Recent[:0:0]
	for _, t := range st.Recent {
		if t > nowS-3600 && t <= nowS+60 { // entries from the future (clock jump) are dropped, never trusted to block forever or to free
			recent = append(recent, t)
		}
	}
	sum := sha256.Sum256([]byte(deviceID))
	key := hex.EncodeToString(sum[:])
	if last, ok := st.Devices[key]; ok && nowS-last < int64(g.MinPerDevice.Seconds()) && last <= nowS+60 {
		return ErrRefreshTooSoon
	}
	if len(recent) >= g.MaxPerHour {
		return ErrRefreshBudget
	}
	for k, t := range st.Devices { // forget devices outside any window so the file stays small
		if nowS-t > 24*3600 {
			delete(st.Devices, k)
		}
	}
	st.Devices[key] = nowS
	st.Recent = append(recent, nowS)
	if err := g.save(st); err != nil {
		return fmt.Errorf("%w: %v", ErrRefreshNoReserve, err)
	}
	return nil
}

func (g *RefreshGuard) save(st refreshState) error {
	b, err := json.Marshal(st)
	if err != nil {
		return err
	}
	tmp, err := os.CreateTemp(filepath.Dir(g.Path), ".refresh-guard-*")
	if err != nil {
		return err
	}
	defer os.Remove(tmp.Name())
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
	return os.Rename(tmp.Name(), g.Path)
}
