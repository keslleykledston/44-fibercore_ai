# PROMPT — Codex Supervisor v2.5.1

Revise PR incremental do Profile Expert Editor contra docs v2.5.1 e todo baseline v2.5. Gate: **PASS/BLOCK** com evidências (caminhos/linhas/testes).

1. Permissões/RLS tenant scoped, nunca referência cross-tenant.
2. Profile real (especialmente referenciado) jamais sobrescrito; desconhecimento de referências bloqueia in-place.
3. Diff usa equivalência semântica por vendor e unidade; `NOT_OBSERVABLE` não é igualdade.
4. Import sanitizado read-only, sem execução ou injection; raw CLI não é aceito em POST/PUT/driver; extensões tipadas allowlisted.
5. ETag e snapshot hash + contagem de refs + firmware/card + approval TTL revalidados antes de executar.
6. Migração em job próprio, maker-checker, canário, partial/unknown e no blind rollback.
7. OpenAPI, schema, DB migrations, cache, observability, Playwright e docs coerentes.
8. Verificar regressões v2.5 ONU discovery, v2.4 CPE e HubSoft-first.

Nenhum write real sem evidência de lab certification do driver/firmware/card. Nunca marcar tests/deploy não executados como aprovados.
