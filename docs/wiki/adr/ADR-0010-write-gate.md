# ADR-0010: Escrita em rede bloqueada por padrão; sem LLM executor

Status: Proposed (aguarda Codex gate) | Data: 2026-10-27 | Owner: Claude Code (implementação)

## Contexto

Regra de segurança do kit.

## Decisão

Nenhum endpoint de escrita em equipamento existe. Job gate (preview→aprovação→pós-check) só na Sprint 3, após homologação por firmware. LLM nunca executa comandos de rede.

## Consequências

Revisão Codex deve bloquear qualquer PR que viole.
