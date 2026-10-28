package olt

import (
	"context"
	"errors"
	"fmt"
	"io"
	"regexp"
	"strings"
	"sync"
	"time"

	"golang.org/x/crypto/ssh"
)

// ErrAmbiguousOutput: a line equal to the prompt appeared inside the output, so the end of the command cannot be trusted.
var ErrAmbiguousOutput = errors.New("cli output contains a line identical to the prompt (fail closed)")

// ErrInteractive: the CLI asked a question the Edge never answers (confirmation, password, ...). Fail closed.
var ErrInteractive = errors.New("cli asked an interactive question (fail closed)")

const quietAfterPrompt = 150 * time.Millisecond

var (
	ansiRe     = regexp.MustCompile(`\x1b\[[0-9;?]*[ -/]*[@-~]`)
	promptRe   = regexp.MustCompile(`^[^\s>#]{1,128}[>#]$`)
	optParamRe = regexp.MustCompile(`\{\s*<cr>[^}]*\}\s*:\s*$`) // Huawei: optional parameters, "<cr>" ends the command
	questionRe = regexp.MustCompile(`(?i)\(\s*y\s*/\s*n\s*\)|\[\s*y\s*/\s*n\s*\]|are you sure|confirm|password\s*:\s*$`)
)

// shell drives ONE interactive CLI session (pty + shell). Some OLT firmwares (e.g. Huawei MA5608T R015) do not answer SSH
// exec requests, so commands must go through the shell. Everything sent here has already passed ReadOnlySession's exact
// allowlist; the only extra byte the shell ever writes is a single Enter to complete an optional-parameter prompt.
type shell struct {
	sess    *ssh.Session
	in      io.WriteCloser
	timeout time.Duration

	mu     sync.Mutex
	buf    strings.Builder
	rerr   error
	notify chan struct{}
	prompt string
	broken bool
}

func openShell(ctx context.Context, c *ssh.Client, timeout time.Duration) (*shell, error) {
	sess, err := c.NewSession()
	if err != nil {
		return nil, err
	}
	// ECHO off: the device echoes on its own; the window is only a protocol parameter, no CLI command is involved.
	if err := sess.RequestPty("vt100", 512, 200, ssh.TerminalModes{ssh.ECHO: 0}); err != nil {
		sess.Close()
		return nil, err
	}
	in, err := sess.StdinPipe()
	if err != nil {
		sess.Close()
		return nil, err
	}
	out, err := sess.StdoutPipe()
	if err != nil {
		sess.Close()
		return nil, err
	}
	if err := sess.Shell(); err != nil {
		sess.Close()
		return nil, err
	}
	sh := &shell{sess: sess, in: in, timeout: timeout, notify: make(chan struct{}, 1)}
	go sh.read(out)
	// Learn the prompt from the login banner: the last line, which must look like "NAME>" or "NAME#".
	_, err = sh.wait(ctx, func(t string) (bool, error) {
		if Paginated(t) {
			return false, ErrPaginated
		}
		if last := lastLine(t); promptRe.MatchString(last) {
			sh.prompt = last
			return true, nil
		}
		return false, nil
	})
	if err != nil {
		sh.close()
		return nil, fmt.Errorf("shell login: %w", err)
	}
	sh.reset()
	return sh, nil
}

func (s *shell) read(r io.Reader) {
	b := make([]byte, 4096)
	for {
		n, err := r.Read(b)
		s.mu.Lock()
		if n > 0 {
			if s.buf.Len()+n > maxOutput {
				s.rerr = errors.New("ssh: output too large")
			} else {
				s.buf.Write(b[:n])
			}
		}
		if err != nil && s.rerr == nil {
			s.rerr = err
		}
		s.mu.Unlock()
		select {
		case s.notify <- struct{}{}:
		default:
		}
		if err != nil || s.rerr != nil {
			return
		}
	}
}

func (s *shell) reset() {
	s.mu.Lock()
	s.buf.Reset()
	s.mu.Unlock()
	select {
	case <-s.notify:
	default:
	}
}

func stripCtl(t string) string { return strings.ReplaceAll(ansiRe.ReplaceAllString(t, ""), "\r", "") }

