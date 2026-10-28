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
