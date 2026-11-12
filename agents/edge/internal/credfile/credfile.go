// Package credfile is the per-OLT credentials file of ADR-0045 (D3): ONE json file per OLT, written only by this Edge, read at the start of every OLT session.
//
//	{"v":1,"username":"...","password":"...","snmp_community":"..."}   (every field optional)
//
// The file is replaced as a whole (temporary 0600 file in the same directory -> fsync -> rename -> fsync of the directory) under a process lock, so a reader sees
// the old content or the new one, never a partial file. Reading is fail-closed: a file that is loose (group/other bits), not ours, a symlink, too big or not valid
// JSON is an error, never "no file". NOTHING in this package ever puts a secret value in an error: a json decoder error can quote a byte of its input, so decoder
// errors are replaced by fixed ones.
package credfile

import (
	"bytes"
	"crypto/rand"
	"encoding/hex"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"os"
	"path/filepath"
	"strings"
	"unicode/utf8"
)

// Limits of ADR-0045 (counted in Unicode code points; see ValidateField).
const (
	MaxUsername  = 64
	MaxPassword  = 128
	MaxCommunity = 64
	maxFileBytes = 8 << 10
	// FormatVersion is the only version this Edge reads or writes.
	FormatVersion = 1
)

var (
	ErrInsecure = errors.New("credentials file or its directory is not private to this user")
	ErrInvalid  = errors.New("credentials file is not valid")
	ErrField    = errors.New("credential field is not valid")
)

// Creds is the content of the file. The empty string means "not present": an empty value is invalid, so it is never a value.
type Creds struct {
	Username, Password, SNMPCommunity string
}

// Fields on the wire (pointers tell "absent" from "empty", and empty is refused).
type wire struct {
	V             int     `json:"v"`
	Username      *string `json:"username,omitempty"`
	Password      *string `json:"password,omitempty"`
	SNMPCommunity *string `json:"snmp_community,omitempty"`
}

// ValidateField applies ADR-0045: not empty, at most max code points (valid UTF-8), no CR, LF or NUL.
func ValidateField(v string, max int) error {
	if v == "" || !utf8.ValidString(v) || utf8.RuneCountInString(v) > max || strings.ContainsAny(v, "\r\n\x00") {
		return ErrField
	}
	return nil
}

// Validate checks every present field.
func (c Creds) Validate() error {
	for _, f := range []struct {
		v   string
		max int
	}{{c.Username, MaxUsername}, {c.Password, MaxPassword}, {c.SNMPCommunity, MaxCommunity}} {
		if f.v != "" {
			if err := ValidateField(f.v, f.max); err != nil {
				return err
			}
		}
	}
	return nil
}

// checkDir demands the directory of the file to be ours and closed to group/other (ADR-0045: 0700).
func checkDir(dir string) error {
	fi, err := os.Stat(dir)
	if err != nil {
		return err
	}
	if !fi.IsDir() {
		return fmt.Errorf("%s: %w", dir, ErrInsecure)
	}
	if fi.Mode().Perm()&0o077 != 0 || !ownedByUs(fi) {
		return fmt.Errorf("%s (directory must be mode 0700 and owned by the Edge user): %w", dir, ErrInsecure)
	}
	return nil
}

