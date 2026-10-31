# Work Sessions

## 2026-10-27 — Build kit authored

Specification, planning docs, prompts, inventory seeds, OpenAPI draft, Compose and API demo created. All hardware integrations remain unverified; status must be updated by implementers with real tests.

## 2026-10-27 — Sprint 0 PR 1
Kit validado (SHA256 OK) e importado; ADR 0001–0010; API real + auth + RLS + migrations; Compose validado; 18 testes PASS; OpenAPI alinhado (X-Workspace-ID, ModuleHealth). Codex gate não executado.

## 2026-10-28 — Entrega completa (PRs 1–14 + adendo v2.1)
Sprint 0→3 (parcial) + frontend + ajuda por construção. PRs 1–14 submetidos ao Codex com `approve` na última rodada de cada um (relato do implementador, não verificável por artefatos: ver CODEX_REVIEW_LOG.md). Ver FINAL_REPORT.md. Aprendizados: E2E real pega bugs que unit tests não pegam (lock sem cryptography; servidor next órfão); `pkill -f` mata o próprio shell; portas do host são disputadas.

## 2026-10-28 — GenieACS, publicação TLS, revisão visual
- GenieACS 4WNET levantado (só GET): sem ONU real; 41 fantasmas `DISCOVERYSERVICE`; riscos altos (cwmp.Auth admin/admin pública; preset `Disparar_Homologacao` sem precondição escreve Wi-Fi). Ver `docs/integrations/GENIEACS_4WNET_SURVEY.md`. Nada alterado no GenieACS.
- Publicado `https://fibercore.devops.k3gsolutions.com.br` (estado LAB) atrás do nginx do host (ADR-0016). Cert LE até 2027-01-26, dry-run de renovação OK. Stack `make up-prod` (projeto compose `fibercore-prod`, Caddy em 127.0.0.1:18480, API 127.0.0.1:18420). Credencial do admin guardada fora do repo, com permissões restritas (local informado ao responsável).
- E2E dev agora exige `FIBERCORE_API_PORT=18421 VENV_PY=<venv>/bin/python` (18420 é a produção).
- Revisão visual do Lovable aplicada (web/17); Codex approve nas duas branches (raw 16 e 17). 28 E2E passed.
- Pendente: MFA, refresh token, CSP com nonce, ensaio de restore, ONU 360/login em passos, capturas reais de OLT, corrigir GenieACS (decisão do dono).

## 2026-10-28 — W9 slice 1 (branch security/19-w9-auth-hardening)
- API: refresh token rotativo com detecção de reuso (migration 0011), MFA TOTP (segredo cifrado, replay, recuperação), `kid` + chave anterior para rotação. ADR-0017.
- BFF/web: cookies `fc_refresh`/`fc_mfa`, passo `/login/mfa`, `middleware` de renovação, logout revoga no servidor.
- Testes: pytest 128 passed (Postgres descartável); E2E 17 passed (incl. refresh, logout, MFA). Lint ruff ok.
- Aberto: tela de cadastro MFA, MFA obrigatório p/ admin, eventos de segurança globais, CSP com nonce.
- Deploy LAB: 0011 aplicada no prod (backup pré-migração fora do repo), MFA_ENCRYPTION_KEY gerada no .env.prod; verificado no site público: login, cookies HttpOnly/Secure, renovação por refresh rotativo (fc_token apagado -> /rede 200, refresh rotacionado), zero issues de console/CSP.
- Edge: saída paginada (--More--) agora falha fechado (ErrPaginated) em vez de gerar inventário parcial marcado complete=true; relógio da fila de nonces injetável (teste do agent quebrava após 10:15Z do dia por relógio real vs. fixture).

## 2026-10-28 — OLT Huawei MA5608T R015, SNMP, correlação, tela MFA
- Edge: shell interativo (pty) + paginador, perfil R015 (CLI), driver SNMP v2c (`transport: snmp`, trava/resfriamento por agente, 1 req/s). Nível do driver segue `identified` (complete=false até promoção).
- API: ADR-0018 (incidente por quedas recentes, migration 0012) em produção LAB.
- MFA (PR 27, main `ddb8f70`): tela `/conta/seguranca`, `MFA_REQUIRED_ROLES` (OFF no LAB), ativação serializada, enroll condicional. `tenant_conn` com `scope="function"` (commit antes da resposta). Codex 4 rodadas, approve.
- LAB redeployado (backup pré-deploy fora do repo); prodcheck: nenhum issue; `/conta/seguranca` redireciona para /login sem sessão.
- Testes: pytest 162 passed; E2E 18 passed (funcional); ruff ok; tsc ok; validate_kit PASS.
- Pendências: ver `NEXT_ACTIONS.md`.

