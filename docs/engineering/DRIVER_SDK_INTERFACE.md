# Driver SDK e template de homologação

## Interface Go/Python conceitual (escolha por domínio)

```text
interface DeviceDriver {
  Identify(ctx, endpoint) -> DeviceIdentity
  GetCapabilities(ctx, model, firmware) -> []Capability
  DiscoverTopology(ctx, target) -> Snapshot[Chassis/Card/PON/ONU]
  ReadMetrics(ctx, target, paths) -> []Observation
  PrepareAction(ctx, actionIntent) -> Preview[diff, prechecks, risk, postcheck]
  ExecuteAction(ctx, approvedJobEnvelope) -> ExternalTaskRef
  GetActionStatus(ctx, ref) -> ActionStatus
  Verify(ctx, action, expectedState) -> VerificationResult
}
```

Implementar portas tipadas e adapters por `vendor -> family -> firmware-major/minor`. Não colocar parser CLI no web/api-core; manter no Edge ou worker de normalização com fixtures. Inventário fica ativo mesmo quando action driver está desabilitado.

## Fixture de homologação

Para cada firmware coletar arquivos sanitizados: `device_identity.json`, `inventory_input.txt`, `inventory_expected.json`, `optics_input.txt`, `optics_expected.json`, `unsupported_cases.json`, `failures.json`, `lab_run.md`, `source_refs.md`, `license_review.md`. Em fixture real substituir serial/CPF/IP público/usuários/tokens por equivalentes sintéticos; preservar estrutura das respostas.

## Regras de template

1. Renderizar service intent no preview; validar VLAN range, GEM/T-CONT/DBA/line profile, compatibilidade CPE e OLT.
2. Detectar conflito de provisionamento, PON capacity, já autorizado e cliente sem contrato.
3. Promover ação somente após certificar exata combinação vendor/model/firmware/operation.
4. Exibir diff e comandos apenas no ambiente autorizado, mascarando senhas.
5. Pós-check independente da saída CLI de sucesso; `commit` não prova serviço online.
6. Versionar template e checksum; mesma intent com revisão nova precisa de aprovação renovada quando impactante.

## Definição de semântica

- `identified`: família conhecida, **sem garantia de leitura**;
- `observed`: leitura comprovada em fixture/lab, sem write;
- `certified`: operação definida e ensaiada por firmware e transport, com evidência de aceite; somente então pode ser habilitada com política do tenant.

## Completude da leitura (obrigatório para `observed`)
`complete=true` numa PON alimenta a correlação de incidentes em massa. O Edge só o declara para drivers `observed`. Para promover um driver, a fixture real deve mostrar como a CLI sinaliza que a listagem terminou (rodapé, total de ONTs, prompt de volta) e o parser deve validar esse sinal: saída sem ele, ou com contagem divergente, é erro, não lista parcial. Saída com prompt de paginação já é rejeitada (`ErrPaginated`), mas truncamento sem marcador só é detectável com o sinal de término real de cada fabricante/firmware.


## Transporte SSH por OLT: shell interativo e algoritmos legados (validado em MA5608T R015)

Observado em equipamento real (2026-10-28, `agents/edge/internal/olt/testdata/huawei_ma5608t/`):
- **Não atende SSH exec**: o comando volta vazio. Config `ssh_mode: "shell"` abre UM shell (pty) por sessão; o prompt é aprendido no login (`NOME>`/`NOME#`) e todo comando só termina quando o MESMO prompt volta.
- **Prompt de parâmetros opcionais** (`{ <cr>|backplane<K>|frameid/slotid<S> }:`): o shell envia exatamente UM Enter por comando (completa o mesmo comando). Um segundo prompt do mesmo tipo, confirmação (`(y/n)`, `are you sure`, senha) → `ErrInteractive`. Paginação → `ErrPaginated` imediato (não espera timeout). Nunca se envia tecla ao pager.
- Shell que falhou/estourou tempo é descartado: nunca reutilizado em estado desconhecido.
- **SSH legado** (`legacy_ssh: true`, padrão `false`): restringe a negociação a DH group14/group1-SHA1, `ssh-rsa`, AES-CBC. É um downgrade explícito, por OLT. A **host key fixada continua obrigatória**, então o downgrade não abre espaço para MITM. Preferir sempre atualizar o firmware/SSH da OLT.
- Elevação de privilégio (`enable`) **não** está implementada nem na allowlist; exige decisão explícita do dono da rede.
- A allowlist exata (`ReadOnlySession`) continua antes de qualquer byte ir ao shell.
- **O shell não prova o fim do comando.** O fim é inferido de um prompt que o próprio equipamento controla (aceito só como última linha inteira igual ao prompt aprendido, sem linha-prompt no meio, após silêncio de `PromptQuiet`, padrão 1 s). Nenhum silêncio fixo garante que nada mais virá. Por isso o transporte shell implementa `EndProver` com `EndProven()==false` e o coletor só declara `complete=true` se **driver `observed` E transporte com fim comprovado** (SSH exec: EOF + exit status). Um driver que use shell só poderá declarar completude no futuro com verificação em banda (ex.: linha de total/contagem de ONUs na própria saída), a ser validada com captura real. Hoje isso não existe: PON via shell é sempre `complete=false`.

