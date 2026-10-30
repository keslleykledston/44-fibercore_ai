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
- v2.2 PR 35 (FC22-002 mínimo) implementado; migração 0015 aplicada no LAB (2026-10-29). Próximo: FC22-003 (envelope source/quality), tenant flags (ADR-0023), 004.
- v2.2 PR 36 (FC22-003 + flags) e PR 37 (FC22-004: vínculo ONU↔CPE por evidência + Customer Context) em `main`; LAB em Alembic 0017 (2026-10-29), flags `onu_cpe_links`/`customer_context`/`subscriber_360` DESLIGADAS no LAB (padrão). Próximo: **PR 38 = FC22-005 Subscriber 360** (UM pedido em lote ao Lovable com UX_HANDOFF.md, sem segredos; mesma rota ONU 360; abas só onde houver suporte; flag `subscriber_360`; capturas 1440×900/390×844; how-to; Codex).
- Decisões pendentes do responsável: TTL do dado de ERP = 7 dias (suposição); ligar `onu_cpe_links`/`customer_context` no LAB (`feature-set`, owner CLI) quando houver CPE real coletado (Edge × NBI ainda não roda de verdade).
- v2.2 PR 38 (FC22-005 Visão 360 do assinante) em `main` e no LAB (2026-10-29); flags `subscriber_360` + `customer_context` (+ `onu_cpe_links` p/ o roteador) DESLIGADAS no LAB. Próximo S1/S2: FC22-006/007/009 (extração do motor de regras R-D001, troubleshooting guiado, NOC command center) e 008; busca por cliente/contrato no ⌘K; 010–013 só com dado real (ADR-0022). Pendências de infra: NBI do GenieACS aberto/sem auth (precisa de autorização do responsável), Edge rodando de verdade, cópia de backup fora do host + GPG.
- (2026-10-29) Responsável: TTL ERP 7d APROVADO; flags `onu_cpe_links`/`customer_context`/`subscriber_360` LIGADAS no LAB; NBI: correção autorizada mas exige root (runbook `GENIEACS_NBI_HARDENING.md`, aguardando admin com root); Edge RODANDO no host do GenieACS (cron, 6 CPEs no LAB). OLT por Edge: NÃO ligada (precisa de autorização explícita; throttle). Backlog segue: FC22-006 → 007 → 008 (validar) → 009.
- (2026-10-29) PR 39 (FC22-006) em `main` e no LAB (Alembic 0018; flag `diagnostic_engine` ligada). Próximo: FC22-007 (troubleshooting guiado) → 008 (validar vs AC-004/009) → 009 (NOC command center).
- (2026-10-29) PR 40 (FC22-007 Diagnóstico guiado) em `main` e no LAB. Próximo: FC22-008 (validar `edge_silent` vs AC-004/009) → FC22-009 (NOC command center: prioridade/impacto).
- (2026-10-29) PR 41 (FC22-008 validação AC-004/009) e PR 42 (FC22-009 NOC Command Center) em `main`; PR 42 no LAB. **Todos os P0 do v2.2 (FC22-001..009) estão feitos.** Restam P1/P2: 010 (topologia/CTO-POP), 011–013 (QoE: bloqueados por dados, ADR-0022), 014–016 (catálogo de operações/dry-run, lock/USP, release center), 018 (P2). Pendências abertas: fechar o NBI do GenieACS (precisa de root: `docs/operations/GENIEACS_NBI_HARDENING.md`); OLT por Edge (precisa de autorização explícita; throttle 1 req/s); cópia de backup fora do host + GPG; ack de incidente pela UI; busca por cliente no ⌘K; R-D002..004 (sem dados Wi-Fi/WAN/sessão ACS).

- (2026-10-29) Edge LIGADO à OLT real em somente leitura (PR 43/44: guard de ritmo persistente; 32 PONs, 775 ONUs coletadas em ~156 s; intervalo 15 min). Driver segue `identified` (nenhuma PON `complete`). PR 45: reconhecer incidente pela UI + cliente no ⌘K (no LAB).
- (2026-10-29) Feature Pack SD-001: gate B0 entregue (`docs/feature-packs/SD-001/`). Aguardando aceite do Tech Lead das decisões D-1…D-6 do relatório; próximo código = SD-PR-01 (contratos e mocks, sem endpoint real). NÃO mexer em `diagnostic_runs`/`R-D001`.

