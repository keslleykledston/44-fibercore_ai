# Edge: OLTs adicionadas pela nuvem, sob política e confiança locais (ADR-0046)

Lado do Edge do cadastro de OLT de ponta a ponta. A nuvem **propõe** uma OLT (IP, porta, fabricante, transporte, impressão digital da chave do host) pelo mesmo canal assinado e cifrado do ADR-0045 (`kind:"olt_connection"`); o Edge só a aceita **dentro da política local** e só a usa **depois** que o administrador deste host a confia com `fibercore-edge managed-trust`. Contrato exato: `docs/wiki/adr/ADR-0046-organizacoes-isoladas-acs-por-organizacao-e-centro-de-olt.md` (D4 e D6). Visão do canal e das chaves: `docs/operations/EDGE_SECRETS.md`.

**Tudo é opt-in.** Sem a seção `managed_olts` no `config.json` o Edge recusa o `kind` (`managed_olts_disabled`) e fica idêntico ao de antes. A seção exige `olt_secrets` (é o mesmo canal).

## O que o Edge nunca faz por ordem da nuvem
- Não conecta fora de `allowed_cidrs`/`allowed_ports`, nem em loopback, multicast, link-local, não especificado, `0.0.0.0/8` e broadcast (mesmo que o CIDR os inclua).
- Não abre sessão, não coleta e **não lê nem envia credencial** de uma OLT `awaiting_local_trust`.
- Não aceita Telnet (`protocol_not_supported`), nem nome de OLT estática (`name_conflict`: a estática manda), nem passa de `max_olts` (contando as estáticas).
- Não "aprende" chave de host: a impressão digital é a **proposta** da nuvem e só vale depois que a pessoa a redigita no host do Edge.
- Não devolve credencial a ninguém (nenhum subcomando imprime credencial).

## Habilitar

1. **Diretório de estado (usuário do serviço do Edge; 0700).** O Edge o cria se faltar e **recusa iniciar** se existir frouxo (como a chave de selagem). Não pode conter outro arquivo do `config.json` (fila, segredos, chave de selagem, `credentials_file` estático).
   ```bash
   sudo install -d -m 0700 -o <usuario-do-edge> -g <usuario-do-edge> /var/lib/fibercore-edge/managed
   ```
2. **`config.json`** (campos novos; `olt_secrets` e `job_public_key` já existem pelo ADR-0045):
   ```json
   "managed_olts": {
     "state_dir": "/var/lib/fibercore-edge/managed",
     "allowed_cidrs": ["10.20.0.0/16"],
     "allowed_ports": [22],
     "max_olts": 16,
     "allow_legacy_ssh": false,
     "allowed_vendors": ["huawei", "zte"],
     "pon_ports": ["0/1/0", "0/1/1"]
   }
   ```
   | Campo | Regra |
   |---|---|
   | `state_dir` | obrigatório; caminho absoluto limpo; 0700, do usuário do Edge. Contém `managed_olts.json`, `trust.json`, `removed.json` (remoções ainda não informadas à nuvem) e `creds/`. |
   | `allowed_cidrs` | **obrigatório**. Recusa `0.0.0.0/0`, `::/0`, prefixo mais largo que `/8` (IPv4) ou `/32` (IPv6) e forma IPv4-mapeada. Use só a rede de gerência das OLTs. |
   | `allowed_ports` | padrão `[22]`. É a porta **efetivamente discada**: `port` (SSH) para `transport:"cli"` e `snmp_port` para `transport:"snmp"` (liste `161` para SNMP). |
   | `max_olts` | obrigatório, 1 a 64: total de OLTs deste Edge, **estáticas incluídas**. Acima disso: `too_many_olts`. |
   | `allow_legacy_ssh` | padrão `false`. Sem isso `legacy_ssh:true` é `legacy_not_allowed`. |
   | `allowed_vendors` | opcional; vazio = os que este binário opera (`huawei`, `zte`). Fora da lista: `vendor_not_allowed`. SNMP só existe para `huawei`. |
   | `pon_ports` | **extensão local** (o ADR-0046 não leva PON na entrega): as portas PON lidas em **toda** OLT gerenciada. Vazio = a OLT é aceita e confiada, mas **não coletada** (o log avisa `pon_ports is empty`). |
