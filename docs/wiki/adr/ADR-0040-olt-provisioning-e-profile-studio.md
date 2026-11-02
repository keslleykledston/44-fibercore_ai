# ADR-0040: OLT Provisioning, Profile Studio e Modo Especialista (v2.5)

Status: **Accepted para a fase somente leitura (P0)** em 2026-11-02 (o responsável delegou a escolha da ordem e pediu que a prioridade fosse analisada); **Proposed para a escrita (P1/P2)**, que exige homologação em LAB e emenda do ADR-0030 | Data: 2026-11-02 | Owner: equipe | Origem: `docs/addenda/v2.5/` (GAP em `GAP_ANALYSIS.md`; pacote em `package/`)

## Contexto
O pacote v2.5 pede três módulos sobre o que já existe: (A) descoberta e autorização de ONU, (B) Profile Studio assistido (intenção de serviço neutra de fabricante) e (C) Modo Especialista N3 (importar, comparar, editar e versionar profiles existentes). O repositório já tem o motor de jobs com aprovações e envelope assinado, o registro de capacidades, o catálogo fechado de consultas somente leitura da OLT (inclusive `olt.autofind`, ainda não validado), o ERP hub HubSoft-first, o padrão de pré-visualização com diff redigido (ADR-0036) e a exclusão por alvo no despacho (FC22-015). Não existe parser de autofind, inventário de profiles, tabela de snapshots nem tela. A OLT Huawei da LAB tem ONTs em uso: nada novo é lido nela sem captura supervisionada (ADR-0032) e ordem do responsável. `HOMOLOGATED_WRITES` está vazio e continua.

## Opções
A. Seguir o backlog já programado (FC22-014 primeiro) e tratar o v2.5 depois. Mantém a linha, mas constrói duas vezes o dry-run/diff e adia o fluxo de maior valor.
B. Construir o v2.5 inteiro, incluindo execução na OLT. Rápido na aparência e inaceitável: nenhum driver de escrita é homologado.
C. **Construir o v2.5 em camadas, somente leitura primeiro**, reaproveitando o motor existente; absorver o FC22-014 no dry-run/preview do v2.5; deixar a execução condicionada à homologação. Escolhida.

## Decisão
1. **Prioridade:** o v2.5 (fase somente leitura) passa à frente do FC22-014, que fica **absorvido** por FC25-07 e FC251-06/08. FC22-010 e FC22-016 seguem no backlog.
2. **Não se reinicia nada:** o v2.5 é aditivo. Reusam-se jobs/aprovações, o registro de capacidades, o catálogo de consultas, o ERP hub, RLS, flags por provedor, a ajuda por construção e o padrão do ADR-0036.
3. **Modelo canônico tipado, sem CLI livre:** o profile editado é um objeto de **campos fechados** (DBA, T-CONT/GEM, VLAN/tradução, QoS, portas da ONU, multicast, descrição) mais `vendor_extensions` sob JSON Schema com allowlist. Nenhum `run_cli`, script ou texto de comando do navegador, da IA ou de formulário chega à OLT. CLI importado é **evidência não confiável**, sanitizada, nunca executável; a prévia de comandos gerados pelo driver é somente leitura.
4. **Fail closed:** `UNKNOWN`, `STALE`, dado parcial, campo não observável ou número desconhecido de referências **bloqueiam** equivalência e aplicação. Equivalência é **semântica** (por campo, unidade e tipo), nunca por nome, ID ou texto.
5. **Sem edição no lugar:** nenhum profile existente, compartilhado ou não, é alterado; vale clone na escrita mesmo com zero referências. Migração de ONUs é job **separado**, com lista explícita e aprovação própria. Estratégias por alvo: `reuse_exact`, `adopt_reference`, `clone_new_revision`, `plan_migration`, `blocked`; os IDs são **locais à OLT**, nunca globais.
6. **Imutabilidade:** snapshot importado e revisão publicada são imutáveis (por concessão do banco: sem `UPDATE`/`DELETE`); o rascunho é mutável com `row_version` e `If-Match`. Publicar uma revisão **não** envia nada à OLT.
7. **Flags desligadas por padrão** (`olt_provisioning.*`); `olt_writes_enabled`, `authorize_onu_real`, `create_profile_real`, `migrate_onus_real` e `bulk_rollout_real` nascem `false` e nenhuma delas é ligada por este ADR.
8. **Escrita (P1/P2), condicionada:** homologação em LAB por vendor/modelo/firmware+patch/placa/operação, maker-checker, `plan_hash` com TTL, locks por OLT/profile/ONU (reusando a exclusão por alvo), canário, pré e pós-verificação com leitura de volta independente, estados `PARTIAL`/`UNKNOWN` sem rollback cego, e uma **emenda do ADR-0030** antes de qualquer operação nova de escrita.
9. **Dados:** DDL do pacote reescrito no padrão do repositório (RLS forçada, `tenant_id` composto, sem `DELETE`); fixtures sintéticas; LOID/serial mascarados por papel; nenhum segredo em auditoria ou captura.

## Consequências
- Primeira entrega testável sem equipamento: núcleo puro (diff semântico, resolução, `plan_hash`), migração aditiva, API de importação/rascunho/comparação/dry-run e a fila de pendentes com mock. Cada PR tem Codex e, se tiver tela, capturas reais e how-to.
- Rollback: as migrações são aditivas (`DROP TABLE`) e as flags estão desligadas; reverter não toca equipamento.
- Risco principal: confundir fixture com integração real. Cada tela e doc diz o que é sintético; `NOT_TESTED` é registrado quando não houve OLT.
- Fora do escopo agora: qualquer escrita em OLT, migração de ONUs, lote, outros fabricantes além do piloto Huawei (firmware e placa **a confirmar** no laboratório).
