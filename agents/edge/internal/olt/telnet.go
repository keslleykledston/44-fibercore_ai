package olt

import (
	"bytes"
	"context"
	"errors"
	"fmt"
	"io"
	"net"
	"regexp"
	"strings"
	"sync"
	"time"
)

// Read-only Telnet transport (ADR-0046 D3 keeps Telnet out of the CLOUD-proposed OLTs; this is the Edge-LOCAL, explicit opt-in path used by static `olts[]` entries of vendors that only
// speak Telnet, today the Intelbras 8820).
//
// Telnet is CLEAR TEXT: the login and everything the device prints cross the network unprotected, and there is no host key to pin. That is why the config demands BOTH
// `transport:"telnet"` and `allow_telnet:true` on that one OLT and the destination in the Edge's own `allowlist` (an IP literal). This session adds nothing on top of that: it
// sends ONLY the login and the commands its Allowed func admits (plus `logout` when it closes), refuses every option the device offers (IAC), never echoes the password, and
// fails closed: a command whose end prompt was not seen is an error, never a partial listing.

var (
	// ErrNoPrompt: the command did not end with the device prompt inside the time/size limits. The output is discarded (a truncated list must never look complete).
	ErrNoPrompt = errors.New("telnet: end-of-command prompt not seen (output discarded)")
	// ErrTelnetLogin: the login did not reach a prompt. The device is tried ONCE per session (no password retry: a lockout would cost the operator the OLT).
	ErrTelnetLogin = errors.New("telnet: login failed")
)

const (
	telnetIAC  = 255
	telnetDONT = 254
	telnetDO   = 253
	telnetWONT = 252
	telnetWILL = 251
	telnetSB   = 250
	telnetSE   = 240
)

var (
	loginPrompt = regexp.MustCompile(`(?i)(login|user ?name)\s*:\s*$`)
	passPrompt  = regexp.MustCompile(`(?i)password\s*:\s*$`)
	loginFailed = regexp.MustCompile(`(?i)(login incorrect|authentication fail|access denied|invalid (user|password)|login failed)`)
)

type TelnetConfig struct {
	Addr     string
	User     string
	Password string
	Dial     DialFunc // must be the allowlist-enforcing dialer (allowlist.List.DialContext)
	// Prompt matches the END of the device output once a command is done (e.g. `intelbras-olt>`). Mandatory: without it no command end can be proven.
	Prompt *regexp.Regexp
	// Allowed is the exact-match read-only allowlist of the driver. Run refuses anything it does not admit, on top of the ReadOnlySession the collector wraps around it.
	Allowed func(cmd string) bool
	// CommandTimeout bounds one command (default 90s: `onu status` is slow on a full OLT). LoginTimeout bounds the login (default 30s). Both sit inside the ctx the caller gives.
	CommandTimeout time.Duration
	LoginTimeout   time.Duration
	// Quiet is the silence required after the prompt before a command is declared done (default 250ms).
	Quiet time.Duration
	// MaxOutput caps one command's output (default 4 MiB); beyond it the command fails.
	MaxOutput int
	// Noise lists lines the device prints that are not part of any answer (e.g. "waiting to execute command"); they are dropped from the output.
	Noise *regexp.Regexp
}

// TelnetSession is one login on one device. Not safe for concurrent Run; the collector runs a session from one goroutine.
type TelnetSession struct {
	conn   net.Conn
	cfg    TelnetConfig
	mu     sync.Mutex
	pend   []byte // bytes read but not yet consumed (already IAC-filtered)
	banner string
	proven bool
	closed bool
	iacBuf []byte // an IAC sequence split across two reads
	prompt *regexp.Regexp
}

// DialTelnet connects through the allowlisted dialer and logs in. Never retried.
func DialTelnet(ctx context.Context, cfg TelnetConfig) (*TelnetSession, error) {
	if cfg.Dial == nil || cfg.Prompt == nil || cfg.Addr == "" {
		return nil, errors.New("telnet: allowlisted dialer, address and prompt are required")
	}
	if cfg.CommandTimeout == 0 {
		cfg.CommandTimeout = 90 * time.Second
	}
	if cfg.LoginTimeout == 0 {
		cfg.LoginTimeout = 30 * time.Second
	}
	if cfg.Quiet == 0 {
		cfg.Quiet = 250 * time.Millisecond
	}
	if cfg.MaxOutput == 0 {
		cfg.MaxOutput = 4 << 20
	}
	raw, err := cfg.Dial(ctx, "tcp", cfg.Addr)
	if err != nil {
		return nil, err
	}
	// the prompt only ends a command when it is the LAST thing printed: the same text followed by typed characters (the device redraws "prompt> command") is not an end
	s := &TelnetSession{conn: raw, cfg: cfg, proven: true, prompt: regexp.MustCompile("(?:" + cfg.Prompt.String() + `)[ \t]*\z`)}
	if err := s.login(ctx); err != nil {
		raw.Close()
		return nil, err
	}
	return s, nil
}

