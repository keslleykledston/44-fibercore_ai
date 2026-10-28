# Decision log

- D-001: GenieACS existente continua local; integração NBI via Edge outbound, sem nova instalação por padrão.
- D-002: TR-369 via controller independente/adaptador, sem confundir GenieACS com suporte USP.
- D-003: Compose piloto; K3s/Kubernetes quando houver HA/rolling update com contratos claros.
- D-004: read-only, auditabilidade e homologação por firmware antes de comandos de escrita.
- D-005: Claude implementa, Codex faz gate, Lovable provê UX, Git mantém documentação e memória.
- D-006 (2026-10-28): domínio público oficial + `/api/v1` via proxy que remove `/api` (ADR-0012). D-007: design system iOS-like e ajuda por construção (ADR-0013). D-008: sessão web por BFF com cookie HttpOnly (ADR-0014).
