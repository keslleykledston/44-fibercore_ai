# Deploy da LAB em 2026-11-12: credenciais de OLT cifradas (ADR-0045) + integração de `main`

Evidência operacional redigida (sem IP, credencial, serial ou conteúdo de backup). Ordem do responsável no chat ("faça o deploy"). Estado: **LAB**, nenhum gate de produção concedido. **Flag `fleet_secrets` DESLIGADA** e seção `olt_secrets` AUSENTE no Edge: nada novo está ativo.

## O que subiu
- **Edge (host do GenieACS), 03:35Z:** binário `0.9.0-lab-f47ae43` (`CGO_ENABLED=0`, linux/amd64, sha256 `993adf02…e1c3` conferido no host). Enviado como arquivo temporário e trocado logo depois de uma coleta da OLT terminar; o binário anterior ficou em `fibercore-edge.prev`. `config.json` **inalterada**; 1 processo; heartbeat com a versão nova 6 s depois; nenhum erro novo no log.
- **Nuvem, ~04:00Z:** `main` inteiro, em `up -d --no-deps` por serviço (Postgres, NATS e proxy NÃO foram recriados). Backup lógico antes (`pg_dump -Fc`, 604 598 bytes, 671 entradas, sha256 OK; já sem a tabela de entregas, `--exclude-table-data`). Migrações 0049 (função de métricas, opt-in) e 0050 (`olt_secret_deliveries`, colunas de chave em `edges`): `alembic_version` = **0050**. `api-core`, `outbox-relay`, `event-consumer`, `job-sweeper` e `web` `Up (healthy)`; `/livez` 200, `/login` 200 pelo proxy.
- Junto, por estarem em `main` (todos desligados por padrão): CSP com nonce em modo **Report-Only** (cabeçalho presente, nada bloqueado), `/metrics` responde 404 (sem token), perfil `observability` não iniciado, imagens base por digest (rebuild puxou as bases pinadas), NATS TLS/ACL não ativado.

## Verificação
- API completa em `main`: 1192 passed; `go vet` e `go test -race ./...` do Edge: todos os pacotes ok; Playwright `puros` 59 passed.
- **Interoperabilidade real (pilha efêmera, não a LAB):** navegador real (Playwright) → API real → **Edge Go real**: o Edge publicou a chave (`pending`), a nuvem mostrou a mesma impressão digital, a confirmação humana liberou, o login/senha digitados foram cifrados no navegador, o Edge os aplicou e gravou o `credentials_file` com modo 0600 e o conteúdo correto. A entrega de `snmp_community` para uma OLT CLI sem `last_down` falhou como projetado (`target_not_configured`).
- LAB depois do deploy: tabela existe e está vazia; flag `fleet_secrets` ligada em 0 provedores; a role da aplicação NÃO lê `sealed`; logs de 3 min sem erro em todos os serviços.

## Não feito / limites
- Nada foi testado na LAB com a flag ligada nem com o Edge real configurado para credenciais.
- Acesso ao host por senha do `.env` via script que não imprime valores; a chave do host foi aceita na primeira conexão (`accept-new`) em `known_hosts` separado, sem conferência de impressão digital.

## Para usar (responsável)
1. No `config.json` do Edge: seção `olt_secrets` e `credentials_file` por OLT (runbook `docs/operations/EDGE_SECRETS.md`; o diretório do armazém deve ser 0700), reiniciar o Edge, rodar `fibercore-edge seal-fingerprint`.
2. `feature-set <tenant> fleet_secrets on`; na tela da OLT confirmar a impressão digital e enviar as credenciais; depois "Testar conexão".

## Reversão
- Edge: `mv fibercore-edge.prev fibercore-edge` e reiniciar (antes, remover `olt_secrets`/`credentials_file` do `config.json`, se tiverem sido adicionados: o binário antigo rejeita as chaves).
- Nuvem: desligar a flag; `alembic downgrade 0048` apaga a tabela de entregas, as funções de métricas e as colunas de chave (e o conteúdo); restaurar o backup só se necessário.
