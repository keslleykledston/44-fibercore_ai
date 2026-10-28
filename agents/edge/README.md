# Fibercore Edge (Go)

Agente outbound-only que roda no site do ISP. **Somente leitura** nesta fase.

- `internal/config` — config JSON local (0600, campos desconhecidos rejeitados, UUIDs, https obrigatório; http só em loopback com `allow_insecure_dev`).
- `internal/allowlist` — todo destino (NBI) precisa estar na lista LOCAL; sem proxy de ambiente, sem redirects, IPs resolvidos link-local/metadata/multicast recusados.
- `internal/nbi` — cliente GenieACS NBI só-GET com projeção mínima (sem árvore de parâmetros => sem PSK/PPPoE), limite de 16 MiB.
- `internal/queue` — store-and-forward SQLite WAL (0600), ordem preservada, dead-letter para rejeição permanente.
- `internal/gateway` — login por service account `edge_agent`, relogin único em 401, classificação Delivered/Retry/Rejected.
- `internal/collector` — GenieACS → `cpe_snapshot` (lotes de 5000, não inventa identidade sem serial). Drivers de OLT: PR 7.
- `cmd/fibercore-edge` — `fibercore-edge -config /etc/fibercore-edge/config.json`.

Teste: `cd agents/edge && go vet ./... && go test ./...`.

Pendências: mTLS (ADR-0011), assinatura/anti-replay de jobs (Sprint 3), SNMP/SSH read-only (PR 7), updater assinado, métricas.