// Banner is what the device printed before the first prompt (model line included), cleaned of IAC and ANSI. The driver reads the model from it.
func (s *TelnetSession) Banner() string { return s.banner }

// EndProven is true only while every command so far ended with the prompt seen (a failed command leaves it false for the rest of the session).
func (s *TelnetSession) EndProven() bool { s.mu.Lock(); defer s.mu.Unlock(); return s.proven }

// Close says goodbye (best effort, the one fixed word that is not a read) and drops the connection.
func (s *TelnetSession) Close() error {
	s.mu.Lock()
	defer s.mu.Unlock()
	if s.closed {
		return nil
	}
	s.closed = true
	_ = s.conn.SetWriteDeadline(time.Now().Add(2 * time.Second))
	_, _ = s.conn.Write([]byte("logout\r\n"))
	return s.conn.Close()
}

func (s *TelnetSession) redact(t string) string {
	if s.cfg.Password != "" {
		t = strings.ReplaceAll(t, s.cfg.Password, "<redacted>")
	}
	return t
}

// readSome reads once with a deadline, filters Telnet control bytes (refusing every option) and appends the plain bytes to s.pend.
func (s *TelnetSession) readSome(deadline time.Time) error {
	_ = s.conn.SetReadDeadline(deadline)
	buf := make([]byte, 16<<10)
	n, err := s.conn.Read(buf)
	if n > 0 {
		s.filter(buf[:n])
	}
	return err
}

func (s *TelnetSession) filter(in []byte) {
	if len(s.iacBuf) > 0 {
		in = append(s.iacBuf, in...)
		s.iacBuf = nil
	}
	for i := 0; i < len(in); i++ {
		b := in[i]
		if b != telnetIAC {
			s.pend = append(s.pend, b)
			continue
		}
		if i+1 >= len(in) {
			s.iacBuf = append([]byte{}, in[i:]...)
			return
		}
		switch cmd := in[i+1]; cmd {
		case telnetIAC:
			s.pend = append(s.pend, telnetIAC)
			i++
		case telnetDO, telnetDONT, telnetWILL, telnetWONT:
			if i+2 >= len(in) {
				s.iacBuf = append([]byte{}, in[i:]...)
				return
			}
			opt := in[i+2]
			switch cmd {
			case telnetDO:
				s.write([]byte{telnetIAC, telnetWONT, opt}) // we offer nothing
			case telnetWILL:
				s.write([]byte{telnetIAC, telnetDONT, opt}) // we accept nothing
			}
			i += 2
		case telnetSB: // skip the whole sub-negotiation up to IAC SE
			j := bytes.Index(in[i+2:], []byte{telnetIAC, telnetSE})
			if j < 0 {
				s.iacBuf = append([]byte{}, in[i:]...)
				return
			}
			i += 2 + j + 1
		default:
			i++ // any other two-byte command: ignored
		}
	}
}

func (s *TelnetSession) write(b []byte) {
	_ = s.conn.SetWriteDeadline(time.Now().Add(5 * time.Second))
	_, _ = s.conn.Write(b)
}

// plain is the pending text with ANSI removed and line ends normalised ("\n"); control characters other than \n and \t are dropped (the bell included).
func plain(b []byte) string {
	t := ansiRe.ReplaceAllString(string(b), "")
	t = strings.ReplaceAll(t, "\r\n", "\n")
	t = strings.ReplaceAll(t, "\r", "\n")
	return strings.Map(func(r rune) rune {
		if r == '\n' || r == '\t' || r >= 0x20 && r != 0x7f {
			return r
		}
		return -1
	}, t)
}

