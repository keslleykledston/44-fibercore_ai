package credfile

import (
	"errors"
	"fmt"
	"os"
	"path/filepath"
	"strings"
	"sync"
	"testing"
)

func privDir(t *testing.T) string {
	t.Helper()
	d := filepath.Join(t.TempDir(), "d")
	if err := os.Mkdir(d, 0o700); err != nil {
		t.Fatal(err)
	}
	return d
}

func put(t *testing.T, path, body string, mode os.FileMode) {
	t.Helper()
	if err := os.WriteFile(path, []byte(body), mode); err != nil {
		t.Fatal(err)
	}
	if err := os.Chmod(path, mode); err != nil {
		t.Fatal(err)
	}
}

func TestReadMissingIsNotAnError(t *testing.T) {
	c, found, err := Read(filepath.Join(privDir(t), "x.json"))
	if err != nil || found || c != (Creds{}) {
		t.Fatalf("%+v %v %v", c, found, err)
	}
}

func TestReadRefusesEverythingThatIsNotPrivateAndValid(t *testing.T) {
	dir := privDir(t)
	p := filepath.Join(dir, "c.json")
	good := `{"v":1,"username":"u","password":"p"}`
	cases := map[string]func(){
		"file 0640": func() { put(t, p, good, 0o640) },
		"file 0604": func() { put(t, p, good, 0o604) },
		"symlink": func() {
			put(t, filepath.Join(dir, "real"), good, 0o600)
			if err := os.Symlink(filepath.Join(dir, "real"), p); err != nil {
				t.Fatal(err)
			}
		},
		"directory as file": func() { _ = os.Mkdir(p, 0o700) },
		"bad json":          func() { put(t, p, `{"v":1,"password":"SEGREDO`, 0o600) },
		"wrong version":     func() { put(t, p, `{"v":2,"username":"u"}`, 0o600) },
		"no version":        func() { put(t, p, `{"username":"u"}`, 0o600) },
		"unknown field":     func() { put(t, p, `{"v":1,"username":"u","x":1}`, 0o600) },
		"empty value":       func() { put(t, p, `{"v":1,"username":""}`, 0o600) },
		"null value":        func() { put(t, p, `{"v":1,"username":null,"password":"x"}`, 0o600) },
		"newline in value":  func() { put(t, p, `{"v":1,"username":"a\nb"}`, 0o600) },
		"too long":          func() { put(t, p, `{"v":1,"password":"`+strings.Repeat("x", 129)+`"}`, 0o600) },
		"trailing data":     func() { put(t, p, good+`{}`, 0o600) },
		"empty file":        func() { put(t, p, ``, 0o600) },
		"huge":              func() { put(t, p, strings.Repeat(" ", maxFileBytes+10), 0o600) },
	}
	for name, mk := range cases {
		_ = os.RemoveAll(p)
		mk()
		if _, found, err := Read(p); err == nil || found {
			t.Errorf("%s: must be an error (fail closed), got found=%v err=%v", name, found, err)
		}
	}
	// the same file in a loose directory
	_ = os.RemoveAll(p)
	put(t, p, good, 0o600)
	if err := os.Chmod(dir, 0o750); err != nil {
		t.Fatal(err)
	}
	if _, _, err := Read(p); err == nil {
		t.Error("a directory open to the group must be refused")
	}
	_ = os.Chmod(dir, 0o700)
	if c, found, err := Read(p); err != nil || !found || c.Username != "u" || c.Password != "p" {
		t.Fatalf("%+v %v %v", c, found, err)
	}
	// relative paths are refused (a cwd surprise)
	if _, _, err := Read("c.json"); err == nil {
		t.Error("relative path")
	}
}

func TestErrorsNeverCarryTheSecret(t *testing.T) {
	dir := privDir(t)
	p := filepath.Join(dir, "c.json")
	secret := "SEGREDO-NAO-VAZAR"
	for _, body := range []string{
		`{"v":1,"password":"` + secret,                  // truncated: the json error would quote bytes
		`{"v":1,"password":"` + secret + `","x":1}`,     // unknown field
		`{"v":1,"password":"` + secret + "\n" + `"}`,    // forbidden char
		`{"v":1,"password":"` + secret + `"} ` + secret, // trailing data
		`{"v":1,"password":` + secret + `}`,             // not a string
		`{"v":"` + secret + `","password":"` + secret + `"}`,
	} {
		put(t, p, body, 0o600)
		_, _, err := Read(p)
		if err == nil || strings.Contains(err.Error(), secret) {
			t.Fatalf("error must exist and be free of the secret: %v", err)
		}
		if err := Merge(p, Creds{Username: "novo"}); err == nil || strings.Contains(err.Error(), secret) {
			t.Fatalf("merge: error must exist and be free of the secret: %v", err)
		}
		if b, _ := os.ReadFile(p); string(b) != body {
			t.Fatal("a file that cannot be merged must stay untouched")
		}
	}
}

func TestMergeKeepsWhatIsNotReplaced(t *testing.T) {
	p := filepath.Join(privDir(t), "c.json")
	if err := Merge(p, Creds{Username: "u1", Password: "p1"}); err != nil {
		t.Fatal(err)
	}
	if err := Merge(p, Creds{SNMPCommunity: "c1"}); err != nil {
		t.Fatal(err)
	}
	c, _, _ := Read(p)
	if c != (Creds{"u1", "p1", "c1"}) {
		t.Fatalf("%+v", c)
	}
	if err := Merge(p, Creds{Username: "u2", Password: "p2"}); err != nil {
		t.Fatal(err)
	}
	c, _, _ = Read(p)
	if c != (Creds{"u2", "p2", "c1"}) {
		t.Fatalf("%+v", c)
	}
	if err := Merge(p, Creds{Password: "a\nb"}); !errors.Is(err, ErrField) {
		t.Fatalf("invalid values are refused before any write: %v", err)
	}
}

