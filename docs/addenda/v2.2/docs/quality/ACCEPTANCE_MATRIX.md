# Matriz de aceite v2.2

| ID | Gate | Evidência necessária |
|---|---|---|
| AC-001 | Incremental | Diff/ADR preservam legado e sprint vigente |
| AC-002 | Tenant | Tenant A não acessa B (API, eventos, projection, search) |
| AC-003 | Identidade | ONU/ONT e CPE dual stack sem duplicar assinante |
| AC-004 | Freshness | Edge offline → stale/unknown; não ONU offline generalizada |
| AC-005 | Capability | ação em firmware não certificado bloqueada |
| AC-006 | Subscriber 360 | origens e observed_at em todos campos externos |
| AC-007 | Diagnóstico | rule version, evidências e hipóteses reproduzíveis |
| AC-008 | QoE | dados insuficientes → score null, status insuficiente |
| AC-009 | NOC | incidentes massivos correlacionados sem duplicar todos clientes |
| AC-010 | Workflow | preview sem executar; aprovação e lock em writes |
| AC-011 | Dual-stack | concorrência TR-069/USP de mesma capability bloqueada |
| AC-012 | Resiliência | queda USP/copilot não derruba ACS/core |
| AC-013 | UX | minimalista, estados edge, acessível/teclado/mobile |
| AC-014 | Help | screenshot real 1440/390 + how-to e help_slug no mesmo PR |
| AC-015 | Segurança | PII/PSK sem aparecer nos logs/screenshots/prompts |
| AC-016 | Docs | wiki status/ADR/changelog + PR SHA + Codex veredito |
| AC-017 | API | OpenAPI reconciliado, compatível e com contract tests |
| AC-018 | Performance | p95 e carga medidos em fixture, não apenas alegados |

Nenhum resultado acima foi executado por este adendo; são critérios de verificação futura.
