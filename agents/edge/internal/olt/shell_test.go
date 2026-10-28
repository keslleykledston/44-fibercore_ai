package olt

import (
	"bufio"
	"context"
	"crypto/ed25519"
	"crypto/rand"
	"crypto/rsa"
	"errors"
	"net"
	"os"
	"strings"
	"sync"
	"testing"
	"time"

	"golang.org/x/crypto/ssh"
)

const testPrompt = "OLT-TEST-1>"

// shellServer imitates the interactive CLI observed on a Huawei MA5608T (R015): no exec support, pty + shell,
// `display version` waits for an Enter (optional-parameter prompt), the pager and confirmations stop the session.
type shellServer struct {
	addr string
	fp   string
	mu   sync.Mutex
	cmds []string
	crs  int
	exec int
}

func startShellSSH(t *testing.T, legacyOnly bool) *shellServer {
	cfg := &ssh.ServerConfig{PasswordCallback: func(ssh.ConnMetadata, []byte) (*ssh.Permissions, error) { return nil, nil }}
	var signer ssh.Signer
	if legacyOnly {
		k, err := rsa.GenerateKey(rand.Reader, 2048)
		if err != nil {
			t.Fatal(err)
		}
		signer, _ = ssh.NewSignerFromKey(k)
		cfg.KeyExchanges = []string{"diffie-hellman-group1-sha1"}
		cfg.Ciphers = []string{"aes128-cbc"}
	} else {
		signer = mustEd25519(t)
	}
	cfg.AddHostKey(signer)
	ln, err := net.Listen("tcp", "127.0.0.1:0")
	if err != nil {
		t.Fatal(err)
	}
	srv := &shellServer{addr: ln.Addr().String(), fp: ssh.FingerprintSHA256(signer.PublicKey())}
	t.Cleanup(func() { ln.Close() })
	go func() {
		for {
			c, err := ln.Accept()
			if err != nil {
				return
			}
			go srv.serve(c, cfg)
		}
	}()
	return srv
}

func (srv *shellServer) serve(c net.Conn, cfg *ssh.ServerConfig) {
	conn, chans, reqs, err := ssh.NewServerConn(c, cfg)
	if err != nil {
		return
	}
	defer conn.Close()
	go ssh.DiscardRequests(reqs)
	for nc := range chans {
		ch, creqs, _ := nc.Accept()
		go func() {
			for r := range creqs {
				switch r.Type {
				case "pty-req":
					r.Reply(true, nil)
				case "exec": // this firmware ignores exec: no output, exit status -1 style
					srv.mu.Lock()
					srv.exec++
					srv.mu.Unlock()
					r.Reply(true, nil)
					ch.Close()
				case "shell":
					r.Reply(true, nil)
					go srv.cli(ch)
				default:
					r.Reply(false, nil)
				}
			}
		}()
	}
}

