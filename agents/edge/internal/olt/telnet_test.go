package olt

import (
	"bytes"
	"context"
	"errors"
	"net"
	"os"
	"path/filepath"
	"strings"
	"sync"
	"testing"
	"time"
)

const (
	fakeUser = "operador"
	fakePass = "S3nha-Fict1cia!"
)

func fixture(t *testing.T, name string) string {
	t.Helper()
	b, err := os.ReadFile(filepath.Join("testdata", "intelbras_8820", name))
	if err != nil {
		t.Fatal(err)
	}
	return string(b)
}

// fakeTelnetOLT is an in-memory Intelbras-like Telnet server: option negotiation, banner with ANSI, login, prompt, "waiting to execute command", sanitized fixture answers.
type fakeTelnetOLT struct {
	ln   net.Listener
	mu   sync.Mutex
	cmds []string // every line received after the login
	iac  []byte   // every IAC byte the client sent back
	pass string   // what the server got as password

	hangOn      string // command whose answer never gets a prompt (connection stays open)
	cutOn       string // command whose answer is cut and the connection closed
	bigOn       string // command whose answer is endless garbage without prompt
	banner      string
	echoPass    bool // misbehaving device that prints the password back in the banner
	answers     map[string]string
	closeSignal chan struct{}
}

func newFakeTelnetOLT(t *testing.T) *fakeTelnetOLT {
	t.Helper()
	ln, err := net.Listen("tcp", "127.0.0.1:0")
	if err != nil {
		t.Fatal(err)
	}
	f := &fakeTelnetOLT{ln: ln, banner: fixture(t, "banner.txt"), closeSignal: make(chan struct{}), answers: map[string]string{
		"card stats":    fixture(t, "card_stats.txt"),
		"olt show port": fixture(t, "olt_show_port.txt"),
		"onu status":    fixture(t, "onu_status.txt"),
	}}
	go f.serve()
	t.Cleanup(func() { close(f.closeSignal); ln.Close() })
	return f
}

func (f *fakeTelnetOLT) addr() string { return f.ln.Addr().String() }

func (f *fakeTelnetOLT) commands() []string {
	f.mu.Lock()
	defer f.mu.Unlock()
	return append([]string{}, f.cmds...)
}

func (f *fakeTelnetOLT) serve() {
	for {
		c, err := f.ln.Accept()
		if err != nil {
			return
		}
		go f.handle(c)
	}
}

// readLine reads up to \n, dropping (and recording) IAC option replies.
func (f *fakeTelnetOLT) readLine(c net.Conn) (string, bool) {
	var line []byte
	buf := make([]byte, 1)
	for {
		if _, err := c.Read(buf); err != nil {
			return "", false
		}
		b := buf[0]
		if b == telnetIAC {
			two := make([]byte, 2)
			if _, err := c.Read(two); err != nil {
				return "", false
			}
			f.mu.Lock()
			f.iac = append(f.iac, b, two[0], two[1])
			f.mu.Unlock()
			continue
		}
		if b == '\n' {
			return strings.TrimRight(string(line), "\r"), true
		}
		line = append(line, b)
	}
}

func crlf(s string) string { return strings.ReplaceAll(s, "\n", "\r\n") }

