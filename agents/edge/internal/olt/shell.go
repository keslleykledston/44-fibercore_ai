package olt

import (
	"context"
	"errors"
	"fmt"
	"io"
	"regexp"
	"strconv"
	"strings"
	"sync"
	"time"

	"golang.org/x/crypto/ssh"
)

// ErrAmbiguousOutput: a line equal to the prompt appeared inside the output, so the end of the command cannot be trusted.
var ErrAmbiguousOutput = errors.New("cli output contains a line identical to the prompt (fail closed)")

// ErrInteractive: the CLI asked a question the Edge never answers (confirmation, password, ...). Fail closed.
var ErrInteractive = errors.New("cli asked an interactive question (fail closed)")

// ErrAfterAnswer marks a question that came AFTER an expected confirmation was answered: the command may have run.
var ErrAfterAnswer = errors.New("cli asked again after the expected confirmation was answered")

// defaultQuietAfterPrompt: how long the line must stay quiet after a candidate prompt. A heuristic, NOT proof of completion
// (see EndProver); it only narrows the window in which a mid-output prompt lookalike can be mistaken for the end.
const defaultQuietAfterPrompt = time.Second

var (
	ansiRe     = regexp.MustCompile(`\x1b\[[0-9;?]*[ -/]*[@-~]`)
	promptRe   = regexp.MustCompile(`^[^\s>#]{1,128}[>#]$`)
	optParamRe = regexp.MustCompile(`\{\s*<cr>[^}]*\}\s*:\s*$`) // Huawei: optional parameters, "<cr>" ends the command
	questionRe = regexp.MustCompile(`(?i)\(\s*y\s*/\s*n\s*\)|\[\s*y\s*/\s*n\s*\]|are you sure|confirm|password\s*:\s*$`)
	// VRP pager: the prompt, then (once a key is pressed) "ESC[<n>D", n blanks and "ESC[<n>D" which overwrite it with the next page.
	moreTailRe   = regexp.MustCompile(`(?i)-{2,}\s*More\s*\(\s*Press\s+'?Q'?\s+to\s+break\s*\)\s*-{2,}$`)
	moreErasedRe = regexp.MustCompile(`(?i)(-{2,}\s*More\s*\(\s*Press\s+'?Q'?\s+to\s+break\s*\)\s*-{2,})\x1b\[(\d+)D( *)\x1b\[(\d+)D`)
)

const defaultMaxPages = 64

// eraseMarkers removes pager prompts the device itself has already overwritten (cursor back by exactly the prompt length,
// blanks, cursor back again). A pager prompt that is NOT erased this way stays in the text and fails closed.
func eraseMarkers(t string) string {
	return moreErasedRe.ReplaceAllStringFunc(t, func(m string) string {
		g := moreErasedRe.FindStringSubmatch(m)
		n := strconv.Itoa(len(g[1]))
		if g[2] == n && g[4] == n && len(g[3]) == len(g[1]) {
			return ""
		}
		return m
	})
}

// shell drives ONE interactive CLI session (pty + shell). Some OLT firmwares (e.g. Huawei MA5608T R015) do not answer SSH
// exec requests, so commands must go through the shell. Everything sent here has already passed ReadOnlySession's exact
// allowlist; the only extra byte the shell ever writes is a single Enter to complete an optional-parameter prompt.
type shell struct {
	sess    *ssh.Session
	in      io.WriteCloser
	timeout time.Duration
	quiet   time.Duration
	pager   bool // press Space (and nothing else) at a VRP "More" prompt
	maxPage int

	mu     sync.Mutex
	buf    strings.Builder
	rerr   error
	notify chan struct{}
	prompt string         // the prompt the last command ended on; it changes with the CLI mode
	pr     *regexp.Regexp // every valid prompt form of this device: <base>[(<mode>)]>|#
	broken bool
}

