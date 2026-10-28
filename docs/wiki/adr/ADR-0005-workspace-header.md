# ADR-0005: Seleção de tenant via X-Workspace-ID validado

Status: Proposed (aguarda Codex gate) | Data: 2026-10-27 | Owner: Claude Code (implementação)

## Contexto

Contrato v2 define `X-Workspace-ID`; segurança proíbe confiar no header sozinho.

## Decisão

Header só seleciona entre memberships reais. Sem membership ou tenant inexistente => 404 idêntico (não revela existência). Usuário com 1 membership pode omitir o header (contrato diz required; desvio documentado e opcional no OpenAPI); com várias => 400. Service accounts ignoram o header.

## Consequências

Testado em `test_auth_rls.py`.