## Perfil `huawei_ma56_r015` (MA5600/MA5603/MA5608T, MA5600V800R015) — validado em equipamento real
Capturas reais sanitizadas em `agents/edge/internal/olt/testdata/huawei_ma5608t/MA5600V800R015C00/` (`lab_run.md`). **Nível no Registry: `identified`** (revisão do Codex: 1 PON / 2 estados não sustentam `observed`). Enquanto for `identified`, nenhuma PON dessa firmware sai `complete=true`; a verificação pelo rodapé já está implementada e testada, mas só passa a valer na promoção.
- **Seleção**: `profile: "huawei_ma56_r015"` na OLT (junto com `ssh_mode: "shell"`, `legacy_ssh: true`, `ssh_pager_space: true`). O driver Huawei genérico **recusa** MA56xx e o perfil R015 recusa o que não for MA56xx; a allowlist de modo de CLI só existe no perfil.
- **Comandos** (allowlist exata): `display version`, `enable`, `config`, `interface gpon F/S`, `display ont info <porta> all`, `display ont optical-info <porta> all`, `quit`, `display board 0`. `enable`/`config`/`interface gpon` só mudam o modo da sessão (necessário: os `display` de ONT só existem dentro de `interface gpon`); nenhuma configuração é alterada. A forma global `display ont info summary 0/0/14` **não existe** nesta release (`Parameter error`). `quit` só é enviado de dentro de `interface gpon`.
- **Pager**: a OLT pagina com `---- More ( Press 'Q' to break ) ----` (~25 linhas) **ignorando a altura do pty**. Com `ssh_pager_space`, o shell responde com **uma única tecla Espaço** por prompt (somente avança a leitura). O dispositivo apaga o prompt com `ESC[37D` + 37 brancos + `ESC[37D`; o driver só remove o prompt se o apagamento for exato (mesma distância e mesmo número de brancos). Limite de 64 páginas. Pager sem apagamento, outro formato de pager, ou limite estourado → `ErrPaginated` (falha fechada). Nunca se envia `Q`, `scroll` nem `screen-length`.
- **Prova de completude EM BANDA**: a listagem termina com `In port 0/ 0/14, the total of ONTs are: 12, online: 3`. `PON.Verified` só é verdadeiro se: o rodapé existe **uma única vez**, nomeia **esta** porta, o total declarado é igual às linhas lidas (ONT-IDs únicos, todos desta porta, estados `online`/`offline` conhecidos) e o número de `online` confere. Falta de linha, rodapé ausente/duplicado/divergente, estado desconhecido ou linha de outra porta → `Verified=false`.
- **Checklist de promoção a `observed`** (todas com captura real sanitizada; **bloqueio (2026-10-29): a OLT homologada não tem PON vazia — as 32 têm de 6 a 60 ONTs —, então o item (a) não pode ser comprovado nela; promover exigiria outra OLT/PON, ou aceitar explicitamente o rodapé de PON vazia como não verificado**): (a) uma PON vazia; (b) uma PON com várias páginas de pager; (c) uma segunda placa/slot; (d) estados fora de online/offline e as causas de queda (`display ont register-info`); (e) PON com ONTs em LOS. Sem isso, `identified`.
- **`complete`** no coletor = driver `observed` **E** (transporte com fim comprovado **OU** `PON.Verified`). Um shell sozinho nunca basta; a contagem da própria OLT é a prova. Isso fecha o achado do Codex sobre prompts forjados no meio da saída: uma saída truncada não bate com o total do rodapé.
- **Limites desta homologação**: 1 PON, 12 ONTs, só estados `online`/`offline`. Causas de queda (LOS, dying-gasp) **não** aparecem nesta tabela (estão em `display ont register-info`, ainda não capturado). Descrições (2ª tabela) são ignoradas. Rx = coluna `Rx power` (lado ONT); `OLT Rx ONT power`, temperatura, tensão e corrente não são enviados ainda.
- **SNMP**: alternativa preferível para volume (sem pager/login, fim do walk inequívoco). OIDs e escalas da `HUAWEI-XPON-MIB` precisam ser confirmados com `snmpwalk` nesta release antes de qualquer driver.