func (srv *shellServer) cli(ch ssh.Channel) {
	defer ch.Close()
	ch.Write([]byte("\r\n  Huawei Integrated Access Software (TEST).\r\n\r\n" + testPrompt))
	rd := bufio.NewReader(ch)
	readLine := func() (string, bool) {
		l, err := rd.ReadString('\r')
		return strings.TrimSpace(l), err == nil
	}
	for {
		line, ok := readLine()
		if !ok {
			return
		}
		srv.mu.Lock()
		if line != "" {
			srv.cmds = append(srv.cmds, line)
		} else {
			srv.crs++
		}
		srv.mu.Unlock()
		ch.Write([]byte(line + "\r\n"))
		switch {
		case line == "display version":
			ch.Write([]byte("{ <cr>|backplane<K>|frameid/slotid<S><Length 1-15> }:"))
			if _, ok := readLine(); !ok {
				return
			}
			srv.mu.Lock()
			srv.crs++
			srv.mu.Unlock()
			ch.Write([]byte("\r\n\r\n  Command:\r\n          display version \r\n\r\n  VERSION : MA5600V800R015C00\r\n  PATCH   : SPC100 HP1013\r\n  PRODUCT : MA5608T\r\n\r\n" + testPrompt))
		case strings.HasPrefix(line, "display ont info summary"):
			ch.Write([]byte("  0/1/0  1  4857544312345678  online\r\n  ---- More ( Press 'Q' to break ) ----"))
			select {} // the pager waits for a key the Edge never sends
		case line == "display slow": // answers the Enter late: the stale parameter prompt stays at the tail meanwhile
			ch.Write([]byte("{ <cr>|backplane<K> }:"))
			if _, ok := readLine(); !ok {
				return
			}
			srv.mu.Lock()
			srv.crs++
			srv.mu.Unlock()
			ch.Write([]byte("\r\n")) // the device echoes the Enter, which re-evaluates the buffer while the prompt is still stale
			time.Sleep(300 * time.Millisecond)
			ch.Write([]byte("\r\n  VERSION : MA5600V800R015C00\r\n  PRODUCT : MA5608T\r\n" + testPrompt))
		case line == "display twice": // asks for optional parameters again after the Enter
			ch.Write([]byte("{ <cr>|backplane<K> }:"))
			if _, ok := readLine(); !ok {
				return
			}
			srv.mu.Lock()
			srv.crs++
			srv.mu.Unlock()
			ch.Write([]byte("\r\n{ <cr>|frameid<S> }:"))
			select {}
		case line == "display mimic": // payload fakes the prompt before the real end
			ch.Write([]byte("  part one\r\n" + testPrompt + "\r\n  part two (would be lost)\r\n" + testPrompt))
		case line == "display late": // prompt, then more output after a short pause
			ch.Write([]byte("  part one\r\n" + testPrompt))
			time.Sleep(60 * time.Millisecond)
			ch.Write([]byte("\r\n  part two\r\n" + testPrompt))
		case line == "display suffix": // a line merely ending with the prompt text is ordinary output
			ch.Write([]byte("  see " + testPrompt + "\r\n  rest\r\n" + testPrompt))
		case line == "display risky":
			ch.Write([]byte("Are you sure to continue? (y/n)[n]:"))
			select {}
		default:
			ch.Write([]byte("  Unknown command\r\n" + testPrompt))
		}
	}
}

func mustEd25519(t *testing.T) ssh.Signer {
	t.Helper()
	_, priv, err := ed25519.GenerateKey(rand.Reader)
	if err != nil {
		t.Fatal(err)
	}
	signer, err := ssh.NewSignerFromKey(priv)
	if err != nil {
		t.Fatal(err)
	}
	return signer
}

func shellCfg(srv *shellServer, legacy bool) SSHConfig {
	return SSHConfig{Addr: srv.addr, User: "u", Password: "pw", HostKeySHA256: srv.fp, Dial: dialer,
		Shell: true, Legacy: legacy, CommandTimout: 3 * time.Second, PromptQuiet: 150 * time.Millisecond}
}

func TestShellIdentifiesRealHuaweiFormatAndCompletesOptionalParameter(t *testing.T) {
	srv := startShellSSH(t, false)
	s, err := DialSSH(context.Background(), shellCfg(srv, false))
	if err != nil {
		t.Fatal(err)
	}
	defer s.Close()
	id, err := Huawei{}.Identify(context.Background(), ReadOnlySession{Inner: s, Allowed: Huawei{}.Allowed})
	if err != nil {
		t.Fatal(err)
	}
	if id.Model != "MA5608T" || id.Firmware != "MA5600V800R015C00" {
		t.Fatalf("identity: %+v", id)
	}
	srv.mu.Lock()
	defer srv.mu.Unlock()
	if len(srv.cmds) != 1 || srv.cmds[0] != "display version" || srv.crs != 1 {
		t.Fatalf("server saw cmds=%v enters=%d (want exactly one command and one completing Enter)", srv.cmds, srv.crs)
	}
}