func (s *TelnetSession) login(ctx context.Context) error {
	deadline := time.Now().Add(s.cfg.LoginTimeout)
	if d, ok := ctx.Deadline(); ok && d.Before(deadline) {
		deadline = d
	}
	sentUser, sentPass := false, false
	var seen strings.Builder
	for {
		text := plain(s.pend)
		tail := strings.TrimRight(text, " \t\n")
		switch {
		case loginFailed.MatchString(text):
			return fmt.Errorf("%w: the device refused the credentials", ErrTelnetLogin)
		case s.prompt.MatchString(text) && (sentPass || !sentUser):
			s.banner = s.redact(text)
			s.pend = nil
			return nil
		case !sentUser && loginPrompt.MatchString(tail):
			s.write([]byte(s.cfg.User + "\r\n"))
			sentUser = true
			seen.WriteString(text)
			s.pend = nil
			continue
		case sentUser && !sentPass && passPrompt.MatchString(tail):
			s.write([]byte(s.cfg.Password + "\r\n"))
			sentPass = true
			seen.WriteString(text)
			s.pend = nil
			continue
		case sentPass && loginPrompt.MatchString(tail):
			return fmt.Errorf("%w: asked for the login again", ErrTelnetLogin)
		}
		if ctx.Err() != nil {
			return ctx.Err()
		}
		if time.Now().After(deadline) {
			return fmt.Errorf("%w: no prompt before the login timeout", ErrTelnetLogin)
		}
		if err := s.readSome(minTime(deadline, time.Now().Add(500*time.Millisecond))); err != nil && !isTimeout(err) {
			if errors.Is(err, io.EOF) {
				return fmt.Errorf("%w: connection closed by the device", ErrTelnetLogin)
			}
			return fmt.Errorf("%w: %s", ErrTelnetLogin, s.redact(err.Error()))
		}
	}
}

// Run sends one allowlisted command and returns its output up to (not including) the end prompt. Any problem is an error and the output is thrown away.
func (s *TelnetSession) Run(ctx context.Context, cmd string) (string, error) {
	s.mu.Lock()
	defer s.mu.Unlock()
	if s.closed {
		return "", errors.New("telnet: session closed")
	}
	if !SafeCommand(cmd) || strings.ContainsRune(cmd, '?') || s.cfg.Allowed == nil || !s.cfg.Allowed(cmd) {
		return "", fmt.Errorf("%w: %q", ErrCommandDenied, cmd)
	}
	s.pend = nil
	s.write([]byte(cmd + "\r\n"))
	deadline := time.Now().Add(s.cfg.CommandTimeout)
	if d, ok := ctx.Deadline(); ok && d.Before(deadline) {
		deadline = d
	}
	var promptSeenAt time.Time
	for {
		if len(s.pend) > s.cfg.MaxOutput {
			s.proven = false
			return "", fmt.Errorf("telnet: output of %q exceeds %d bytes (discarded)", cmd, s.cfg.MaxOutput)
		}
		text := plain(s.pend)
		if s.prompt.MatchString(text) {
			if promptSeenAt.IsZero() {
				promptSeenAt = time.Now()
			}
		} else {
			promptSeenAt = time.Time{}
		}
		if !promptSeenAt.IsZero() && time.Since(promptSeenAt) >= s.cfg.Quiet {
			return s.finish(cmd, text), nil
		}
		if ctx.Err() != nil {
			s.proven = false
			return "", ctx.Err()
		}
		now := time.Now()
		if now.After(deadline) {
			s.proven = false
			return "", fmt.Errorf("%w: %q", ErrNoPrompt, cmd)
		}
		wait := minTime(deadline, now.Add(100*time.Millisecond))
		if err := s.readSome(wait); err != nil && !isTimeout(err) {
			s.proven = false
			if errors.Is(err, io.EOF) {
				return "", fmt.Errorf("%w: connection closed by the device during %q", ErrNoPrompt, cmd)
			}
			return "", fmt.Errorf("telnet: read: %s", s.redact(err.Error()))
		}
	}
}

// finish drops the echoed command line, the noise lines and the end prompt line.
func (s *TelnetSession) finish(cmd, text string) string {
	lines := strings.Split(text, "\n")
	for len(lines) > 0 && strings.TrimSpace(lines[len(lines)-1]) == "" {
		lines = lines[:len(lines)-1]
	}
	if n := len(lines); n > 0 && s.prompt.MatchString(lines[n-1]) {
		lines = lines[:n-1]
	}
	var out []string
	for i, l := range lines {
		if t := strings.TrimSpace(l); t == cmd || (i < 2 && strings.HasSuffix(t, "> "+cmd)) {
			continue // the device echoes what we typed (alone, or after a redrawn prompt)
		}
		if s.cfg.Noise != nil && s.cfg.Noise.MatchString(l) {
			continue
		}
		out = append(out, l)
	}
	return s.redact(strings.Join(out, "\n")) + "\n"
}

func minTime(a, b time.Time) time.Time {
	if a.Before(b) {
		return a
	}
	return b
}
