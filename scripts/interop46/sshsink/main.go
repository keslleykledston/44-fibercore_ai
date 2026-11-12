// sshsink: servidor SSH de TESTE da interoperação do ADR-0046. Não é código de produção e não fica em agents/.
// Escuta em N endereços (um por IP:porta), tem UMA chave de host conhecida (a impressão digital sai em -fingerprint-file) e REGISTRA
// toda tentativa de conexão numa linha JSON (-log): aceite TCP, falha de handshake (o cliente abortou, p.ex. chave do host diferente da pinada),
// tentativa de autenticação (usuário + se a senha confere com a esperada; NUNCA a senha) e comandos executados.
// A senha esperada vem de -user/-pass-file (valores de teste descartáveis).
package main

import (
	"crypto/ed25519"
	"crypto/rand"
	"crypto/subtle"
	"encoding/json"
	"encoding/pem"
	"flag"
	"fmt"
	"io"
	"net"
	"os"
	"strings"
	"sync"
	"time"

	"golang.org/x/crypto/ssh"
)

var (
	logMu sync.Mutex
	logF  *os.File
)

func rec(m map[string]any) {
	m["ts"] = time.Now().UTC().Format(time.RFC3339Nano)
	b, _ := json.Marshal(m)
	logMu.Lock()
	defer logMu.Unlock()
	logF.Write(append(b, '\n'))
}

func main() {
	listen := flag.String("listen", "", "lista IP:porta separada por vírgula")
	logPath := flag.String("log", "", "arquivo de log (JSON por linha)")
	fpPath := flag.String("fingerprint-file", "", "onde gravar a impressão digital SHA256 da chave do host")
	user := flag.String("user", "", "usuário esperado")
	passFile := flag.String("pass-file", "", "arquivo com a senha esperada")
	keyFile := flag.String("host-key-file", "", "chave privada do host (criada se não existir)")
	udp := flag.String("udp", "", "lista IP:porta UDP (SNMP de teste): cada datagrama é registrado e NÃO é respondido")
	flag.Parse()
	pw, err := os.ReadFile(*passFile)
	if err != nil || *listen == "" || *logPath == "" || *user == "" {
		fmt.Fprintln(os.Stderr, "uso: sshsink -listen IP:PORTA[,..] -log F -fingerprint-file F -user U -pass-file F")
		os.Exit(2)
	}
	expected := strings.TrimRight(string(pw), "\r\n")
	logF, err = os.OpenFile(*logPath, os.O_CREATE|os.O_WRONLY|os.O_APPEND, 0o600)
	if err != nil {
		panic(err)
	}
	_, priv, _ := ed25519.GenerateKey(rand.Reader)
	signer, _ := ssh.NewSignerFromKey(priv)
	if *keyFile != "" { // chave do host estável entre reinícios do sink (a impressão digital pinada nos Edges continua valendo)
		if raw, err := os.ReadFile(*keyFile); err == nil {
			if sg, err := ssh.ParsePrivateKey(raw); err == nil {
				signer = sg
			}
		} else {
			blk, _ := ssh.MarshalPrivateKey(priv, "")
			if err := os.WriteFile(*keyFile, pem.EncodeToMemory(blk), 0o600); err != nil {
				panic(err)
			}
		}
	}
	if err := os.WriteFile(*fpPath, []byte(ssh.FingerprintSHA256(signer.PublicKey())+"\n"), 0o600); err != nil {
		panic(err)
	}
	for _, addr := range strings.Split(*listen, ",") {
		ln, err := net.Listen("tcp", addr)
		if err != nil {
			fmt.Fprintln(os.Stderr, "listen:", err)
			os.Exit(1)
		}
		go func(addr string, ln net.Listener) {
			for {
				c, err := ln.Accept()
				if err != nil {
					return
				}
				go serve(addr, c, signer, *user, expected)
			}
		}(addr, ln)
	}
	if *udp != "" {
		for _, addr := range strings.Split(*udp, ",") {
			ua, err := net.ResolveUDPAddr("udp", addr)
			if err != nil {
				panic(err)
			}
			pc, err := net.ListenUDP("udp", ua)
			if err != nil {
				fmt.Fprintln(os.Stderr, "listen udp:", err)
				os.Exit(1)
			}
			go func(addr string, pc *net.UDPConn) {
				b := make([]byte, 2048)
				for {
					n, _, err := pc.ReadFromUDP(b)
					if err != nil {
						return
					}
					rec(map[string]any{"event": "udp_packet", "listener": addr, "bytes": n}) // só o tamanho: o conteúdo (community v2c) nunca é gravado
				}
			}(addr, pc)
		}
	}
	fmt.Println("sshsink pronto")
	select {}
}

func serve(listener string, c net.Conn, signer ssh.Signer, user, pass string) {
	defer c.Close()
	rec(map[string]any{"event": "tcp_accept", "listener": listener})
	cfg := &ssh.ServerConfig{
		PasswordCallback: func(m ssh.ConnMetadata, p []byte) (*ssh.Permissions, error) {
			ok := subtle.ConstantTimeCompare([]byte(m.User()), []byte(user)) == 1 && subtle.ConstantTimeCompare(p, []byte(pass)) == 1
			rec(map[string]any{"event": "auth_attempt", "listener": listener, "user_ok": m.User() == user, "password_ok": ok})
			if ok {
				return nil, nil
			}
			return nil, fmt.Errorf("denied")
		},
	}
	cfg.AddHostKey(signer)
	conn, chans, reqs, err := ssh.NewServerConn(c, cfg)
	if err != nil {
		rec(map[string]any{"event": "handshake_failed", "listener": listener, "err": err.Error()})
		return
	}
	defer conn.Close()
	rec(map[string]any{"event": "session_open", "listener": listener})
	go ssh.DiscardRequests(reqs)
	for nc := range chans {
		if nc.ChannelType() != "session" {
			nc.Reject(ssh.UnknownChannelType, "no")
			continue
		}
		ch, rq, _ := nc.Accept()
		go func() {
			defer ch.Close()
			for r := range rq {
				switch r.Type {
				case "exec":
					cmd := ""
					if len(r.Payload) > 4 {
						cmd = string(r.Payload[4:])
					}
					rec(map[string]any{"event": "exec", "listener": listener, "cmd": cmd})
					r.Reply(true, nil)
					ch.SendRequest("exit-status", false, []byte{0, 0, 0, 0})
					return
				case "pty-req", "shell":
					r.Reply(true, nil)
					if r.Type == "shell" {
						rec(map[string]any{"event": "shell", "listener": listener})
						io.WriteString(ch, "\r\n")
						return
					}
				default:
					r.Reply(false, nil)
				}
			}
		}()
	}
}
