# ADR-0011: Identidade do Edge e estratégia de segredos

Status: Proposed (aguarda Codex gate) | Data: 2026-10-27 | Owner: Claude Code

## Contexto
O Edge acessa GenieACS/OLT dentro do ISP e fala com o Cloud só outbound. Segredos (NBI, OLT, JWT) não podem ir a Git, logs, LLM ou ao Cloud em texto claro.

## Decisão
1. **Identidade:** alvo = mTLS com certificado curto por Edge; interino (Sprint 0) = service account `edge_agent` (token 15 min, permissão única `edge:heartbeat`). Registro e revogação de Edge são operações do role dono (CLI), nunca da API.
2. **Segredos do Cloud:** variáveis de ambiente ou Docker secrets (`*_FILE`); `.env.dev` gerado aleatório e ignorado pelo Git; `.env` do operador nunca lido por agentes.
3. **Segredos de dispositivo (NBI/OLT):** ficam **somente no Edge** (arquivo com permissão 0600 ou secret store local). O Cloud guarda apenas `credential_secret_ref`. Nada de credencial em `edges`, jobs, outbox ou logs.
4. **Rotação:** token de service account curto; certificados curtos; segredo mostrado uma vez na criação.
5. **Allowlist de destino** definida localmente no Edge (anti-SSRF).

## Consequências
Mock Edge (`tools/mocks/edge.py`) prova allowlist e heartbeat. Pendências: mTLS real, CRL, rate-limit de heartbeat, rotação automática.
