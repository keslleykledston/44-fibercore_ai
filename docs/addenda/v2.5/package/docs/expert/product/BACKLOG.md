# FC251 — Backlog incremental, não reiniciar v2.5

| ID | Pri | Dependência | Entrega / critério |
|---|---|---|---|
| FC251-00 | P0 | repo existente | GAP, ADR, backlog e planos sem mudanças invasivas |
| FC251-01 | P0 | FC25-06 | Inventário de profiles nativos / contagem de referências, snapshot read-only com freshness |
| FC251-02 | P0 | FC251-01 | Normalização vendor por schema e proveniência, `UNKNOWN` explícito |
| FC251-03 | P0 | FC25-04 | Importar snapshot/catalogo como referência imutável e clonar draft |
| FC251-04 | P0 | FC251-02/03 | Diff semântico multi-origem e teste de unidades/tags/references |
| FC251-05 | P0 | FC251-04 | Editor Expert de campos tipados por capacidade; sem CLI raw |
| FC251-06 | P0 | FC251-04/05 | Dry-run `reuse/adopt/clone/block` por OLT e impacto ONU |
| FC251-07 | P0 | UI | Design responsivo, RBAC, estados e help/screenshots reais |
| FC251-08 | P1 | jobs/approvals | Publicar nova revisão imutável com change log e maker-checker |
| FC251-09 | P1 | lab certified driver | Clone de profile no laboratório com preflight e readback independente |
| FC251-10 | P1 | FC251-09 | Migração de ONUs por job SEPARADO, canário e rollback seguro |
| FC251-11 | P1 | FC251-09 | Configuração por alvo e drift/reconciliação manual (sem auto-fix) |
| FC251-12 | P2 | driver homologado | Portabilidade multi-vendor + extensões semânticas por firmware |
| FC251-13 | P2 | rule engine + tools | IA N3 só sugere diff, nunca executa |

Ordem respeita os gates v2.5 e HubSoft-first; tarefas podem correr em paralelo sem interromper as sprints atuais.