// Read returns the content of the file. found=false (and nil error) only when the file does not exist; every other problem is an error.
func Read(path string) (c Creds, found bool, err error) {
	if !filepath.IsAbs(path) {
		return c, false, fmt.Errorf("%s: path must be absolute: %w", path, ErrInvalid)
	}
	if err := checkDir(filepath.Dir(path)); err != nil {
		return c, false, err
	}
	li, err := os.Lstat(path)
	if errors.Is(err, os.ErrNotExist) {
		return c, false, nil
	}
	if err != nil {
		return c, false, err
	}
	if !li.Mode().IsRegular() { // a symlink or a special file is never followed
		return c, false, fmt.Errorf("%s (not a regular file): %w", path, ErrInsecure)
	}
	f, err := openNoFollow(path)
	if err != nil {
		return c, false, err
	}
	defer f.Close()
	fi, err := f.Stat() // the permissions that count are those of the file we actually hold
	if err != nil {
		return c, false, err
	}
	if !fi.Mode().IsRegular() || fi.Mode().Perm()&0o077 != 0 || !ownedByUs(fi) {
		return c, false, fmt.Errorf("%s (file must be mode 0600 and owned by the Edge user): %w", path, ErrInsecure)
	}
	if fi.Size() > maxFileBytes {
		return c, false, fmt.Errorf("%s (too big): %w", path, ErrInvalid)
	}
	b, err := io.ReadAll(io.LimitReader(f, maxFileBytes+1))
	if err != nil {
		return c, false, err
	}
	defer zero(b)
	c, err = parse(b)
	if err != nil {
		return Creds{}, false, fmt.Errorf("%s: %w", path, err)
	}
	return c, true, nil
}

func parse(b []byte) (Creds, error) {
	var probe map[string]json.RawMessage // an explicit null is neither "absent" nor a value: not a file this Edge wrote
	if json.Unmarshal(b, &probe) != nil {
		return Creds{}, ErrInvalid
	}
	for _, v := range probe {
		if string(bytes.TrimSpace(v)) == "null" {
			return Creds{}, ErrInvalid
		}
	}
	var w wire
	dec := json.NewDecoder(bytes.NewReader(b))
	dec.DisallowUnknownFields()
	if dec.Decode(&w) != nil || dec.More() || w.V != FormatVersion { // never the decoder's text: it can quote the input
		return Creds{}, ErrInvalid
	}
	var c Creds
	for _, f := range []struct {
		src *string
		dst *string
		max int
	}{{w.Username, &c.Username, MaxUsername}, {w.Password, &c.Password, MaxPassword}, {w.SNMPCommunity, &c.SNMPCommunity, MaxCommunity}} {
		if f.src == nil {
			continue
		}
		if ValidateField(*f.src, f.max) != nil { // present but empty or out of the limits: the file is not one this Edge wrote
			return Creds{}, ErrInvalid
		}
		*f.dst = *f.src
	}
	return c, nil
}

// Marshal is the exact byte form that Merge stores.
func Marshal(c Creds) ([]byte, error) {
	if err := c.Validate(); err != nil {
		return nil, err
	}
	w := wire{V: FormatVersion}
	if c.Username != "" {
		w.Username = &c.Username
	}
	if c.Password != "" {
		w.Password = &c.Password
	}
	if c.SNMPCommunity != "" {
		w.SNMPCommunity = &c.SNMPCommunity
	}
	return json.Marshal(w)
}

// Merge replaces, in the file at path, the fields that are set in `set` and keeps the others (read-and-merge). It takes the process lock of the file, so two
// writers never lose each other's update. A file that exists but cannot be read is NOT overwritten (the merge could not keep what is in it).
func Merge(path string, set Creds) error {
	if !filepath.IsAbs(path) {
		return fmt.Errorf("%s: path must be absolute: %w", path, ErrInvalid)
	}
	if err := set.Validate(); err != nil {
		return err
	}
	dir := filepath.Dir(path)
	if err := checkDir(dir); err != nil {
		return err
	}
	unlock, err := lockFile(path)
	if err != nil {
		return err
	}
	defer unlock()
	removeLeftovers(dir)
	cur, _, err := Read(path)
	if err != nil {
		return err
	}
	if set.Username != "" {
		cur.Username = set.Username
	}
	if set.Password != "" {
		cur.Password = set.Password
	}
	if set.SNMPCommunity != "" {
		cur.SNMPCommunity = set.SNMPCommunity
	}
	b, err := Marshal(cur)
	if err != nil {
		return err
	}
	defer zero(b)
	return WriteAtomic(path, b)
}

