# ADR-0039: QoS-001 — diagnóstico de qualidade do serviço (adendo ao SD-001)

Status: **Accepted (2026-10-31)** — aprovado pelo responsável; o PR A e o PR B seguem com Codex e flags OFF | Data: 2026-10-31 | Owner: equipe | Origem: `docs/addenda/v2.2-qos/` (PR0: CURRENT_STATE, GAP_MAP, plano). Relaciona-se a ADR-0028 (diagnostic jobs passivos), ADR-SD-002 (leitura de parâmetros do CPE), ADR-0030 (bancada), ADR-0038 (Speed Diagnostics) e à emenda proposta do ADR-0030 desta data.

## Contexto
O adendo pede "Diagnóstico de Qualidade do Serviço" sobre o SD-001: leituras (WAN/PPPoE, Ethernet, óptica, Wi-Fi, CPU), testes leves de ping e DNS, traceroute opcional, e o COMPLETO reusando o teste de banda. O repositório já tem a leitura passiva (`cpe_state`), a óptica da OLT, as regras R-D001/R-D002, o motor TR-143 único e a aba "Teste de banda" no sidebar. Faltam ping/DNS/traceroute, Ethernet/CPU, a entidade de suite, as hipóteses e o cartão de UI (ver GAP_MAP). Três fatos do código limitam o desenho:
1. `IPPing`/`NSLookup` **escrevem** `DiagnosticsState` no CPE: são escrita, e toda escrita em CPE passa hoje pelo catálogo de bancada (ADR-0030); `HOMOLOGATED_WRITES` está vazio.
2. `busy_reason()` só conhece `speed_test_runs`: ping e banda poderiam disputar o mesmo `DiagnosticsState`.
3. Não há regra para identificar a **WAN de serviço** fora da bancada.

## Decisão (proposta)
1. **RÁPIDO passivo para qualquer ONT**, sem tocar o aparelho: lê o que o produto já retém (`cpe_state`, óptica da OLT) e normaliza em métricas com valor, unidade, origem (`TR069_READ|ACS_CACHE|OLT_ADAPTER|SD001`), escopo, `collectedAt`, frescor e estado (`valid|stale|not_supported|not_available|not_applicable|failed|inconclusive`). Nunca zero por ausência; óptica nunca com origem `TR069`.
2. **Testes ativos só na bancada** (emenda ao ADR-0030): `ping_test` e `dns_test` entram no catálogo fechado, com destinos **lógicos** (ids; endereços e nomes só na configuração local do Edge, como em `speed_endpoints`). Fora da bancada continuam bloqueados; ampliar é decisão futura com evidência por modelo/firmware.
3. **Reserva compartilhada por CPE** (entrega obrigatória do PR A): uma única reserva sob o mesmo lock consultivo para toda operação que escreve diagnóstico (banda, ping, DNS), tomada antes de criar o job e liberada em estado terminal, incluindo jobs pendentes; `busy_reason()` passa a consultá-la. Teste nos dois sentidos e sob concorrência. Os limites de PON e de provedor do SD-001 continuam valendo.
4. **Suite `quality_runs` (tabela filha, aditiva, migração 0036)** e endpoints por CPE no padrão de `app/api/speed.py`: `POST/GET /v1/cpes/{id}/quality/runs`. Guarda modo (`quick|full`), estado (`completed|partial|failed|timeout`), métricas normalizadas, hipóteses e **referências** (ids de jobs de ping/DNS e `run_group_id` do SD-001). RLS forçada, idempotência por `(tenant, usuário, Idempotency-Key)`. Não altera `diagnostic_jobs` (imutável e passivo, ADR-0028) nem `speed_test_runs`.
5. **COMPLETO = RÁPIDO + referência ao SD-001**, sem segundo motor TR-143 e sem chamar TR-143 por outro caminho. Enquanto o gate do SD-001 estiver fechado (`redirect_unverified`), o COMPLETO mostra `speed=not_available` e preserva a parte rápida.
6. **Leituras novas, lista fechada espelhada**: `eth_link_status` e `eth_link_speed_mbps` no `cpe_state` (Edge `params.go`, API, CHECK do banco e teste cruzado). Erros de Ethernet (delta), CPU/memória, Wi-Fi retries/associados e traceroute ficam para um lote 2, cada um com a sua homologação. Endereços IP, MAC, SSID: nunca.
7. **Hipóteses determinísticas e transparentes** em função pura (`LAN_LINK_100M`, `OPTICAL_ATTENTION` por perfil, `EXTERNAL_PATH_POTENTIAL`/`ACCESS_PATH_POTENTIAL` só com SD-001 válido, `DNS_POTENTIAL`, `PACKET_LOSS`; `WIFI_POTENTIAL` só com dado homologado). Sem score, sem "qualidade OK", sem SLA. Sem evidência: "dados insuficientes".
8. **Governança**: flags independentes `quality_diagnostics`, `quality_active_tests`, `quality_full` (todas OFF); permissões `diagnostics:quality_read`, `diagnostics:quality_run`, `diagnostics:quality_run_full` (o completo exige também `diagnostics:speed_run`); auditoria `quality.requested|blocked`. Desligar QoS não afeta SD-001, ONU 360 nem provisionamento.
9. **UX**: aba "Qualidade" no sidebar existente e cartão no ONU 360; 4 indicadores e "Ver detalhes por camada"; sem página nova. Copiloto fora deste lote (`smart_diagnostics_copilot` segue bloqueada).

