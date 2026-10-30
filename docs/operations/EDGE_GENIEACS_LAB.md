# Edge no host do GenieACS (LAB)

O Edge é **outbound-only e somente leitura** (README em `agents/edge`). Aqui ele roda no mesmo host do GenieACS e lê o NBI por loopback; só faz conexões de saída HTTPS para o gateway do FiberCore.

## Instalado em 2026-10-29
- Sem root: diretório próprio do usuário de serviço (`~/fibercore-edge`, modo 0700) com o binário estático (`linux/amd64`, `CGO_ENABLED=0`, versão `0.1.0-lab-<commit>`), `config.json` (0600), arquivo do segredo da service account `edge_agent` (0600), fila SQLite (0600), `run.sh` e `edge.log` (rotaciona em 5 MiB).
- Persistência: `cron` (`* * * * *` e `@reboot`) chamando `run.sh`; `flock -n` garante uma instância e religa o processo se cair. Não há systemd de usuário nem root neste host.
- Config: `gateway_url` = domínio público do LAB + `/api`; `nbi_url` = `http://127.0.0.1:7557`; `allowlist` = só `127.0.0.1:7557`; `jobs_enabled: false` (nenhum job); `olts`: uma OLT em somente leitura (ver abaixo).
- Registro no LAB: edge `edge-genieacs-lab`, service account `edge-genieacs-lab-agent` (papel `edge_agent`: só heartbeat, inventário e execução de jobs assinados), conector `genieacs-lab`.
- Resultado verificado: heartbeat chegando ao LAB; 6 CPEs ingeridos (37 identidades `DISCOVERYSERVICE` descartadas pelo Edge, só contagem no log).

## Operar
- Ver estado: `ps` do processo `fibercore-edge`; `tail edge.log` (JSON, sem identificadores de CPE).
- Atualizar: enviar o novo binário como `fibercore-edge.new` no mesmo diretório; o `run.sh` o troca na próxima partida (para trocar já, encerrar o processo; o cron o religa em ≤ 1 min).
- Desinstalar: remover as duas linhas do `crontab`, encerrar o processo, apagar o diretório; revogar a service account no LAB.

## Não coberto
OLT (CLI, somente leitura): LIGADA em 2026-10-29 com autorização explícita (perfil `huawei_ma56_r015`, SSH em modo shell com algoritmos legados só para essa OLT, host key fixada, 32 PONs). O guard de ritmo (`olt-guard.json`, `edge.lock`) impõe uma coleta por vez, intervalo de 15 min e resfriamento de 15 min após falha, e sobrevive a restart; a primeira coleta completa levou ~156 s (775 ONUs). A OLT real tem throttle de SNMP (1 req/s, resfriamento de 5 min no transporte SNMP, não usado aqui). Credenciais só em arquivo 0600 no host do Edge. Fechar o NBI para fora: `GENIEACS_NBI_HARDENING.md` (precisa de root).

## Leitura ativa de parâmetros do CPE (ADR-SD-002 item 4) — desligada por padrão
- Autorizada pelo responsável em 2026-10-29 para a LAB. Só roda com `"jobs_enabled": true`, `"job_public_key"` e `"refresh_tasks": true` no `config.json` do Edge; a nuvem precisa ter a chave de assinatura de jobs.
- Disparo: job `refresh` aprovado sobre UM CPE (R0, sem aprovação humana extra). Cada job faz até 5 tarefas `getParameterValues` (uma conexão ao CPE por tarefa), no máximo 1 por dispositivo a cada 10 min e 20 por hora.
- Nunca em lote por PON. Para desligar: `"refresh_tasks": false` e reiniciar o Edge (o job passa a falhar fechado).
- Verificação depois do primeiro teste: no GenieACS conferir (somente leitura) que não ficou tarefa nem falha pendente para o dispositivo (`GET /tasks`, `GET /faults` filtrando o `_id`).

## Consultas somente leitura da OLT (`olt_query`, ADR-0029) — ligado em 2026-10-30
- Autorizada pelo responsável. Só `olt.version` e `olt.board` (rollout do ADR-0029 item 7). As consultas rodam na sessão CLI da coleta periódica (sem login extra), depois dos comandos dela; uma consulta pode esperar até a próxima janela (15 min). Resultado tipado e fechado; a saída crua nunca sai do Edge.
- Config do Edge: `"olt_query_enabled": true`, `"olt_query"` em `allowed_operations` e `"cloud_id"` (id da OLT na nuvem) na entrada da OLT. Fila durável: `olt-queries.json` (0600) ao lado da fila do Edge.
- Nuvem: flag do provedor `olt_query` (owner CLI `feature-set`), permissão `olt_query:run` (isp_admin, engineer, noc_n2), cota 10/h por usuário, 60/h por provedor, 20/h por OLT.
- Desligar: `olt_query_enabled` removido (ou `false`) e reiniciar o Edge; e/ou `feature-set <tenant> olt_query off`. A cópia anterior da configuração fica em `config.json.pre-oltquery`.
- Mover a OLT para outro Edge: `olt-transfer-start` e, depois do último arrendamento + 60 s, `olt-transfer-finish` (ver CHANGELOG, PR 89). Os relógios do Edge e da nuvem devem estar a menos de 45 s um do outro.