## Atualização 2026-10-29 (SD-001)
- ADR-0025 aceito. SD-PR-01 (contratos/mocks/flags off) em PR 47. Próximo: SD-PR-02, SD-PR-03; ADR-SD-002 (caminhos permitidos do NBI + redação no Edge) antes de qualquer leitura de WAN/PPPoE/Wi-Fi.
- Dono: fechar o NBI do GenieACS (`docs/operations/GENIEACS_NBI_HARDENING.md`) — tem root.

- Catálogo de consultas da OLT pronto e inerte (PR 49). Próximo: ADR do canal (params no envelope assinado, resultado só parseado, orçamento de consultas sob demanda respeitando o guard) e capturas supervisionadas para promover as consultas N.

## Atualização 2026-10-29 (leitura ativa)
- Leitura ativa de parâmetros (ADR-SD-002 item 4) implantada na LAB e ensaiada com falha limpa; falta um CPE que responda à conexão para ver dado real. Ligar o transporte `cpe_state` (migração) só depois disso.
- Operador: o NBI do GenieACS continua aberto; fechar conforme `docs/operations/GENIEACS_NBI_HARDENING.md`.
- (2026-10-29) NBI do GenieACS FECHADO pelo responsável (bind em loopback + firewall); verificado de fora e de dentro, Edge segue com heartbeat. Pendente do responsável: autenticação CWMP e um CPE real alcançável (`_id` com Inform recente + Connection Request alcançável) para o refresh real e o transporte `cpe_state`.
- (2026-10-29) ONT de bancada Huawei no ACS (Inform ok, com auth CWMP). Connection Request manual funciona; o refresh via NBI (`connection_request`) enfileira (202 em ~30 ms) mas a ONT não abre sessão — causa a investigar com root (log de erro do NBI) ou mudar o fluxo para esperar o Inform periódico (ADR + Codex). Sem dado real até lá.
- (2026-10-29) Refresh sem dado: causa = credencial de Connection Request da ONT difere de `cwmp.connectionRequestAuth` do ACS (401). Responsável iguala na ONT; depois repetir o ensaio supervisionado. Acesso: `sudo` funciona no host do ACS com a senha do próprio usuário (a `ROOT_PASSWORD` do .env não é aceita; removê-la do .env).
- (2026-10-29) Refresh ativo LEU dado real da ONT de bancada (link WAN + 2 rádios Wi-Fi). Próximo: investigar numeração de WANConnectionDevice neste firmware (sem ampliar a lista às cegas) e então `cpe_state` (migração 0019, RLS 2 tenants) para levar o dado ao cloud.
- (2026-10-30) `cpe_state` (PR 53) em main e na LAB com dado real da ONT de bancada (7 linhas). Próximo: regras R-D002…R-D004 versionadas lendo `cpe_state` (sem observação = desconhecido, nunca zero) e o Visão 360; SD-PR-03 `diagnostic_jobs`; ADR do canal de consultas da OLT; itens pequenos (E2E com flags off, p95). Ops: autenticação CWMP/rotação, backups fora do host + GPG.
- (2026-10-30) PRs 54 (R-D002) e 55 (diagnostic_jobs passivos, migração 0020) em main; `diagnostic_engine` já estava LIGADA na LAB (responsável) e a R-D002 foi executada lá com dado real; `smart_diagnostics_jobs` segue DESLIGADA (ligar é decisão do responsável). Próximo: ADR do canal de consultas da OLT; itens pequenos (E2E com flags off, p95/carga, R-D003 versionada); FC22-010 topologia. Bloqueados: testes ativos (ADR-SD-003), copiloto (ADR-0015/SD-006), remediação (homologação).
- (2026-10-30) ADR-0029 (canal `olt_query`) escrito e aprovado pelo Codex (5 rodadas); status Proposed até o aceite do responsável. Sem código. Depois do aceite: implementar o canal só para olt.version/olt.board, com ensaio supervisionado.

