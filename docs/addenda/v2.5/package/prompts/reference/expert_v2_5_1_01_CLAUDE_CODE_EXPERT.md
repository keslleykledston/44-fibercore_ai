# PROMPT MESTRE — Claude Code — FiberCore AI v2.5.1 Profile Expert Editor

Integre o módulo **Profile Expert Editor** como extensão incremental do **OLT Provisioning & Profile Studio v2.5**. Não reinicie o projeto nem crie um segundo editor isolado.

1. Leia `README_START_HERE.md`, `docs/product/PRD_V2_5_1.md`, arquitetura, UX, segurança, OpenAPI, schema e testes do pacote. Reconciliar com PRD/backlog/ADRs anteriores (v2.1–v2.5), sem sobrescrever mudanças existentes.
2. Audite o repositório real: descubra o que está implementado, o que é stub e a sprint atual. Entregue GAP, ADR de extensão, dependências e plano em PRs pequenos. **Não presuma que o ZIP v2.5 foi integrado**.
3. Reuse FastAPI, Postgres/RLS, Next.js, RBAC, Device Capability Registry, OLT drivers tipados, Edge Connector mTLS, Planner v2.5, Jobs/Approvals/outbox, Help e Observability. Preserve HubSoft-first e v2.4.
4. Primeiro entregue **inventário read-only de profiles físicos por OLT**, snapshots imutáveis e redigidos, importação de referência e comparação semântica. Driver piloto Huawei MA5608T release exato apenas quando houver dados, fixtures enquanto isso.
5. Crie `Profile Expert Editor` com `simple/expert` na mesma tela; N3 pode ajustar DBA/T-CONT/GEM, VLAN/service-port, QoS, portas, tags e extensões **somente quando o driver e firmware declararem suporte**. Não há entrada de CLI livre, scripts shell nem execução pelo LLM.
6. Implementar `clone draft`, versionamento, patch history, ETag, validação schema/capability, diff por alvo e estratégias `reuse_exact`, `adopt_reference`, `clone_new_revision`, `plan_migration`, `blocked`.
7. Profiles existentes compartilhados ou com referência desconhecida nunca são editados em-place. Plano de migração é um job **separado**, com autorização distinta. CLI gerada só visualização read-only redigida.
8. Preview/dry-run primeiro. Writes somente depois de laboratório, release gate por firmware+placa, fingerprints/freshness, locks, aprovação hash-bound, canário, readback independente, auditoria e rollback compensatório seguro. Nenhuma OLT de produção durante esta entrega.
9. UI minimalista iOS-like, estados claros, mobile adaptado, `/ajuda` e screenshots Playwright verdadeiros no PR. Não ocupar a tela N1 com dados N3.
10. Codex deve revisar segurança, multitenant, TOCTOU, parsing, semântica, exclusões involuntárias, retries e testes; Lovable fornece UX de handoff.

**Primeira entrega objetiva:** GAP + ADR + backlog conciliado + mocks + GET inventory/snapshot + import immutable + compare semantic + testes. Declare apenas trabalhos realmente feitos, com caminhos e comandos de teste. Se integração real não estiver disponível, registre `BLOCKED` para homologação, não simule como produção.