## 2026-10-29 — PR 37 (FC22-004) mesclado e implantado no LAB
- Migration 0017 `onu_cpe_links`; `POST /v1/onu-cpe-links/suggest|{id}/confirm|{id}/reject`, `GET /v1/onu-cpe-links`, `GET /v1/customers/{id}/context`; card "Roteador (CPE)" na ONU 360. Codex 5 rodadas → approve (raw em `docs/wiki/reviews/raw/37-*`).
- Testes: pytest 226 passed; E2E 42 passed; ruff/tsc/validate_* PASS. Deploy: backup verificado (20261029T045308Z), `make up-prod`, Alembic 0017, RLS forçada em `onu_cpe_links`, prodcheck sem issues. Não verificado ao vivo: comportamento com flags ligadas no LAB (desligadas por padrão).
## 2026-10-29 — PR 38 (FC22-005) mesclado e implantado no LAB
- `/assinantes/[id]` (Visão 360), lista de clientes com busca/paginação (`GET /v1/customers` + `offset`/`q`), flags `subscriber_360`+`customer_context`. Lovable: 1 lote (projeto 13aaf09e…, commit 1ad87e8; chamada MCP deu timeout ocioso mas o agente concluiu), só referência visual (ver `docs/ux/lovable/README.md`).
- Codex 3 rodadas → approve. pytest 227 passed; E2E 45 passed; validate_* PASS. Deploy: backup 20261029T052517Z verificado, `make up-prod`, Alembic 0017, prodcheck sem issues. Flags desligadas no LAB: fluxo ligado só no E2E/pytest.
## 2026-10-29 — PR 39 (FC22-006) + Edge no GenieACS
- R-D001 v1 extraída (pura, versionada), `diagnostic_runs` append-only, `/v1/diagnostics/*`; Codex approve em 1 rodada; pytest 237. Edge instalado no host do GenieACS (cron, sem root), 6 CPEs no LAB; NBI não fechado (sem root; runbook). Flags do LAB ligadas por autorização do responsável.
## 2026-10-29 — PR 40 (FC22-007)
- `/assinantes/diagnostico/[id]`, BFF de execução, `onu_id` no escopo, `pon_id` no contexto; Codex 5 rodadas → approve; pytest 238, E2E 48; Lovable 2º lote (4,7 créditos). Deploy no LAB feito.
## 2026-10-29 — PRs 41 e 42
- FC22-008: `AC_VALIDATION_FC22-008.md` (+2 testes, mutante reprovado; Codex achou citação errada de teste). FC22-009: `/v1/incidents` com `impact`/`summary`/`order=priority` (prioridade ANTES do limite; todos os Edges silenciosos classificam), `/v1/incidents/{id}`, `/noc` com 4 KPIs e painel lateral. Lovable 3º lote (5,2 créditos). pytest 251, E2E 49. Deploy no LAB feito.

## 2026-10-30 — bancada (ADR-0030) até o H2 pronto
- PR 57 (Edge: claim durável, lease assinada, identidade relida do ACS, única tarefa `reboot`, prazo `notAfter`), PR 58 (primeira execução, migração 0022, advisory lock), PR 59 (firmware). Codex: 2, 5 e 5 rodadas, approve. `make test-api` 373 passed; `go test -race ./...` PASS.
- Deploy LAB: backup `fibercore-20261030T030646Z.dump`; Alembic 0022; Edge novo; bancada ligada (alvo, registro identified, flag, seção bench no Edge). Nada enviado a equipamento.


## 2026-10-30/31 — captura supervisionada (ADR-0032 item 1, PR 95)
- Edge: modo captura (`olts[].capture`): saída crua só em `captures/` (0700/0600, 24 h, 10 arquivos), orçamento persistido (2/sessão, 4/h, agregado 8), execução única (`done.json`; reexecutar = apagar o marcador), lote inteiro sob um mutex. Codex 5 rodadas → approve. `go vet` + `go test ./...` PASS; teste de concorrência com `-race`. Merge `76a52c0`, push feito.
- Próximo: reimplantar o Edge (binário `0.1.0-lab-76a52c0`) com o lote 1 numa janela de coleta; recolher os arquivos crus por SFTP, sanitizar, escrever parsers, `Validated`, apagar os crus e registrar a remoção verificada.

