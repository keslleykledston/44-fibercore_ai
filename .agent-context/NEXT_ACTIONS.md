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
- Feito: perfil `huawei_ma56_r015` (modo de CLI, pager por Espaço, prova de completude pelo rodapé da OLT), MA5608T R015 mantido `identified` (1 PON não sustenta observed; checklist de promoção no DRIVER_SDK_INTERFACE), capturas reais sanitizadas.
- Pendente: `display ont register-info` (causas de queda LOS/dying-gasp) e mais PONs/OLTs para ampliar a homologação; SNMP (`snmpwalk` de leitura + credencial no `.env`).
- Pendente do dono: restringir SSH do host do GenieACS; credencial SNMP de leitura.

## Atualização 2026-10-28 (cobertura ampla + SNMP)
- (resolvido, ADR-0018) a regra de `pon_mass_outage` passou a usar quedas recentes; a promoção da R015 a `observed` ainda depende do checklist (PON vazia, causas de queda via register-info/SNMP).
- Próximos: ler `register-info` só das ONTs que mudaram de estado (causa da queda), driver SNMP (OIDs em DRIVER_SDK_INTERFACE.md, SNMPv3), restringir SSH do host do GenieACS.

## Atualização 2026-10-28 (correlação + LAB + causas)
- ADR-0018 mergeada e publicada no LAB (migration 0012; backup pg_dump antes; login/telas/renovação verificados). pytest 151, Codex approve na rodada 5.
- Causas de queda mapeadas (SNMP 46.1.24: 13=dying-gasp, 2=LOSi/LOBi, 1=link-down). Próximo: driver SNMP no Edge (SNMPCOMMUNITY já no .env; preferir v3), com UDP pela allowlist e prova de fim de tabela.
- Pendente do dono: restringir SSH do host do GenieACS; migrar SNMP para v3.

## Atualização 2026-10-28 (driver SNMP)
- Feito: `transport:"snmp"` (v2c, GET/GETBULK, varredura com prova de fim de tabela, duas varreduras cruzadas). Validado ao vivo em 1 PON (12 ONTs = CLI). O agente SNMP da OLT limita a taxa (~17 pedidos/20 s e fica mudo >1 min): ritmo padrão 1 req/s e orçamento por ciclo.
- Pendente do dono: avisar o NOC que testes SNMP de hoje podem ter silenciado o agente por alguns minutos; confirmar se há limite de taxa configurado na OLT (CPCAR/anti-ataque) e migrar para SNMPv3.

## Atualização 2026-10-28 (tela MFA)
- Feito: `/conta/seguranca` (ativar/desativar MFA, QR, códigos de recuperação uma vez), política `MFA_REQUIRED_ROLES` (403 mfa_enrolment_required, sem auto-downgrade, boot falha com papel inexistente), how-to publicado com capturas reais, E2E.
- Pendente: redefinição de MFA por administrador (auditada); regeneração de códigos; ligar `FIBERCORE_MFA_REQUIRED_ROLES=isp_admin` no LAB depois que o admin cadastrar; eventos de segurança globais.
- Edge × NBI (2026-10-29): coletor validado contra payload real (43 dispositivos; fixture sintética em `agents/edge/internal/collector/testdata/`), filtro de `DISCOVERYSERVICE`. NÃO foi possível abrir túnel TCP pelo SSH do host do GenieACS (timeout do canal); a leitura real foi um `curl` remoto equivalente. Pendente: Edge rodando de fato na rede do GenieACS, NBI fechado/autenticado (ver KNOWN_ISSUES).
- MFA (2026-10-29): redefinição por administrador FEITA (ver ADR-0017). Pendente: aprovação por segundo administrador, e-mail ao alvo (sem canal de e-mail), regeneração de códigos, eventos de segurança globais.
- R015 → `observed` (2026-10-29): NÃO é possível comprovar o item (a) do checklist com captura real: as 32 PONs da OLT homologada têm 6 a 60 ONTs (nenhuma vazia). Mantido `identified`. Causas de queda: o caminho SNMP já mapeia 13→dying_gasp, 2→los (validado 10/10); o CLI não traz causa na tabela (só em `register-info` por ONT, caro) e o `suspected_cause` do Cloud já usa dying_gasp/los quando o transporte os entrega. Falta: Edge SNMP rodando na produção (throttle da OLT: 1 req/s, 5 min de resfriamento).
- Restore (2026-10-29): ensaio PASS (LAB). Pendente: backup agendado + cópia fora do host; chave do MFA guardada à parte.
- MFA: regeneração de códigos FEITA (2026-10-29). Backup agendado FEITO (cron 03:15; falta cópia fora do host + cifra).

## Adendo v2.2 (2026-10-29)
- Ler `docs/addenda/v2.2/GAP_ANALYSIS.md` antes de qualquer FC22. PR 34 = planejamento. Próximo: PR 35 = FC22-002 fatia mínima (tabela `device_capabilities`, `GET /v1/devices/{id}/capabilities`, bloco "Capacidades" na ONU 360, how-to + capturas, Codex). Depois S1: 003, 004 (vínculo ONU↔CPE, ADR-0021), 005 (Lovable em lote, flags por tenant ADR-0023).
- Não declarar feito sem código + teste + captura real + how-to + Codex. Scores só com dado real (ADR-0022).
- v2.2 PR 35 (FC22-002 mínimo) implementado; migração 0015 ainda NÃO aplicada no LAB até o merge. Próximo: FC22-003 (envelope source/quality), tenant flags (ADR-0023), 004.
