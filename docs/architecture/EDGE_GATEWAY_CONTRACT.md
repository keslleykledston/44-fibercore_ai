# Contrato Edge ↔ Gateway (v1, rascunho implementável)

- **Transporte alvo:** Edge abre conexão **outbound** TCP 443 (WebSocket ou gRPC stream) com TLS 1.3 e **mTLS**. Certificado de cliente curto (24 h–7 d), CN/SAN = `edge_id`, serial registrado em `edges.certificate_serial`; revogação = `edges.status='revoked'` + CRL no gateway.
- **Frames:** `contracts/edge-frame.schema.json` (`hello`, `heartbeat`, `job`, `job_ack`, `job_result`, `snapshot`). `job` carrega `contracts/job-envelope.schema.json` (assinado, com `nonce`, `expires_at`, `intent_sha256`).
- **Anti-replay:** `seq` monotônico por sessão; `nonce` de job guardado pelo Edge até `expires_at`; job expirado ou nonce repetido => rejeitado e reportado.
- **Allowlist local:** URL do GenieACS NBI e IPs de OLT vêm do arquivo de config do Edge, nunca do Cloud. Pedido para host fora da lista => `denied` + evento de auditoria.
- **Somente operações tipadas:** nenhuma string de comando livre; `operation` ∈ enum do envelope. Na Sprint 1 só `collect`/`refresh` (R0).
- **Offline:** Edge enfileira resultados em SQLite WAL e reenvia com `seq`; Cloud marca dados como `stale` por frescor, nunca "offline falso" por falha do Edge.
- **Interino implementado (Sprint 0):** `POST /v1/edge/heartbeat` com bearer de service account (`edge_agent`), validado em `tests/test_edge.py`. O stream mTLS é entrega da Sprint 1 (Edge Go + Gateway).
