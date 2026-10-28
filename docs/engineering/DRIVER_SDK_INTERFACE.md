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
