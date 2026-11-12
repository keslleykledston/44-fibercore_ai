package managedcollect

import (
	"context"
	"errors"
	"testing"
)

func TestTheTrustIsLookedAtOnceMoreAtTheMomentOfTheConnection(t *testing.T) {
	f := newFx(t, nil)
	f.add(f.entry("OLT-A", "10.20.1.5"))
	f.creds("OLT-A")
	f.trust("OLT-A")
	e := f.entry("OLT-S", "10.20.1.6")
	e.Transport = "snmp"
	f.add(e)
	f.creds("OLT-S")
	f.trust("OLT-S")
	for _, s := range f.b.Sources() { // credentials are read, the session is about to dial
		if s.Open != nil {
			if _, _, err := s.Open(context.Background()); err != nil {
				t.Fatal(err)
			}
		} else {
			s.OpenSNMP(context.Background())
		}
	}
	if len(f.opened) != 1 || len(f.snmp) != 1 {
		t.Fatalf("setup: %d %d", len(f.opened), len(f.snmp))
	}
	dialOK, gate := f.opened[0].Dial, f.snmp[0].Gate
	if release, err := gate(); err != nil {
		t.Fatal("while trusted the agent may be contacted:", err)
	} else {
		release()
	}
	// the operator revokes after verify() and before the connection: neither the TCP dial nor the SNMP contact may happen
	f.remove("OLT-A")
	f.remove("OLT-S")
	if _, err := dialOK(context.Background(), "tcp", "10.20.1.5:22"); !errors.Is(err, ErrNotTrusted) {
		t.Fatalf("the dial after a revocation: %v", err)
	}
	if _, err := gate(); !errors.Is(err, ErrNotTrusted) {
		t.Fatalf("the SNMP agent must not be contacted after a revocation: %v", err)
	}
}

func TestAChangeOfVendorIsNotTrusted(t *testing.T) {
	f := newFx(t, nil)
	e := f.entry("OLT-A", "10.20.1.5")
	f.add(e)
	f.creds("OLT-A")
	f.trust("OLT-A")
	e.Vendor = "zte" // same address, port and host key: another driver, other commands
	f.add(e)
	if got := f.names(); len(got) != 0 {
		t.Fatalf("a vendor change must need a new confirmation: %v", got)
	}
}
