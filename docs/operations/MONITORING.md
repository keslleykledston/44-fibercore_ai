# Monitoramento e recuperação automática (LAB)

O que acontece quando um módulo falha, quem recupera e quem avisa. Para operar: `ops/watchdog/watchdog.py` (cron, a cada minuto).

## O que recupera sozinho
| Falha | Mecanismo | Limite |
|---|---|---|
| Processo de um contêiner morre | `restart: unless-stopped` do Docker | — |
| Contêiner `unhealthy` sem estado (api-core, web, **outbox-relay, event-consumer**) por 2 ciclos seguidos (~2 min) | watchdog: `docker restart` | 3 ações por contêiner por hora; depois só avisa (`precisa de pessoa`) |
| `postgres` ou `nats` `unhealthy` | **não reinicia**: só avisa (reiniciar interromperia gravações e publicações) | pessoa decide |
| Contêiner parado que deveria estar de pé | watchdog: `docker start` (`migrate` terminado com código 0 é normal) | idem |
| Relay ou consumer vivos mas travados | batimento: o laço toca `/tmp/hb` só em iteração bem-sucedida (relay sem exceção; consumer com lote sem falha de handler **e** banco alcançável); o healthcheck falha se o arquivo tiver mais de 60 s | o watchdog reinicia |
| Evento perdido no barramento | `python -m app.workers.relay replay <ts>`; consumidores idempotentes | manual |
| Edge cai | `cron` + `flock` no host do GenieACS religa em ≤ 1 min | — |
| Nó de teste de banda cai | a sonda de saúde do Edge marca `down`; a nuvem deixa de oferecer o teste | volta sozinho com o nó |

## O que só avisa (não há o que reiniciar daqui)
- Edge sem heartbeat há mais de 5 min (ou nenhum Edge).
- Evento do outbox sem publicar há mais de 5 min.
- Nenhum backup concluído nas últimas 26 h.
- Disco (`/` ou `/var/lib/docker`) com menos de 10% livre.
- Watchdog sem acesso ao banco.

Falha ao coletar (Docker ou banco indisponível) é estado **desconhecido**: os alertas daquele assunto ficam como estão e nunca viram `resolvido`; só uma coleta saudável resolve.

Cada chave de alerta repete no máximo 1 vez por hora e emite `resolvido` quando a condição some. Uma recuperação automática bem-sucedida gera um aviso de uma vez só.

## Onde o aviso aparece
- Sempre: `~/fibercore-watchdog/watchdog.log` (JSON por linha, 0600, rotaciona em 2 MiB). Sem segredo, sem endereço de cliente.
- Opcional: webhook. Gravar a URL `https://…` em `~/fibercore-watchdog/webhook.url` (modo **0600**; com permissão aberta é ignorada) — Slack/Teams/n8n etc. O corpo é `{"text": "…"}`.
- E-mail: depende do SMTP (pendência do responsável); quando existir, basta um receptor de webhook que envie e-mail.

## Instalar / remover
```bash
( crontab -l; echo '* * * * * cd /home/suporte/projects/44-FiberCore && /usr/bin/python3 ops/watchdog/watchdog.py >/dev/null 2>&1' ) | crontab -
```
Remover: apagar essa linha do `crontab`. Estado em `~/fibercore-watchdog/` (`state.json`, `watchdog.log`).

## O que NÃO cobre
- O host do Edge só tem `cron`: se o host inteiro cair, o aviso vem pela ausência de heartbeat (acima), não de lá.
- Não reinicia o host, não limpa disco, não mexe em OLT, ONT ou ACS.
- Não substitui Prometheus/Alertmanager; é o mínimo para o LAB.
