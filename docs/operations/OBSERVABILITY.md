# Observabilidade: Prometheus e Grafana (opt-in)

Decisão e limites: `docs/wiki/adr/ADR-0043-observabilidade-prometheus-grafana.md`. Complementa o watchdog (`docs/operations/MONITORING.md`), não o substitui.
**Nada disto sobe por padrão.** Sem `--profile observability` o compose é o mesmo de antes.

## O que existe
| Peça | Onde | Porta |
|---|---|---|
| RED da API (`GET /metrics`, token) | `api-core` | interna `api-core:8000` |
| Exportador de agregados (Edges, OLTs, outbox, jobs, backup, disco) | `fibercore-exporter` | interna `:9101` |
| Exportador do NATS (lag do consumidor) | `nats-exporter` | interna `:7777` |
| Prometheus (regras de alerta) | `prometheus` | `127.0.0.1:19090` |
| Grafana (2 painéis provisionados) | `grafana` | `127.0.0.1:19300` |

Portas do host: `FIBERCORE_PROMETHEUS_PORT`, `FIBERCORE_GRAFANA_PORT`. Só loopback. Para ver de outra máquina: túnel SSH (`ssh -L 19300:127.0.0.1:19300 host`); não publicar.

## Ligar (LAB)
```bash
scripts/observability-init.sh            # cria ~/fibercore-observability/observability.env (0600); não imprime valores
docker compose --env-file .env.prod --env-file ~/fibercore-observability/observability.env \
  -f infra/compose/compose.yaml --profile observability up -d
```
- O **mesmo** `FIBERCORE_METRICS_TOKEN` chega à API (`METRICS_TOKEN`, liga o `/metrics`) e ao Prometheus. A API é **recriada** ao receber a variável nova: janela curta de reinício da `api-core`; fazer fora de horário de uso e só com ordem do responsável.
- Subir o perfil sem `FIBERCORE_METRICS_TOKEN` ou sem `FIBERCORE_GRAFANA_ADMIN_PASSWORD` no ambiente **falha com mensagem clara** (`environment variable ... required by secret ... is not set`), nunca sobe com segredo vazio. Sem o perfil, essas variáveis não são exigidas.
- Backup: `FIBERCORE_BACKUP_DIR` = diretório dos backups (montado somente-leitura; só o `mtime` dos `fibercore-prod-*.dump.done` é lido; padrão do arquivo: `FIBERCORE_BACKUP_GLOB`). **Sem essa variável o alerta de backup dispara de propósito** (o padrão é um diretório vazio).
- Senha do Grafana (usuário `admin`): `grep '^FIBERCORE_GRAFANA_ADMIN_PASSWORD=' ~/fibercore-observability/observability.env`. **Só vale na primeira criação do volume `grafana_data`**; para trocar depois: `docker compose exec grafana grafana cli admin reset-admin-password <nova>` (ou apagar o volume, perdendo estado do Grafana; os painéis vêm de arquivo).
- Projeto compose diferente (ex.: `-p fibercore-prod`): o nome dos volumes e redes acompanha o projeto; use o mesmo `-p` do resto da stack.

## Desligar / reverter
```bash
docker compose -f infra/compose/compose.yaml --profile observability stop prometheus grafana nats-exporter fibercore-exporter
docker compose -f infra/compose/compose.yaml --profile observability rm -f prometheus grafana nats-exporter fibercore-exporter
```
Fechar o `/metrics` da API: esvaziar `FIBERCORE_METRICS_TOKEN` e recriar a `api-core` (a rota volta a ser 404). Apagar dados: `docker volume rm <projeto>_prometheus_data <projeto>_grafana_data`.

## Métricas (todas sem identificador de tenant, usuário, Edge, OLT, serial, endereço ou segredo)
API (`fibercore_http_*`): `requests_total{method,route,code}`, `request_duration_seconds` (histograma, `{method,route}`), `requests_in_flight`; `fibercore_api_build_info{version}`, `fibercore_api_start_time_seconds`. `route` é o template da rota; `unmatched` quando nada casou.

