package managedolts

import (
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"errors"
	"fmt"
	"os"
	"path/filepath"
	"regexp"
	"sort"
	"strings"
	"time"

	"github.com/keslleykledston/44-fibercore_ai/agents/edge/internal/credfile"
)

// File names inside the state directory.
const (
	RegistryFile = "managed_olts.json"
	TrustFile    = "trust.json"
	RemovedFile  = "removed.json"
	CredsDir     = "creds"
	lockBase     = "managed-state" // the lock file is managed-state.lock
	fileVersion  = 1
	maxFileBytes = 1 << 20
)

// States of a managed OLT as the Edge reports them (ADR-0046 D6).
const (
	StateAwaiting = "awaiting_local_trust"
	StateTrusted  = "trusted"
	StateRemoved  = "removed"
)

var (
	// ErrState: the registry or the trust file exists but cannot be trusted (loose permissions, not ours, a link, not valid). Fail closed: nothing of it is used.
	ErrState = errors.New("managed olts state is unreadable")
	// ErrNotFound: no managed OLT with that name.
	ErrNotFound = errors.New("no managed olt with that name")
	// ErrChanged: the entry is not the one that was shown (it changed between the display and the confirmation).
	ErrChanged = errors.New("the managed olt changed since it was shown")
)

// Store is the registry (managed_olts.json), the trust (trust.json) and the credentials directory (creds/) of the managed OLTs. Writes are atomic (temporary 0600 file
// -> fsync -> rename -> fsync of the directory, the credfile pattern) and serialised by a lock file, so the Edge and `fibercore-edge managed-trust` can run together.
// Reads take no lock: each file is replaced whole, and a registry/trust pair that is mid-change reads as "not trusted", never as trusted.
type Store struct {
	Dir string
	Now func() time.Time
}

func (s *Store) now() time.Time {
	if s.Now != nil {
		return s.Now()
	}
	return time.Now()
}

func (s *Store) registryPath() string { return filepath.Join(s.Dir, RegistryFile) }
func (s *Store) trustPath() string    { return filepath.Join(s.Dir, TrustFile) }
func (s *Store) lockPath() string     { return filepath.Join(s.Dir, lockBase) }

// CredsPath is the credentials file the Edge keeps for the managed OLT of that name (created by credfile.Merge when a credential arrives).
func (s *Store) CredsPath(name string) string {
	return filepath.Join(s.Dir, CredsDir, CredsFileName(name))
}

var simpleName = regexp.MustCompile(`^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$`)

// CredsFileName is <name>.json for an ordinary name; any other name (spaces, accents, path separators, dots first...) cannot reach a path as it is, so it becomes a
// sanitised prefix + "~" + the first 12 hex of its SHA-256 (the "~" cannot be in an ordinary name, so the two forms never collide).
func CredsFileName(name string) string {
	if simpleName.MatchString(name) {
		return name + ".json"
	}
	var b strings.Builder
	for _, r := range name {
		if b.Len() >= 32 {
			break
		}
		switch {
		case r >= 'a' && r <= 'z', r >= 'A' && r <= 'Z', r >= '0' && r <= '9':
			b.WriteRune(r)
		case b.Len() > 0 && (r == '.' || r == '_' || r == '-'):
			b.WriteRune(r)
		default:
			b.WriteByte('_')
		}
	}
	sum := sha256.Sum256([]byte(name))
	return b.String() + "~" + hex.EncodeToString(sum[:])[:12] + ".json"
}

// Init prepares the state directory: created 0700 when missing (an existing one is checked, never loosened), the credentials directory likewise, and the temporary files
// of a crashed write are removed. Anything loose is an error (the caller refuses to start, like for the seal key).
func (s *Store) Init() error {
	if !filepath.IsAbs(s.Dir) {
		return fmt.Errorf("%w: state_dir must be absolute", ErrState)
	}
	if err := os.MkdirAll(s.Dir, 0o700); err != nil {
		return fmt.Errorf("%w: %v", ErrState, err)
	}
	if err := credfile.CheckPrivateDir(s.Dir); err != nil {
		return fmt.Errorf("%w: %v", ErrState, err)
	}
	if err := s.EnsureCredsDir(); err != nil {
		return err
	}
	credfile.RemoveLeftovers(s.lockPath())
	return nil
}

// EnsureCredsDir makes sure creds/ exists (0700, ours).
func (s *Store) EnsureCredsDir() error {
	d := filepath.Join(s.Dir, CredsDir)
	if err := credfile.CheckPrivateDir(s.Dir); err != nil {
		return fmt.Errorf("%w: %v", ErrState, err)
	}
	if err := os.MkdirAll(d, 0o700); err != nil {
		return fmt.Errorf("%w: %v", ErrState, err)
	}
	if err := credfile.CheckPrivateDir(d); err != nil {
		return fmt.Errorf("%w: %v", ErrState, err)
	}
	return nil
}

