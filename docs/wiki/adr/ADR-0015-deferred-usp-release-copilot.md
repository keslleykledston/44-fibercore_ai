# ADR-0015: USP/TR-369, Release Center e Copiloto ficam FORA desta entrega

Status: Proposed | Data: 2026-10-28 | Owner: Claude Code

## Contexto
Backlog Sprint 3/4 inclui adapter USP + simulador, Release Center e copiloto LLM multi-provider. Nenhum tem pré-requisito de campo satisfeito: controlador USP não escolhido (OB-USPC é só candidato de laboratório), sem catálogo de releases assinadas, e o copiloto exige dados confiáveis, política de PII e provedor definido.

## Decisão
Não implementar nesta fase. Os módulos `usp-tr369`, `copilot` e Release Center permanecem `feature_flag: false` e **não** aparecem como saudáveis (`unknown/disabled` no registry). O contrato neutro de USP (`docs/architecture/TR069_TR369_INTEROP.md`) e `docs/ai/COPILOT_SPEC.md` seguem como especificação. O copiloto, quando existir, só poderá chamar ferramentas read-only e nunca executa comandos de rede (regra 7 do prompt mestre).

## Consequências
Pré-requisitos para retomar: (1) escolha e laboratório do controlador USP; (2) política de assinatura/rollout de releases do Edge; (3) decisão de provedor LLM + política LGPD. Cada item terá ADR própria e gate Codex.
