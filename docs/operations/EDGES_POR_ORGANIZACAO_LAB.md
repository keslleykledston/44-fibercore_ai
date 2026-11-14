# Edges por organização na LAB (2026-11-14)

Um Edge por organização cliente, no host da LAB, falando com a API por loopback (`http://127.0.0.1:18480/api`, `allow_insecure_dev`). Cada Edge tem **a própria service account** (papel `edge_agent`, presa ao `edge_id` da organização) e só enxerga as OLTs da própria organização. Evidência de separação: com RLS, a organização A vê só as suas OLTs/ONUs e sem organização o resultado é zero.

## Estado
| Organização | OLTs coletando | Observação |
|---|---|---|
| WA TELECOM | 2 Datacom (mesmo IP, portas diferentes: `nat_shared_ip`) | VSOL cadastrada sem coleta: credencial recusada, sem driver |
| GL CONNECT | 1 Datacom | |
| ARAUJO | 1 Datacom + 1 Huawei MA5800 (R022, 16 PONs da placa GPON) | `nat_shared_ip` nas duas |
| JGA | 1 Huawei MA5800 (R024, 16 PONs da placa do slot 1; 8 com ONUs) | causas de queda (LOS/dying-gasp) já aparecem |
| ASANET | 1 Intelbras 8820 por Telnet (**texto claro**) | |
| FW NETWORK | nenhuma | inalcançável do servidor |

Todos os drivers estão em `identified` (ADR-0052). Nada é escrito nas OLTs.

## Layout (fora do repositório)
`~/fibercore-edges/` (0700): `bin/fibercore-edge`, `run-edge.sh <slug>` (teste manual) e uma pasta por organização com `config.json` (0600), `edge.secret` (segredo da service account), um `<olt>.secret` por OLT (senha), `queue.json`, `edge.log`, `edge.pid`. **Nenhuma credencial entra no repositório, na memória ou na documentação.**

## Operar
- Serviço (systemd de usuário, linger ligado, sobe no boot, `Restart=always`): `systemctl --user status|restart|stop fibercore-edge@<slug>`. Unidade: `~/.config/systemd/user/fibercore-edge@.service`. O `run-edge.sh` é só para teste manual: não usar junto com o serviço.
- Depois de uma falha a OLT fica em cooldown (15 min). Para repetir já: parar o Edge e apagar `olt-guard.json` da pasta dele.
- Host key: fixada por SHA256 colhida com `ssh-keyscan` deste servidor (confiança na primeira vez); a que vale é a que o cliente Go negocia (ECDSA, senão ED25519/RSA). Se o equipamento trocar de chave a coleta falha com `host key mismatch (got ...)`: conferir com o cliente antes de trocar o valor.
- Atualizar o binário: `cd agents/edge && CGO_ENABLED=0 go build -o ~/fibercore-edges/bin/fibercore-edge ./cmd/fibercore-edge` e reiniciar cada Edge.
- Persistência: configurada em 2026-11-14 (systemd de usuário; os 5 serviços estão `enabled`). Ainda não testada com um reboot real.
- Nomes das organizações: os informados pelo responsável (os hostnames dos equipamentos são ignorados).

## Telnet (ASANET)
O usuário e a senha cruzam a rede em claro até a OLT. Só com `transport: telnet` e `allow_telnet: true` na entrada. Recomendado: VPN/rede privada até o cliente.

## Teste de conexão pela plataforma (ADR-0053, 2026-11-14)
As 7 OLTs passam no teste (`POST /v1/fleet/olts/{id}/connection-test`): identidade devolvida bate com a coleta (`matches_collected: true`); `patch` e `uptime_seconds` ficam "não informado". Para isso, em cada Edge: `jobs_enabled`, `job_public_key` (chave pública derivada da semente de assinatura da LAB, nunca a semente), `allowed_operations: ["collect","olt_query"]`, `olt_query_enabled: true` e `cloud_id` (id da OLT na nuvem) em cada OLT. Na nuvem: flag `olt_query` ligada nas 5 organizações (`feature-set <tenant> olt_query on`). O resultado só volta na próxima janela de coleta (até ~15 min); limite de 1 teste a cada 15 min e 4 por hora por OLT.

## Lista de ONTs a autorizar (`olt.autofind`) na MA5800 (ADR-0054)
- Só leitura (`display ont autofind all`), pela mesma sessão da coleta. Pedido: `POST /v1/olts/{id}/queries/olt.autofind` (flag `olt_query`); o resultado vem na janela de coleta seguinte (até ~15 min). Depois, `POST /v1/olts/{id}/onus/unregistered/sync` (flag `onu_discovery`, ligada nas 5 organizações em 2026-11-14; só lista, nada é autorizado nem removido) transforma a leitura em fila.
- Teste real em 2026-11-14 nas duas MA5800 (ARAUJO e JGA): `SUCCEEDED`, `{"entries": []}` (nenhuma ONT aguardando). O layout COM entradas ainda não foi visto nesta família: o parser é o da R015 e falha fechado.
- O Edge deixou de enviar `quit` ao fim da coleta MA5800 (a OLT pergunta y/n). Binário e API reimplantados e os 5 Edges reiniciados.