## Fora de escopo
iperf/TR-471, TR-369/USP, auto-remediação, edição de Wi-Fi, reboot, varredura em lote, score, análise preditiva, comparação com plano contratado sem fonte integrada, traceroute neste lote.

## Consequências
- O RÁPIDO passivo pode ir a qualquer ONT com dados; o ativo só existe na bancada até nova decisão. Uma ONT fora da bancada mostra "teste ativo indisponível" com o motivo, nunca um resultado inventado.
- A reserva compartilhada é uma alteração de comportamento do SD-001 (banda passa a recusar quando há ping em curso); entra com teste de regressão do SD-001.
- Rollback: desligar a flag; tabelas e colunas aditivas ficam inertes.

## Alternativas descartadas
- **Estender `diagnostic_jobs`** com a suite: quebraria a imutabilidade e o replay (ADR-0028).
- **Outro motor/fila para ping/DNS**: duplicaria jobs, lock e auditoria.
- **Ping/DNS no gate global**: `HOMOLOGATED_WRITES` vazio de propósito.

## Aprovação
Aprovado por: o responsável do projeto, pelo chat da sessão, 2026-10-31 ("aprovado ADR-0039"); a emenda do ADR-0030 desta data foi aprovada junto.

## Implementação (2026-10-31) — fatiada em três PRs, por causa do Connection Request
O plano falava de 2 PRs de código; o primeiro teste real de banda mostrou que o ACS não completa o Connection Request da ONT de bancada (ver `docs/wiki/bench/H-speed_test_download-tentativa-1-2026-10-31.md`), o que bloqueia qualquer teste ativo. Para não misturar o que se prova com o que não se consegue provar, a entrega fica assim:
1. **PR A (este): RÁPIDO passivo, suíte e API.** `app/core/quality.py` (puro), migração 0037 `quality_runs`, `app/api/quality.py` (`GET capabilities`, `POST/GET runs`), flags `quality_diagnostics|quality_full|quality_active_tests` (OFF), permissões `diagnostics:quality_read|quality_run|quality_run_full`. A leitura usa só `cpe_state` (cache do ACS) e a ONU ligada na OLT; o COMPLETO REFERENCIA um grupo do SD-001 que o chamador já tem (`speed_group_id`, recente, do mesmo CPE) e **não inicia teste nenhum**. Nenhum código toca o Edge, o ACS ou o aparelho (teste de varredura do fonte).
2. **PR B: aba "Qualidade" no sidebar, ajuda com capturas reais, changelog.**
3. **PR C (depende do Connection Request ou do modo fila): `ping_test`/`dns_test` na bancada, reserva compartilhada por CPE, métricas de Ethernet.** As regras de hipótese que usam esses dados já existem em `quality.py`, dormentes e testadas com entradas sintéticas.
Decisões de implementação: TTL da óptica = 20 min (a OLT é coletada a cada 15 min e a rodada leva até ~3 min); a WAN do cache é sempre `WAN_UNCLASSIFIED` (o cache não diz se é a de serviço); ausência de Wi-Fi é `not_available`, nunca `not_applicable`; o limiar de "degradado" nas regras de caminho é 50 % da referência, declarado como constante.