func (f *fakeTelnetOLT) handle(c net.Conn) {
	defer c.Close()
	// option negotiation: the device offers ECHO and SGA, asks for the terminal type, and sends a sub-negotiation the client must skip
	c.Write([]byte{telnetIAC, telnetDO, 24, telnetIAC, telnetWILL, 1, telnetIAC, telnetWILL, 3, telnetIAC, telnetSB, 24, 1, telnetIAC, telnetSE})
	c.Write([]byte("\r\n\x1b[1;31mIntelbras Embedded Platform 16.2 olt8820plus\x1b[0m\r\n\r\nolt8820plus login: "))
	user, ok := f.readLine(c)
	if !ok {
		return
	}
	c.Write([]byte("Password: "))
	pass, ok := f.readLine(c)
	if !ok {
		return
	}
	f.mu.Lock()
	f.pass = pass
	f.mu.Unlock()
	if user != fakeUser || pass != fakePass {
		c.Write([]byte("\r\nLogin incorrect\r\n\r\nolt8820plus login: "))
		return
	}
	extra := ""
	if f.echoPass {
		extra = "(!) last login with " + pass + "\r\n"
	}
	c.Write([]byte("\r\n" + f.banner + "\x1b[93m(!) Warning, there are 189 active alarms\x1b[0m\r\n" + extra + "\r\nintelbras-olt> "))
	for {
		line, ok := f.readLine(c)
		if !ok {
			return
		}
		f.mu.Lock()
		f.cmds = append(f.cmds, line)
		f.mu.Unlock()
		if line == "logout" {
			return
		}
		switch {
		case line == f.hangOn:
			c.Write([]byte(line + "\r\nGPON 1\r\n"))
			<-f.closeSignal
			return
		case line == f.cutOn:
			c.Write([]byte(line + "\r\n" + crlf(f.answers[line][:len(f.answers[line])/2])))
			return
		case line == f.bigOn:
			chunk := bytes.Repeat([]byte("x"), 4096)
			for i := 0; i < 64; i++ {
				if _, err := c.Write(chunk); err != nil {
					return
				}
			}
			<-f.closeSignal
			return
		}
		body, known := f.answers[line]
		if !known {
			c.Write([]byte("\a" + line + "\r\n%% Invalid command\r\nintelbras-olt> "))
			continue
		}
		out := "\a" + line + "\r\n"
		if line == "onu status" {
			out += "\r\nThe OLT system is processing, waiting to execute command...\r\n\x1b[F\x1b[K\x1b[F\x1b[K"
		}
		c.Write([]byte(out))
		time.Sleep(5 * time.Millisecond) // the answer arrives in more than one read
		c.Write([]byte(crlf(body) + "intelbras-olt> "))
	}
}

func dialFake(f *fakeTelnetOLT, pass string) DialFunc {
	return func(ctx context.Context, network, addr string) (net.Conn, error) {
		var d net.Dialer
		return d.DialContext(ctx, network, f.addr())
	}
}

func telnetCfg(f *fakeTelnetOLT, pass string) TelnetConfig {
	return TelnetConfig{
		Addr: "192.0.2.10:23", User: fakeUser, Password: pass, Dial: dialFake(f, pass),
		Prompt: IntelbrasPrompt, Allowed: IntelbrasAllowed, Noise: IntelbrasNoise,
		CommandTimeout: 2 * time.Second, LoginTimeout: 2 * time.Second, Quiet: 20 * time.Millisecond,
	}
}

func openFake(t *testing.T, f *fakeTelnetOLT) *TelnetSession {
	t.Helper()
	s, err := DialTelnet(context.Background(), telnetCfg(f, fakePass))
	if err != nil {
		t.Fatalf("dial: %v", err)
	}
	t.Cleanup(func() { s.Close() })
	return s
}

func TestTelnetLoginRefusesOptionsAndCleansBanner(t *testing.T) {
	f := newFakeTelnetOLT(t)
	s := openFake(t, f)
	if got := s.Banner(); !strings.Contains(got, "olt8820plus") || strings.Contains(got, "\x1b") || strings.Contains(got, "\x00") {
		t.Fatalf("banner not clean: %q", got)
	}
	// DO 24 -> WONT 24, WILL 1 -> DONT 1, WILL 3 -> DONT 3; the sub-negotiation is skipped (no reply)
	f.mu.Lock()
	got := append([]byte{}, f.iac...)
	f.mu.Unlock()
	want := []byte{telnetIAC, telnetWONT, 24, telnetIAC, telnetDONT, 1, telnetIAC, telnetDONT, 3}
	if !bytes.Equal(got, want) {
		t.Fatalf("IAC replies = %v, want %v", got, want)
	}
	if f.pass != fakePass {
		t.Fatal("device did not receive the password")
	}
}

func TestTelnetRunStripsNoiseAndEchoAndProvesEnd(t *testing.T) {
	f := newFakeTelnetOLT(t)
	s := openFake(t, f)
	out, err := s.Run(context.Background(), "onu status")
	if err != nil {
		t.Fatal(err)
	}
	if strings.Contains(out, "waiting to execute") || strings.Contains(out, "intelbras-olt>") || strings.Contains(out, "\x1b") || strings.Contains(out, "\a") {
		t.Fatalf("noise/prompt/ANSI left in output: %q", out[:200])
	}
	if !strings.Contains(out, "GPON 1") || !strings.Contains(out, "Configured ONUs: 13, Active ONUs = 11") {
		t.Fatal("answer lost")
	}
	if strings.HasPrefix(strings.TrimSpace(out), "onu status") {
		t.Fatal("command echo left in output")
	}
	if !s.EndProven() {
		t.Fatal("EndProven must be true after a command that ended with the prompt")
	}
}