func openShell(ctx context.Context, c *ssh.Client, timeout, quiet time.Duration, pager bool) (*shell, error) {
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
	if quiet <= 0 {
		quiet = defaultQuietAfterPrompt
	}
	sh := &shell{sess: sess, in: in, timeout: timeout, quiet: quiet, pager: pager, maxPage: defaultMaxPages, notify: make(chan struct{}, 1)}
	go sh.read(out)
	// Learn the prompt from the login banner: the last line, which must look like "NAME>" or "NAME#".
	_, err = sh.wait(ctx, func(t string) (bool, error) {
		if Paginated(t) {
			return false, ErrPaginated
		}
		if last := lastLine(t); promptRe.MatchString(last) {
			base := strings.TrimRight(last, "># ")
			if i := strings.IndexByte(base, '('); i >= 0 {
				base = base[:i]
			}
			if base == "" {
				return false, nil
			}
			sh.prompt = last
			sh.pr = regexp.MustCompile("^" + regexp.QuoteMeta(base) + `(?:\([^()\s]{1,64}\))?[>#]$`)
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
			case <-time.After(s.quiet):
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

func (s *shell) Run(ctx context.Context, cmd string) (string, error) { return s.run(ctx, cmd, nil, "") }

// RunConfirm is Run for ONE command that is known to ask ONE confirmation. If, and only if, the question the CLI shows matches `expect`, `answer` is
// typed (once). Any other question, or a second one, still fails closed.
func (s *shell) RunConfirm(ctx context.Context, cmd string, expect *regexp.Regexp, answer string) (string, error) {
	return s.run(ctx, cmd, expect, answer)
}

// questionError keeps the text the CLI asked (a prompt, no secrets) so the operator can see what it wanted.
func questionError(line string) error {
	line = strings.TrimSpace(line)
	if len(line) > 160 {
		line = line[:160]
	}
	return fmt.Errorf("%w: %q", ErrInteractive, line)
}

func (s *shell) run(ctx context.Context, cmd string, expect *regexp.Regexp, answer string) (string, error) {
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
	answered := false
	askedLine := "" // the question as shown when the answer was typed
	pages, spaceAt := 0, 0
	var final string
	text, err := s.wait(ctx, func(t string) (bool, error) {
		c := stripCtl(eraseMarkers(t))
		tail := strings.TrimRight(c, " \t\n")
		if s.pager && moreTailRe.MatchString(tail) {
			if pages >= s.maxPage {
				return false, ErrPaginated
			}
			if len(t) > spaceAt { // new output since the last key: one Space per pager prompt, never anything else
				spaceAt, pages = len(t), pages+1
				_, err := io.WriteString(s.in, " ")
				return false, err
			}
			return false, nil
		}
		if Paginated(c) {
			return false, ErrPaginated
		}
		if optParamRe.MatchString(tail) {
			if !crSent {
				crSent, crAt = true, len(tail)
				_, err := io.WriteString(s.in, "\r") // Enter completes the SAME command without optional parameters
				return false, err
			}
			if len(tail) > crAt { // new output ended in another parameter prompt: one Enter per command, never more
				return false, questionError(lastLine(c))
			}
			return false, nil // still the stale prompt: the device has not answered the Enter yet
		}
		if questionRe.MatchString(lastLine(c)) {
			ll := strings.TrimSpace(lastLine(c))
			if answered && strings.HasPrefix(ll, askedLine) {
				return false, nil // still the question we answered, now with the echo of our own answer on the line: wait for the device
			}
			if !answered && expect != nil && expect.MatchString(lastLine(c)) {
				answered, askedLine = true, ll
				_, err := io.WriteString(s.in, answer+"\r") // the one expected confirmation, once
				return false, err
			}
			if answered {
				return false, errors.Join(questionError(lastLine(c)), ErrAfterAnswer) // a DIFFERENT question after the answer
			}
			return false, questionError(lastLine(c))
		}
		f, done, err := finished(c, cmd, s.pr)
		final = f
		return done, err
	})
	if err != nil {
		s.broken = true // never reuse a shell in an unknown state
		s.close()
		return "", err
	}
	s.prompt = final
	return tidy(eraseMarkers(text), cmd, final), nil
}

// finished reports whether the command output is complete. The prompt is text the device controls, so the end is only
// accepted when the first non-empty line is exactly the echoed command, the LAST line is a valid prompt of this device
// (the CLI mode, hence the prompt, may change with the command), and no other line looks like a prompt at all; anything
// else that resembles a prompt inside the output is ambiguous and fails closed.
func finished(c, cmd string, pr *regexp.Regexp) (final string, done bool, err error) {
	lines := strings.Split(strings.TrimRight(c, " \t\n"), "\n")
	first := 0
	for first < len(lines) && strings.TrimSpace(lines[first]) == "" {
		first++
	}
	if first >= len(lines)-1 || strings.TrimSpace(lines[first]) != cmd {
		return "", false, nil
	}
	final = strings.TrimSpace(lines[len(lines)-1])
	if !pr.MatchString(final) {
		return "", false, nil
	}
	for _, l := range lines[first : len(lines)-1] {
		if pr.MatchString(strings.TrimSpace(l)) {
			return "", false, ErrAmbiguousOutput
		}
	}
	return final, true, nil
}

// tidy drops ONLY the initial command echo, the optional-parameter prompt that follows it and the trailing prompt; every
// other line is device payload, even if it happens to contain the command text (Huawei prints a "Command:" block).
func tidy(text, cmd, prompt string) string {
	lines := strings.Split(stripCtl(text), "\n")
	end := len(lines) - 1
	for end >= 0 && strings.TrimSpace(lines[end]) == "" {
		end--
	}
	first := 0
	for first < len(lines) && strings.TrimSpace(lines[first]) == "" {
		first++
	}
	var out []string
	for i, l := range lines {
		t := strings.TrimSpace(l)
		switch {
		case i < first:
		case i == first && t == cmd:
		case i == first+1 && optParamRe.MatchString(t) && strings.TrimSpace(lines[first]) == cmd:
		case i == end && t == prompt:
		default:
			out = append(out, l)
		}
	}
	return strings.TrimLeft(strings.Join(out, "\n"), "\n")
}