func lastLine(t string) string {
	t = strings.TrimRight(stripCtl(t), " \t\n")
	if i := strings.LastIndex(t, "\n"); i >= 0 {
		t = t[i+1:]
	}
	return strings.TrimSpace(t)
}

// wait polls the accumulated output until cond reports done, the read side fails, the deadline passes or ctx is cancelled.
func (s *shell) wait(ctx context.Context, cond func(text string) (bool, error)) (string, error) {
	deadline := time.NewTimer(s.timeout)
	defer deadline.Stop()
	for {
		s.mu.Lock()
		text, rerr := s.buf.String(), s.rerr
		s.mu.Unlock()
		if done, err := cond(text); err != nil {
			return text, err
		} else if done {
			// The prompt is device-controlled text: only trust it once the line has been quiet for a moment.
			select {
			case <-s.notify:
				continue
			case <-time.After(quietAfterPrompt):
				return text, nil
			case <-ctx.Done():
				return text, ctx.Err()
			}
		}
		if rerr != nil {
			return text, rerr
		}
		select {
		case <-s.notify:
		case <-deadline.C:
			return text, errors.New("ssh: command timeout")
		case <-ctx.Done():
			return text, ctx.Err()
		}
	}
}

func (s *shell) close() {
	s.in.Close()
	s.sess.Close()
}

func (s *shell) Run(ctx context.Context, cmd string) (string, error) {
	if s.broken {
		return "", errors.New("ssh: shell closed after a previous failure")
	}
	s.reset()
	if _, err := io.WriteString(s.in, cmd+"\r"); err != nil {
		s.broken = true
		s.close()
		return "", err
	}
	crSent, crAt := false, 0
	text, err := s.wait(ctx, func(t string) (bool, error) {
		c := stripCtl(t)
		if Paginated(c) {
			return false, ErrPaginated
		}
		tail := strings.TrimRight(c, " \t\n")
		if optParamRe.MatchString(tail) {
			if !crSent {
				crSent, crAt = true, len(tail)
				_, err := io.WriteString(s.in, "\r") // Enter completes the SAME command without optional parameters
				return false, err
			}
			if len(tail) > crAt { // new output ended in another parameter prompt: one Enter per command, never more
				return false, ErrInteractive
			}
			return false, nil // still the stale prompt: the device has not answered the Enter yet
		}
		if questionRe.MatchString(lastLine(c)) {
			return false, ErrInteractive
		}
		return finished(c, cmd, s.prompt)
	})
	if err != nil {
		s.broken = true // never reuse a shell in an unknown state
		s.close()
		return "", err
	}
	return tidy(text, cmd, s.prompt), nil
}

// finished reports whether the command output is complete. The prompt is text the device controls, so the end is only
// accepted when the first non-empty line is exactly the echoed command, the LAST line is exactly the learned prompt, and no
// other line equals the prompt; anything else that looks like a prompt inside the output is ambiguous and fails closed.
func finished(c, cmd, prompt string) (bool, error) {
	lines := strings.Split(strings.TrimRight(c, " \t\n"), "\n")
	first := 0
	for first < len(lines) && strings.TrimSpace(lines[first]) == "" {
		first++
	}
	if first >= len(lines)-1 || strings.TrimSpace(lines[first]) != cmd {
		return false, nil
	}
	if strings.TrimSpace(lines[len(lines)-1]) != prompt {
		return false, nil
	}
	for _, l := range lines[first : len(lines)-1] {
		if strings.TrimSpace(l) == prompt {
			return false, ErrAmbiguousOutput
		}
	}
	return true, nil
}

// tidy drops the command echo, the optional-parameter prompt and the trailing prompt, keeping the device output.
func tidy(text, cmd, prompt string) string {
	lines := strings.Split(stripCtl(text), "\n")
	end := len(lines) - 1
	for end >= 0 && strings.TrimSpace(lines[end]) == "" {
		end--
	}
	var out []string
	echoed := false
	for i, l := range lines {
		t := strings.TrimSpace(l)
		switch {
		case !echoed && strings.Contains(t, cmd):
			echoed = true
		case optParamRe.MatchString(t):
		case i == end && strings.HasSuffix(t, prompt):
		default:
			out = append(out, l)
		}
	}
	return strings.TrimLeft(strings.Join(out, "\n"), "\n")
}
