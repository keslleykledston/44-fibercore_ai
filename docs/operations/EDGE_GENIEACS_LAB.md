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
