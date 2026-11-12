#!/usr/bin/env python3
"""Interop ADR-0046: proxy HTTP de TESTE entre o Edge Go real e a API (só loopback), para forjar/repetir entregas que a API de verdade nunca emitiria.

Modos (arquivo JSON de controle, relido a cada requisição; ausente = "pass"):
  {"mode":"pass"}            repassa tudo (e, em cada GET .../secret-deliveries/next com 200, GUARDA a resposta em <capture>)
  {"mode":"tamper_sealed"}   troca 1 caractere do blob selado da entrega entregue ao Edge
  {"mode":"tamper_sig"}      troca 1 caractere da assinatura
  {"mode":"tamper_olt"}      troca o nome da OLT (muda a AAD e o que a assinatura cobre)
  {"mode":"replay","file":"<arquivo capturado>"}   no lugar de cada GET .../next responde 200 com a entrega JÁ capturada (mesmo delivery_id, mesmo lease_token)
Registra em <log> uma linha por requisição (método, caminho, status): nenhum corpo, nenhum cabeçalho de autorização.
Uso: edgeproxy.py <porta> <api_base> <controle.json> <log> <capture_dir>
"""
from __future__ import annotations

import json
import os
import sys
import threading
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

PORT, API, CTRL, LOG, CAPTURE = int(sys.argv[1]), sys.argv[2].rstrip("/"), sys.argv[3], sys.argv[4], sys.argv[5]
lock = threading.Lock()


def mode() -> dict:
    try:
        return json.load(open(CTRL))
    except (OSError, ValueError):
        return {"mode": "pass"}


def flip(s: str) -> str:
    return s[:-2] + ("A" if s[-2] != "A" else "B") + s[-1]


class H(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, *a):  # silencioso
        pass

    def _do(self):
        n = int(self.headers.get("content-length") or 0)
        body = self.rfile.read(n) if n else None
        m = mode()
        is_next = self.command == "GET" and self.path.split("?")[0].endswith("/v1/edge/secret-deliveries/next")
        tag = ""
        if is_next and m.get("mode") == "replay":
            data = open(m["file"], "rb").read()
            self._send(200, [("content-type", "application/json")], data)
            self._log(200, "replayed")
            return
        req = urllib.request.Request(API + self.path, data=body, method=self.command)
        for k, v in self.headers.items():
            if k.lower() not in ("host", "content-length", "connection", "accept-encoding"):
                req.add_header(k, v)
        try:
            with urllib.request.urlopen(req, timeout=30) as r:
                status, hdrs, data = r.status, r.getheaders(), r.read()
        except urllib.error.HTTPError as e:
            status, hdrs, data = e.code, e.headers.items(), e.read()
        if is_next and status == 200:
            d = json.loads(data)
            md = m.get("mode")
            if md == "tamper_sealed":
                d["sealed"], tag = flip(d["sealed"]), "tampered:sealed"
            elif md == "tamper_sig":
                d["signature"], tag = flip(d["signature"]), "tampered:signature"
            elif md == "tamper_olt":
                d["olt_name"], tag = d["olt_name"] + "X", "tampered:olt_name"
            data = json.dumps(d).encode()
            with lock:
                if md == "pass":
                    os.makedirs(CAPTURE, exist_ok=True)
                    open(os.path.join(CAPTURE, d["id"] + ".json"), "wb").write(data)
                    tag = "captured"
        self._send(status, [(k, v) for k, v in hdrs if k.lower() not in ("content-length", "transfer-encoding", "connection")], data)
        self._log(status, tag)

    def _send(self, status, hdrs, data):
        self.send_response(status)
        for k, v in hdrs:
            self.send_header(k, v)
        self.send_header("content-length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _log(self, status, tag=""):
        with lock, open(LOG, "a") as f:
            f.write(json.dumps({"method": self.command, "path": self.path.split("?")[0], "status": status, "note": tag}) + "\n")

    do_GET = do_POST = do_PUT = do_DELETE = _do


if __name__ == "__main__":
    ThreadingHTTPServer(("127.0.0.1", PORT), H).serve_forever()
