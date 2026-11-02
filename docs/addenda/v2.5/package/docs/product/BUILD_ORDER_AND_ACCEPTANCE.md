# Backlog incremental e critérios de aceite

| Fase | Entrega | Aceite mínimo | Dependência |
|---|---|---|---|
| P0.1 | GAP, ADR e contratos alinhados ao repo | rotas sem duplicidade, backlog conciliado | repo real |
| P0.2 | Driver read-only Discovery Huawei LAB/fixture | origem, PON, serial, freshness e conflitos | Capability Registry |
| P0.3 | Inventário e snapshot profiles por OLT | fingerprint, uso, unknown, versão card, data coleta | Edge + Driver |
| P0.4 | Wizard Service Intent | schema, validações, draft versionado | Templates |
| P0.5 | Expert import + clone + diff | sem writes, ETag, campos homologados, diff seguro | P0.3 |
| P0.6 | Prévia e reconciliação multi-OLT | reuse/adopt/clone/blocked por alvo e plano hash | P0.4-5 |
| P0.7 | UI e Ajuda | N1 simples; N3 avançado; screenshots reais | P0.2-6 |
| P1.1 | Publicação de template versionado | revisão imutável e revisão de segurança | P0 |
| P1.2 | Driver write em LAB e ações tipadas | cert exata, maker-checker, preflight, readback | P1.1 |
| P1.3 | Autorizar ONU em LAB | PON + VLAN + serviço verificado, partial unknown | P1.2 |
| P1.4 | Create/clone profile em OLT LAB | não impacta refs existentes, dry-run | P1.2 |
| P2.1 | Lote com canário OLTs múltiplas | concorrência limitada, compensação, sem global rollback | P1 |
| P2.2 | Migração controlada de ONUs | aprovação separada, lista explícita e pós-check | P1 |
| P2.3 | Assistência IA N3 read-only | sugere diff sem autoridade para deploy | P0-P2 |

**Definição de pronto em cada PR:** código + testes de segurança/isolamento + documentação + screenshot real se UI + logs/observabilidade + Codex PASS. Reportar `NOT_TESTED` quando não houve equipamento real.
