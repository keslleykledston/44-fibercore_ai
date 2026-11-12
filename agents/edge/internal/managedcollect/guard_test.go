package managedcollect

import (
	"context"
	"errors"
	"path/filepath"
	"testing"
	"time"

	"github.com/keslleykledston/44-fibercore_ai/agents/edge/internal/credfile"
	"github.com/keslleykledston/44-fibercore_ai/agents/edge/internal/olt"
)

type countingSession struct{ ran []string }

func (c *countingSession) Run(_ context.Context, cmd string) (string, error) {
	c.ran = append(c.ran, cmd)
	return "ok", nil
}

type shellLike struct{ countingSession }

func (*shellLike) EndProven() bool { return false } // an interactive shell cannot prove where a command ends

func TestNoCommandIsSentAfterARevocation(t *testing.T) {
	f := newFx(t, nil)
	f.add(f.entry("OLT-A", "10.20.1.5"))
	f.creds("OLT-A")
	f.trust("OLT-A")
	inner := &countingSession{}
	f.b.OpenSSH = func(_ context.Context, _ olt.SSHConfig) (olt.Session, func(), error) { return inner, func() {}, nil }
	src := f.b.Sources()
	sess, closeFn, err := src[0].Open(context.Background())
	if err != nil {
		t.Fatal(err)
	}
	defer closeFn()
	if out, err := sess.Run(context.Background(), "display version"); err != nil || out != "ok" {
		t.Fatalf("%q %v", out, err)
	}
	f.remove("OLT-A")
	if _, err := sess.Run(context.Background(), "display version"); !errors.Is(err, ErrNotTrusted) {
		t.Fatalf("a command after a revocation: %v", err)
	}
	if len(inner.ran) != 1 {
		t.Fatalf("the OLT saw %v", inner.ran)
	}
}

func TestTheGuardedSessionStillSaysWhetherTheTransportProvesTheEndOfACommand(t *testing.T) {
	f := newFx(t, nil)
	f.add(f.entry("OLT-A", "10.20.1.5"))
	f.creds("OLT-A")
	f.trust("OLT-A")
	f.b.OpenSSH = func(_ context.Context, _ olt.SSHConfig) (olt.Session, func(), error) {
		return &shellLike{}, func() {}, nil
	}
	sess, _, err := f.b.Sources()[0].Open(context.Background())
	if err != nil {
		t.Fatal(err)
	}
	if olt.EndProven(sess) {
		t.Fatal("a shell transport must still not be able to prove a PON complete through the wrapper")
	}
	f.b.OpenSSH = func(_ context.Context, _ olt.SSHConfig) (olt.Session, func(), error) {
		return &countingSession{}, func() {}, nil
	}
	sess, _, _ = f.b.Sources()[0].Open(context.Background())
	if !olt.EndProven(sess) {
		t.Fatal("an exec transport proves it")
	}
}

type fakeReader struct{ calls int }

func (r *fakeReader) Get(context.Context, []string) (map[string]olt.SNMPValue, error) {
	r.calls++
	return nil, nil
}
func (r *fakeReader) Walk(context.Context, string, int) ([]olt.SNMPRow, error) {
	r.calls++
	return nil, nil
}

func TestNoSNMPRequestStartsAfterARevocation(t *testing.T) {
	f := newFx(t, nil)
	e := f.entry("OLT-S", "10.20.1.6")
	e.Transport = "snmp"
	f.add(e)
	f.creds("OLT-S")
	f.trust("OLT-S")
	rd := &fakeReader{}
	f.b.OpenSNMP = func(_ context.Context, _ olt.SNMPConfig) (olt.SNMPReader, func(), error) { return rd, func() {}, nil }
	r, closeFn, err := f.b.Sources()[0].OpenSNMP(context.Background())
	if err != nil {
		t.Fatal(err)
	}
	defer closeFn()
	if _, err := r.Get(context.Background(), []string{"1"}); err != nil {
		t.Fatal(err)
	}
	f.remove("OLT-S")
	if _, err := r.Get(context.Background(), []string{"1"}); !errors.Is(err, ErrNotTrusted) {
		t.Fatalf("%v", err)
	}
	if _, err := r.Walk(context.Background(), "1", 10); !errors.Is(err, ErrNotTrusted) {
		t.Fatalf("%v", err)
	}
	if rd.calls != 1 {
		t.Fatalf("the agent saw %d requests", rd.calls)
	}
}

func TestTheDialAndTheSNMPContactTakeTheSharedLockSoARevocationCannotSlipBetween(t *testing.T) {
	f := newFx(t, nil)
	f.add(f.entry("OLT-A", "10.20.1.5"))
	f.creds("OLT-A")
	f.trust("OLT-A")
	e := f.entry("OLT-S", "10.20.1.6")
	e.Transport = "snmp"
	f.add(e)
	f.creds("OLT-S")
	f.trust("OLT-S")
	for _, s := range f.b.Sources() {
		if s.Open != nil {
			s.Open(context.Background())
		} else {
			s.OpenSNMP(context.Background())
		}
	}
	dial, allowed := f.opened[0].Dial, f.snmp[0].Allowed
	// a writer holding the exclusive side (a revocation in progress) blocks the next dial and the next SNMP contact until it is done
	unlock, err := credfile.Lock(filepath.Join(f.st.Dir, "managed-state"))
	if err != nil {
		t.Fatal(err)
	}
	dialed, contacted := make(chan struct{}), make(chan struct{})
	go func() { dial(context.Background(), "tcp", "10.20.9.9:22"); close(dialed) }() // not in the allowlist: refused, but only after the lock
	go func() { allowed("10.20.1.6:161"); close(contacted) }()
	select {
	case <-dialed:
		t.Fatal("the dial must wait for the revocation in progress")
	case <-contacted:
		t.Fatal("the SNMP contact must wait for the revocation in progress")
	case <-time.After(300 * time.Millisecond):
	}
	unlock()
	for _, c := range []chan struct{}{dialed, contacted} {
		select {
		case <-c:
		case <-time.After(5 * time.Second):
			t.Fatal("they must proceed once it is done")
		}
	}
}