type registryFile struct {
	V    int     `json:"v"`
	OLTs []Entry `json:"olts"`
}

type trustEntry struct {
	Name   string `json:"name"`
	Digest string `json:"digest"`
	At     int64  `json:"at"`
}

type trustFile struct {
	V       int          `json:"v"`
	Trusted []trustEntry `json:"trusted"`
}

var digestRe = regexp.MustCompile(`^[0-9a-f]{64}$`)

func (s *Store) readState(path string, into any) (found bool, err error) {
	if err := credfile.CheckPrivateDir(s.Dir); err != nil {
		if errors.Is(err, os.ErrNotExist) {
			return false, nil
		}
		return false, fmt.Errorf("%w: %v", ErrState, err)
	}
	b, err := credfile.ReadStateFile(path, maxFileBytes)
	if credfile.IsNotExist(err) {
		return false, nil
	}
	if err != nil {
		return false, fmt.Errorf("%w: %v", ErrState, err)
	}
	dec := json.NewDecoder(strings.NewReader(string(b)))
	dec.DisallowUnknownFields()
	if dec.Decode(into) != nil || dec.More() { // never the decoder's text
		return false, fmt.Errorf("%w: %s is not valid", ErrState, filepath.Base(path))
	}
	return true, nil
}

func (s *Store) readRegistry() ([]Entry, error) {
	var f registryFile
	found, err := s.readState(s.registryPath(), &f)
	if err != nil || !found {
		return nil, err
	}
	if f.V != fileVersion || len(f.OLTs) > MaxOLTs {
		return nil, fmt.Errorf("%w: %s has an unknown version or too many entries", ErrState, RegistryFile)
	}
	seen := map[string]bool{}
	for _, e := range f.OLTs {
		if e.Validate() != nil || seen[e.Name] {
			return nil, fmt.Errorf("%w: %s has an invalid or repeated entry", ErrState, RegistryFile)
		}
		seen[e.Name] = true
	}
	return f.OLTs, nil
}

func (s *Store) readTrust() (map[string]trustEntry, error) {
	var f trustFile
	found, err := s.readState(s.trustPath(), &f)
	if err != nil || !found {
		return map[string]trustEntry{}, err
	}
	if f.V != fileVersion {
		return nil, fmt.Errorf("%w: %s has an unknown version", ErrState, TrustFile)
	}
	m := map[string]trustEntry{}
	for _, t := range f.Trusted {
		if t.Name == "" || !digestRe.MatchString(t.Digest) {
			return nil, fmt.Errorf("%w: %s has an invalid entry", ErrState, TrustFile)
		}
		m[t.Name] = t
	}
	return m, nil
}

func (s *Store) writeRegistry(list []Entry) error {
	sort.Slice(list, func(i, j int) bool { return list[i].Name < list[j].Name })
	if list == nil {
		list = []Entry{}
	}
	b, err := json.Marshal(registryFile{V: fileVersion, OLTs: list})
	if err != nil {
		return err
	}
	return credfile.WriteAtomic(s.registryPath(), b)
}

func (s *Store) writeTrust(m map[string]trustEntry) error {
	l := make([]trustEntry, 0, len(m))
	for _, t := range m {
		l = append(l, t)
	}
	sort.Slice(l, func(i, j int) bool { return l[i].Name < l[j].Name })
	b, err := json.Marshal(trustFile{V: fileVersion, Trusted: l})
	if err != nil {
		return err
	}
	return credfile.WriteAtomic(s.trustPath(), b)
}

// Item is one managed OLT with its state.
type Item struct {
	Entry   Entry
	Trusted bool
}

// State is "trusted" or "awaiting_local_trust".
func (i Item) State() string {
	if i.Trusted {
		return StateTrusted
	}
	return StateAwaiting
}

// List returns every managed OLT of the registry, sorted by name, with its trust state. An OLT is trusted ONLY when trust.json holds the digest of exactly its present
// connection fields.
func (s *Store) List() ([]Item, error) {
	reg, err := s.readRegistry()
	if err != nil {
		return nil, err
	}
	tr, err := s.readTrust()
	if err != nil {
		return nil, err
	}
	out := make([]Item, 0, len(reg))
	for _, e := range reg {
		t, ok := tr[e.Name]
		out = append(out, Item{Entry: e, Trusted: ok && t.Digest == e.Digest()})
	}
	sort.Slice(out, func(i, j int) bool { return out[i].Entry.Name < out[j].Entry.Name })
	return out, nil
}

