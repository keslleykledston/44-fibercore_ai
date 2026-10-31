# PROMPT DE REVIEW — CODEX

Atue como revisor técnico independente do PR do FiberCore 2.2 `SD-001 — Speed Diagnostics TR-143`.

Compare o **diff real** do PR com `docs/01` até `docs/08`, `contracts`, `checklists/CODE_REVIEW.md` e arquitetura existente. Não reimplemente; faça gate de qualidade e segurança.

Valide:
1. Integração Edge outbound/GenieACS local sem expor NBI.
2. Interface correta de WAN serviço por dispositivo/firmware, sem usar MGMT como banda do cliente.
3. HTTP GET download e HTTP PUT upload, cálculos corretos e counters de interface distintos da transação.
4. Tratamento `200`/`202` NBI, confirmação `8 DIAGNOSTICS COMPLETE` quando acessível, resultados stale e timeout sem retry ofensivo.
5. RBAC/tenant/RLS/URLs permitidas/SSRF/concorrência por ONT-PON-tenant e logs sem segredos.
6. Reúso de módulo existente, aditividade, feature flag e rollback.
7. UI acessível, minimalista, sem métricas inventadas, help center com screenshot real.
8. Testes automatizados e evidência de homologação; diferenciação entre simulado e real.

Responder no formato:
- **VEREDITO:** PASS / WARN / BLOCK
- **ACHADOS:** severidade, arquivo:linha, prova, impacto, remediação mínima
- **COBERTURA:** testes executados, faltantes, riscos residuais
- **REGRESSÕES/INTEGRIDADE:** módulos atuais afetados
- **RECOMENDAÇÃO DE MERGE:** pode/não pode, condicionantes

Não autorizar merge com falhas BLOCK, especialmente NBI público, tenant bypass, stale results, URL arbitrária ou saturação não controlada de PON.
