# Known issues

- GenieACS remoto existente ainda não inspecionado; a URL NBI, versão, ACL e permissões serão levantadas por administrador.
- USP Controller de produção não escolhido/homologado; laboratório deve avaliar OB-USPC e alternativas, requisitos de escala/licença.
- Catálogo FTTx não equivale a driver testado. Não executar comandos sem fixtures/homologação.
- API e docker bootstrap são scaffolding, não aplicação pronta; o P0 de segurança ainda é atividade de Sprint 0.

- `users_global.password_hash` legível pelo role runtime (sem RLS). Mitigar com função SECURITY DEFINER.
- Login: lockout por conta após 5 falhas/15 min (tabela `login_attempts`, `Retry-After: 900`; aceita o risco de bloqueio malicioso de uma conta). **Ainda sem** rate-limit por IP, MFA, refresh token ou revogação de token antes do `exp` (TTL 15 min).
- Header `X-Workspace-ID` opcional para usuário com 1 membership (contrato original: obrigatório).
- NATS em dev sem TLS/ACL. Imagens Docker por tag, não digest.
- `/livez` `/readyz` `/version` estão na raiz (fora de `/v1`); contrato OpenAPI ainda não os descreve.
- Tabelas de domínio (edges, olts, onus, cpes, jobs…) do `postgres_baseline_draft.sql` ainda não migradas.
- JetStream: `FIBERCORE_EVENTS` sem expiração por idade (max_age=0); definir `max_bytes` + alerta de uso antes de piloto. `published_at` ≠ consumido. Recuperação: `python -m app.workers.relay replay <ISO-ts> [tenant]` (replay incrementa `replay_gen` => novo Nats-Msg-Id, ignora a janela de dedupe; consumidores idempotentes pelo ledger).
- Ingestão: limite 5000 ONU/CPE por snapshot e 8 MiB por corpo; ainda sem rate-limit por agente (a implementar no Gateway/proxy ou middleware com Redis/NATS KV). Chunked upload recusado (411).
- Drivers OLT: fixtures sintéticas; comandos/colunas reais por firmware NÃO validados. Transporte SSH usa canal `exec`; CLIs que exigem shell interativo precisam de adapter com prompt (homologar em lab). SNMP ainda não implementado. Senha de OLT em arquivo 0600 no Edge (sem cofre).
- Job gate: sem sweeper periódico (varredura oportunista no `next`); sem rotação de chave de assinatura (kid) ainda; `JOB_SIGNING_KEY` vem de env — usar secret manager antes de piloto.
- Web: `npm audit` reporta postcss (dependência interna do Next 15.5.28, só em build; CSS é nosso). Corrigir ao migrar para Next >=16.4 (breaking) — pendente. Sem CSP ainda (Next exige nonces); HSTS só após TLS real.
- Web: `/v1/auth/workspaces` + seletor de workspace implementados; MFA/refresh/rate-limit ainda ausentes (bloqueiam publicação).
- Capturas: tempos relativos são mascarados (cinza) nas imagens; seed recria dados a cada execução.