// Get returns one managed OLT; found=false when the registry has none with that name.
func (s *Store) Get(name string) (Item, bool, error) {
	l, err := s.List()
	if err != nil {
		return Item{}, false, err
	}
	for _, it := range l {
		if it.Entry.Name == name {
			return it, true, nil
		}
	}
	return Item{}, false, nil
}

// UpsertResult says what an Upsert changed.
type UpsertResult struct {
	Created      bool // the name was not in the registry
	Changed      bool // the registry file was rewritten
	TrustCleared bool // a trust entry that no longer matched was dropped
}

// Upsert stores the entry (a set of the same content is a no-op) and DROPS the local trust whenever the trusted digest is not the digest of this entry: any change of a
// connection field (address, port, protocol, transport, host key, snmp_port, ssh_mode, legacy_ssh) sends the OLT back to awaiting_local_trust, and going back to an
// earlier value does not bring the trust back. A brand new name starts with an empty credentials file (nothing left from an earlier OLT of that name is ever reused).
func (s *Store) Upsert(e Entry) (UpsertResult, error) {
	var res UpsertResult
	if err := e.Validate(); err != nil {
		return res, err
	}
	if err := credfile.CheckPrivateDir(s.Dir); err != nil {
		return res, fmt.Errorf("%w: %v", ErrState, err)
	}
	unlock, err := credfile.Lock(s.lockPath())
	if err != nil {
		return res, err
	}
	defer unlock()
	reg, err := s.readRegistry()
	if err != nil {
		return res, err
	}
	tr, err := s.readTrust()
	if err != nil {
		return res, err
	}
	idx := -1
	for i := range reg {
		if reg[i].Name == e.Name {
			idx = i
		}
	}
	switch {
	case idx < 0:
		res.Created = true
		if len(reg) >= MaxOLTs {
			return res, fmt.Errorf("%w: the registry is full", ErrState)
		}
		if err := s.removeCreds(e.Name); err != nil {
			return res, err
		}
		reg = append(reg, e)
		res.Changed = true
	case reg[idx] != e:
		reg[idx] = e
		res.Changed = true
	}
	if res.Changed {
		if err := s.writeRegistry(reg); err != nil {
			return res, err
		}
	}
	if t, ok := tr[e.Name]; ok && t.Digest != e.Digest() {
		delete(tr, e.Name)
		if err := s.writeTrust(tr); err != nil {
			return res, err
		}
		res.TrustCleared = true
	}
	return res, nil
}

// Remove deletes the registry entry, its trust and its credentials file. It is idempotent (a name that is not there is not an error) and always attempts all of it, so a
// redelivery after a crash finishes what the first attempt did not. BEFORE anything is deleted it records a durable tombstone (removed.json) for the Cloud id of the entry
// that is being deleted, so the "removed" state is still reported after a restart; the reporter clears it once the Cloud has it. A tombstone is NEVER dropped to make
// room: when ErrTooManyRemovals pending ones exist, the removal is refused before anything is written or deleted. It returns the Cloud id of the entry that was there
// ("" when none; a name that was never there leaves no tombstone: there is nothing the Cloud could still believe about it).
func (s *Store) Remove(name string) (cloudID string, err error) {
	if err := credfile.CheckPrivateDir(s.Dir); err != nil {
		if errors.Is(err, os.ErrNotExist) {
			return "", nil
		}
		return "", fmt.Errorf("%w: %v", ErrState, err)
	}
	unlock, err := credfile.Lock(s.lockPath())
	if err != nil {
		return "", err
	}
	defer unlock()
	reg, err := s.readRegistry()
	if err != nil {
		return "", err
	}
	tr, err := s.readTrust()
	if err != nil {
		return "", err
	}
	tomb, err := s.readTombstones()
	if err != nil {
		return "", err
	}
	kept := reg[:0:0]
	for _, e := range reg {
		if e.Name == name {
			cloudID = e.CloudID
			continue
		}
		kept = append(kept, e)
	}
	if cloudID != "" { // first the tombstone: a fall after this line and before the next ones is finished by the redelivery
		grown, err := addTombstone(tomb, cloudID, s.now().Unix())
		if err != nil {
			return cloudID, err
		}
		if err := s.writeTombstones(grown); err != nil {
			return cloudID, err
		}
	}
	if len(kept) != len(reg) {
		if err := s.writeRegistry(kept); err != nil {
			return cloudID, err
		}
	}
	if _, ok := tr[name]; ok {
		delete(tr, name)
		if err := s.writeTrust(tr); err != nil {
			return cloudID, err
		}
	}
	return cloudID, s.removeCreds(name)
}

