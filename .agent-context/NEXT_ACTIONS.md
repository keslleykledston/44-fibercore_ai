# Next Actions

1. Campo: capturas reais OLT (firmware exato) + NBI GenieACS lab → fixtures reais → promover drivers.
2. W9: MFA, refresh de token, CSP/HSTS, rate-limit na borda, DNS/TLS reais; executar CI no GitHub (criar PRs via UI/`gh`).
3. Observabilidade (Prometheus/Grafana) + ensaio de restore/falha; piloto INTERNAL_PILOT só após gate.
4. USP/Release Center/Copiloto (ADR-0015) quando houver pré-requisitos.
5. Revisão visual Lovable (docs/ux/lovable/README.md) e ONU 360 / ⌘K.

## Atualização 2026-10-28
1. Dono do GenieACS: trocar `cwmp.Auth`, desativar preset `Disparar_Homologacao`, rotacionar PSK; expor NBI por rede privada (VPN) para o Edge.
2. Capturas reais de OLT/ONU para promover drivers a `observed`.
3. W9: MFA, refresh token, CSP com nonce, kid de chaves, cofre, monitoramento TLS/5xx, ensaio de restore (gate de INTERNAL_PILOT).
4. W8: ONU 360, login em passos, EntityDetailDrawer.

## Atualização W9 slice 1 (2026-10-28)
1. Tela "Segurança da conta" (cadastro/desativação de MFA) + política MFA obrigatório para `isp_admin`.
2. Registro global de eventos de segurança (login, MFA, refresh, reuso).
3. CSP com nonce; monitoramento TLS/5xx; ensaio de restore; paginação `---- More ----` no driver.
