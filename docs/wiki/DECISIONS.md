# Decision log

- D-001: GenieACS existente continua local; integração NBI via Edge outbound, sem nova instalação por padrão.
- D-002: TR-369 via controller independente/adaptador, sem confundir GenieACS com suporte USP.
- D-003: Compose piloto; K3s/Kubernetes quando houver HA/rolling update com contratos claros.
- D-004: read-only, auditabilidade e homologação por firmware antes de comandos de escrita.
- D-005: Claude implementa, Codex faz gate, Lovable provê UX, Git mantém documentação e memória.
- D-006 (2026-10-28): domínio público oficial + `/api/v1` via proxy que remove `/api` (ADR-0012). D-007: design system iOS-like e ajuda por construção (ADR-0013). D-008: sessão web por BFF com cookie HttpOnly (ADR-0014).
- D-009 (2026-10-29): adendo v2.2 adotado como PATCH incremental em `docs/addenda/v2.2/` (pacote intacto, checksums verificados); análise de GAP e matriz de conflitos em `GAP_ANALYSIS.md`; ADR-0019…0023 (Proposed). Reusar o motor de jobs (sem `/workflow-previews`), sem novos deployables, capability por perfil, scores só com dado real (`insufficient_data`).
- D-0047 (2026-11-13): ADR-0047 — ciclo de vida da organização e console do operador. Sem revenda, sem cobrança (por enquanto). Fatia A (suspender/reativar/renomear com imposição em `get_principal` + console com saúde e flags pela tela; flags de escrita em rede só pela CLI) aceita; fatia B (limites técnicos por organização, migração 0055) aceita e construída; fatia C (e-mail transacional, ADR-0048, migração 0056) aceita e construída; fatias D a F (escopo por site/OLT, encerrar organização, API/webhooks/SSO) propostas.
- D-0048 (2026-11-14): ADR-0048 — e-mail transacional (fatia C do ADR-0047). SMTP só do ambiente da plataforma, TLS sempre; convite e troca de senha por e-mail são ato explícito do administrador (link só de `PUBLIC_BASE_URL`, corpo da fila apagado ao enviar, ilegível pela aplicação, auditoria sem o link); avisos de segundo fator redefinido e de suspensão/reativação sem segredo; sem alerta, sem texto livre.
