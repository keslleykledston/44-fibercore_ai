# Deploy da LAB em 2026-11-02: API, Edge e conferência da R-D004

Evidência operacional redigida (nenhum IP, serial, credencial ou conteúdo de backup). Ordem do responsável no chat ("faça": passos 1 a 3). Estado de produção: **LAB**, nenhum gate de produção concedido.

## Antes
- Web da LAB já em `fdf4da8` (deploy anterior da mesma sessão); API/relay/consumer em versão anterior; banco no head **0038**; Edge do host do ACS `0.1.0-lab-90d6b9d`, 1 processo.
- Backup lógico `pg_dump -Fc` feito por `scripts/backup.sh` (`COMPOSE_PROJECT=fibercore-prod`), arquivo `fibercore-20261102T053308Z.dump` (459132 bytes, 0600, **sem cifra**, fora do git em `build/backups`), sha256 do dump: `006e2748c0d02c1e81c234a246e94d2db3edb534c3b033c2af83c31c61ac5345`.

## Passo 1: API e migração
- Comando: `docker compose -p fibercore-prod --env-file .env.prod -f infra/compose/compose.yaml up -d --build migrate api-core outbox-relay event-consumer`.
- `migrate` saiu com sucesso; `alembic_version` = **0039**; colunas `cpes.last_inform_at` e `cpes.last_inform_observed_at` existem (aditivas, nulas; reversão: `alembic downgrade 0038` ou `DROP COLUMN`).
- `api-core`, `outbox-relay` e `event-consumer` `Up (healthy)`; `/livez` 200; `postgres`, `nats`, `proxy` e `web` não foram tocados.
- Dentro do contêiner da API: `diagnostics.RULES` = R-D001, R-D002, R-D003, R-D004 (versão 1).

## Passo 2: Edge
- Binário compilado de `fdf4da8` (`CGO_ENABLED=0 GOOS=linux GOARCH=amd64`, `-X main.version=0.1.0-lab-fdf4da8`), sha256 `d714b504f6e60d7113f1af9a33168b98db936ddafc7e9e54a101d70a05967414`.
- O script esperou o fim de uma coleta da OLT (guard de ritmo), enviou `fibercore-edge.new`, guardou `fibercore-edge.prev` no host e encerrou o processo; o `run.sh` (cron) subiu o novo. **Config inalterada.**
- Log de partida às 05:39:01Z: `fibercore-edge starting` `version 0.1.0-lab-fdf4da8`, 2 coletores, 37 identidades `DISCOVERYSERVICE` descartadas (como antes); 1 processo; versão do binário em execução confirmada.

## Passo 3: conferência com dado real (somente leitura)
- Banco da LAB: **9 CPEs, 9 com `last_inform_at`**, 9 com `last_inform_observed_at` nos últimos 10 min; idade do Inform de 177 s a ~154 dias (CPEs que não informam há muito tempo, sem relação com a bancada).
- R-D004 v1 avaliada pela função pura sobre os dados reais dos 2 vínculos ONU↔CPE **confirmados** (as 2 ONTs de bancada): ONU online com leitura de 270 s, Inform de 185 s e 364 s atrás, snapshot do CPE de 90 s → **`observed`: "the CPE informed the ACS recently"** nas duas. A hipótese `acs_session_stale` **não** ocorreu na LAB; ela segue provada só por teste automatizado.
- Não foi feita execução pela API (`POST /v1/diagnostics/runs`): o administrador da LAB tem MFA e ele não é contornado; a avaliação usou a mesma função pura, fora da API.
