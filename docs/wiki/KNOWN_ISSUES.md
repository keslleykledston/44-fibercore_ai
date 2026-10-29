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
- Login: o lockout por conta permite DoS direcionado (quem conhece o e-mail bloqueia por 15 min); mitigações: throttle por IP (30 falhas/15 min; `TRUSTED_PROXY=true` atrás do Caddy), recuperação `python -m app.cli unlock-login <chave>`; desafio/atraso progressivo e MFA permanecem pendentes.
- Throttle por IP: depende do `X-Forwarded-For` do Caddy repassado pelo BFF; em Compose dev a porta 127.0.0.1:18420 do api-core permite spoof de XFF (só afeta o limite por IP; o lockout por conta continua). Não publicar essa porta.
- E2E: `assinantes: ... aprovação` falhou 2 vezes em ~10 execuções locais (não reproduzido em 6 consecutivas); causa não identificada. CI usa `retries: 1`; investigar com trace se reaparecer.
- **GenieACS real (inspecionado em 2026-10-29, somente leitura)**: o NBI (porta 7557) responde **sem autenticação** e escuta em **todas** as interfaces do host (de fora do host a conexão foi recusada a partir do servidor do FiberCore, o que sugere firewall, mas isso não prova que a internet não alcança). O NBI do GenieACS também ESCREVE: restringir a loopback/rede privada e exigir autenticação antes de qualquer uso além de leitura pelo Edge. A porta CWMP também escuta em todas as interfaces. Dos 43 dispositivos, 37 são identidades provisórias `DISCOVERYSERVICE` (serial aleatório a cada Inform, desde abril); o Edge agora as descarta. Restam 6 entradas, 5 delas de teste/laboratório: a base de CPEs reais do GenieACS ainda está praticamente vazia (as ONTs ainda não apontam para ele).
