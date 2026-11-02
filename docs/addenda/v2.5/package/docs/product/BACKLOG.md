# Backlog incremental FC25 — preservar as sprints atuais

| ID | Pri | Entrega | Critérios objetivos |
|---|---|---|---|
| FC25-00 | P0 | GAP real repo, ADR e plano | Reutilização de inventory, jobs, capability, HubSoft, Edge, RLS, Help |
| FC25-01 | P0 | Discovery adapter **read only** com fixtures | Normalização Huawei piloto; não confundir Edge down / ONU offline |
| FC25-02 | P0 | Fila ONUs pendentes | Busca/filtros + risco/conflito/freshness + screenshot/how-to |
| FC25-03 | P0 | Binding segura ONU ↔ OS/assinante HubSoft | Status read-only; ambiguidade bloqueia aprovação |
| FC25-04 | P0 | Service intent schema + catálogo | Versionamento, RBAC, validation e fixtures |
| FC25-05 | P0 | Profile Studio wizard simples | Cartões + campos condicionais + preview; help |
| FC25-06 | P0 | OLT driver capabilities + inventory profile | Por firmware/placa/card; não homologado read-only |
| FC25-07 | P0 | Dry-run resolver e map lógico→IDs locais | Reuso e drift, collision test, zero write |
| FC25-08 | P1 | Wizard ONU autorizar + approval | Preflight, snapshot hash, maker-checker quando aplicável |
| FC25-09 | P1 | Implementação driver Huawei MA5608T lab | Certificação escrita por release exato, testes reais e logs redigidos |
| FC25-10 | P1 | Execution saga, verification e audit | Estados `UNKNOWN`/`PARTIAL`, no blind retry/rollback |
| FC25-11 | P1 | Deploy seletivo em múltiplas OLTs | Preview por alvo, canário, fila, sem overwrite perfil compartilhado |
| FC25-12 | P1 | Drift detection e reconciliação assistida | Classificação e nenhuma correção silenciosa |
| FC25-13 | P1 | Homologação por modelo + serviço | Lab checklist; publicar só com Certificação; docs/screenshots |
| FC25-14 | P2 | Adaptadores ZTE/FiberHome/Nokia/Datacom | Individual por release e feature; sem presumir sintaxe igual |

Sequência: FC25-00 → 01-04 → 05-07 (somente leitura) → 08-10 (lab) → 11-13 (piloto controlado) → 14. Não deslocar automaticamente HubSoft-first nem tarefas v2.4; conciliar PRDs e backlogs.