3. **Reiniciar o Edge** (a seção só é lida no start; a partir daí o registro é relido a cada ciclo).
4. **Confirmar cada OLT localmente** (passo humano, obrigatório). A OLT chega como `awaiting_local_trust`; o resultado da entrega é `applied` com `code:"awaiting_local_trust"` e a tela da nuvem mostra "aguardando confirmação no Edge".
   ```bash
   fibercore-edge managed-list  -config /etc/fibercore-edge/config.json
   fibercore-edge managed-trust -config /etc/fibercore-edge/config.json OLT-CENTRO-01
   ```
   `managed-list` mostra nome, `ip:porta`, fabricante, transporte, estado, conformidade com a política e a impressão digital **proposta**. `managed-trust` mostra nome, `ip:porta`, fabricante e a impressão digital proposta e **exige que você a redigite**. **Compare com a impressão digital que a própria OLT mostra** (ou `ssh-keyscan` a partir da rede da OLT), nunca com a tela da nuvem. Se não bater, nada é confiado. Só depois a OLT é coletada, no próximo ciclo, sem reiniciar.
5. Ligar as flags `fleet_provision` e `fleet_secrets` do provedor na nuvem por último.

## O que zera a confiança
A confiança fica em `trust.json` como o **resumo SHA-256** dos campos de conexão confiados (nome, `address`, `port`, `protocol`, `transport`, `host_key_sha256`, `snmp_port`, `ssh_mode`, `legacy_ssh` e `vendor`, este último porque escolhe o driver, isto é, os comandos que rodam). Por isso:
- Editar `managed_olts.json` à mão **não ativa nada** (uma OLT nova nasce sem confiança; mudar qualquer desses campos numa já confiada a tira da confiança; voltar ao valor antigo na mão devolve exatamente o que foi confiado).
- Uma entrega `set` que mude qualquer desses campos **apaga** a confiança (e voltar ao valor antigo **não** a traz de volta): rode `managed-trust` de novo. Só o `cloud_id` não zera (não muda para onde o Edge conecta nem o que roda).
- `remove` apaga o registro, a confiança e o arquivo de credenciais.

A confiança e a política são **reverificadas a cada ciclo e de novo na abertura de cada sessão**: uma OLT removida, alterada ou que deixou de caber na política (CIDR/porta/fabricante/legado reduzidos depois) deixa de ser coletada na hora. A confiança é conferida mais uma vez **no instante da conexão** (TCP ou contato SNMP), depois da leitura das credenciais. A revogação vale para a **próxima** conexão: uma sessão que já está aberta termina a sua rodada de leitura (somente leitura; no máximo o orçamento de tempo da OLT, 9 min).

## Credenciais
`ssh_login` e `snmp_community` (ADR-0045) para uma OLT gerenciada vão para `state_dir/creds/<nome>.json` (0600, em `creds/` 0700), automaticamente, **mesmo antes da confiança** (nunca usadas antes dela). Sem registro gerenciado nem `credentials_file` estático: `target_not_configured`. `ssh_login` só para transporte `cli`, `snmp_community` só para `snmp`. Nomes que não são "comuns" (`[A-Za-z0-9][A-Za-z0-9._-]{0,63}`) viram `<prefixo>~<12 hex do SHA-256>.json` (nunca um caminho vindo da nuvem).

## Estado reportado à nuvem
`POST /v1/edge/managed-olts/state` `{"items":[{"cloud_id","state":"awaiting_local_trust|trusted|removed"}]}` (até 64 por chamada), a cada ciclo do laço de entregas (30 s) **quando algo muda** e, no mínimo, a cada 5 min. `removed` é dito uma vez após um `remove`; a pendência é durável (`removed.json`, gravada antes de apagar o registro) e só é limpa depois que a nuvem aceitou o reporte, então uma queda ou reinício do Edge no meio não a perde (no máximo 256 pendências; as mais antigas saem primeiro). `5xx`/`429`/rede: tenta no ciclo seguinte, sem falha de entrega. `404`: "nuvem antiga" (uma linha de log, nova tentativa em 1 h). Outra recusa 4xx: espera 5 min.

