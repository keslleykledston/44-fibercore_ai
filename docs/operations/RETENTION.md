# Retenção e medição do histórico de estado das ONUs (`onu_state_events`)

## Retenção agendada (LAB)
- Rotina: `scripts/retention-scheduled.sh` — confere que o papel do banco usado é dono/BYPASSRLS (pré-condição da função), chama `onu_state_events_prune(400)` (mantém 400 dias e, por ONU, o último evento anterior ao corte), com `flock`. Log: `~/fibercore-backups/retention.log` (0600): `OK removidos=N de M (keep_days=400)` ou `FALHA …`.
- Cron do usuário do LAB (instalado em 2026-10-30; roda depois do backup das 03:15): `45 3 * * * cd /home/suporte/projects/44-FiberCore && ./scripts/retention-scheduled.sh >/dev/null 2>&1`
- Verificar: `crontab -l | grep retention` e `tail ~/fibercore-backups/retention.log`. Uma linha `FALHA` no log é o único sinal (a rotina não avisa ninguém): olhar junto com o log do backup.
- Mínimo aceito: 370 dias (a maior janela de consulta é 365). Variável `FIBERCORE_EVENTS_KEEP_DAYS`.

## Medição de desempenho
- `N_ONU=30000 EV_PER=40 scripts/perf-onu-events.sh` (Postgres descartável na porta 55442; depois `docker rm -f fc-perf-pg`). Gera ONUs e eventos, roda `/unstable` em 30 e 365 dias (5 amostras, mediana e pior), o relatório offline (500 ONUs) e o histórico de 1 ONU, e imprime o plano `EXPLAIN (ANALYZE, BUFFERS)`.
- Resultado de 2026-10-30 (30 000 ONUs, 1 230 000 eventos): `/unstable` 30 d mediana 369 ms (pior 2,6 s a frio); 365 d mediana 1,5 s; relatório offline 72 ms; histórico de 1 ONU ~1 ms.