### Cobertura real do perfil R015 (2026-10-28): 32 PONs, 775 ONTs
Leitura das 32 PONs das placas 0 e 1 (`display ont info <porta> all`, Espaço no pager): 6 a 60 ONTs por PON, 0 a 5 páginas de pager. Em **todas** o total do rodapé = linhas lidas e só aparecem os estados `online`/`offline`; o parser verifica 32/32. Fixtures sanitizadas: PON de 5 páginas (60 ONTs), PON de 6 ONTs sem pager, PON da 2ª placa com 4 páginas (53 ONTs) e `register-info`. A coluna `Description` da 2ª tabela contém texto livre que **identifica assinantes**: nunca vai para fixture, log ou payload (as fixtures a trazem neutralizada).
Não coberto: PON sem ONT (formato do rodapé desconhecido → `Verified=false`, fail-safe) e a **causa da queda**, que não está nessa tabela (está em `display ont register-info <porta> <ont>`: `DownCause: ONT dying-gasp`, `ONT link-down`, ...; fixtures `register_info_*`).

### Achado: a regra de incidente em massa não serve para este parque (por isso o nível segue `identified`)
`apps/api/app/api/noc.py` abre `pon_mass_outage` quando uma PON **completa** tem ≥5 ONTs e ≥80% em `offline|los|dying_gasp`. Nesta OLT 290 de 775 ONTs (37%) estão offline de forma crônica (cadastros antigos/sem uso). Com `complete=true` a regra abriria incidente **permanente e falso** em 2 das 32 PONs (0/0/9: 33 de 38 offline; 0/1/5: 5 de 6), sem queda alguma. Promover o driver a `observed` antes de mudar a correlação criaria alarme falso. **Resolvido pela ADR-0018 (migration 0012):** a correlação agora usa quedas recentes (online→down na janela de 6 h, só em snapshot fresco), exclui as crônicas do cálculo e resolve pelas ONUs que o incidente cobre. A promoção a `observed` segue dependendo do checklist (PON vazia, causas de queda).

### SNMP (v2c) validado na MA5608T R015 — leitura
Alcance: UDP/161 da OLT (a OLT só é alcançável a partir da rede do host do GenieACS). A community não é registrada no repositório; recomendar SNMPv3 `authPriv` e ACL por origem (v2c trafega a community em claro). O agente SNMP da OLT é lento: respondeu a `snmpget` com várias colunas por pacote, e uma varredura com muitos pedidos curtos seguidos gerou timeouts. Preferir GET com muitos OIDs por PDU, pausa entre pacotes e nunca varrer a tabela inteira.
`ifIndex` GPON = `0xFA000000 + slot·8192 + porta·256` (PON 0/0/14 = 4194307584). Índice da ONT = `<ifIndex>.<ont-id>`. Base `1.3.6.1.4.1.2011.6.128.1.1.2`:
| Tabela.coluna | Conteúdo | Validação vs CLI |
|---|---|---|
| `43.1.3` | SN (OCTET STRING 8 bytes) | 12/12 iguais |
| `43.1.9` | descrição (texto livre; dado de assinante) | confere nas amostras |
| `46.1.15` | estado de execução: 1 online, 2 offline | 12/12 iguais |
| `46.1.24` | código da última queda (offline): **13 = dying-gasp, 2 = LOSi/LOBi (perda óptica), 1 = link-down** reportado pela ONT | 10 ONTs offline cruzadas com `display ont register-info` (a causa mais recente): 10/10 |
| `45.1.2` | vendor-id da ONT (inteiro = 4 letras ASCII) | confere com `register-info` |
| `51.1.1..5` | temperatura °C, corrente mA, Tx ×0,01 dBm, Rx ×0,01 dBm, tensão mV (`2147483647` = sem leitura) | Rx igual ao CLI (−13,28) |
Não confirmados: `51.1.6` (valor ≈ distância em m, hipótese) e a origem do `OLT Rx ONT power`. SNMP dá fim de tabela inequívoco (o walk termina), o que dispensa pager e prompt, mas só vira driver depois de nova validação e revisão.