## Códigos de resultado (ADR-0046 D5)
`applied` (com `code:"awaiting_local_trust"` enquanto não confiada); falhas: `managed_olts_disabled`, `protocol_not_supported`, `vendor_not_supported`, `vendor_not_allowed`, `address_not_allowed`, `port_not_allowed`, `too_many_olts`, `legacy_not_allowed`, `name_conflict`, e os do ADR-0045 (`bad_signature`, `bad_key_id`, `aad_mismatch`, `expired`, `decrypt_failed`, `invalid_payload`, `stale`, `target_not_configured`, `write_failed`, `state_unreadable`). `name_conflict` também cobre o mesmo dispositivo (IP) ou o mesmo `cloud_id` de outra OLT já configurada. Cada código está no `Result` do Edge e nunca leva valor.

## Resolução de problemas
| Sintoma | Causa | Ação |
|---|---|---|
| Edge não inicia: `managed olts state` | `state_dir` frouxo ou de outro usuário | `chmod 0700`, dono do Edge |
| `managed-list` falha: `unreadable` | `managed_olts.json`/`trust.json` com permissão frouxa, de outro usuário, inválido ou link | corrigir; nada é lido pela metade e nenhuma OLT gerenciada é coletada |
| Confiada e não coletada | `pon_ports` vazio, fora da política, conflito com OLT estática, sem credencial entregue, acima de `max_olts` | `managed-list` (coluna POLICY) e o log (`managed olts: not collected …`) |
| `managed-trust` recusa | impressão digital digitada ≠ proposta; OLT mudou durante a confirmação; fora da política | conferir na OLT; rodar de novo |

## Reversão
- **Parar de coletar as gerenciadas**: remover `managed_olts` do `config.json` e reiniciar. As estáticas seguem; o Edge passa a responder `managed_olts_disabled`; registro, confiança e credenciais ficam no disco, sem uso (apague `state_dir` se quiser).
- **Uma só OLT**: pedir `remove` pela nuvem, ou apagar a entrada pela nuvem; ou desfazer a confiança removendo a linha dela de `trust.json` (parar o Edge antes) ou mudando a entrada.
- **Binário**: o binário anterior (`fibercore-edge.prev`) **recusa** `config.json` com `managed_olts` (campos desconhecidos são rejeitados). Para voltar o binário, remova antes a seção.
- **Nuvem**: desligar `fleet_provision`/`fleet_secrets`; o Edge só recebe `204`/recusas.

## Limite declarado (R-2, ADR-0046)
Uma nuvem comprometida por inteiro pode **propor** qualquer IP/porta dentro de `allowed_cidrs`/`allowed_ports` e uma impressão digital. Nenhuma conexão nem envio de credencial acontece antes de `managed-trust`; o que ela consegue é encher o registro (até `max_olts`) e criar pendências de confirmação. Mitigação: CIDRs apertados (só a rede de gerência), `max_olts` baixo, `allowed_vendors` explícito. Quem confia uma OLT sem comparar a impressão digital **com a OLT** anula a proteção.

## Implantação do binário novo (checklist; NÃO executado por este trabalho)
1. Backup do `config.json` e do binário atual (`fibercore-edge.prev`).
2. `cd agents/edge && go vet ./... && go test -race ./...` e o binário versionado com `-X main.version=...` (a versão é injetada na compilação; o padrão `0.1.0-dev` não muda no código).
3. Trocar o binário **sem** mexer no `config.json` e reiniciar: comportamento idêntico (feature off).
4. Só depois acrescentar `managed_olts` (um `config.json` novo quebra o binário antigo), reiniciar, `managed-list`.
5. Ordem do ADR: **Edge primeiro**, depois nuvem/web; flags por último.