func TestShellReusesOneSessionAndStripsEchoAndPrompt(t *testing.T) {
	srv := startShellSSH(t, false)
	s, err := DialSSH(context.Background(), shellCfg(srv, false))
	if err != nil {
		t.Fatal(err)
	}
	defer s.Close()
	for i := 0; i < 2; i++ {
		out, err := s.Run(context.Background(), "display version")
		if err != nil {
			t.Fatal(err)
		}
		if strings.Contains(out, testPrompt) || strings.HasPrefix(strings.TrimSpace(out), "display version") || strings.Contains(out, "<cr>") {
			t.Fatalf("echo/prompt not stripped: %q", out)
		}
		if !strings.Contains(out, "VERSION : MA5600V800R015C00") {
			t.Fatalf("missing payload: %q", out)
		}
	}
}

func TestShellPagerFailsClosedFastAndPoisonsTheSession(t *testing.T) {
	srv := startShellSSH(t, false)
	s, err := DialSSH(context.Background(), shellCfg(srv, false))
	if err != nil {
		t.Fatal(err)
	}
	defer s.Close()
	start := time.Now()
	_, err = s.Run(context.Background(), "display ont info summary 0/1/0")
	if !errors.Is(err, ErrPaginated) {
		t.Fatalf("want ErrPaginated, got %v", err)
	}
	if time.Since(start) > 2*time.Second {
		t.Fatal("pager must be detected, not waited out until the timeout")
	}
	if _, err := s.Run(context.Background(), "display version"); err == nil {
		t.Fatal("a shell left at the pager must never be reused")
	}
	srv.mu.Lock()
	defer srv.mu.Unlock()
	if srv.crs != 0 {
		t.Fatal("no key may be sent to the pager")
	}
}

func TestShellInteractiveQuestionFailsClosedWithoutAnswering(t *testing.T) {
	srv := startShellSSH(t, false)
	s, err := DialSSH(context.Background(), shellCfg(srv, false))
	if err != nil {
		t.Fatal(err)
	}
	defer s.Close()
	if _, err := s.Run(context.Background(), "display risky"); !errors.Is(err, ErrInteractive) {
		t.Fatalf("want ErrInteractive, got %v", err)
	}
	srv.mu.Lock()
	defer srv.mu.Unlock()
	if srv.crs != 0 {
		t.Fatal("a confirmation must never be answered")
	}
}

func TestShellDoesNotUseExecAndReadOnlyWrapperStillBlocksBeforeTheWire(t *testing.T) {
	srv := startShellSSH(t, false)
	s, err := DialSSH(context.Background(), shellCfg(srv, false))
	if err != nil {
		t.Fatal(err)
	}
	defer s.Close()
	ro := ReadOnlySession{Inner: s, Allowed: Huawei{}.Allowed}
	if _, err := ro.Run(context.Background(), "undo ont 0/1/0 1"); !errors.Is(err, ErrCommandDenied) {
		t.Fatalf("want ErrCommandDenied, got %v", err)
	}
	srv.mu.Lock()
	defer srv.mu.Unlock()
	if len(srv.cmds) != 0 || srv.exec != 0 {
		t.Fatalf("denied command reached the server: cmds=%v exec=%d", srv.cmds, srv.exec)
	}
}

func TestLegacySSHIsAnExplicitOptIn(t *testing.T) {
	srv := startShellSSH(t, true) // SHA1 DH group1 + ssh-rsa + aes128-cbc only, like the MA5608T
	if _, err := DialSSH(context.Background(), shellCfg(srv, false)); err == nil {
		t.Fatal("modern defaults must refuse a legacy-only peer")
	}
	s, err := DialSSH(context.Background(), shellCfg(srv, true))
	if err != nil {
		t.Fatalf("legacy opt-in must connect: %v", err)
	}
	defer s.Close()
	if out, err := s.Run(context.Background(), "display version"); err != nil || !strings.Contains(out, "MA5608T") {
		t.Fatalf("out=%q err=%v", out, err)
	}
	bad := shellCfg(srv, true)
	bad.HostKeySHA256 = "SHA256:AAAA"
	if _, err := DialSSH(context.Background(), bad); err == nil || !strings.Contains(err.Error(), "host key mismatch") {
		t.Fatalf("the pinned host key is still mandatory in legacy mode: %v", err)
	}
}

