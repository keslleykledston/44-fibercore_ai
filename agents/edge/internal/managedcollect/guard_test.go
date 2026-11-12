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

// gatedReader behaves like the real driver: it asks the gate before the socket exists (done by DialSNMP, here by the hook) and before EVERY packet.
type gatedReader struct {
	gate  func() (func(), error)
	calls int
}

func (r *gatedReader) packet() error {
	release, err := r.gate()
	if err != nil {
		return err
	}
	defer release()
	r.calls++
	return nil
}

func (r *gatedReader) Get(context.Context, []string) (map[string]olt.SNMPValue, error) {
	return nil, r.packet()
}
func (r *gatedReader) Walk(context.Context, string, int) ([]olt.SNMPRow, error) {
	return nil, r.packet()
}

func TestNoSNMPPacketIsSentAfterARevocationAndTheGateIsTheOnesOfTheDriver(t *testing.T) {
	f := newFx(t, nil)
	e := f.entry("OLT-S", "10.20.1.6")
	e.Transport = "snmp"
	f.add(e)
	f.creds("OLT-S")
	f.trust("OLT-S")
	rd := &gatedReader{}
	f.b.OpenSNMP = func(_ context.Context, c olt.SNMPConfig) (olt.SNMPReader, func(), error) {
		if c.Gate == nil {
			t.Error("the SNMP session of a managed OLT must carry the gate")
		}
		rd.gate = c.Gate
		return rd, func() {}, nil
	}
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
		t.Fatalf("the agent saw %d packets", rd.calls)
	}
}

func TestARevocationWaitsForTheSNMPExchangeInFlight(t *testing.T) {
	f := newFx(t, nil)
	e := f.entry("OLT-S", "10.20.1.6")
	e.Transport = "snmp"
	f.add(e)
	f.creds("OLT-S")
	f.trust("OLT-S")
	var gate func() (func(), error)
	f.b.OpenSNMP = func(_ context.Context, c olt.SNMPConfig) (olt.SNMPReader, func(), error) {
		gate = c.Gate
		return &gatedReader{gate: c.Gate}, func() {}, nil
	}
	if _, _, err := f.b.Sources()[0].OpenSNMP(context.Background()); err != nil {
		t.Fatal(err)
	}
	release, err := gate() // a packet is on the wire
	if err != nil {
		t.Fatal(err)
	}
	removed := make(chan struct{})
	go func() { f.remove("OLT-S"); close(removed) }()
	select {
	case <-removed:
		t.Fatal("the revocation must wait for the exchange in flight")
	case <-time.After(300 * time.Millisecond):
	}
	release()
	select {
	case <-removed:
	case <-time.After(5 * time.Second):
		t.Fatal("and proceed when it is over")
	}
	if _, err := gate(); !errors.Is(err, ErrNotTrusted) {
		t.Fatalf("after the revocation no packet may start: %v", err)
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
	dial, gate := f.opened[0].Dial, f.snmp[0].Gate
	// a writer holding the exclusive side (a revocation in progress) blocks the next dial and the next SNMP contact until it is done
	unlock, err := credfile.Lock(filepath.Join(f.st.Dir, "managed-state"))
	if err != nil {
		t.Fatal(err)
	}
	dialed, contacted := make(chan struct{}), make(chan struct{})
	go func() { dial(context.Background(), "tcp", "10.20.9.9:22"); close(dialed) }() // not in the allowlist: refused, but only after the lock
	go func() {
		if release, err := gate(); err == nil {
			release()
		}
		close(contacted)
	}()
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