## Atualização 2026-10-30 (bancada, ADR-0030)
- PRs 56–59 em `main` e na LAB (Alembic 0022, API e web saudáveis; Edge `0.5.1-lab-6816ed1` no host do GenieACS): gate de bancada nuvem + Edge, primeira execução (`first_run`), firmware do CPE no snapshot (V5R019C10S350 já na nuvem).
- LAB pronta e FECHADA: `bench_writes` LIGADA; alvo de bancada cadastrado (owner_epoch 1); registro `reboot_cpe` = `supported`/`identified` (evidência `docs/wiki/bench/H1-identificacao-2026-10-30.md`); Edge com seção `bench` (1 dispositivo) e `reboot_cpe` em `allowed_operations`. **Nenhuma escrita é possível sem a autorização PRÉVIA do responsável** (nem foi enviada nenhuma).
- **Ação do responsável (única necessária para o H2):** (1) aceite do H1 (arquivo acima); (2) um segundo `isp_admin` para aprovar (distinto do solicitante); (3) no momento da manobra: `bench-authorize dd0a7d62-403a-446d-96b2-05e85aaae15f reboot_cpe f851bae3-0f58-4c8b-aa86-2849d14e8263 --from <agora> --to <agora+15min> --by <nome> --first-run` (owner CLI, ver `docs/wiki/bench/RUNBOOK-H2-REBOOT.md`). Depois: criar o job (preview → submit), aprovar com o outro admin, acompanhar; escrever a evidência (`TEMPLATE.md`) e promover a `observed` com `capability-set --evidence-file`.
- Reverter o Edge: `config.json.pre-bench` no host (cópia da configuração anterior). Desligar: `feature-set ... bench_writes off` ou remover a seção `bench`.
- Próximo código (sem equipamento): `olt_query` (ADR-0029, simuladores), H3/H4 só por emenda do ADR-0030 + autorização.

## Atualização 2026-10-30 (H2 feito)
- H2 `reboot_cpe` REAL executado na ONT de bancada com sucesso e aceito pelo responsável; registro `observed` (evidência `docs/wiki/bench/H2-reboot_cpe-2026-10-30.md`). Próximas autorizações de reboot são NORMAIS (sem `--first-run`); ritmo do Edge: 1 reboot por 30 min por dispositivo.
- Pedido do responsável: repetir o teste para validar (após 04:02 UTC, nova autorização normal). Depois: H3 (SSID `BANCADA-…`) e H4 (ONU na OLT) só por emenda do ADR-0030 + autorização.

## Backlog acrescentado em 2026-10-30 (a pedido do responsável; encaixar na ordem ideal, sem atropelar as fases)
- **Relatório "ONUs offline há mais de X horas"** por OLT e PON (ex.: agendar retirada, contatar o cliente), com exportação CSV. Hoje há `onus.down_since`/`last_online_at` do snapshot da OLT, mas nenhuma consulta/relatório por duração nem histórico de transições. Passos: (1) consulta `GET /v1/onus` com filtro `status=offline` + `down_for_min` e filtros por OLT/PON (leitura, sem migração); (2) exportação CSV e tela; (3) tabela de histórico `onu_state_events` (migração) para "tempo acumulado offline no mês"; (4) política: ONU crônica fora das regras de queda em massa continua separada. Ordem sugerida: depois do H4 (`onu_reset`/`onu_deactivate`) e antes de um 2º modelo de ONU, ou em paralelo se o H4 estiver esperando autorização.
- **2º modelo de ONU para homologar:** pode começar o H2/H3 (TR-069, por perfil) em paralelo à parte da OLT; o `bench.olt` do Edge hoje é UMA ONU (precisa virar lista para o H4 do 2º modelo) e o ADR-0030 precisa de emenda (lista fechada). Precisa da ONT nova na bancada, do fabricante/modelo e da posição na OLT.

