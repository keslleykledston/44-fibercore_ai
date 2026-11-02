# Contrato do reconciliador e editor avançado

## Interfaces do driver (tipadas, não CLI passthrough)
```python
class OltProfileReadAdapter(Protocol):
    async def inventory_profiles(self, target: OltTarget) -> list[NativeProfileSummary]: ...
    async def read_profile_snapshot(self, target: OltTarget, native_key: NativeKey) -> ProfileSnapshot: ...
    async def count_references(self, target: OltTarget, native_key: NativeKey) -> ReferenceEvidence: ...
    async def read_capabilities(self, target: OltTarget) -> CapabilityEvidence: ...

class OltProfilePlanningAdapter(Protocol):
    async def normalize(self, snapshot: ProfileSnapshot) -> NormalizedProfile: ...
    async def validate(self, draft: CanonicalDraft, capability: CapabilityEvidence) -> ValidationResult: ...
    async def compile_typed_plan(self, draft: CanonicalDraft, target: OltTarget) -> PlannedActions: ...
    async def verify_plan(self, plan: ApprovedPlan, target: OltTarget) -> VerificationResult: ...
```

Executar somente usando o executor tipado do v2.5 (certificado). Nenhum endpoint de `exec_command`, `run_cli`, `ssh_command` genérico. Um editor visual pode permitir **ver** a CLI gerada pelo driver certificado, em bloco read-only e com redação de segredos. Para exceções vendor-native, usar `vendor_extensions` com JSON Schema assinado, allowlisted e homologado; texto de comando **nunca** vira ação.

## Algoritmo de reconciliação
1. `read(native profile)` → `snapshot+provenance`, coletar quantidade de ONU/service references (`null` se não verificável).
2. `normalize` com mapeamentos testados; guardar `observed`, `normalized`, `unknown`, `vendor_extensions` e confiança.
3. `compare(template revision, snapshot)` como campos **semânticos** (set, ordered list quando ordem tem significado, unit normalization kbps, tag stack). Classificar `EQUAL`, `CHANGE`, `ADD`, `REMOVE`, `NOT_OBSERVABLE`, `UNSUPPORTED`, `CONFLICT`.
4. Propor `reuse_exact` se fingerprint semântico realmente igual e evidencia fresca; `adopt_reference` se apenas vincular perfil externo após validação; `clone_new_revision` se mudança significativa; `plan_migration` para ONUs atuais somente em job distinto; `blocked` caso faltas.
5. `preview` com preconditions, impacts, dependencies, new profile ID/name mapping, transaction limitations, risk, approval policy.
6. Fase opcional write só após lab e autorização: revalidate snapshot+references+firmware, `prepare`, `apply` typed, readback, verificar referência e serviço; estados `VERIFIED/PARTIAL/FAILED/UNKNOWN`.

## Propriedades mínimas normalizadas
- Contexto: `technology`, vendor/product/firmware/card, profile kind, nome/ID local, referencia da OLT.
- GPON quando aplicável: `dba_type`, assured/max/fixed kbps, T-CONT allocations, GEM bindings, line mapping, ONU port capabilities, VLAN tag/translation/QinQ, multicast/IGMP, QoS/shaping_owner, service-port references.
- XGS-PON e EPON usam extensões e compiladores próprios; **não** forçar semântica GPON em todas tecnologias.
- Matriz de compatibilidade por modelo/firmware/placa e operação. Mostrar `unsupported/unknown` se sem evidência.
- QoS não deve duplicar limitação já aplicada por BNG; plano 500 Mbps não se traduz automaticamente em DBA 500 Mbps.

## Regras de conversão
Comparar `500 Mbps` com `500000 kbps` normalizados, mas não colapsar *assured* vs *maximum* ou upstream vs downstream. Comparar VLAN 200 `tagged` é diferente de VLAN 200 `translation`. Profile com mesmo nome mas conteúdo distinto = `CONFLICT`, nunca overwrite. Nomes/IDs nativos são localizados por alvo e não entram no hash de equivalência quando intencionalmente irrelevantes.

## Import/export
- Import da OLT = read-only, ETag e origem preservados.
- Import de catálogo = cópia de revisão imutável; não altera original.
- Export = JSON schema validado, assinatura/hash, sem credenciais/CLI executável; marcado `DRAFT|CERTIFIED` e vendor/firmware scope.

## Templates legados e ajustes manuais
O driver poderá reconhecer e importar **saídas de configuração obtidas da OLT** por parsers versionados e testados, mantendo o texto original sanitizado apenas para auditoria. Itens desconhecidos entram em `unparsed_lines/NOT_OBSERVABLE`; nunca convertê-los em comandos executáveis. O usuário N3 poderá editar o **modelo canônico tipado** em JSON/YAML ou formulário visual, com a mesma validação backend. Uma alteração manual de propriedade unsupported deverá retornar erro explícito, não ser simplesmente ignorada na renderização. Converter `Line Profile` Huawei em objetos `tcont/gem/vlan` só se o driver da release comprovar semântica. ZTE ou FiberHome não herdam esse mesmo compilador.