func TestTelnetCloseSendsLogoutOnly(t *testing.T) {
	f := newFakeTelnetOLT(t)
	s := openFake(t, f)
	if _, err := s.Run(context.Background(), "card stats"); err != nil {
		t.Fatal(err)
	}
	s.Close()
	deadline := time.Now().Add(time.Second)
	for time.Now().Before(deadline) && len(f.commands()) < 2 {
		time.Sleep(10 * time.Millisecond)
	}
	if got := f.commands(); len(got) != 2 || got[0] != "card stats" || got[1] != "logout" {
		t.Fatalf("device saw %v, want [card stats logout]", got)
	}
	if _, err := s.Run(context.Background(), "card stats"); err == nil {
		t.Fatal("a closed session must not run")
	}
}

func TestTelnetDeniesWhatIsNotAllowlistedAndSendsNothing(t *testing.T) {
	f := newFakeTelnetOLT(t)
	s := openFake(t, f)
	for _, cmd := range []string{
		"set2default", "systemreboot", "restore", "reboot", "clear", "delete", "set", "add", "modify", "up", "down", "config", "configure terminal",
		"?", "onu ?", "onu status ?", "onu status gpon 1", "card stats ", " card stats", "card stats; reboot", "card stats | more", "CARD STATS", "onu show",
		"alarm show", "interface show", "shelfctrl monitor", "logout", "olt show port\r\nreboot", "",
	} {
		if _, err := s.Run(context.Background(), cmd); !errors.Is(err, ErrCommandDenied) {
			t.Errorf("%q: err = %v, want ErrCommandDenied", cmd, err)
		}
	}
	if got := f.commands(); len(got) != 0 {
		t.Fatalf("the device received %v; a denied command must never leave the Edge", got)
	}
	if !s.EndProven() {
		t.Fatal("a denied command is not a transport failure")
	}
}

func TestIntelbrasAllowlistIsExactAndHasNoQuestionMark(t *testing.T) {
	for _, ok := range []string{"card stats", "olt show port", "onu status"} {
		if !IntelbrasAllowed(ok) || !(Intelbras{}).Allowed(ok) {
			t.Errorf("%q must be allowed", ok)
		}
	}
	for _, bad := range []string{
		"set2default", "systemreboot", "restore", "reboot", "clear", "delete", "set", "add", "modify", "up", "down", "config", "?", "onu ?", "onu status ?",
		"onu status gpon 1", "card stats x", "card", "olt", "onu", "olt show", "olt show port 1", "onu show", "alarm show", "sfp show gpon 1", "interface show",
	} {
		if IntelbrasAllowed(bad) {
			t.Errorf("%q must NOT be allowed", bad)
		}
	}
	for c := range intelbrasCommands {
		if strings.Contains(c, "?") || !SafeCommand(c) {
			t.Errorf("allowlisted %q must be a plain safe command", c)
		}
	}
}

func TestTelnetWrongPasswordNeverLeaksIt(t *testing.T) {
	f := newFakeTelnetOLT(t)
	_, err := DialTelnet(context.Background(), telnetCfg(f, "senha-errada-fictícia"))
	if !errors.Is(err, ErrTelnetLogin) {
		t.Fatalf("err = %v, want ErrTelnetLogin", err)
	}
	if strings.Contains(err.Error(), "senha-errada") {
		t.Fatalf("password in error: %v", err)
	}
	if got := f.commands(); len(got) != 0 {
		t.Fatalf("nothing but the login may be sent, device saw %v", got)
	}
}

func TestTelnetRedactsPasswordEchoedByTheDevice(t *testing.T) {
	f := newFakeTelnetOLT(t)
	f.echoPass = true
	s := openFake(t, f)
	if strings.Contains(s.Banner(), fakePass) {
		t.Fatalf("password echoed by the device reached the banner: %q", s.Banner())
	}
	if !strings.Contains(s.Banner(), "<redacted>") {
		t.Fatalf("expected the redaction mark in %q", s.Banner())
	}
	f.answers["card stats"] = "esta saida repete " + fakePass + "\n"
	out, err := s.Run(context.Background(), "card stats")
	if err != nil {
		t.Fatal(err)
	}
	if strings.Contains(out, fakePass) {
		t.Fatalf("password in command output: %q", out)
	}
}