## Estado do H4 (2026-10-30 ~05:50 UTC)
- `ont reset 14 10` PEDE CONFIRMAÇÃO no CLI da OLT: o Edge parou (fail-closed), a ONU NÃO foi reiniciada (ACS: `_lastBoot` inalterado). Job `6c5d99e1-…` FAILED, alvo travado, autorização `fe3a6406-…` consumida. Próximo: capturar o texto exato da pergunta (sonda supervisionada, responde "n"), tratar UMA confirmação conhecida por comando, Codex, nova autorização do responsável.

## Atualização 2026-10-30 (H4 feito)
- H2 (`reboot_cpe`), H3 (`set_wifi_ssid`) e H4 (`onu_reset`, `onu_deactivate`) REAIS na ONT de bancada, todos `observed` e aceitos. Próximas autorizações são NORMAIS (sem `--first-run`).
- Pendentes: (1) cooldown pós-falha da bancada configurável no Edge (hoje 15 min em memória; editar o arquivo não adianta sem reiniciar); (2) relatório de ONUs offline há X horas; (3) 2º modelo de ONU (`bench.olt` vira lista + emenda do ADR-0030); (4) `olt_query` (ADR-0029); (5) persistência do SSID após reboot (teste opcional).

## Atualização 2026-10-30 (backlog)
- Feito: cooldown pós-falha da bancada configurável (PR 67) e relatório `GET /v1/onus/offline` (PR 68; JSON/CSV; sem tela ainda). Próximos: tela do relatório (Next.js, com Lovable só para o visual), histórico de transições online/offline (`onu_state_events`, migração) para tempo acumulado, 2º modelo de ONU, `olt_query` (ADR-0029).


## Atualização 2026-10-30 (Last down time da OLT)
- Feito: PR 69 (API: `onus.olt_down_at`, migração 0023, ingest `last_down_at`, base `olt_reported` no relatório) e PR 70 (Edge: bloco opcional `last_down` na entrada CLI Huawei R015; leitura SNMP focada em segundo plano, 1×/h, após a coleta CLI, mesmo travamento do dispositivo; ~1 requisição por 5 ONUs offline). LAB: API em 0023; Edge `0.8.0-lab-7c61592` com `last_down` ligado (community em arquivo 0600 do host; config anterior em `config.json.pre-lastdown`). Primeira leitura real: acompanhar `olt collected ... /last-down` no `edge.log`, depois conferir `GET /v1/onus/offline` (base `olt_reported`).
- Operacional: não autorizar manobra da bancada nos ~3 min após uma coleta CLI em que a leitura SNMP rode (no máximo 1×/h); a OLT aparece ocupada nesse intervalo.
- Próximos: tela do relatório (Next.js), `onu_state_events`, 2º modelo de ONU, `olt_query` (ADR-0029).
- (2026-10-30, fim) `last_down` por SNMP: NÃO homologado na OLT real (4 timeouts do Edge; agente SNMP fica mudo sem padrão claro e é compartilhado com o monitoramento do ISP). Desligado no LAB. Decisão do responsável pendente: (a) combinar com o ISP uma janela/limite para o SNMP da OLT e tentar de novo; (b) obter o "Last down time" pela CLI (uma sessão, comando por ONU offline, ritmo baixo); (c) ficar só com `since_last_online`/transições observadas. Não sondar o agente SNMP sem essa decisão.
- (2026-10-30, noite) DECIDIDO pelo responsável: opção (b). `down_times` (CLI, `display ont register-info`, mesma sessão da coleta, ≤15 ONUs offline por coleta) ligado no LAB; SNMP `last_down` continua desligado e sem sondagem. Leituras reais OK (14 de 15 por coleta). Acompanhar o preenchimento das ~212 ONUs restantes e depois: tela do relatório (Next.js), `onu_state_events`.

