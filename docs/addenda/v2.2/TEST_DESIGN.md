# v2.2 — Desenho de testes (matriz de aceite × evidência real hoje × plano)

Nada do adendo foi executado "por ele": a coluna *Hoje* só cita testes que **existem e rodam** no repo (pytest 195, E2E, validadores). *Plano* é o que será criado, no PR indicado.

| AC | Gate | Hoje (evidência real) | Plano |
|---|---|---|---|
| AC-001 | Incremental | PRs mergeados com Codex; migrações aditivas; `tests/validate_addendum_v22.py` (este PR) | cada PR: diff aditivo + checksum do adendo |
| AC-002 | Tenant | `test_auth_rls.py`, `test_onu360.py`, `test_members.py` (A/B, 404/403) | idem para cada rota nova (PR 35: capacidades A/B) |
| AC-003 | Identidade | `test_inventory.py` (serial canônico, conflitos, binding único) | ADR-0021: vínculo ONU↔CPE com evidência |
| AC-004 | Freshness | `test_noc.py` (Edge silencioso ⇒ `edge_silent`), `test_inventory.py` (stale ≠ offline) | estender a blocos novos |
| AC-005 | Capability | `test_jobs.py` (escrita `operation_not_homologated`) | PR 35: `unknown` padrão; FC22-014: gate por perfil |
| AC-006 | Subscriber 360 | `test_onu360.py` (parcial: `source`, `observed_at` no ONU 360) | FC22-004/005 |
| AC-007 | Diagnóstico | regra `pon_mass_outage` testada em `test_noc.py` | FC22-006: versão + execuções reproduzíveis |
| AC-008 | QoE | — | FC22-011: `insufficient_data` sem dado |
| AC-009 | NOC | `test_noc.py` (correlação por quedas, ADR-0018) | FC22-009 (impacto) |
| AC-010 | Workflow | `test_jobs.py` (preview, aprovações, TTL, nonce) | FC22-014 |
| AC-011 | Dual-stack | — (USP não implementado) | quando houver 2º protocolo |
| AC-012 | Resiliência | `test_modules.py`, readiness fail-closed | módulos opcionais novos |
| AC-013 | UX | E2E axe claro/escuro, teclado | por tela |
| AC-014 | Help | `validate_help.py`, `help-screenshots.spec.ts` (10 artigos) | por tela |
| AC-015 | Segurança | `scripts/secrets-scan.sh`, testes de não-eco de PII/segredos | idem + varredura das capturas |
| AC-016 | Docs | CHANGELOG/ADR/raw reviews por PR | idem |
| AC-017 | API | `validate_kit.py` (contrato vigente) + `validate_addendum_v22.py` (reconciliado) | contract tests por rota |
| AC-018 | Performance | — | medir p95 em fixture antes de alegar |