Exportador: `fibercore_exporter_db_up`, `fibercore_edges_active`, `fibercore_edges_never_heartbeat`, `fibercore_edge_heartbeat_age_seconds_max`, `fibercore_olts_registered`, `fibercore_olts_never_collected`, `fibercore_olt_collection_age_seconds_max`, `fibercore_outbox_unpublished`, `fibercore_outbox_oldest_unpublished_age_seconds`, `fibercore_jobs{state}`, `fibercore_jobs_in_flight_oldest_age_seconds`, `fibercore_backup_dir_readable`, `fibercore_backup_files_found`, `fibercore_backup_last_success_timestamp_seconds`, `fibercore_disk_free_ratio{fs="docker|backup"}`. Séries "máximo/mais antigo" **somem** quando não há objeto (outbox drenado, nenhum Edge com heartbeat): ausência não é zero.

NATS: `jetstream_consumer_num_pending`, `jetstream_consumer_num_ack_pending` (lag do `event-consumer`).

## Alertas (`infra/observability/prometheus/rules/fibercore.rules.yml`)
| Alerta | Condição | Severidade |
|---|---|---|
| FiberCoreApiDown | scrape da API falha 2 min | critical |
| FiberCoreApi5xx | > 5 % de 5xx por 5 min (≥ 0,05 req/s) | critical |
| FiberCoreApiLatencyP95 | p95 > 2 s por 10 min | warning |
| FiberCoreEdgeSilent | Edge mais antigo sem heartbeat > 300 s | critical |
| FiberCoreNoActiveEdge | nenhum Edge ativo, ou Edge que nunca enviou heartbeat (10 min) | warning |
| FiberCoreOltCollectionStale | coleta mais antiga > 60 min | warning |
| FiberCoreOltNeverCollected | OLT cadastrada que nunca coletou, por 60 min (desde o 1º scrape visto) | warning |
| FiberCoreOutboxBacklog | evento sem publicar > 300 s | critical |
| FiberCoreConsumerLag | > 1000 pendentes por 10 min (limiar inicial) | warning |
| FiberCoreJobStuck | job em andamento sem mudar > 30 min | warning |
| FiberCoreDiskLow | espaço livre < 10 % (`fs`) | critical |
| FiberCoreBackupStale | sem marcador, ou último > 26 h | critical |
| FiberCoreBackupDirUnreadable | diretório de backup não configurado/montado/legível (10 min) | critical |
| FiberCoreExporterDown / FiberCoreNatsExporterDown | exportador fora ou sem banco | warning |

**Sem notificação automática** (sem Alertmanager): olhar `http://127.0.0.1:19090/alerts` ou o painel "Pipeline, frota e operação". O aviso por webhook continua sendo o do watchdog. Limiares de tempo = os do watchdog; os outros são iniciais e devem ser calibrados após alguns dias de dados.

## Dashboards (Grafana > pasta FiberCore)
- **FiberCore - API (RED):** alvo, req/s, 5xx, p95, em andamento, tempo ativo, versão; taxa por código; latência geral e por rota (10 mais lentas); 5xx por rota.
- **FiberCore - Pipeline, frota e operação:** alertas em disparo; outbox e lag do relay; lag do consumidor; jobs por estado; Edges e OLTs (heartbeat/coleta mais antigos); backup e disco.
Os painéis são somente-leitura (arquivo versionado em `infra/observability/grafana/dashboards`); para mudar, editar o JSON e abrir PR.

## Validar
```bash
scripts/observability-validate.sh                      # promtool: config, regras, testes das regras (usa o promtool do PATH ou o do contêiner fixado, sem rede)
make test-api                                          # inclui test_metrics.py e test_observability_config.py
```
Teste de ponta a ponta sem tocar a LAB: use um projeto compose próprio (`-p`), portas altas livres e `down -v` ao fim. Se o Docker acusar `all predefined address pools have been fully subnetted`, fixe uma sub-rede livre para a rede `control` num arquivo de override.

## Problemas conhecidos
- `FiberCoreApiDown` com a API de pé: `METRICS_TOKEN` vazio na API (rota 404) ou diferente do token do Prometheus (401). O token do Prometheus é lido na criação do contêiner: mudou o valor, recriar `prometheus` e `api-core`.
- Sem `fibercore_edge_heartbeat_age_seconds_max` no gráfico: nenhum Edge ativo enviou heartbeat ainda.
- `fs="docker"` é o sistema de arquivos onde o Docker guarda os dados (`/var/lib/docker`), não necessariamente `/`.
- Prometheus e Grafana rodam sem `read_only` (ver ADR-0043 §2); demais serviços novos são somente-leitura.