## Backlog acrescentado em 2026-10-30 (a pedido do responsável): fase "Dispositivos" (gestão de dispositivos)
Hoje não existe área dedicada: há API (`/v1/cpes`, `/v1/cpes/{id}/state`, `/capabilities`, `/v1/edges`) e só o bloco de CPE dentro da ONU 360. PRD: UC-04 (gestão remota dual-stack), UC-06 (atualizações), módulos `edge-fleet` e `cpe-unified`, UX-02 (ONU/CPE 360 com abas). Ordem (cada entrega com testes, Codex e evidência; só leitura até a última):
1. **Tela de CPEs** (`/dispositivos`): lista com filtros (fabricante/modelo/protocolo/fonte/frescor) e detalhe do CPE (identidade, protocolos, estado WAN/Wi-Fi lido, ONU vinculada, capacidades). Só leitura. Item de menu "Dispositivos" (7ª área: exige exceção ao limite de 6 do design system ou fundir com Rede; decidir no PR).
2. **Frota de Edges** (`/dispositivos/edges`): versão, heartbeat, fila, fontes (GenieACS/OLT), último erro sem segredos. Só leitura.
3. **Matriz de modelos e capacidades**: modelo × firmware × operação × nível (identified/observed/certified) a partir do Capability Registry e das evidências da bancada (H2–H4). Só leitura.
4. **Ações UC-04 na tela do CPE**: reiniciar/alterar Wi-Fi pelo fluxo de jobs já homologado (preview, aprovação, pós-check), visível só para o que estiver `observed` para o alvo; fora da bancada continua bloqueado (`HOMOLOGATED_WRITES` vazio).
5. UC-06 (atualizações/firmware): só desenho (ADR) por ora; execução em lote não entra no MVP.

## Backlog acrescentado em 2026-10-30 (a pedido do responsável): desenho e construção do RBAC
Estado hoje: 8 papéis FIXOS no código (`ROLE_PERMISSIONS` em `apps/api/app/core/security.py`: isp_admin, engineer, noc_n2, noc_n1, support, auditor, platform_support, edge_agent), 1 papel por membro (`tenant_memberships.role`), permissão checada por rota com `require("…")`, MFA obrigatório por papel (`MFA_REQUIRED_ROLES`), RLS por provedor. Lacunas: não há papéis por provedor, escopo (OLT/PON/site), tela de gestão, fluxo de mudança de papel com trava/auditoria, catálogo único de permissões, nem teste que prove a matriz inteira. A tabela de papéis de `docs/security/SECURITY_AND_APPROVALS.md` (Wi-Fi/PSK, CSV, releases) não está refletida no código.
**Ordem (antes da entrega 4 da fase Dispositivos, que põe botões de ação na tela e precisa deste desenho):**
1. **Desenho (ADR, aprovação do responsável antes de construir):** catálogo de permissões (nome, verbo, recurso, risco R0–R3), papéis de sistema (modelo) e papéis customizados por provedor, escopo (provedor → site/OLT/PON), separação de funções (quem solicita ≠ quem aprova; já existe para jobs), delegação da `platform_support` (prazo, motivo, auditoria), contas de serviço/Edge (mínimo necessário), política de MFA por papel/risco, modelo de auditoria, migração dos 8 papéis atuais sem mudar o que cada um pode hoje.
2. **Catálogo único + teste de inventário:** fonte única das permissões; teste que varre as rotas e exige que todo `require()` esteja no catálogo e que cada papel tenha exatamente o conjunto esperado (matriz negativa); gerar a matriz em `docs/` a partir do código (sem divergência).
3. **Papéis e atribuição no banco** (migração, RLS): papéis customizados por provedor sobre o catálogo; API de atribuição com travas (não remover o último admin, ninguém escala o próprio papel, só concede o que tem, MFA recente para conceder papel de risco) e auditoria de toda mudança.
4. **Escopo por OLT/site** (filtro por linha nas leituras e nas ações; negação por padrão fora do escopo).
5. **Tela Administração → Papéis e permissões:** matriz papel × permissão, membros e papéis, "o que posso fazer" do usuário logado, histórico de mudanças; gestão de MFA continua em Membros.
6. **Testes e revisão:** matriz positiva/negativa, isolamento entre provedores, tentativas de escalada, concorrência (dois admins), Codex adversarial por entrega; nada de produção sem gate formal.

