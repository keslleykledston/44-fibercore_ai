# NATS com TLS mútuo e ACL por papel (runbook)

Decisão e limites: `docs/wiki/adr/ADR-0044-nats-tls-mutuo-e-acl-por-papel.md`. **Opt-in e desligado**: o `compose.yaml` sozinho segue sem TLS/ACL. Nada aqui foi aplicado na LAB.

Quem fala NATS: só `outbox-relay` (papel `relay`) e `event-consumer` (papel `consumer`). `api-core` e o Edge Go não se conectam ao NATS e não têm identidade.

## Variáveis dos clientes (Python)
| Variável | Efeito |
|---|---|
| `NATS_TLS_CA` | CA que assinou o servidor; liga TLS com verificação de servidor (nome do host incluído) |
| `NATS_TLS_CERT` + `NATS_TLS_KEY` | certificado e chave do papel (a identidade); exigem `NATS_TLS_CA` e vêm juntos |
| `NATS_INBOX_PREFIX` | prefixo de resposta (`_INBOX.relay` / `_INBOX.consumer`): o ACL só deixa o papel escutar o próprio |
| `NATS_URL` | `tls://nats:4222` quando seguro |

Sem nenhuma definida: conexão idêntica à de hoje. Definida pela metade ou ilegível: o processo CAI na partida (nunca cai para conexão sem TLS). O connect tem prazo total de 20 s.

## Gerar a PKI (fora do repositório)
```bash
# diretório 0700 FORA do repo (o script recusa um diretório rastreável pelo Git); para contêiner com uid 10001, chaves legíveis só dentro desse diretório:
KEY_MODE=0644 scripts/nats-tls.sh gen /srv/fibercore/nats-pki      # ca.pem/ca.key, server.*, relay.*, consumer.*
```
- `ca.key` só é usada para emitir. Depois de gerar, guarde-a fora do host de produção (cofre/offline) e remova da pasta; `issue` precisa dela de volta.
- `*.pem` e `*.key` estão no `.gitignore`; o gitleaks do CI segue valendo. Nunca colar certificado/chave em chat, issue ou ADR.

## Plano de ativação na LAB (NÃO executado; decisão e janela do responsável)
Pré: backup lógico (`scripts/backup.sh`), `scripts/restore-rehearsal.sh` recente, `python3 scripts/images.py check` verde. O JetStream usa o mesmo volume `nats_data` nos dois modos (o NATS não é coberto pelo backup; o outbox reconstrói: `relay replay`).
1. Gerar a PKI (acima) no host; conferir `ls -l` (dir 0700).
2. Ensaio fora da stack real: `python -m pytest apps/api/tests/test_nats_acl.py` (precisa de Docker e da suíte de testes do `scripts/test-env.sh`).
3. Janela curta (eventos ficam no outbox enquanto o relay está parado; nada se perde): parar `outbox-relay` e `event-consumer`; subir o NATS seguro e os dois clientes JUNTOS, com o mesmo projeto e `--env-file` do `make up-prod`:
   ```bash
   FIBERCORE_NATS_TLS_DIR=/srv/fibercore/nats-pki docker compose -p fibercore-prod --env-file .env.prod \
     -f infra/compose/compose.yaml -f infra/compose/nats-secure.compose.override.yaml --profile public up -d nats outbox-relay event-consumer
   ```
   (`api-core`, `web`, `proxy`, `postgres`, `job-sweeper` não mudam; o monitor 8222 continua HTTP interno e o healthcheck/`/readyz` seguem iguais.)
4. Verificar: `docker logs <nats>` sem `Permissions Violation` nem `Authorization Violation`; `docker compose ... ps` com os dois clientes `healthy`; criar um evento real (ex.: uma ação auditada) e conferir `event.consumed` no `audit_log` e a contagem do stream `FIBERCORE_EVENTS` subindo.
5. Voltar (rollback): repetir o `up` SEM o `-f ...override.yaml` (volta `-js -sd /data -m 8222`, `NATS_URL=nats://nats:4222` sem TLS). O stream e o durável `audit-projection` continuam no volume.
6. Conferir no log do NATS que cada processo conectou com o nome do papel (`fibercore-relay`, `fibercore-consumer`).

Pegadinha do host da LAB: o Docker já esgotou os pools de endereço (criar rede nova falha com "all predefined address pools have been fully subnetted"); `up` de projeto existente reaproveita a rede e não é afetado. O teste de integração usa `network_mode: bridge` por isso.

## Rotação
- **Certificado de papel** (a cada ≤ 90 dias, ou na suspeita de vazamento da chave): `KEY_MODE=0644 scripts/nats-tls.sh issue <dir> relay` (ou `consumer`), depois `docker compose ... up -d --force-recreate outbox-relay` (o processo lê o arquivo na partida). O servidor NÃO precisa de reinício (valida contra a CA e o nome do papel). O certificado antigo continua válido até expirar: para cortá-lo já, faça a revogação abaixo.
- **Certificado do servidor**: `scripts/nats-tls.sh issue <dir> server`, depois `docker kill -s HUP <contêiner nats>` (recarrega sem derrubar o JetStream; medido: o servidor passa a apresentar o certificado novo). Clientes não mudam (verificam a CA e o nome `nats`).
- **CA** (a cada ≤ 3 anos): gerar uma CA nova num diretório novo, criar um `ca.pem` com as DUAS CAs concatenadas (`cat ca-velha.pem ca-nova.pem`), distribuir o pacote para servidor e clientes, reemitir todos os certificados com a CA nova, e só então retirar a CA velha do pacote.
- Registrar a data de cada rotação em `.agent-context/WORK_SESSION_LOG.md` (sem caminhos de chave).

## Revogação (chave de um papel vazou)
Não há CRL/OCSP. Remover o usuário do `infra/nats/nats-server.conf` (ou da cópia em uso) e `docker kill -s HUP <nats>`: medido, a conexão existente cai e nova conexão com aquele certificado leva `Authorization Violation`. Depois gerar uma identidade nova (SAN `fibercore-<papel>-2`, usuário novo no ACL) ou reemitir após trocar a CA. Enquanto isso, o relay/consumer ficam sem barramento (os eventos esperam no outbox).

## Diagnóstico
- `Authorization Violation` / `tls: ... certificate`: certificado de outra CA, expirado (`openssl x509 -noout -dates -in <pem>`), SAN sem usuário no ACL, ou cliente sem as variáveis `NATS_TLS_*`.
- `Permissions Violation for Publish/Subscription to "<subject>"` no log do servidor: o papel tentou algo fora do ACL. Atualizar o ACL é mudança revisada (ADR-0044); uma atualização do `nats-py` que mude os subjects da API do JetStream aparece aqui e no teste de integração.
- `returning true from eof_received() has no effect when using ssl`: aviso do asyncio/nats-py (Python 3.12), sem efeito.
