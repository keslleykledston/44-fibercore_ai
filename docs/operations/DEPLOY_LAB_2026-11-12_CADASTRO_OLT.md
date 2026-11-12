# Deploy da LAB em 2026-11-12 (02:5x UTC): cadastro de OLT (migração 0048)

Evidência operacional redigida (sem IP, credencial ou conteúdo de backup). Ordem do responsável no chat ("Pode seguir no deploy do cadastro"). Estado: **LAB**, nenhum gate de produção concedido.

## Escopo
Só o commit `c970047` (merge do cadastro de OLT). **Não** foram implantados os commits posteriores de `main` (CSP, observabilidade/migração 0049, imagens por digest, NATS TLS/ACL): seguem integrados em `main` e desligados, sem deploy.

## Antes
- Banco no head **0047**; 2 OLTs, nenhuma com endereço. Disco `/var` com 37 GB livres.
- Backup lógico `pg_dump -Fc` (`scripts/backup.sh`, `COMPOSE_PROJECT=fibercore-prod`): 602 426 bytes, 669 entradas no `pg_restore -l`, `sha256` conferido (OK). Nome/caminho só no host, sem cifra.

## Passos
1. `git checkout c970047` (detached) e `docker compose -p fibercore-prod ... up -d --build migrate api-core outbox-relay event-consumer`. `migrate` saiu com sucesso; `alembic_version` = **0048**; colunas `olts.mgmt_address` (inet) e `olts.snmp_version` existem; `fibercore_app` tem INSERT/UPDATE nelas. `api-core`, `outbox-relay`, `event-consumer` `Up (healthy)`.
2. `up -d --build web`: `Up (healthy)`; `/livez` 200, `/login` 200 pelo proxy, `/rede/frota` sem sessão 307 (login).
3. Dentro da API: `OltIn` aceita `pop_name`, `mgmt_address`, `snmp_version`. Logs de 3 min da API e do web sem erro.
4. `git checkout main` ao fim.

## Não verificado
- Navegação autenticada na UI da LAB (o administrador tem MFA, que não é contornado): o cadastro novo foi provado em pilha efêmera (e2e 4 passed), não na LAB. `postgres`, `nats`, `proxy`, `job-sweeper` não foram tocados.

## Reversão
`alembic downgrade 0047` APAGA as colunas `mgmt_address` e `snmp_version` (e os dados nelas); o código anterior ignora as colunas. Restaurar o backup acima só se necessário.