func TestShellLoginWithoutPromptTimesOutInsteadOfHanging(t *testing.T) {
	ln, err := net.Listen("tcp", "127.0.0.1:0")
	if err != nil {
		t.Fatal(err)
	}
	defer ln.Close()
	signer := mustEd25519(t)
	cfg := &ssh.ServerConfig{PasswordCallback: func(ssh.ConnMetadata, []byte) (*ssh.Permissions, error) { return nil, nil }}
	cfg.AddHostKey(signer)
	go func() {
		c, err := ln.Accept()
		if err != nil {
			return
		}
		conn, chans, reqs, err := ssh.NewServerConn(c, cfg)
		if err != nil {
			return
		}
		defer conn.Close()
		go ssh.DiscardRequests(reqs)
		for nc := range chans {
			ch, creqs, _ := nc.Accept()
			go func() {
				for r := range creqs {
					r.Reply(true, nil)
					if r.Type == "shell" {
						ch.Write([]byte("Password:")) // never reaches a prompt
					}
				}
			}()
		}
	}()
	s, err := DialSSH(context.Background(), SSHConfig{Addr: ln.Addr().String(), User: "u", Password: "pw",
		HostKeySHA256: ssh.FingerprintSHA256(signer.PublicKey()), Dial: dialer, Shell: true, CommandTimout: time.Second})
	if err != nil {
		t.Fatal(err)
	}
	defer s.Close()
	if _, err := s.Run(context.Background(), "display version"); err == nil {
		t.Fatal("a login that never reaches a prompt must fail")
	}
}

type stubSession struct{ out string }

func (s stubSession) Run(context.Context, string) (string, error) { return s.out, nil }

// Real capture (MA5608T MA5600V800R015C00): the transport output is tidied and the identity parses.
func TestRealMA5608TDisplayVersionCapture(t *testing.T) {
	raw, err := os.ReadFile("testdata/huawei_ma5608t/MA5600V800R015C00/display_version.txt")
	if err != nil {
		t.Fatal(err)
	}
	out := tidy(string(raw), "display version", "OLT-TEST-1>")
	if strings.Contains(out, "<cr>") || strings.Contains(out, "OLT-TEST-1>") || strings.HasPrefix(strings.TrimSpace(out), "display version") {
		t.Fatalf("echo/prompt not stripped:\n%s", out)
	}
	if !strings.Contains(out, "Command:") || !strings.Contains(out, "          display version") {
		t.Fatalf("legitimate payload that contains the command text must be preserved:\n%s", out)
	}
	id, err := Huawei{}.Identify(context.Background(), stubSession{out})
	if err != nil {
		t.Fatal(err)
	}
	if id.Vendor != "huawei" || id.Model != "MA5608T" || id.Firmware != "MA5600V800R015C00" {
		t.Fatalf("identity: %+v", id)
	}
}

func TestShellSlowAnswerToEnterIsNotASecondQuestion(t *testing.T) {
	srv := startShellSSH(t, false)
	s, err := DialSSH(context.Background(), shellCfg(srv, false))
	if err != nil {
		t.Fatal(err)
	}
	defer s.Close()
	out, err := s.Run(context.Background(), "display slow")
	if err != nil || !strings.Contains(out, "PRODUCT : MA5608T") {
		t.Fatalf("out=%q err=%v", out, err)
	}
}

func TestShellSecondParameterPromptFailsClosedAfterOneEnter(t *testing.T) {
	srv := startShellSSH(t, false)
	s, err := DialSSH(context.Background(), shellCfg(srv, false))
	if err != nil {
		t.Fatal(err)
	}
	defer s.Close()
	if _, err := s.Run(context.Background(), "display twice"); !errors.Is(err, ErrInteractive) {
		t.Fatalf("want ErrInteractive, got %v", err)
	}
	srv.mu.Lock()
	defer srv.mu.Unlock()
	if srv.crs != 1 {
		t.Fatalf("exactly one Enter per command, saw %d", srv.crs)
	}
}

