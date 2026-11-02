# PRD incremental v2.5.1 — Profile Expert Editor

## Objetivo
Um operador **Engenharia/N3** poderá transformar profiles já criados em OLTs ou no catálogo FiberCore em templates reutilizáveis e seguros, otimizando parâmetros avançados conforme especificidades reais, usando edição semântica, comparação e validação antes de qualquer aplicação. Usuários N1/N2 continuam no wizard simples.

## Personas e autorização
- `olt.profile.read` (NOC): visualizar inventário/snapshots sanitizados.
- `olt.profile.draft.edit` (N3): importar/clonar/editar rascunhos, nunca executar por si.
- `olt.profile.publish` (N3/gestor designado): publicar versão lógica depois dos checks e eventual revisão por outra pessoa.
- `olt.profile.deploy.request` (engenharia): solicitar execução.
- `olt.profile.deploy.approve` (aprovador distinto, maker-checker quando policy exigir): autorizar o hash exato do plano.
- Permissão de executar no driver/Edge fica no worker com credencial curta, nunca no browser/LLM; por tenant e alvo.

## Experiência principal
1. **Explorar**: selecionar ISP, POP, OLT, firmware, placa PON. Listar profiles nativos e bindings existentes (DBA, Line, Service, T-CONT, GEM, VLAN, ONU-Type, traffic, outros por vendor). Coleta read-only, data age e confiança.
2. **Importar snapshot**: trazer config como **referência imutável** com hash, origem, nome e ID locais, contagem de ONUs que usam, capacidade de edição por campo, status `complete/partial/unknown`.
3. **Comparar**: selecionar template lógico ou outro snapshot. Diff semântico `equal/change/add/remove/not_observable/unsupported/conflict`; origem e consequência em uma linha. Nunca comparar só por nome.
4. **Editar**: abrir rascunho clonado, campos estruturados e validações imediatas: DBA/T-CONT, GEM, VLAN/QinQ, Ethernet ports, QoS owner/shaping, multicast/IGMP/VoIP, model constraints, ordem de serviço, descrição. Campos vendor-specific só quando schema/capability validado; `raw CLI` jamais em campo editável de execução.
5. **Resolver binding**: por OLT, selecionar `reuse_exact`, `adopt_reference`, `clone_new_revision`, `plan_migration` ou `blocked`. Profile compartilhado: preferir clone-on-write; separar migração do deploy do profile.
6. **Simular**: dry-run por OLT com diff, dependências, impacto, contas de referências, names/IDs livres, conflitos, janela e risco. Marcar targets explicitamente (default nenhum).
7. **Publicar**: versão imutável do template lógico com changelog, autor e fingerprint; publicação não executa OLT. Execução exige aprovação, driver lab-certified e gate de release.
8. **Auditar**: timeline: importação → edição → revisão → aprovação → execução → readback → `VERIFIED/PARTIAL/UNKNOWN/FAILED`.

## Regras irrenunciáveis
- Sem mudança in-place em profile já referenciado em produção; clonar e migrar ONUs em job separado.
- Nunca auto-corrigir drift nem sincronizar alterações externas sem revisão.
- Reaproveitar profile físico se semanticamente idêntico, não apenas pelo ID/nome.
- Per-target: versão firmware, OLT, card, tecnologia PON e vendor driver certificados.
- Operações de backend não aceitam texto CLI arbitrário, scripts shell ou comandos enviados pelo LLM.
- Importar da OLT nunca muda o equipamento; importação não requer credenciais write.
- Nenhuma transação global presumida entre OLTs; cada uma pode falhar separadamente.
- Persistir proveniência e timestamp de cada campo observado, com `STALE/UNKNOWN` versus `OFFLINE`.

## Escopo e não-escopo
**V1 Expert (P0):** inventário, import read-only, clone draft, diff semântico, editor de campos homologados, preview e documentação.
**P1:** publish versionado e bindings por OLT, aprovação, deploy canário em laboratório, pós-check, migração separada.
**P2:** multi-OLT rollout, detecção/reconciliação drift avançada, export de bundles revisáveis, assistência IA somente sugestão.
Fora: CLI shell arbitrária em produção, alteração massiva silenciosa, edição direta de credenciais CPE, autoaprendizagem executável a partir de textos de configuração.

## Evidência de pronto
Demonstrar `import -> clone -> edit -> diff -> validate -> preview` em fixtures; diffs confiáveis, sem side effects. Em P1, cenário laboratorial real com comprovação de readback e sem impacto em profiles compartilhados. Screenshots e How-to no mesmo PR.
