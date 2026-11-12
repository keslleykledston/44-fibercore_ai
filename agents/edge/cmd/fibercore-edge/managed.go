package main

import (
	"bufio"
	"errors"
	"flag"
	"fmt"
	"io"
	"strings"
	"text/tabwriter"

	"github.com/keslleykledston/44-fibercore_ai/agents/edge/internal/config"
	"github.com/keslleykledston/44-fibercore_ai/agents/edge/internal/managedolts"
)

// loadManaged reads the configuration and opens the managed-OLT store (read side: it creates nothing). Exit code 2 = usage or configuration.
func loadManaged(cfgPath string, stderr io.Writer) (*managedolts.Policy, *managedolts.Store, int) {
	cfg, err := config.Load(cfgPath, version)
	if err != nil {
		fmt.Fprintln(stderr, "invalid config:", err)
		return nil, nil, 2
	}
	if cfg.ManagedOLTs == nil {
		fmt.Fprintln(stderr, "managed_olts is not enabled in this configuration")
		return nil, nil, 2
	}
	pol, err := managedolts.NewPolicy(*cfg.ManagedOLTs)
	if err != nil {
		fmt.Fprintln(stderr, "managed_olts policy:", err)
		return nil, nil, 2
	}
	return pol, &managedolts.Store{Dir: cfg.ManagedOLTs.StateDir}, 0
}

// runManagedList implements `fibercore-edge managed-list [-config PATH]` (ADR-0046): one line per OLT the Cloud added, with its address, vendor, state and the host key
// fingerprint it PROPOSED. It reads the registry and the trust, never the credentials, and prints nothing secret.
func runManagedList(args []string, stdout, stderr io.Writer) int {
	fs := flag.NewFlagSet("managed-list", flag.ContinueOnError)
	fs.SetOutput(stderr)
	cfgPath := fs.String("config", "/etc/fibercore-edge/config.json", "config file (mode 0600)")
	if err := fs.Parse(args); err != nil || fs.NArg() != 0 {
		return 2
	}
	pol, st, code := loadManaged(*cfgPath, stderr)
	if code != 0 {
		return code
	}
	items, err := st.List()
	if err != nil {
		fmt.Fprintln(stderr, "managed olts:", err)
		return 1
	}
	if len(items) == 0 {
		fmt.Fprintln(stdout, "no managed OLTs")
		return 0
	}
	tw := tabwriter.NewWriter(stdout, 0, 4, 2, ' ', 0)
	fmt.Fprintln(tw, "NAME\tADDRESS\tVENDOR\tTRANSPORT\tSTATE\tPOLICY\tPROPOSED HOST KEY FINGERPRINT")
	for _, it := range items {
		e := it.Entry
		policy := "ok"
		if c := pol.Check(e); c != "" {
			policy = c // the OLT no longer fits the local policy: it will not be collected, and managed-trust will refuse it
		}
		fmt.Fprintf(tw, "%s\t%s\t%s\t%s\t%s\t%s\t%s\n", e.Name, e.HostPort(), e.Vendor, e.Transport, it.State(), policy, e.HostKeySHA256)
	}
	tw.Flush()
	return 0
}

// runManagedTrust implements `fibercore-edge managed-trust [-config PATH] <name>` (ADR-0046 D4): the LOCAL trust of one managed OLT. It shows what the Cloud proposed (name,
// ip:port, vendor and the SSH host key fingerprint) and REQUIRES the operator to retype the fingerprint, which the operator must have taken from the device itself (or
// ssh-keyscan from the OLT's own network), NOT from the Cloud screen; it refuses when the retyped value does not match. Only then is the trust stored (as the digest of the
// connection fields that were shown). Nothing here reads or prints a credential.
func runManagedTrust(args []string, stdin io.Reader, stdout, stderr io.Writer) int {
	fs := flag.NewFlagSet("managed-trust", flag.ContinueOnError)
	fs.SetOutput(stderr)
	cfgPath := fs.String("config", "/etc/fibercore-edge/config.json", "config file (mode 0600)")
	if err := fs.Parse(args); err != nil {
		return 2
	}
	rest := fs.Args()
	if len(rest) > 1 { // flags may also come after the name
		if err := fs.Parse(rest[1:]); err != nil || fs.NArg() != 0 {
			return 2
		}
		rest = rest[:1]
	}
	if len(rest) != 1 {
		fmt.Fprintln(stderr, "usage: fibercore-edge managed-trust [-config PATH] <name>")
		return 2
	}
	name := rest[0]
	pol, st, code := loadManaged(*cfgPath, stderr)
	if code != 0 {
		return code
	}
	it, found, err := st.Get(name)
	if err != nil {
		fmt.Fprintln(stderr, "managed olts:", err)
		return 1
	}
	if !found {
		fmt.Fprintln(stderr, "there is no managed OLT with that name (see: fibercore-edge managed-list)")
		return 1
	}
	e := it.Entry
	if c := pol.Check(e); c != "" {
		fmt.Fprintf(stderr, "refused: this OLT does not fit the local policy (%s); it cannot be trusted until the policy or the Cloud entry changes\n", c)
		return 1
	}
	fmt.Fprintf(stdout, "name:        %s\naddress:     %s\ntransport:   %s\nvendor:      %s\nproposed SSH host key fingerprint (from the Cloud):\n  %s\n", e.Name, e.HostPort(), e.Transport, e.Vendor, e.HostKeySHA256)
	if it.Trusted {
		fmt.Fprintln(stdout, "state:       already trusted (nothing to do)")
		return 0
	}
	fmt.Fprint(stdout, "\nThe Cloud chose this address and this key. Compare the fingerprint with the one shown by the OLT itself (or by ssh-keyscan run from the OLT's network),\nnot with the Cloud screen. Retype the fingerprint to trust this OLT: ")
	line, err := bufio.NewReaderSize(stdin, 512).ReadString('\n')
	if err != nil && !errors.Is(err, io.EOF) {
		fmt.Fprintln(stderr, "\nno input")
		return 1
	}
	if strings.TrimSpace(line) != e.HostKeySHA256 { // exact, case-sensitive: a base64 fingerprint is
		fmt.Fprintln(stderr, "\nrefused: the fingerprint you typed does not match the proposed one; nothing was trusted")
		return 1
	}
	switch err := st.Trust(name, e.Digest()); {
	case errors.Is(err, managedolts.ErrChanged):
		fmt.Fprintln(stderr, "\nrefused: the OLT changed in the Cloud while you were confirming; run managed-list and managed-trust again")
		return 1
	case errors.Is(err, managedolts.ErrNotFound):
		fmt.Fprintln(stderr, "\nrefused: the OLT was removed while you were confirming")
		return 1
	case err != nil:
		fmt.Fprintln(stderr, "\ncould not store the trust:", err)
		return 1
	}
	fmt.Fprintf(stdout, "\ntrusted: %s at %s. It is collected from the next round (the Edge re-reads the registry every round; no restart).\n", e.Name, e.HostPort())
	return 0
}