Mapeamento de causa para o status da ONU (proposto, ainda sem driver): `13 → dying_gasp` (energia do cliente), `2 → los` (perda óptica; suspeita de fibra/CTO), `1 → offline` (link-down informado pela ONT, causa não determinada). Outros códigos → `offline` sem causa. Só vale para a última queda de uma ONU que está offline agora; ONU online não tem causa. `register-info` mostra o histórico (várias quedas por ONU, com horários) e não é necessário para o estado atual quando o SNMP está disponível.

### Driver SNMP no Edge (`transport: "snmp"`) — somente leitura, v2c
- **Config**: `transport:"snmp"`, `snmp_address` (**IP literal** `ip:161`, também listado em `allowlist`; sem DNS), `snmp_community_file` (0600), `snmp_pace_ms` (0 = 1000; **mínimo 1000**, imposto no código e na config), `snmp_max_requests` (padrão 400 por ciclo, máx. 1000; conta **pacotes**, retransmissões inclusas), `pon_ports`. Campos SSH não são aceitos junto. Só Huawei/MA5600 R015.
- **Somente leitura por construção**: o código só emite GET e GETBULK (teste proíbe `Set`/trap no fonte); a community nunca vai a log nem a erro (redigida).
- **Completude com prova de protocolo**: a varredura é um laço GETBULK próprio; **única saída de sucesso** = o agente respondeu com OID fora da subárvore ou `endOfMibView`. Timeout, OIDs não crescentes, resposta vazia, limite de linhas ou orçamento de pedidos = erro (snapshot inteiro falha, sem dados parciais). Duas varreduras independentes da mesma PON (estado `46.1.15` e serial `43.1.3`) precisam listar os mesmos ONT-IDs, com estados conhecidos (1/2), seriais de 8 bytes e únicos; só então `PON.Verified=true`. O coletor ainda exige driver `observed` para `complete=true`.
- **Estado e causa**: `46.1.15` 1→online, 2→offline; offline + `46.1.24`: 13→`dying_gasp`, 2→`los`, resto→`offline`. Rx = `51.1.4`/100 dBm só para online (`2147483647` = sem leitura).
- **LIMITE OPERACIONAL MEDIDO (importante)**: o agente SNMP da MA5608T **limita a taxa**. Responde em 20–200 ms, mas depois de ~17 pedidos em ~20 s **para de responder a qualquer pedido por mais de 1 minuto**. Isso pode afetar outros clientes SNMP da mesma community (ex.: monitoramento). Por isso há um **piso de 1 pedido/s** (não é um ritmo provadamente seguro, só o mínimo defensável com a medição que existe), orçamento de pacotes por ciclo (cada retransmissão consome pace e orçamento; o deadline do ciclo interrompe uma chamada bloqueada) e **resfriamento de 5 min por OLT depois de qualquer falha de SNMP** (o Edge não toca no agente mudo); uma PON de 12 ONTs custa ~7 pedidos, uma de 60 ONTs ~20. Para cobrir as 32 PONs o CLI continua sendo a via principal; o SNMP serve a poucas PONs/ciclos espaçados até que o limite do agente (ou a configuração da OLT) seja conhecido.
- **Validação ao vivo**: PON 0/0/14 lida pelo driver Go: 12 ONTs, 3 online, `Verified=true`, igual ao CLI. As PONs grandes (60 e 53 ONTs) **não** puderam ser lidas por SNMP: o agente deixou de responder (limite acima). O teste ao vivo é opt-in (`R015_SNMP_ADDR`, `R015_SNMP_COMMUNITY_FILE`, `R015_SNMP_PONS`).