func TestTelnetDialErrorDoesNotLeakPassword(t *testing.T) {
	cfg := TelnetConfig{Addr: "192.0.2.10:23", User: fakeUser, Password: fakePass, Prompt: IntelbrasPrompt,
		Dial: func(ctx context.Context, network, addr string) (net.Conn, error) {
			return nil, errors.New("dial " + addr + ": refused (" + fakePass + ")")
		}}
	_, err := DialTelnet(context.Background(), cfg)
	if err == nil {
		t.Fatal("want error")
	}
	// the dialer error is the allowlist's own message; the password is never sent to it, so it cannot contain one it did not get from us
	if _, err := DialTelnet(context.Background(), TelnetConfig{Addr: "x:23", Prompt: IntelbrasPrompt}); err == nil {
		t.Fatal("a missing allowlisted dialer must fail closed")
	}
}

func TestTelnetCommandWithoutPromptTimesOutAndDiscardsOutput(t *testing.T) {
	f := newFakeTelnetOLT(t)
	f.hangOn = "onu status"
	cfg := telnetCfg(f, fakePass)
	cfg.CommandTimeout = 300 * time.Millisecond
	s, err := DialTelnet(context.Background(), cfg)
	if err != nil {
		t.Fatal(err)
	}
	defer s.Close()
	start := time.Now()
	out, err := s.Run(context.Background(), "onu status")
	if !errors.Is(err, ErrNoPrompt) || out != "" {
		t.Fatalf("out=%q err=%v, want ErrNoPrompt and no output", out, err)
	}
	if time.Since(start) > 2*time.Second {
		t.Fatal("the command timeout was not honoured")
	}
	if s.EndProven() {
		t.Fatal("EndProven must be false after a command whose end was not seen")
	}
}

func TestTelnetCutConnectionNeverReturnsPartialOutput(t *testing.T) {
	f := newFakeTelnetOLT(t)
	f.cutOn = "onu status"
	s := openFake(t, f)
	out, err := s.Run(context.Background(), "onu status")
	if !errors.Is(err, ErrNoPrompt) || out != "" {
		t.Fatalf("out=%q err=%v", out, err)
	}
	if s.EndProven() {
		t.Fatal("EndProven must be false")
	}
}

func TestTelnetByteLimit(t *testing.T) {
	f := newFakeTelnetOLT(t)
	f.bigOn = "card stats"
	cfg := telnetCfg(f, fakePass)
	cfg.MaxOutput = 16 << 10
	s, err := DialTelnet(context.Background(), cfg)
	if err != nil {
		t.Fatal(err)
	}
	defer s.Close()
	if out, err := s.Run(context.Background(), "card stats"); err == nil || out != "" || !strings.Contains(err.Error(), "exceeds") {
		t.Fatalf("out=%d bytes err=%v, want the byte limit error", len(out), err)
	}
}

func TestTelnetContextCancelStopsTheCommand(t *testing.T) {
	f := newFakeTelnetOLT(t)
	f.hangOn = "olt show port"
	s := openFake(t, f)
	ctx, cancel := context.WithTimeout(context.Background(), 150*time.Millisecond)
	defer cancel()
	if _, err := s.Run(ctx, "olt show port"); err == nil {
		t.Fatal("want error")
	}
}

func TestTelnetFilterIACSplitAcrossReadsAndEscapedFF(t *testing.T) {
	a, b := net.Pipe()
	defer a.Close()
	defer b.Close()
	go func() { // drain the replies
		buf := make([]byte, 64)
		for {
			if _, err := b.Read(buf); err != nil {
				return
			}
		}
	}()
	s := &TelnetSession{conn: a}
	s.filter([]byte{'a', telnetIAC})                              // IAC at the very end of a read
	s.filter([]byte{telnetDO, 1, 'b', telnetIAC, telnetIAC, 'c'}) // completes DO 1, then an escaped 0xFF
	s.filter([]byte{telnetIAC, telnetSB, 24, 1})                  // sub-negotiation split...
	s.filter([]byte{'x', 'y', telnetIAC, telnetSE, 'd'})          // ...and closed later; its payload is not data
	if want := []byte{'a', 'b', 0xFF, 'c', 'd'}; !bytes.Equal(s.pend, want) {
		t.Fatalf("pend = %v, want %v", s.pend, want)
	}
}

func TestPlainRemovesANSICursorAndBell(t *testing.T) {
	got := plain([]byte("\x07onu status\r\n\x1b[F\x1b[K\x1b[F\x1b[KGPON 1\r\n\x1b[93mwarn\x1b[0m\x08"))
	if got != "onu status\nGPON 1\nwarn" {
		t.Fatalf("plain = %q", got)
	}
}