## 2026-10-31 — PRs 95, 96, 97 no LAB
- PR 95 (captura) + lote 1 na OLT real: time/sync/temperature ok; alarm.active paginou (Edge recusa saída paginada); autofind espera o orçamento (4/h). PR 96 (ERP HubSoft primeiro, HS-01/HS-02, só mocks, migração 0030). PR 97 (lote 1 validado: fixtures reais, parsers, nuvem, tela; Codex 3 rodadas).
- LAB: Alembic 0030; Edge `0.1.0-lab-b731997` (implantado antes da nuvem) com `capture`; API+web com catálogo `7e386eb3…`, ROLLOUT = version, board, time, sync, temperature. Backups `fibercore-20261031T011751Z` e `…T014058Z`.
- Pendências: ZTE (reinício manual do responsável → conferir ACS); autofind (próxima janela após 01:49 UTC) e paginação de alarm.active/history/event.history; HubSoft HS-03+ (precisa de segredo/host/instância do dono); ADR-0032 itens 3–5.

## 2026-10-31 (cont.) — PR 98 no LAB; lote 1 fechado; lote 2 agendado
- PR 98 (cache primeiro, ADR-0032 item 4; Codex 4 rodadas): migração 0031 no LAB, API+web implantados. Cache alimentado só por jobs; rota de ingestão do Edge + poda de `olt_metric_samples` ficam para o item 5 (rotinas).
- Lote 1: `olt.autofind` -> "Failure: The automatically found ONTs do not exist" (só o caso vazio visto; fixture guardada, consulta NÃO validada: sem o formato com ONTs não há parser honesto). `olt.alarm.active` paginou (Edge recusa).
- Lote 2 agendado (config do Edge): slot.cpu/mem/board nos slots 0-2 e pon.ont.summary da PON da bancada (0/14); 4 capturas/h => ~2,5 h. Depois: fixtures, parsers, promoção.

## 2026-10-31 (cont.) — PRs 99, 100, 101 no LAB
- PR 99 ONT Config (leitura, FC24-00/01, ADR-0034, migração 0032, flag `ont_config`); PR 100 sidebar de configuração do aparelho (FC24-02); PR 101 ONU Quick Inspector (UX 2.2, ADR-0035, flag `onu_quick_inspector`). Todas as flags DESLIGADAS no LAB. Sem dado real de ONT lido; só perfis sintéticos rotulados.
- Pendências: ligar flags por tenant + capturas reais da ajuda (`ont/consultar-configuracao`, `rede/resumo-da-onu`); FC24-03 (preview/jobs), FC24-04 (Edge lê/escreve, só lab autorizado); lote 2 da captura da OLT em andamento; ZTE aguardando reinício do responsável; HubSoft HS-03+ aguardando credenciais/instância.

## 2026-10-31 (cont.) — PR 102 no LAB
- PR 102 ONT Config FC24-03 (ADR-0036, migração 0033 `cpe_config_changes`, Codex 5 rodadas, approve na 5ª): pré-visualização com diff/risco/aprovações/bloqueios em ordem fixa; submissão SEMPRE 409 (`executed:false`), idempotente, sem job. Permissões `ont_config:request`/`ont_config:request_high` (NOC N1 não pede). MFA recente segue a política única da plataforma (contestado no Codex r1). Suíte API completa PASS, ruff e secrets-scan rc=0. LAB: Alembic 0033, backup `fibercore-20261031T044411Z.dump` antes do deploy; flag `ont_config` segue desligada.
- Próximo: lote 2 da captura da OLT (conferir `cap_fetch.py`), FC24-04 só com autorização de laboratório; UI de pedido de mudança só junto com o executor.
- Flags `ont_config`, `onu_quick_inspector`, `erp_hubsoft` ligadas no LAB (CLI de dono). Usuário de coleta da homologação criado por pedido do responsável: `captura-homologacao@k3gsolutions.com.br`, papel `noc_n1` (somente leitura, sem `customers:read`, sem MFA cadastrado), senha só em arquivo 0600 do scratchpad (nunca no repo/chat). Login por `/v1/auth/token` conferido (`mfa_required: false`). Uso: só capturas da ajuda com a ONU de bancada/ZTE (a descrição de ONU da OLT pode ter nome de cliente). Encerrar ao fim da homologação: remover a participação pela tela Equipe (ou desativar) e apagar o arquivo.