func TestShellPromptLookalikeInsideOutputFailsClosed(t *testing.T) {
	for _, cmd := range []string{"display mimic", "display late"} {
		srv := startShellSSH(t, false)
		s, err := DialSSH(context.Background(), shellCfg(srv, false))
		if err != nil {
			t.Fatal(err)
		}
		out, err := s.Run(context.Background(), cmd)
		if !errors.Is(err, ErrAmbiguousOutput) {
			t.Fatalf("%s: want ErrAmbiguousOutput, got out=%q err=%v", cmd, out, err)
		}
		if _, err := s.Run(context.Background(), "display version"); err == nil {
			t.Fatalf("%s: a shell with ambiguous output must not be reused", cmd)
		}
		s.Close()
	}
}

func TestShellTransportNeverProvesTheEndOfACommand(t *testing.T) {
	srv := startShellSSH(t, false)
	sh, err := DialSSH(context.Background(), shellCfg(srv, false))
	if err != nil {
		t.Fatal(err)
	}
	defer sh.Close()
	if EndProven(sh) {
		t.Fatal("an interactive shell must not claim an unambiguous end of command")
	}
	ex := startSSH(t, "pw")
	e, err := DialSSH(context.Background(), SSHConfig{Addr: ex.addr, User: "u", Password: "pw", HostKeySHA256: ex.fp, Dial: dialer})
	if err != nil {
		t.Fatal(err)
	}
	defer e.Close()
	if !EndProven(e) {
		t.Fatal("SSH exec ends with EOF + exit status")
	}
}

func TestShellLineEndingWithPromptTextIsOrdinaryOutput(t *testing.T) {
	srv := startShellSSH(t, false)
	s, err := DialSSH(context.Background(), shellCfg(srv, false))
	if err != nil {
		t.Fatal(err)
	}
	defer s.Close()
	out, err := s.Run(context.Background(), "display suffix")
	if err != nil || !strings.Contains(out, "see "+testPrompt) || !strings.Contains(out, "rest") {
		t.Fatalf("out=%q err=%v", out, err)
	}
}

func TestTidyKeepsPayloadLinesThatMentionTheCommand(t *testing.T) {
	raw := "display version\n{ <cr>|x }:\n  last command: display version\n  display version\n  VERSION : V1\nOLT-TEST-1>"
	out := tidy(raw, "display version", "OLT-TEST-1>")
	want := "  last command: display version\n  display version\n  VERSION : V1"
	if out != want {
		t.Fatalf("got %q want %q", out, want)
	}
}

func TestCloseReleasesARunBlockedWaitingForTheLoginPrompt(t *testing.T) {
	ln, err := net.Listen("tcp", "127.0.0.1:0")
	if err != nil {
		t.Fatal(err)
	}
	defer ln.Close()
	signer := mustEd25519(t)
	cfg := &ssh.ServerConfig{PasswordCallback: func(ssh.ConnMetadata, []byte) (*ssh.Permissions, error) { return nil, nil }}
	cfg.AddHostKey(signer)
	go func() {
		c, err := ln.Accept()
		if err != nil {
			return
		}
		conn, chans, reqs, err := ssh.NewServerConn(c, cfg)
		if err != nil {
			return
		}
		defer conn.Close()
		go ssh.DiscardRequests(reqs)
		for nc := range chans {
			ch, creqs, _ := nc.Accept()
			go func() {
				for r := range creqs {
					r.Reply(true, nil) // shell opens but the banner never reaches a prompt
					_ = ch
				}
			}()
		}
	}()
	s, err := DialSSH(context.Background(), SSHConfig{Addr: ln.Addr().String(), User: "u", Password: "pw",
		HostKeySHA256: ssh.FingerprintSHA256(signer.PublicKey()), Dial: dialer, Shell: true, CommandTimout: 20 * time.Second})
	if err != nil {
		t.Fatal(err)
	}
	done := make(chan error, 1)
	go func() { _, err := s.Run(context.Background(), "display version"); done <- err }()
	time.Sleep(300 * time.Millisecond)
	start := time.Now()
	s.Close()
	select {
	case err := <-done:
		if err == nil {
			t.Fatal("run must fail after Close")
		}
	case <-time.After(3 * time.Second):
		t.Fatal("Close did not release the blocked Run")
	}
	if time.Since(start) > 3*time.Second {
		t.Fatal("Close was held behind the command timeout")
	}
}