// tempPrefix marks the temporary files of this package; a leftover from a crash is removed by the next writer.
const tempPrefix = ".fc-tmp-"

// testHook lets a test stop the write at a named stage (nil in production).
var testHook func(stage string) error

func hook(stage string) error {
	if testHook != nil {
		return testHook(stage)
	}
	return nil
}

// WriteAtomic replaces path with data: temporary 0600 file in the same directory -> write -> fsync -> rename -> fsync of the directory. The temporary file is
// created O_EXCL with mode 0600 (never wider, whatever the umask) and removed on every failure path.
func WriteAtomic(path string, data []byte) (err error) {
	dir := filepath.Dir(path)
	var rnd [8]byte
	if _, err := rand.Read(rnd[:]); err != nil {
		return err
	}
	tmp := filepath.Join(dir, tempPrefix+hex.EncodeToString(rnd[:]))
	f, err := os.OpenFile(tmp, os.O_WRONLY|os.O_CREATE|os.O_EXCL, 0o600)
	if err != nil {
		return err
	}
	defer func() {
		if err != nil {
			f.Close()
			os.Remove(tmp)
		}
	}()
	if err = f.Chmod(0o600); err != nil {
		return err
	}
	if _, err = f.Write(data); err != nil {
		return err
	}
	if err = hook("written"); err != nil {
		return err
	}
	if err = f.Sync(); err != nil {
		return err
	}
	if err = f.Close(); err != nil {
		return err
	}
	if err = hook("synced"); err != nil {
		return err
	}
	if err = os.Rename(tmp, path); err != nil {
		return err
	}
	// the rename must survive a power cut: the directory entry is flushed too
	return syncDir(dir)
}

// removeLeftovers deletes temporary files an earlier crash left behind (the caller holds the lock, so none belongs to a live writer).
func removeLeftovers(dir string) {
	ents, err := os.ReadDir(dir)
	if err != nil {
		return
	}
	for _, e := range ents {
		if strings.HasPrefix(e.Name(), tempPrefix) {
			os.Remove(filepath.Join(dir, e.Name()))
		}
	}
}

// RemoveLeftovers is removeLeftovers under the lock of path (for the start of the Edge).
func RemoveLeftovers(path string) {
	if checkDir(filepath.Dir(path)) != nil {
		return
	}
	unlock, err := lockFile(path)
	if err != nil {
		return
	}
	defer unlock()
	removeLeftovers(filepath.Dir(path))
}

func zero(b []byte) {
	for i := range b {
		b[i] = 0
	}
}

// Zero wipes a buffer that held a secret (best effort: Go strings made from it are not wiped).
func Zero(b []byte) { zero(b) }

// CreateExclusive stores data at path ONLY if nothing is there: a complete temporary file (0600, fsynced) is hard-linked to the final name, and link(2) fails with
// os.ErrExist instead of replacing. A concurrent creator therefore cannot overwrite the winner, and nobody sees a partial file. The temporary name is removed either way.
func CreateExclusive(path string, data []byte) (err error) {
	dir := filepath.Dir(path)
	var rnd [8]byte
	if _, err := rand.Read(rnd[:]); err != nil {
		return err
	}
	tmp := filepath.Join(dir, ".fc-new-"+hex.EncodeToString(rnd[:])) // not tempPrefix: a Merge in the same directory must not sweep it away
	f, err := os.OpenFile(tmp, os.O_WRONLY|os.O_CREATE|os.O_EXCL, 0o600)
	if err != nil {
		return err
	}
	defer os.Remove(tmp)
	if err = f.Chmod(0o600); err == nil {
		if _, err = f.Write(data); err == nil {
			err = f.Sync()
		}
	}
	if cerr := f.Close(); err == nil {
		err = cerr
	}
	if err != nil {
		return err
	}
	if err = os.Link(tmp, path); err != nil {
		return err // os.ErrExist when someone else got there first
	}
	return syncDir(dir)
}
