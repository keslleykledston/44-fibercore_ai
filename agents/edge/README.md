# Fibercore Edge (Go)

Agente outbound-only que roda no site do ISP. **Somente leitura** nesta fase.

- `internal/config` — config JSON local (0600, campos desconhecidos rejeitados, UUIDs, https obrigatório; http só em loopback com `allow_insecure_dev`).
- `internal/allowlist` — todo destino (NBI) precisa estar na lista LOCAL; sem proxy de ambiente, sem redirects, IPs resolvidos link-local/metadata/multicast recusados.
- `internal/nbi` — cliente GenieACS NBI só-GET com projeção mínima (sem árvore de parâmetros => sem PSK/PPPoE), limite de 16 MiB.
- `internal/queue` — store-and-forward SQLite WAL (0600), ordem preservada, dead-letter para rejeição permanente.
- `internal/gateway` — login por service account `edge_agent`, relogin único em 401, classificação Delivered/Retry/Rejected.
- `internal/collector` — GenieACS → `cpe_snapshot` (lotes de 5000, não inventa identidade sem serial; descarta a identidade provisória `DISCOVERYSERVICE` — ONTs que informam com serial aleatório antes de serem conhecidas — e só registra CONTAGENS do que foi deixado de fora, nunca identificadores). Drivers de OLT: PR 7.
- `cmd/fibercore-edge` — `fibercore-edge -config /etc/fibercore-edge/config.json`.

Teste: `cd agents/edge && go vet ./... && go test ./...`.

Pendências: mTLS (ADR-0011), assinatura/anti-replay de jobs (Sprint 3), SNMP/SSH read-only (PR 7), updater assinado, métricas.

## Exemplo: OLT Huawei MA5608T R015 (valores fictícios; segredo em arquivo 0600, host key fixada)
```json
{"name":"olt-exemplo","vendor":"huawei","profile":"huawei_ma56_r015","address":"192.0.2.10:22","username":"leitura",
 "secret_file":"/etc/fibercore-edge/olt-exemplo.secret","host_key_sha256":"SHA256:...","pon_ports":["0/0/14"],
 "ssh_mode":"shell","ssh_pager_space":true,"legacy_ssh":true}
```
`legacy_ssh` habilita DH group1/14-SHA1, `ssh-rsa` e AES-CBC **só para esta OLT** (a MA5608T R015 não oferece mais nada); a host key fixada continua obrigatória.

## Exemplo: OLT por SNMP (v2c, somente leitura; valores fictícios)
```json
{"name":"olt-exemplo-snmp","vendor":"huawei","transport":"snmp","snmp_address":"192.0.2.10:161",
 "snmp_community_file":"/etc/fibercore-edge/olt-exemplo.snmp","snmp_pace_ms":1000,"snmp_max_requests":300,"pon_ports":["0/0/14"]}
```
`192.0.2.10:161` precisa constar em `allowlist` e ser IP literal. `snmp_pace_ms` nunca fica abaixo de 1000. A OLT medida limita a taxa do agente SNMP (ver `docs/engineering/DRIVER_SDK_INTERFACE.md`).

## Exemplo: "Last down time" da OLT (canal SNMP somente leitura dentro de uma entrada CLI; valores fictícios)
```json
{"name":"olt-exemplo","vendor":"huawei","profile":"huawei_ma56_r015","address":"192.0.2.10:22", "...":"(campos CLI como acima)",
 "last_down":{"snmp_address":"192.0.2.10:161","snmp_community_file":"/etc/fibercore-edge/olt-exemplo.snmp",
              "snmp_pace_ms":1000,"snmp_max_requests":400,"every_seconds":3600}}
```
Só para entrada CLI Huawei com o perfil validado. A OLT é a MESMA (mesmo nome, mesmo IP; `snmp_address` em `allowlist` e IP literal). Depois de cada coleta CLI, no máximo a cada `every_seconds` (padrão 3600, mínimo 900), o Edge lê por SNMP (GET, 1 requisição/s) o "Last down time" das ONUs que a última coleta CLI mostrou fora do ar (leitura focada: 2 OIDs por ONU, ~1 requisição a cada 10 ONUs; o ONT-ID vem da listagem CLI e o serial é conferido na própria resposta, então um ONT-ID que mudou de dono não rende horário), porta por porta, e o horário viaja como `last_down_at` no próximo snapshot. A leitura roda em segundo plano, com orçamento próprio (nunca bloqueia nem encurta a rodada de coleta), uma vez por snapshot CLI, e descarta a resposta se um snapshot CLI mais novo chegou durante a leitura. Falha ou timeout nunca derrubam a coleta CLI; o agente SNMP fica 5 min em paz depois de uma falha e o retry só vem no próximo intervalo. O horário é esquecido quando a ONU volta e nunca é herdado por uma nova queda.
