# Known issues

- GenieACS remoto existente ainda não inspecionado; a URL NBI, versão, ACL e permissões serão levantadas por administrador.
- USP Controller de produção não escolhido/homologado; laboratório deve avaliar OB-USPC e alternativas, requisitos de escala/licença.
- Catálogo FTTx não equivale a driver testado. Não executar comandos sem fixtures/homologação.
- API e docker bootstrap são scaffolding, não aplicação pronta; o P0 de segurança ainda é atividade de Sprint 0.

- `users_global.password_hash` legível pelo role runtime (sem RLS). Mitigar com função SECURITY DEFINER.
- Sem rate-limit/lockout no login, sem MFA, sem refresh token, sem revogação de token antes do `exp` (TTL 15 min).
- Header `X-Workspace-ID` opcional para usuário com 1 membership (contrato original: obrigatório).
- NATS em dev sem TLS/ACL. Imagens Docker por tag, não digest.
- `/livez` `/readyz` `/version` estão na raiz (fora de `/v1`); contrato OpenAPI ainda não os descreve.
- Tabelas de domínio (edges, olts, onus, cpes, jobs…) do `postgres_baseline_draft.sql` ainda não migradas.
- JetStream: `FIBERCORE_EVENTS` sem expiração por idade (max_age=0); definir `max_bytes` + alerta de uso antes de piloto. `published_at` ≠ consumido. Recuperação: `python -m app.workers.relay replay <ISO-ts> [tenant]` (replay dentro da janela de dedupe de 1h é descartado pelo bus; consumidores idempotentes).