- (2026-10-30) RBAC: decisões do responsável — só papéis de sistema por ora (sem customizados); novo papel de sistema `access_manager` (Gestor de Acesso) além do `isp_admin` para conceder papéis; MFA recente 10 min; delegação da plataforma 8 h renovável. Em aberto: escopo por OLT/site (pediu explicação) e confirmar a dispensa de SoD na bancada. Construção em andamento: entrega 1 (catálogo único + teste de inventário de rotas + matriz gerada), sem mudar comportamento.
- (2026-10-30, tarde) RBAC entrega 2 FEITA e no LAB (migração 0024, PR 79): papel `access_manager`, `GET /v1/roles`, `PUT /v1/members/{id}/role` via função SQL única e role dedicada `fibercore_rbac` (segredo `FIBERCORE_RBAC_DB_PASSWORD` em `.env.prod`/`.env.dev`, nunca no repositório; sem a conexão dedicada a rota dá 503). Decisões: escopo por OLT/site DEPOIS; dispensa de SoD da bancada MANTIDA. Próximos do RBAC: entrega 3 (tela Administração → Papéis e permissões: matriz, membros e papéis, "o que posso fazer", histórico), entrega 5 (delegação da plataforma 8 h + MFA recente 10 min); entrega 4 (escopo) adiada. Depois: entrega 4 de Dispositivos (ações na tela do CPE, usando `devices:act:*`), `onu_state_events`, 2º modelo de ONU, `olt_query`.
- (2026-10-30, noite) RBAC entrega 3 FEITA e no LAB (PR 80): tela `/administracao/papeis` (o que posso fazer, membros e troca de papel, matriz, histórico), `permissions` em `/v1/auth/me`, `GET /v1/members/role-history`. Falta do RBAC: entrega 5 (delegação da `platform_support` 8 h com motivo + MFA recente 10 min nas permissões R3/`mfa_recent` do catálogo; também a via `api` da autorização de bancada, ADR-0031 §2(e)); entrega 4 (escopo) adiada por decisão. Depois: Dispositivos entrega 4 (ações na tela do CPE com `devices:act:*`), `onu_state_events`, 2º modelo de ONU, `olt_query`. Pendência de teste: o `scripts/e2e.sh` completo (stack de seed) não foi rodado nesta máquina; a UI foi validada numa stack efêmera própria.
- (2026-10-30, noite) RBAC entrega 5 FEITA (PR 81, migração 0025): MFA recente 10 min (ligada por padrão; no LAB a exceção `FIBERCORE_MFA_RECENT_ENFORCE=false` está no `.env.prod` até o isp_admin ativar o MFA — remover a linha depois) e delegação da plataforma 8 h. Falta do RBAC: via `api` da autorização de bancada (decidir quem detém `bench:authorize`); entrega 4 (escopo) adiada. Próximo: Dispositivos entrega 4 (ações na tela do CPE), `onu_state_events`, 2º modelo de ONU, `olt_query`.
- (2026-10-30, noite) Dispositivos entrega 4 FEITA (PR 82): card Ações no CPE (reiniciar, Wi-Fi de bancada) sobre o motor de jobs; nada novo de escrita. Próximo: `onu_state_events`, 2º modelo de ONU na bancada (precisa de autorização do responsável), `olt_query`, UC-06 só como ADR. Pendentes do responsável: ativar o MFA e remover a exceção `FIBERCORE_MFA_RECENT_ENFORCE=false`; decidir quem detém `bench:authorize`.
- (2026-10-30, noite) Autorização de bancada pela API FEITA (PR 83, migração 0026) por decisão do responsável: operador (noc_n2) para cima autoriza; OLT-side só engineer/isp_admin; autorizador ≠ solicitante e ≠ aprovador. `owner_cli` continua ligado. Pendente do responsável: ativar o MFA (a exigência de MFA recente já está ligada no LAB).
- (2026-10-30, noite) RBAC redesenhado por pedido do responsável (PR 84, migração 0027): tela única Equipe e acessos com convite por link (sem SMTP), mudar função, redefinir senha por link, remover, atividade, funções em linguagem simples, troca da própria senha. Pendente: "esqueci minha senha" autoatendido e envio real do convite exigem e-mail (SMTP) — decisão do responsável; ativar o MFA do LAB.
- (2026-10-30, noite) MFA passa a ser pedido SÓ NO LOGIN (decisão do responsável, ADR-0031 item 10): `MFA_RECENT_ENFORCE` desligada por padrão; a pendência "ativar o MFA para destravar o administrador" deixa de bloquear. Ativar o MFA continua recomendado (Conta › Segurança da conta).
- (2026-10-30, noite) `onu_state_events` FEITO e no LAB (PR 85, migração 0028; baseline 775 = 775 ONUs; Codex 4 rodadas, approve; backup `fibercore-20261030T203333Z.dump`): histórico por gatilho, `GET /v1/onus/{id}/history`, `GET /v1/onus/unstable`, colunas 30 d no relatório e cartão na ONU 360. Ordem causal por `seq` (tempos empatados não se reordenam; `at` nunca recua), ranking/filtros no SQL com janela limitada, baseline = instante da migração, retenção: função `onu_state_events_prune(keep_days>=370)` (só dono do banco; ainda sem agendamento no host — `SELECT onu_state_events_prune(400)`). Próximo: `olt_query` (ADR-0029, só simuladores). Bloqueados por insumo do responsável: 2º modelo de ONU (ONT nova) e e-mail de convite (SMTP).

