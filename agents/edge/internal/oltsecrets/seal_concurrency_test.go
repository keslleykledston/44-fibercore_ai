package oltsecrets

import (
	"os"
	"path/filepath"
	"strings"
	"sync"
	"testing"
)

// Two (or many) processes starting at once over the same seal_key_file must end with ONE key on disk, and every one of them must hold (and so publish) that key.
func TestConcurrentFirstStartsAgreeOnTheKeyOnDisk(t *testing.T) {
	for round := 0; round < 20; round++ {
		path := filepath.Join(privDir(t), "seal.json")
		const n = 8
		keys := make([]*Key, n)
		created := make([]bool, n)
		errs := make([]error, n)
		var wg sync.WaitGroup
		start := make(chan struct{})
		for i := 0; i < n; i++ {
			wg.Add(1)
			go func(i int) {
				defer wg.Done()
				<-start
				keys[i], created[i], errs[i] = LoadOrCreateKey(path)
			}(i)
		}
		close(start)
		wg.Wait()
		disk, err := LoadKey(path)
		if err != nil {
			t.Fatal(err)
		}
		winners := 0
		for i := 0; i < n; i++ {
			if errs[i] != nil {
				t.Fatalf("round %d #%d: %v", round, i, errs[i])
			}
			if keys[i].KeyID() != disk.KeyID() {
				t.Fatalf("round %d #%d holds %s but the disk has %s: it would publish a key that is not the persisted one", round, i, keys[i].KeyID(), disk.KeyID())
			}
			if created[i] {
				winners++
			}
		}
		if winners != 1 {
			t.Fatalf("round %d: exactly one creator expected, got %d", round, winners)
		}
		ents, _ := os.ReadDir(filepath.Dir(path))
		for _, e := range ents {
			if strings.HasPrefix(e.Name(), ".fc-") {
				t.Fatalf("temporary file left: %s", e.Name())
			}
		}
	}
}
