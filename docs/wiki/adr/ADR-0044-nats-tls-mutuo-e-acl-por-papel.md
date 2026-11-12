# ADR-0044: NATS com TLS mútuo e ACL por papel (opt-in)

Status: Accepted (implementação opt-in; NÃO ativada na LAB) | Data: 2026-11-11 | Owner: Claude Code (implementação), Codex (revisão)

## Contexto

O ADR-0007 deixou o NATS do Compose sem TLS e sem ACL "apenas dev"; o `KNOWN_ISSUES` listava isso como pendência antes de qualquer piloto além da LAB. Hoje qualquer processo que alcance a porta 4222 da rede interna pode publicar em `fibercore.events.<tenant>.*` (forjar evento de outro tenant), ler todos os eventos, apagar/purgar streams e consumidores.

Levantamento do código (2026-11-11), por quem realmente se conecta ao NATS:

| Componente | Fala NATS? | Como |
|---|---|---|
| `outbox-relay` (`app.workers.relay`) | sim | `bus.connect`; publica `fibercore.events.>`; `ensure_streams` |
| `event-consumer` (`app.events.consumer`) | sim | `bus.connect`; consumidor durável `audit-projection` (pull, ack/nak/term), DLQ `fibercore.dlq.>`; `ensure_streams` |
| `api-core` | **não** | grava no outbox (PostgreSQL); só sonda o monitor HTTP 8222 |
| Edge Go | **não** | fala HTTPS com a API (ingestão/jobs); `agents/edge` não tem cliente NATS nem dependência |

O diagrama de `ARCHITECTURE.md` mostra "NATS -> Edge Gateway" como intenção de longo prazo; o código não faz isso.

## Opções

1. TLS no listener + usuário/senha (hash bcrypt) por papel. Simples, mas senha em variável de ambiente/arquivo e dependência de ferramenta de hash.
2. **TLS mútuo com identidade pelo certificado (`verify_and_map`) + ACL por usuário.** Sem senha em lugar nenhum; a chave privada do papel é a credencial; revogar = tirar o usuário do ACL e recarregar. Só `openssl` para gerar.
3. NKEYs/JWT (modo operador). Mais poderoso (revogação, contas), mais peças para um único serviço de eventos; adiado.

## Decisão

Opção 2, **opt-in**, desligada por padrão: o `compose.yaml` e o comportamento atual (LAB, dev, testes) não mudam.

- Servidor: `infra/nats/nats-server.conf` (sem segredos): `tls { verify: true, verify_and_map: true }` e permissões mínimas por papel, medidas contra o código real (nats-py 2.16 do lock, servidor 2.11): `fibercore-relay` publica `fibercore.events.>` e usa a API de stream só dos dois streams do projeto; `fibercore-consumer` publica só `fibercore.dlq.>`, os acks da `FIBERCORE_EVENTS`, e usa a API do consumidor `audit-projection`. Cada um só escuta o próprio prefixo de resposta (`_INBOX.relay.>`, `_INBOX.consumer.>`). Quem precisar de outro durável edita o ACL (revisão explícita).
- **Não existe identidade para a API nem para o Edge**: nenhum deles fala NATS, e usuário inexistente não vaza. O teste `test_only_the_relay_and_the_consumer_speak_nats` falha se um cliente NATS novo aparecer (inclusive no Go do Edge): isso passa a exigir papel + ACL + atualização deste ADR. Consequência para o pedido original de "variáveis de configuração no Edge": não há o que configurar; o Edge antigo continua exatamente como está, com o recurso ligado ou desligado.
- Clientes Python (`app/events/bus.py`, `connect_options`): `NATS_TLS_CA`, `NATS_TLS_CERT`+`NATS_TLS_KEY`, `NATS_INBOX_PREFIX`. Nada definido = conexão idêntica à de hoje (teste). Qualquer coisa definida é tudo-ou-nada e **falha fechada**: certificado sem chave, identidade sem CA, arquivo ilegível ou chave que não é do certificado derrubam o processo na partida; nunca caem para conexão sem TLS. O servidor é sempre verificado (CA + nome do host). `connect()` ganhou um prazo total de 20 s: o cliente do nats-py contra um servidor só-TLS esperava para sempre (observado), e processo que falha é reiniciado e visível.
- PKI: `scripts/nats-tls.sh gen|issue` (openssl, ECDSA P-256), sempre FORA do repositório (o script recusa um diretório rastreável; `*.pem`/`*.key` no `.gitignore`). Certificados de papel valem 90 dias, CA 3 anos. Procedimento de geração, rotação e revogação: `docs/operations/NATS_TLS_ACL.md`.
- Ativação: `infra/compose/nats-secure.compose.override.yaml` (só monta o arquivo de cada serviço; `ca.key` nunca entra em contêiner).

Alternativas rejeitadas agora: senha por papel (opção 1) e NKEYs (opção 3); podem entrar depois sem mudar o desenho dos papéis. O monitor HTTP 8222 continua sem autenticação, só na rede interna do Compose (já era assim; não publicar).

## Consequências

- Prova (teste de integração `apps/api/tests/test_nats_acl.py`, projeto compose isolado `fibercore-natsit-*`, portas altas livres, `down -v` ao final, PKI descartável em `build/`): sem credencial, TLS sem certificado de cliente, certificado de outra CA, servidor de outra CA, identidade desconhecida (CA certa, sem usuário) e certificado expirado são recusados; o relay e o consumer REAIS (`relay_once`, `consume_batch`, `ensure_streams`, ack/nak/term, DLQ) funcionam com as permissões mínimas; papel errado recebe `Permissions Violation` e nada muda no stream (sem forjar, apagar, purgar, espiar ou consumir). Mutações do ACL (alargar o consumer; remover `$JS.ACK`) quebram os testes.
- Limites conhecidos: (a) sem CRL/OCSP: um certificado vazado vale até expirar OU até o usuário sair do ACL (recarregar o servidor revoga na hora, ver runbook); (b) uma chave privada comprometida de um papel dá exatamente as permissões daquele papel, não mais; (c) o isolamento por tenant dentro do subject continua sendo do consumidor (`parts[2] == tenant_id`): o ACL não separa tenants (todos os eventos passam pelo mesmo relay); (d) o acesso ao monitor 8222 e ao volume `nats_data` é do host/rede, não deste ADR.
- Rollback: remover o override do `up` e trocar `NATS_URL` de volta; relay e consumer sobem juntos com o NATS (cliente sem TLS é recusado, e vice-versa). Os dados do JetStream ficam no mesmo volume nos dois modos.
- Pendente (decisão do responsável): ativar na LAB (plano em `docs/operations/NATS_TLS_ACL.md`, NÃO executado).