// MaxTombstones bounds removed.json. It is a ceiling for a Cloud that has not accepted any report for a very long time, not a retention policy: nothing is ever evicted to
// make room (a removal that would exceed it is refused with ErrTooManyRemovals, before anything is deleted).
const MaxTombstones = 4096

// tombstoneCap is MaxTombstones (a variable only so a test can lower it).
var tombstoneCap = MaxTombstones

// ErrTooManyRemovals: too many removals are waiting to be reported to the Cloud.
var ErrTooManyRemovals = errors.New("too many removals are waiting to be reported to the Cloud")

type tombstone struct {
	CloudID string `json:"cloud_id"`
	At      int64  `json:"at"`
}

type tombstoneFile struct {
	V       int         `json:"v"`
	Removed []tombstone `json:"removed"`
}

func addTombstone(l []tombstone, id string, at int64) ([]tombstone, error) {
	for _, t := range l {
		if t.CloudID == id {
			return l, nil
		}
	}
	if len(l) >= tombstoneCap {
		return l, ErrTooManyRemovals
	}
	return append(l, tombstone{CloudID: id, At: at}), nil
}

func (s *Store) readTombstones() ([]tombstone, error) {
	var f tombstoneFile
	found, err := s.readState(filepath.Join(s.Dir, RemovedFile), &f)
	if err != nil || !found {
		return nil, err
	}
	if f.V != fileVersion || len(f.Removed) > MaxTombstones {
		return nil, fmt.Errorf("%w: %s has an unknown version or too many entries", ErrState, RemovedFile)
	}
	for _, t := range f.Removed {
		if !ValidCloudID(t.CloudID) {
			return nil, fmt.Errorf("%w: %s has an invalid entry", ErrState, RemovedFile)
		}
	}
	return f.Removed, nil
}

func (s *Store) writeTombstones(l []tombstone) error {
	if l == nil {
		l = []tombstone{}
	}
	b, err := json.Marshal(tombstoneFile{V: fileVersion, Removed: l})
	if err != nil {
		return err
	}
	return credfile.WriteAtomic(filepath.Join(s.Dir, RemovedFile), b)
}

// Tombstones lists the Cloud ids of the OLTs that were deleted and whose "removed" state the Cloud has not been told yet (durable: it survives a restart).
func (s *Store) Tombstones() ([]string, error) {
	l, err := s.readTombstones()
	if err != nil {
		return nil, err
	}
	out := make([]string, 0, len(l))
	for _, t := range l {
		out = append(out, t.CloudID)
	}
	sort.Strings(out)
	return out, nil
}

// ClearTombstones drops the tombstones of these Cloud ids (the Cloud has been told, or the OLT came back).
func (s *Store) ClearTombstones(ids []string) error {
	if len(ids) == 0 {
		return nil
	}
	if err := credfile.CheckPrivateDir(s.Dir); err != nil {
		return fmt.Errorf("%w: %v", ErrState, err)
	}
	unlock, err := credfile.Lock(s.lockPath())
	if err != nil {
		return err
	}
	defer unlock()
	l, err := s.readTombstones()
	if err != nil {
		return err
	}
	drop := map[string]bool{}
	for _, id := range ids {
		drop[id] = true
	}
	kept := l[:0:0]
	for _, t := range l {
		if !drop[t.CloudID] {
			kept = append(kept, t)
		}
	}
	if len(kept) == len(l) {
		return nil
	}
	return s.writeTombstones(kept)
}

// removeCreds deletes the credentials file of a name and its lock file (missing files are fine).
func (s *Store) removeCreds(name string) error {
	p := s.CredsPath(name)
	for _, f := range []string{p, p + ".lock"} {
		if err := os.Remove(f); err != nil && !errors.Is(err, os.ErrNotExist) {
			return err
		}
	}
	return nil
}

// Trust records the local trust of the entry that was SHOWN to the operator: it only succeeds when the entry still has that digest (the Cloud may have changed it
// meanwhile), so what is trusted is exactly what was displayed and confirmed.
func (s *Store) Trust(name, digest string) error {
	if err := credfile.CheckPrivateDir(s.Dir); err != nil {
		return fmt.Errorf("%w: %v", ErrState, err)
	}
	unlock, err := credfile.Lock(s.lockPath())
	if err != nil {
		return err
	}
	defer unlock()
	reg, err := s.readRegistry()
	if err != nil {
		return err
	}
	var cur *Entry
	for i := range reg {
		if reg[i].Name == name {
			cur = &reg[i]
		}
	}
	if cur == nil {
		return ErrNotFound
	}
	if cur.Digest() != digest {
		return ErrChanged
	}
	tr, err := s.readTrust()
	if err != nil {
		return err
	}
	tr[name] = trustEntry{Name: name, Digest: digest, At: s.now().Unix()}
	return s.writeTrust(tr)
}
