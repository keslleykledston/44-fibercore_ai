package jobs

import (
	"errors"
	"os"
	"path/filepath"
	"testing"
)

const authA = "11111111-1111-4111-8111-111111111111"

func TestClaimsSingleUseAndPersistent(t *testing.T) {
	p := filepath.Join(t.TempDir(), "claims.json")
	c, err := OpenClaims(p)
	if err != nil {
		t.Fatal(err)
	}
	if err := c.Claim(authA, "job1", "dev-1", 3); err != nil {
		t.Fatal(err)
	}
	if err := c.Claim(authA, "job2", "dev-1", 3); !errors.Is(err, ErrClaimTaken) {
		t.Fatalf("second claim of same authorization must be refused, got %v", err)
	}
	if st, _ := os.Stat(p); st.Mode().Perm() != 0o600 {
		t.Fatalf("mode %v", st.Mode().Perm())
	}
	// restart: claim without result becomes UNKNOWN and is never retried
	c2, err := OpenClaims(p)
	if err != nil {
		t.Fatal(err)
	}
	if got := c2.State(authA); got != ClaimUnknown {
		t.Fatalf("want UNKNOWN after restart, got %q", got)
	}
	if err := c2.Claim(authA, "job1", "dev-1", 3); !errors.Is(err, ErrClaimTaken) {
		t.Fatalf("restart must not allow re-claim, got %v", err)
	}
}

func TestClaimsEpochNeverGoesBack(t *testing.T) {
	c, _ := OpenClaims(filepath.Join(t.TempDir(), "c.json"))
	if err := c.Claim(authA, "j", "dev-1", 5); err != nil {
		t.Fatal(err)
	}
	if err := c.Claim("22222222-2222-4222-8222-222222222222", "j2", "dev-1", 4); !errors.Is(err, ErrStaleEpoch) {
		t.Fatalf("got %v", err)
	}
	if c.MaxEpoch("dev-1") != 5 {
		t.Fatal("epoch memory lost")
	}
}

func TestClaimsFailClosedOnCorruptOrUnwritable(t *testing.T) {
	d := t.TempDir()
	p := filepath.Join(d, "c.json")
	if err := os.WriteFile(p, []byte("{not json"), 0o600); err != nil {
		t.Fatal(err)
	}
	if _, err := OpenClaims(p); !errors.Is(err, ErrClaimStore) {
		t.Fatalf("corrupt store must be refused, got %v", err)
	}
	c, _ := OpenClaims(filepath.Join(d, "ok.json"))
	if err := os.RemoveAll(d); err != nil {
		t.Fatal(err)
	}
	if err := c.Claim(authA, "j", "dev-1", 1); err == nil {
		t.Fatal("claim must fail when the store cannot be written")
	}
	if c.State(authA) != "" || c.MaxEpoch("dev-1") != 0 {
		t.Fatal("a failed claim must leave no trace in memory")
	}
}

func TestClaimsFinish(t *testing.T) {
	p := filepath.Join(t.TempDir(), "c.json")
	c, _ := OpenClaims(p)
	_ = c.Claim(authA, "j", "dev-1", 1)
	if err := c.Finish(authA, ClaimDone); err != nil {
		t.Fatal(err)
	}
	c2, _ := OpenClaims(p)
	if c2.State(authA) != ClaimDone {
		t.Fatalf("got %q", c2.State(authA))
	}
	if err := c.Finish("33333333-3333-4333-8333-333333333333", ClaimDone); err == nil {
		t.Fatal("unknown claim must error")
	}
}
