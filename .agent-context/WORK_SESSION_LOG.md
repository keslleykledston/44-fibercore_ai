# Work Sessions

## 2026-10-27 — Build kit authored

Specification, planning docs, prompts, inventory seeds, OpenAPI draft, Compose and API demo created. All hardware integrations remain unverified; status must be updated by implementers with real tests.

## 2026-10-27 — Sprint 0 PR 1
Kit validado (SHA256 OK) e importado; ADR 0001–0010; API real + auth + RLS + migrations; Compose validado; 18 testes PASS; OpenAPI alinhado (X-Workspace-ID, ModuleHealth). Codex gate não executado.

## 2026-10-28 — Entrega completa (PRs 1–14 + adendo v2.1)
Sprint 0→3 (parcial) + frontend + ajuda por construção. PRs 1–14 submetidos ao Codex com `approve` na última rodada de cada um (relato do implementador, não verificável por artefatos: ver CODEX_REVIEW_LOG.md). Ver FINAL_REPORT.md. Aprendizados: E2E real pega bugs que unit tests não pegam (lock sem cryptography; servidor next órfão); `pkill -f` mata o próprio shell; portas do host são disputadas.

## 2026-10-28 — GenieACS, publicação TLS, revisão visual
- GenieACS 4WNET levantado (só GET): sem ONU real; 41 fantasmas `DISCOVERYSERVICE`; riscos altos (cwmp.Auth admin/admin pública; preset `Disparar_Homologacao` sem precondição escreve Wi-Fi). Ver `docs/integrations/GENIEACS_4WNET_SURVEY.md`. Nada alterado no GenieACS.
- Publicado `https://fibercore.devops.k3gsolutions.com.br` (estado LAB) atrás do nginx do host (ADR-0016). Cert LE até 2027-01-26, dry-run de renovação OK. Stack `make up-prod` (projeto compose `fibercore-prod`, Caddy em 127.0.0.1:18480, API 127.0.0.1:18420). Admin em `/home/suporte/.fibercore-admin-credentials` (0600, fora do repo).
- E2E dev agora exige `FIBERCORE_API_PORT=18421 VENV_PY=<venv>/bin/python` (18420 é a produção).
- Revisão visual do Lovable aplicada (web/17); Codex approve nas duas branches (raw 16 e 17). 28 E2E passed.
- Pendente: MFA, refresh token, CSP com nonce, ensaio de restore, ONU 360/login em passos, capturas reais de OLT, corrigir GenieACS (decisão do dono).
