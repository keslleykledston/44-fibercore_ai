package olt

import (
	"bytes"
	"context"
	"errors"
	"fmt"
	"io"
	"net"
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
}

type SSHSession struct {
	client *ssh.Client
	cfg    SSHConfig
}

// Limitation: commands run on SSH *exec* channels. CLIs that only offer an interactive shell need a shell-mode
// adapter with prompt handling, to be validated per firmware in the lab before use.
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
	conn, chans, reqs, err := ssh.NewClientConn(raw, cfg.Addr, sc)
	if err != nil {
		raw.Close()
		return nil, err
	}
	return &SSHSession{client: ssh.NewClient(conn, chans, reqs), cfg: cfg}, nil
}

func (s *SSHSession) Close() error { return s.client.Close() }

func (s *SSHSession) Run(ctx context.Context, cmd string) (string, error) {
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
