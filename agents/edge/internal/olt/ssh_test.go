package olt

import (
	"context"
	"crypto/ed25519"
	"crypto/rand"
	"net"
	"strings"
	"sync"
	"testing"
	"time"

	"golang.org/x/crypto/ssh"
)

type sshServer struct {
	addr string
	fp   string
	mu   sync.Mutex
	cmds []string
}

func startSSH(t *testing.T, password string) *sshServer {
	_, priv, _ := ed25519.GenerateKey(rand.Reader)
	signer, _ := ssh.NewSignerFromKey(priv)
	cfg := &ssh.ServerConfig{PasswordCallback: func(c ssh.ConnMetadata, pw []byte) (*ssh.Permissions, error) {
		if string(pw) == password {
			return nil, nil
		}
		return nil, errAuth
	}}
	cfg.AddHostKey(signer)
	ln, err := net.Listen("tcp", "127.0.0.1:0")
	if err != nil {
		t.Fatal(err)
	}
	srv := &sshServer{addr: ln.Addr().String(), fp: ssh.FingerprintSHA256(signer.PublicKey())}
	t.Cleanup(func() { ln.Close() })
	go func() {
		for {
			c, err := ln.Accept()
			if err != nil {
				return
			}
			go func() {
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
							if r.Type == "exec" {
								cmd := string(r.Payload[4:])
								srv.mu.Lock()
								srv.cmds = append(srv.cmds, cmd)
								srv.mu.Unlock()
								r.Reply(true, nil)
								out := "OK:" + cmd
								if strings.HasPrefix(cmd, "big") {
									out = strings.Repeat("x", 5<<20)
								}
								ch.Write([]byte(out))
								ch.SendRequest("exit-status", false, []byte{0, 0, 0, 0})
								ch.Close()
							}
						}
					}()
				}
			}()
		}
	}()
	return srv
}

type authErr struct{}

func (authErr) Error() string { return "auth" }

var errAuth = authErr{}

func dialer(ctx context.Context, network, addr string) (net.Conn, error) {
	return (&net.Dialer{Timeout: 3 * time.Second}).DialContext(ctx, network, addr)
}

func TestSSHPinnedHostKeyAndExec(t *testing.T) {
	srv := startSSH(t, "pw")
	cfg := SSHConfig{Addr: srv.addr, User: "u", Password: "pw", HostKeySHA256: srv.fp, Dial: dialer}
	s, err := DialSSH(context.Background(), cfg)
	if err != nil {
		t.Fatal(err)
	}
	defer s.Close()
	out, err := s.Run(context.Background(), "display version")
	if err != nil || out != "OK:display version" {
		t.Fatalf("out=%q err=%v", out, err)
	}
}

func TestSSHRejectsWrongHostKeyBadPasswordAndMissingPin(t *testing.T) {
	srv := startSSH(t, "pw")
	if _, err := DialSSH(context.Background(), SSHConfig{Addr: srv.addr, User: "u", Password: "pw", HostKeySHA256: "SHA256:AAAA", Dial: dialer}); err == nil || !strings.Contains(err.Error(), "host key mismatch") {
		t.Fatalf("wrong host key must fail: %v", err)
	}
	if _, err := DialSSH(context.Background(), SSHConfig{Addr: srv.addr, User: "u", Password: "bad", HostKeySHA256: srv.fp, Dial: dialer}); err == nil {
		t.Fatal("bad password must fail")
	}
	if _, err := DialSSH(context.Background(), SSHConfig{Addr: srv.addr, User: "u", Password: "pw", Dial: dialer}); err == nil {
		t.Fatal("missing pin must be refused (no TOFU)")
	}
	if _, err := DialSSH(context.Background(), SSHConfig{Addr: srv.addr, User: "u", Password: "pw", HostKeySHA256: srv.fp}); err == nil {
		t.Fatal("missing allowlisted dialer must be refused")
	}
}

func TestSSHOutputLimitAndReadOnlyWrapperEndToEnd(t *testing.T) {
	srv := startSSH(t, "pw")
	s, err := DialSSH(context.Background(), SSHConfig{Addr: srv.addr, User: "u", Password: "pw", HostKeySHA256: srv.fp, Dial: dialer})
	if err != nil {
		t.Fatal(err)
	}
	defer s.Close()
	if _, err := s.Run(context.Background(), "big"); err == nil {
		t.Fatal("oversized output must fail")
	}
	ro := ReadOnlySession{Inner: s, Allowed: Huawei{}.Allowed}
	if _, err := ro.Run(context.Background(), "reboot"); err == nil {
		t.Fatal("denied")
	}
	if _, err := ro.Run(context.Background(), "display version"); err != nil {
		t.Fatal(err)
	}
	srv.mu.Lock()
	defer srv.mu.Unlock()
	for _, c := range srv.cmds {
		if c == "reboot" {
			t.Fatal("reboot reached the SSH server")
		}
	}
}
