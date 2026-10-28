package olt

import (
	"bytes"
	"context"
	"errors"
	"fmt"
	"io"
	"net"
	"sync"
	"time"

	"golang.org/x/crypto/ssh"
)

const maxOutput = 4 << 20

// DialFunc must be the allowlist-enforcing dialer (allowlist.List.DialContext).
type DialFunc func(ctx context.Context, network, addr string) (net.Conn, error)

type SSHConfig struct {
	Addr          string
	User          string
	Password      string
	HostKeySHA256 string // "SHA256:..." pinned fingerprint; mandatory (no trust-on-first-use, no InsecureIgnoreHostKey)
	Dial          DialFunc
	CommandTimout time.Duration
	// Shell: run commands in an interactive pty shell (one per session) instead of SSH exec. Needed by firmwares that
	// ignore exec requests (validated: Huawei MA5608T R015).
	Shell bool
	// PromptQuiet: silence required after a candidate prompt in shell mode (default 1s). Not proof of completion.
	PromptQuiet time.Duration
	// Legacy: allow ONLY the old algorithm set some OLT firmwares still require (DH group1/group14-SHA1, ssh-rsa, AES-CBC).
	// A per-OLT, explicit downgrade; the pinned host key stays mandatory, so a downgrade cannot be exploited by a MITM.
	Legacy bool
}

type SSHSession struct {
	client *ssh.Client
	cfg    SSHConfig
	mu     sync.Mutex
	sh     *shell
}

// Commands run on SSH exec channels by default; cfg.Shell switches to an interactive shell with prompt handling.
func DialSSH(ctx context.Context, cfg SSHConfig) (*SSHSession, error) {
	if cfg.HostKeySHA256 == "" || cfg.Dial == nil {
		return nil, errors.New("ssh: host key fingerprint and allowlisted dialer are required")
	}
	if cfg.CommandTimout == 0 {
		cfg.CommandTimout = 30 * time.Second
	}
	raw, err := cfg.Dial(ctx, "tcp", cfg.Addr)
	if err != nil {
		return nil, err
	}
	sc := &ssh.ClientConfig{
		User: cfg.User,
		Auth: []ssh.AuthMethod{ssh.Password(cfg.Password)},
		HostKeyCallback: func(_ string, _ net.Addr, key ssh.PublicKey) error {
			if got := ssh.FingerprintSHA256(key); got != cfg.HostKeySHA256 {
				return fmt.Errorf("ssh: host key mismatch (got %s)", got)
			}
			return nil
		},
		Timeout: 15 * time.Second,
	}
	if cfg.Legacy {
		sc.KeyExchanges = []string{"diffie-hellman-group14-sha1", "diffie-hellman-group1-sha1"}
		sc.Ciphers = []string{"aes128-ctr", "aes128-cbc"}
		sc.HostKeyAlgorithms = []string{ssh.KeyAlgoRSA}
	}
	conn, chans, reqs, err := ssh.NewClientConn(raw, cfg.Addr, sc)
	if err != nil {
		raw.Close()
		return nil, err
	}
	return &SSHSession{client: ssh.NewClient(conn, chans, reqs), cfg: cfg}, nil
}

// EndProven: SSH exec has an in-band end (EOF + exit status); the shell mode infers it from the prompt and cannot prove it.
func (s *SSHSession) EndProven() bool { return !s.cfg.Shell }

// Close tears the connection down FIRST, so a Run blocked in openShell or waiting for a prompt is released immediately
// instead of Close waiting for the command timeout behind s.mu.
func (s *SSHSession) Close() error {
	err := s.client.Close()
	s.mu.Lock()
	if s.sh != nil {
		s.sh.close()
	}
	s.mu.Unlock()
	return err
}

func (s *SSHSession) Run(ctx context.Context, cmd string) (string, error) {
	if s.cfg.Shell {
		s.mu.Lock()
		defer s.mu.Unlock()
		if s.sh == nil {
			sh, err := openShell(ctx, s.client, s.cfg.CommandTimout, s.cfg.PromptQuiet)
			if err != nil {
				return "", err
			}
			s.sh = sh
		}
		return s.sh.Run(ctx, cmd)
	}
	sess, err := s.client.NewSession()
	if err != nil {
		return "", err
	}
	defer sess.Close()
	var out bytes.Buffer
	sess.Stdout = &limitedWriter{w: &out, left: maxOutput}
	done := make(chan error, 1)
	go func() { done <- sess.Run(cmd) }()
	select {
	case err := <-done:
		if err != nil {
			return "", err
		}
		return out.String(), nil
	case <-time.After(s.cfg.CommandTimout):
		sess.Close()
		return "", errors.New("ssh: command timeout")
	case <-ctx.Done():
		sess.Close()
		return "", ctx.Err()
	}
}

type limitedWriter struct {
	w    io.Writer
	left int
}

func (l *limitedWriter) Write(p []byte) (int, error) {
	if len(p) > l.left {
		return 0, errors.New("ssh: output too large")
	}
	l.left -= len(p)
	return l.w.Write(p)
}