- (2026-10-30, noite) `olt_query` fatia 1 (nuvem, PR 86, no LAB desde o backup `fibercore-20261030T204927Z.dump`; Codex 3 rodadas, approve; smoke: nada oferecido, POST dá 409 olt_query_disabled, 0 jobs): operação, intenção fechada, permissão, flag, cota, rollout e endpoints, tudo INERTE (`EDGE_SUPPORT=False`). Próximas fatias (Edge, só simuladores): (2) fila persistente + estados `QUEUED→CLAIMED→EXECUTED→REPORTED` + verificação do envelope (catálogo/`olt_ref`) + orçamento 5/sessão e 20/h no mesmo arquivo do guard; (3) arrendamento e `owner_epoch` (transferência em duas fases); (4) parsers tipados de `olt.version`/`olt.board` e resultado tipado de volta à nuvem; (5) ligar `EDGE_SUPPORT` com ensaio no LAB (a habilitação na OLT real exige autorização do responsável e a confirmação de instância única, ADR-0029).
- (2026-10-30, noite) `olt_query` fatia 2 (Edge, PR 87): `ParseIntent`/`CatalogVersion`, verificador de envelope e fila durável `oltquery` prontos e testados, ainda desligados do executor. Próximo (fatia 3): chave local `olt_query_enabled` + `QueryCheck` (olt_ref ∈ OLTs configuradas), laço que enfileira o envelope, executa na MESMA sessão CLI da coleta depois dos comandos dela (guard/flock/intervalo/cooldown de 15 min), simulador de sessão, parsers tipados de `olt.version` e `olt.board`, relatório do resultado tipado à nuvem (rota de resultado precisa aceitar o objeto tipado) e abortar o lote em falha. Depois: arrendamento/`owner_epoch` (fatia 4) e ligar `EDGE_SUPPORT` com ensaio no LAB (fatia 5).
- (2026-10-30, noite) `olt_query` fatia 3 (executor no Edge + resultado tipado, PR 88; Codex 9 rodadas, approve; API no LAB desde o backup `fibercore-20261030T211526Z.dump`, inerte; o binário do Edge NÃO foi reimplantado — a coleta real segue como estava, e `olt_query_enabled` é desligado por padrão): feita e testada só em simulador. Faltam: (4) arrendamento e `owner_epoch` (transferência de OLT em duas fases, ADR-0029 item 3); (5) ligar `olt_query.EDGE_SUPPORT` e a flag no LAB com ensaio supervisionado. O ensaio na OLT real exige AUTORIZAÇÃO do responsável (janela combinada, uma consulta por vez, `olt.version` primeiro) e a confirmação de instância única de Edge; a pressuposição "sessão termina em config após o snapshot" só se confirma lá.
- (2026-10-30, noite) `olt_query` fatia 4 (arrendamento e `owner_epoch`, PR 89): feita em simulador; migração 0029 ainda NÃO está no LAB até o merge. Resta só a fatia 5 (ligar `EDGE_SUPPORT` e a flag no LAB com ensaio supervisionado), que depende da AUTORIZAÇÃO do responsável.