## 2026-10-31 (cont.) — PRs 103–107
- PR 103 Gestão de ONUs no padrão do protótipo Lovable (ADR-0037; Codex 6 rodadas): matriz de PONs, árvore OLT/PON, lista com filtros, painel de detalhes ao lado com abas Resumo/Aparelho/Histórico, painéis frontais conceituais (LED só do que o estado implica), ONU 360° com trilha e painel frontal; tudo atrás da flag `onu_quick_inspector` (agora LIGADA no LAB junto com `ont_config` e `erp_hubsoft`). PR 104/105 matriz: âmbar para fora, vermelho só LOS, causas mistas, compacta. PR 106: janela de dado recente da OLT 15 -> 35 min (OLT consultada a cada 15 min; CPE/ACS seguem 15 min). Ajuda: capturas reais do LAB (ONU de bancada) refeitas no layout novo.
- Usuário de coleta da homologação: `captura-homologacao@k3gsolutions.com.br` (noc_n1, sem MFA); senha só em arquivo 0600 do scratchpad. Encerrar ao fim da homologação.
- PR 107 lote 2a da OLT: slot.cpu e slot.mem validados (Validated, fora do ROLLOUT até haver seletor de slot). Brutos apagados no Edge (a pasta de capturas estava cheia e bloqueava slot.board/pon.ont.summary). Edge novo (versão `0.1.0-lab-75ed006`) implantado ANTES da nuvem (hash do catálogo 959fdad3…); depois `make up-prod`.
- Pendências: lote 2b (slot.board ×3, pon.ont.summary da PON 0/14) assim que o Edge capturar; seletor de slot na tela para oferecer cpu/mem; NOC `EVAL_FRESH_FOR` (15 min) igual ao intervalo da OLT; FC24-04 só com autorização de laboratório; ZTE (reinício manual do responsável).

## 2026-10-31 (cont.) — Speed Diagnostics PR 109 (nuvem) mergeado
- PR 108 (docs) e PR 109 (nuvem: ADR-0038, migração 0034, `app/core/speed.py`, `app/api/speed.py`, catálogo de bancada, flag `speed_diagnostics` OFF, `bench.SPEED_EDGE_SUPPORT=False`; Codex 8 rodadas, approve; 727 testes PASS) em `main` (d3b3fd0). Nada executado em ONT/OLT/ACS.
- Próximo: PR 2 (Edge Go `internal/speed`, NBI de escrita fechado, descoberta, testes com NBI falso; Edge implantado ANTES da nuvem), depois PR 3 (UX, ajuda, guia de homologação).
- Só o responsável: autorizar homologação na ONT de bancada + aprovar emenda ao ADR-0030; nó de teste e ACL; WAN de serviço da bancada; janela de baixa carga.

## 2026-10-31 (cont.) — Speed Diagnostics: PRs 110 e 111 mergeados
- PR 110 (Edge Go: `internal/speed`, `internal/nbi/speed.go`, ramo no `bench.Runner`, envelope, seção `speed`, saúde dos nós; nuvem: `SPEED_EDGE_SUPPORT=True`, migração 0035 com destino→Edge dono, `POST /v1/edge/speed-health`, contrato do envelope) e PR 111 (aba/cartão `SpeedTestSection`, BFF, ajuda com capturas reais e de cenário rotuladas, guia de homologação, recuo provado) em `main` (d6b6d08, cca8ed6). Testes: API 732 PASS, Go todos os pacotes PASS, e2e do speed 12 passed + 1 do recuo.
- Aprendizados: uma correção de leitura periódica fora de ordem virou 6 rodadas de Codex só de segurança de tráfego na tela; guardas de UI (contador de requisição, marcador de pedido em curso por aparelho em sessionStorage, 5xx = ambíguo) têm teste e2e. `python3 -` sem entrada trava o shell: nunca deixar no comando.
- Pilha efêmera de UI parada. Nenhum Edge/LAB reimplantado.
