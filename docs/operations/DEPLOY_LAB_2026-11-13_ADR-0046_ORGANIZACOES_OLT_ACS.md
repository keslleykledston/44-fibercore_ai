# Deploy da LAB em 2026-11-13: organizações isoladas, ACS por organização e centro de OLT (ADR-0046)

Evidência operacional redigida (sem IP, credencial, serial ou conteúdo de backup). Ordem do responsável no chat ("pode fazer agora"). Estado: **LAB**, nenhum gate de produção concedido. **Flags `fleet_provision`, `fleet_secrets` e `acs_registry` DESLIGADAS** em todos os provedores e `managed_olts` AUSENTE no Edge: nada novo está ativo.

## O que subiu (ordem: Edge, depois nuvem)
- **Edge (host do GenieACS), ~02:57Z:** binário `0.9.0-lab-d983858` (`CGO_ENABLED=0`, linux/amd64, `-trimpath -s -w`), sha256 `adc75fea…5670` conferido no host. Enviado como `fibercore-edge.new`; o atual (`993adf02…`, 0.9.0-lab-f47ae43) ficou em `fibercore-edge.prev`; trocado depois de o log da coleta da OLT ficar estável por 20 s (o `run.sh` aplica o `.new` na partida). `config.json` **inalterada**; 1 processo; "fibercore-edge starting" com a versão nova; heartbeat vivo na nuvem.
- **Nuvem, ~02:58Z:** `main` em `d983858`. Backup lógico antes (`scripts/backup.sh`, `fibercore-prod`): 638 389 bytes, 720 entradas no `pg_restore -l`, sha256 OK (sem a tabela de entregas). `up -d --build migrate api-core outbox-relay event-consumer job-sweeper` e depois `web --no-deps`. `alembic_version` = **0053** (0051 centro de OLT, 0052 ACS, 0053 organizações). Todos `Up (healthy)`; `/api/livez` 200, `/login` 200, `/rede/frota`, `/rede/acs` e `/plataforma/organizacoes` sem sessão 307 (login).
- **Efeito colateral:** o `migrate` depende do NATS e o Compose **recriou o contêiner do NATS** (volume do JetStream preservado). O `event-consumer` registrou uma única rajada de erro de DNS no instante da recriação (02:58:02Z) e voltou sozinho; depois disso nenhum erro. Diferente do deploy anterior, em que o NATS não foi recriado.

## Verificação
- Antes do deploy, em `main`: API 1296 passed; Go `vet` e `test -race` (19 pacotes) ok; `tsc` ok; Playwright `puros` 78 passed; e2e `funcional`+`frota` 93 passed (inclui o formulário único); interoperação real navegador → API → Edge Go: 9 provas PASS (`INTEROP_ADR-0046_2026-11-12.md`).
- LAB depois do deploy: 5 funções `SECURITY DEFINER` novas existem; flags novas ligadas em 0 provedores; logs de 5 min sem erro em `api-core`, `web`, `outbox-relay` e `job-sweeper`.

## Não feito / limites
- Nada testado na LAB com as flags ligadas nem com `managed_olts` no Edge real; nenhuma OLT real tocada (interop usou servidor SSH de teste).
- Riscos R-2 e R-3 do ADR-0046 aceitos pelo responsável ("prossiga"); as flags continuam desligadas até ele mandar ligar.
- Acesso ao host do Edge por senha do `.env` via script que não imprime valores.

## Para usar (responsável)
1. No Edge, seção `managed_olts` com política local (`allowed_cidrs`, `allowed_ports`, `max_olts`, `allowed_vendors`) e `olt_secrets` (`docs/operations/EDGE_MANAGED_OLTS.md`, `EDGE_SECRETS.md`); reiniciar; `fibercore-edge seal-fingerprint`.
2. `feature-set <tenant> fleet_provision on`, `fleet_secrets on` e (ACS) `acs_registry on`; na tela da OLT confirmar a impressão digital da chave do Edge; cadastrar pelo formulário único; no host do Edge rodar `fibercore-edge managed-trust <nome>`.

## Reversão
- Edge: `mv fibercore-edge.prev fibercore-edge` e `pkill -x fibercore-edge` (o cron religa).
- Nuvem: flags já desligadas; `alembic downgrade 0050` desfaz 0053, 0052 e 0051 (apaga os dados dessas tabelas/colunas); restaurar o backup só se necessário.
