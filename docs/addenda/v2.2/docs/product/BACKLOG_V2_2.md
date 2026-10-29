# Backlog aditivo: FC22-001...FC22-018

| ID | Pri | Fase | Story / entrega | Dependência e aceite |
|---|---|---|---|---|
| FC22-001 | P0 | planejamento | Audit do repo + matriz de gaps/impacto | checkpoint e ADR sem sobrescrita |
| FC22-002 | P0 | base | Capability Registry modelo+firmware+protocolo | migrations, auth e tests; unknown default |
| FC22-003 | P0 | base | Data freshness/provenance em snapshots | observed_at/quality + tests stale |
| FC22-004 | P0 | API | Customer Context API read-only | auth tenant + contratos + fixtures |
| FC22-005 | P0 | UX | Subscriber 360 | interface + estados + help/screenshots |
| FC22-006 | P0 | regras | Deterministic Diagnostic Rule Engine | rules versioned, no LLM write |
| FC22-007 | P0 | UX | Guided Troubleshooting N1 | passo e evidências + help/screenshots |
| FC22-008 | P0 | NOC | Incidente agrupado por PON/OLT | checks collector-down + dedup |
| FC22-009 | P0 | UX | NOC Command Center | prioridade + impacto com fonte |
| FC22-010 | P1 | rede | Network Explorer POP/OLT/PON/CTO/ONU | relações com fonte/confidence |
| FC22-011 | P1 | QoE | Optical Health score | fórmula v1, coverage, insufficient_data |
| FC22-012 | P1 | QoE | Home Experience score | só com telemetria disponível |
| FC22-013 | P1 | UX | Wi-Fi Experience | capabilities/UX sem dados inventados |
| FC22-014 | P1 | automação | Workflow Definition Registry + preview | dry-run, versioned, approvals |
| FC22-015 | P1 | segurança | Mutation lock across CWMP/USP | tests concurrent writes + postcheck |
| FC22-016 | P1 | plataforma | Module health/version/changelog UX | isolamento de falhas e canary |
| FC22-017 | P1 | docs | Contextual Help Screenshots/How-to | E2E Playwright real; Codex gate |
| FC22-018 | P2 | IA | Copilot read-only Customer Context tools | tenant scope, RAG, redaction |

## Dependências
FC22-001 precede todos. FC22-002/003 -> 004 -> 005/006 -> 007/008/009. FC22-002/003 -> 011/012 -> 013. FC22-002 e job approvals existentes -> 014/015. FC22-017 acompanha **todos os PRs de tela**, não é tarefa única de fim.

## Entregas por sprint
- **S0 aditivo:** FC22-001, ADRs, contratos, issues e testes de migração.
- **S1 incremental:** FC22-002 a 005.
- **S2 incremental:** FC22-006 a 009.
- **S3 incremental:** FC22-010 a 013.
- **S4 incremental:** FC22-014 a 016; FC22-018 em trilha posterior.

## Definition of Done
Feature flag por tenant, contrato+tests, segurança+RLS, observabilidade, estados de ausência, doc técnica/ADR/wiki, prova de que módulo opcional não derruba core; tela exige E2E, screenshots reais e manual `/ajuda`; revisão Codex PASS, Lovable UX review quando relevante.
