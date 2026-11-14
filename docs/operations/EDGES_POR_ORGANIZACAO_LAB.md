# Edges por organização na LAB (2026-11-14)

Um Edge por organização cliente, no host da LAB, falando com a API por loopback (`http://127.0.0.1:18480/api`, `allow_insecure_dev`). Cada Edge tem **a própria service account** (papel `edge_agent`, presa ao `edge_id` da organização) e só enxerga as OLTs da própria organização. Evidência de separação: com RLS, a organização A vê só as suas OLTs/ONUs e sem organização o resultado é zero.

## Estado
| Organização | OLTs coletando | Observação |
|---|---|---|
| WA TELECOM | 2 Datacom (mesmo IP, portas diferentes: `nat_shared_ip`) | VSOL cadastrada sem coleta: credencial recusada, sem driver |
| GL CONNECT | 1 Datacom | |
| ARAUJO | 1 Datacom + 1 Huawei MA5800 (R022, 16 PONs da placa GPON) | `nat_shared_ip` nas duas |
| JGA | 1 Huawei MA5800 (R024, PONs 0/1/0 e 0/1/1) | ampliar depois da validação |
| ASANET | 1 Intelbras 8820 por Telnet (**texto claro**) | |
| FW NETWORK | nenhuma | inalcançável do servidor |

Todos os drivers estão em `identified` (ADR-0052). Nada é escrito nas OLTs.

## Layout (fora do repositório)
`~/fibercore-edges/` (0700): `bin/fibercore-edge`, `run-edge.sh <slug>` e uma pasta por organização com `config.json` (0600), `edge.secret` (segredo da service account), um `<olt>.secret` por OLT (senha), `queue.json`, `edge.log`, `edge.pid`. **Nenhuma credencial entra no repositório, na memória ou na documentação.**

## Operar
- Subir/parar: `~/fibercore-edges/run-edge.sh <slug>`; `kill $(cat ~/fibercore-edges/<slug>/edge.pid)`.
- Depois de uma falha a OLT fica em cooldown (15 min). Para repetir já: parar o Edge e apagar `olt-guard.json` da pasta dele.
- Host key: fixada por SHA256 colhida com `ssh-keyscan` deste servidor (confiança na primeira vez); a que vale é a que o cliente Go negocia (ECDSA, senão ED25519/RSA). Se o equipamento trocar de chave a coleta falha com `host key mismatch (got ...)`: conferir com o cliente antes de trocar o valor.
- Atualizar o binário: `cd agents/edge && CGO_ENABLED=0 go build -o ~/fibercore-edges/bin/fibercore-edge ./cmd/fibercore-edge` e reiniciar cada Edge.
- Persistência após reinício do servidor: **não configurada** (sem cron/systemd). Decisão pendente do responsável.

## Telnet (ASANET)
O usuário e a senha cruzam a rede em claro até a OLT. Só com `transport: telnet` e `allow_telnet: true` na entrada. Recomendado: VPN/rede privada até o cliente.
