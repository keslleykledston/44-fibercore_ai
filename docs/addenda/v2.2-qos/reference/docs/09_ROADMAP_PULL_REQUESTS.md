# Plano incremental de PRs — sem sobreposição

## PR 0 — Inventário e plano (documentação, nenhum write em dispositivos)
- Descobrir `CLAUDE.md`/`AGENTS.md`, arquitetura real, diagnóstico/job engine, tipo de telemetria e SD-001 existente.
- Entregar `CURRENT_STATE.md` (links de paths), `GAP_MAP.md` (feito/estender/novo), `IMPLEMENTATION_PLAN.md` com regressão/risco.
- Verificar como a WAN de serviço é identificada hoje e se há adapter OLT para óptica. Se não for comprovado, deixar bloqueio explícito.

## PR 1 — Backend e capability
- Acrescentar campos/identificadores do QoS ao mecanismo de diagnósticos atual; **preferir adição ao schema** existente. Sem recriar tabela de speed tests, sem nova API duplicada.
- Adicionar mapping opcional TR-181/IGD para leituras e PING/DNS; ações só no Edge existente, acesso NBI protegido.
- Reusar retries, idempotência, jobs, horários, tenant, RLS, locks e auditoria.
- Resultados normalizados com frescor, fonte, status granular, teste `Requested` associado e dados saneados.
- Integração COMPLETO chama serviço existente do SD-001; se este estiver em PR separado, criar interface/contrato e integração desativada até merge.
- Testes Q01–Q18 automatizados que não dependem de hardware; fake NBI, clock controlado e fixtures.

## PR 2 — Sidebar, documentação e homologação
- Inserir `Qualidade do serviço` no drawer atual, 2 modos, mensagens de parcial/bridge/frescor e histórico curto.
- Reusar hooks/estado e padrões de design; sem nova página no menu e sem componentes paralelos.
- Adicionar hipóteses determinísticas, com IDs de métricas e ressalvas, e somente depois expor os registros ao Copilot já existente.
- Capturas reais, how-to, changelog, matriz de suporte, documentação de rollout, testes de UI/a11y e regressão.
- Feature flag OFF, pedir Code Review Codex e aceite de operação antes de habilitar.

## Dependências e bloqueadores
| Dependência | Ação se faltar |
|---|---|
| Adapter GenieACS/Edge real | Não criar endpoint público; menor extensão no Edge atual |
| Identificação da WAN serviço | Bloquear testes ativos de serviço, expor `WAN_UNVERIFIED` |
| SD-001 executável | RÁPIDO funciona; COMPLETO informa etapa de banda indisponível; nenhum segundo motor |
| Capability Registry existente | Reutilizar; se não existe no repo, documentar lacuna e colocar extensões mínimas propostas sem criar sistema novo |
| Adapter OLT óptica | Manter origem indisponível, não inventar vendor path |
| Captura de browser real | Não alegar UI homologada; PR permanece pendente de aceite visual |

## Ativação e rollback
1. Migrar apenas campos/tabela filha realmente indispensáveis; não alterar schema Speed sem necessidade.
2. Fazer testes CI; aprovar PRs com Codex; homologar primeiro em ambiente não produtivo.
3. Habilitar `quality.enabled` somente em tenant e perfil de dispositivo piloto; active tests flag OFF até avaliação.
4. Habilitar `quick` em canário; depois `full` sob RBAC e supervisão do NOC.
5. Erro/regressão: desligar flag QoS; os serviços SD-001/GenieACS/ONU 360 devem permanecer funcionando. Não fazer rollback destrutivo do banco.