// A failure at ANY point of the replacement leaves the old file exactly as it was and no temporary file around: there is never a partial credentials file.
func TestWriteIsAtomicWhateverStageFails(t *testing.T) {
	p := filepath.Join(privDir(t), "c.json")
	if err := Merge(p, Creds{Username: "antigo", Password: "antigo-pw"}); err != nil {
		t.Fatal(err)
	}
	before, _ := os.ReadFile(p)
	for _, stage := range []string{"written", "synced"} {
		testHook = func(s string) error {
			if s == stage {
				return errors.New("boom")
			}
			return nil
		}
		if err := Merge(p, Creds{Username: "novo", Password: "novo-pw"}); err == nil {
			t.Fatalf("%s: the failure must surface", stage)
		}
		testHook = nil
		after, _ := os.ReadFile(p)
		if string(after) != string(before) {
			t.Fatalf("%s: the old file changed: %s", stage, after)
		}
		ents, _ := os.ReadDir(filepath.Dir(p))
		for _, e := range ents {
			if strings.HasPrefix(e.Name(), tempPrefix) {
				t.Fatalf("%s: temporary file left: %s", stage, e.Name())
			}
		}
	}
	if err := Merge(p, Creds{Username: "novo", Password: "novo-pw"}); err != nil {
		t.Fatal(err)
	}
}

// A crash (not a returned error) leaves the temporary file: the old content still stands and the next writer cleans it.
func TestACrashedWriterLeavesTheOldFileAndTheNextWriterCleans(t *testing.T) {
	dir := privDir(t)
	p := filepath.Join(dir, "c.json")
	_ = Merge(p, Creds{Username: "antigo", Password: "antigo-pw"})
	left := filepath.Join(dir, tempPrefix+"cafebabe")
	put(t, left, `{"v":1,"password":"meio-escrito`, 0o600)
	if c, _, err := Read(p); err != nil || c.Username != "antigo" {
		t.Fatalf("the old content must still be what readers see: %+v %v", c, err)
	}
	RemoveLeftovers(p)
	if _, err := os.Lstat(left); err == nil {
		t.Fatal("leftover not removed")
	}
}

// Readers running while writers replace the file only ever see a complete, valid file (old or new), never an error or a partial one.
func TestReadersNeverSeeAPartialFileWhileWritersReplaceIt(t *testing.T) {
	p := filepath.Join(privDir(t), "c.json")
	if err := Merge(p, Creds{Username: "u0", Password: "p0"}); err != nil {
		t.Fatal(err)
	}
	stop := make(chan struct{})
	var wg sync.WaitGroup
	var bad error
	var mu sync.Mutex
	for r := 0; r < 4; r++ {
		wg.Add(1)
		go func() {
			defer wg.Done()
			for {
				select {
				case <-stop:
					return
				default:
				}
				c, found, err := Read(p)
				if err != nil || !found || c.Username == "" || c.Password == "" || c.Username[1:] != c.Password[1:] {
					mu.Lock()
					bad = fmt.Errorf("reader saw %+v found=%v err=%v", c, found, err)
					mu.Unlock()
					return
				}
			}
		}()
	}
	var ww sync.WaitGroup
	for w := 0; w < 3; w++ {
		ww.Add(1)
		go func(w int) {
			defer ww.Done()
			for i := 0; i < 25; i++ {
				n := fmt.Sprintf("%d%d", w, i)
				if err := Merge(p, Creds{Username: "u" + n, Password: "p" + n}); err != nil {
					mu.Lock()
					bad = err
					mu.Unlock()
					return
				}
			}
		}(w)
	}
	ww.Wait()
	close(stop)
	wg.Wait()
	if bad != nil {
		t.Fatal(bad)
	}
}

// Two writers of DIFFERENT fields never lose each other's update (read-and-merge under the lock).
func TestConcurrentMergesOfDifferentFieldsAreBothKept(t *testing.T) {
	p := filepath.Join(privDir(t), "c.json")
	var wg sync.WaitGroup
	for i := 0; i < 20; i++ {
		wg.Add(2)
		go func(i int) {
			defer wg.Done()
			_ = Merge(p, Creds{Username: fmt.Sprintf("u%d", i), Password: fmt.Sprintf("p%d", i)})
		}(i)
		go func(i int) { defer wg.Done(); _ = Merge(p, Creds{SNMPCommunity: fmt.Sprintf("c%d", i)}) }(i)
	}
	wg.Wait()
	c, _, err := Read(p)
	if err != nil || c.Username == "" || c.Password == "" || c.SNMPCommunity == "" || c.Username[1:] != c.Password[1:] {
		t.Fatalf("%+v %v", c, err)
	}
}

func TestFileAndLockAreCreated0600UnderAnyUmask(t *testing.T) {
	old := setUmask(0)
	defer setUmask(old)
	p := filepath.Join(privDir(t), "c.json")
	if err := Merge(p, Creds{Username: "u", Password: "p"}); err != nil {
		t.Fatal(err)
	}
	for _, f := range []string{p, p + ".lock"} {
		if fi, err := os.Stat(f); err != nil || fi.Mode().Perm() != 0o600 {
			t.Fatalf("%s: %v %v", f, fi, err)
		}
	}
}

func TestMergeRefusesALooseDirectory(t *testing.T) {
	dir := privDir(t)
	if err := os.Chmod(dir, 0o755); err != nil {
		t.Fatal(err)
	}
	if err := Merge(filepath.Join(dir, "c.json"), Creds{Username: "u", Password: "p"}); err == nil {
		t.Fatal("a loose directory must be refused")
	}
}
