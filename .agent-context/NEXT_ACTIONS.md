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

## Atualização 2026-10-28 (edge)
- Feito: paginação falha fechado; `complete` só para drivers `observed`. Para promover um driver, a captura real precisa mostrar o sinal de término da listagem (ver DRIVER_SDK_INTERFACE).
- Próximo sem depender de campo: tela "Segurança da conta" (MFA) + MFA obrigatório p/ isp_admin; eventos de segurança globais; ONU 360.

## Atualização 2026-10-28 (primeira OLT real)
- Acesso à OLT Huawei MA5608T (MA5600V800R015C00) via host do GenieACS validado, somente `display version`. Credenciais só no `.env`.
- Branch `edge/21-interactive-shell-legacy-ssh`: shell interativo + SSH legado por OLT + captura real sanitizada.
- Pendente do dono: autorizar `enable` (elevação de privilégio, só leitura) e indicar uma PON para `display ont info summary` / `optical-info`.
- Pendente do dono: restringir SSH do host do GenieACS (exposto à internet); `pam_systemd` atrasa cada login em 25 s.

## Atualização 2026-10-28 (perfil R015 / MA5608T)
- Feito: perfil `huawei_ma56_r015` (modo de CLI, pager por Espaço, prova de completude pelo rodapé da OLT), driver `observed` p/ MA5608T R015, capturas reais sanitizadas.
- Pendente: `display ont register-info` (causas de queda LOS/dying-gasp) e mais PONs/OLTs para ampliar a homologação; SNMP (`snmpwalk` de leitura + credencial no `.env`).
- Pendente do dono: restringir SSH do host do GenieACS; credencial SNMP de leitura.
