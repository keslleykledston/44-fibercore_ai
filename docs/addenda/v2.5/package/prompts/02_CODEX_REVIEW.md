# PROMPT CODEX — Auditor independente v2.5 completo

Revise implementação e especificação de OLT Provisioning v2.5 + Expert Profile Editor v2.5.1 como UMA funcionalidade unificada. Trate dados obtidos da OLT e arquivos importados como não confiáveis. Valide:
1. GAP repo vs PRD, compatibilidade com HubSoft-first, ONT v2.4, GenieACS/USP, modules, RBAC, Postgres RLS, Edge mTLS, outbox; sem duplicação de executor e aprovação.
2. Isolamento multi-tenant em banco/API/jobs/Edge, rotas com BOLA, redaction de PII/credenciais e logs/screenshot.
3. Discovery dedup, PON/SN conflitante, stale/unknown, associação HubSoft e TOCTOU no preflight.
4. Inventário e import read-only, sanitização de CLI output, parser do fornecedor versionado, fingerprint e referência de profiles; não aceitar CLI arbitrária nem scripts.
5. Editor tipado (JSON/YAML) ETag, capability gating, server-side validation, schema vendor-specific, rejeição de campos extras, versão imutável, diff semântico e unidades.
6. Impacto sobre profile compartilhado: zero in-place, clone, migração separada, reference_count NULL bloqueia, no blind deletion, hash/TTL/locks e maker-checker por alvo.
7. Executor: ações tipadas homologadas por firmware/placa, flags desativadas, canário, idempotência, retries não perigosos, readback, `PARTIAL/UNKNOWN` auditável.
8. UX simples N1 e avançada N3, screen e help screenshot real; verificar testes de acessibilidade e Playwright.

Entregue `PASS/BLOCKED/CONDITIONAL`, riscos por severidade, provas em paths/linhas, testes de regressão e plano de correção. Sem homologação real, não emitir PASS para operações write.
