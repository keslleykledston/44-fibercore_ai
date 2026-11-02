# Reconciliação de templates com profiles já existentes

## Cenários e decisões
| Situação encontrada | Decisão segura |
|---|---|
| Profile igual semanticamente, evidência completa/fresca | `reuse_exact` + binding local, zero writes |
| Profile de terceiros igual e identidade comprovada | `adopt_reference` com origem/fingerprint, sem edição física |
| Mesmo nome/ID, conteúdo diferente | `CONFLICT`, não sobrescrever |
| Profile diferente e em uso por várias ONUs | `clone_new_revision`; IDs exclusivos por alvo; não migrar ONUs involuntariamente |
| Uso/referências não consultáveis | bloquear migração, preferir draft ou plano `blocked` |
| Dados parciais/stale/firmware alterado | pedir nova coleta e novo preview, nenhuma execução |
| Desejo de trocar ONUs de profile | job de migração separado com ONUs explicitamente listadas e aprovação |

## Algoritmo
1. `get_native_inventory` e `get_snapshot`; coletar vendor, modelo OLT, firmware+patch, placa, GPON/XGS-PON/EPON, nome e ID **locais**, dependências e contagem de referências (nullable).
2. `normalize` por parser versionado com proveniência por campo, unidade e semântica exatas. Não comparar VLAN `tagged` com `translation` como equivalentes; não colapsar DBA assured/max, nem upstream/downstream.
3. `semantic_diff` com categorias `EQUAL/CHANGE/ADD/REMOVE/NOT_OBSERVABLE/UNSUPPORTED/CONFLICT` e status de observação. Equivalência exige campos necessários completos, sem unknown.
4. `resolve_bindings`: decidir profile existente, criar variante, ou bloquear; registrar razões, número de ONUs impactadas, dependências T-CONT/GEM/DBA, service-port e VLAN.
5. `plan` com ações tipadas versionadas e `preview` por OLT; exibir custo/risco/afetações, no-op e precondições. Nunca mapear diretamente ID de outra OLT.
6. `publish` snapshot lógico imutável. `request_deploy` exige maker-checker/hash/TTL e revalidação de fingerprint, firmware, referências e locks no Edge. Qualquer divergência invalida plano.
7. `apply` em canário com executores de comandos homologados **internos do driver** e `verify` readback separado; registrar falhas parciais e compensação manual/verificada. Nunca deletar profile compartilhado como rollback.

## Edição manual N3 de templates
- Seção `Formulário`: editor organizado por grupos (DBA, line/T-CONT/GEM, VLAN, ONU ports, service-port, QoS, multicast), com feedback imediato.
- Seção `YAML/JSON`: editor do **mesmo AST declarativo**, com esquema `expert-profile-draft.schema.json`, RBAC N3, If-Match, comparação e snapshot de alterações. Não aceitar root keys arbitrárias.
- Seção `Configuração nativa`: para texto de configuração legado, mostrar **somente como evidência**. Permitir notas/annotations e export de relatório para engenharia, **não envio direto de CLI**. O parâmetro unsupported continua bloqueado até driver e schema homologados.
- Export seguro de revisão: JSON/YAML canônico, checksum, escopo fabricante/firmware/placa, nunca senha ou comandos executáveis.

## Evitar falsas inferências
- Plano comercial 500 Mbps não significa configurar 500 Mbps DBA upstream, caso controle seja no BNG.
- Uma ONU vista em PON não tem necessariamente modelo identificado; campo unknown impede auto-template específico.
- Sucesso SSH/CLI ou HTTP 202 não equivale ao serviço entregue; exigir status físico, perfis, VLAN/service path, e dados de BNG/CPE quando disponíveis.
