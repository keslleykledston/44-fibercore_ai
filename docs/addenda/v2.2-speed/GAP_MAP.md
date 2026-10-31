# Speed Diagnostics (TR-143) — mapa de lacunas

Legenda: **existe** (usar como está) · **estender** (acrescentar sem mudar o que há) · **novo** · **fora de escopo**.

| # | Requisito do pacote | Situação | Como |
|---|---|---|---|
| 1 | Ação "Testar banda" no sidebar/painel da ONU | **estender** | Nova aba/seção no `OnuQuickInspector` (e bloco na ONU 360°), atrás da flag; sem página nova |
| 2 | Reutilizar GenieACS/Edge/Registry | **existe** | Nada é recriado; só novo job `speed_test` no Edge e operação no motor de jobs |
| 3 | NBI nunca exposto | **existe** | Só o Edge fala com o NBI; o teste não muda isso (cliente NBI continua privado) |
| 4 | Descoberta de compatibilidade por fabricante/modelo/firmware | **estender** | Duas coisas separadas: **observação** pelo Edge (presença do objeto, `_writable`, root; só informa a UI) e **homologação** no registro de capacidades (operações `speed_test_download`/`speed_test_upload`, protocolo `tr069`, evidência por modelo+firmware, escrita pelo dono). Classificação `SUPPORTED/PARTIAL/UNSUPPORTED/UNKNOWN` em função pura na nuvem. O registro **não abre escrita sozinho** (ADR-0019/0030) |
| 5 | Validar WAN de serviço (não usar gerência) | **novo** | Referência da WAN de serviço escrita pelo dono na homologação (evidência explícita por modelo+firmware; Edge-local). `cpe_config_fields` (`wan.type` ≠ bridge, VLAN) é só sinal auxiliar: se não casar com a referência, recusa (`WAN_UNVERIFIED`). Sem referência = nada é enviado (ADR-0027: WAN inferida não substitui confirmação) |
| 6 | Catálogo de destinos (CORE/INTERNET), sem URL livre | **novo** | Tabela `speed_endpoints` na nuvem **sem URL** (nome lógico, alvo, região, habilitado, saúde); a URL real vive só no Edge (config local) com validação verificável (esquema/porta fixos, IP fixado no carregamento, recusa de loopback/link-local/metadados, `INTERNET` sem faixa privada, `CORE` só em `core_cidrs`, sem redirecionamento, sondagem de saúde); o job carrega só o id lógico |
| 7 | Job TR-143 (Device:2 e IGD:1) com `Requested` numa chamada só | **novo** (Edge) | Pacote Go `internal/speed`: monta `setParameterValues` (Interface + URL [+ `TestFileLength`] + `DiagnosticsState`) em UM task; root único por dispositivo; caminho de escrita próprio e fechado, com varredura de fonte ampliada |
| 8 | NBI 200 ≠ concluído; 202 = pendente | **novo** (Edge) | 200/202 só movem para "coletando"; conclusão = `Completed` + frescor/correlação; nunca reenvia `Requested` |
| 9 | Conclusão por Inform `8 DIAGNOSTICS COMPLETE` | **fora de escopo** (não há canal) | Polling controlado do cache do ACS (3–5 s, teto 120 s/direção) com checagem de `BOMTime`/`EOMTime` e `_timestamp`; registrado como limitação |
| 10 | Cálculo de Mbps e qualidade | **novo** | Função pura `compute` (T09–T11, T19): DL = `8·TestBytesReceived/dt`; UL = `8·TestFileLength/dt` (ou `TestBytesSent` homologado); `TotalBytes*` só como métrica rotulada; `<3 s` = parcial; timestamps inválidos = inconclusivo; nunca 0 Mbps |
| 11 | Persistir resultado tenant-safe | **novo** | Migração aditiva 0034 `speed_endpoints` + `speed_test_runs` (RLS forçada como as demais); o job reutiliza `jobs` |
| 12 | Download e upload sequenciais; um por vez | **novo** | Execução = 1 run com 2 jobs; o 2º só nasce quando o 1º termina (ou expira); nunca em paralelo no mesmo CPE |
| 13 | Limites: 1/ONT, 1/PON, 2/tenant | **novo** | Reserva transacional (advisory lock por tenant) contando runs ativos; PON via vínculo ONU↔CPE **confirmado**; sem PON = bloqueado (`PON_UNKNOWN`); `409` quando ocupado |
| 14 | RBAC, tenant, auditoria | **estender** | Permissão nova `diagnostics:speed_run` (R2, escopável) no catálogo + papéis + `team_info` + matriz; leitura via `inventory:read`; auditoria `speed_test.requested/blocked/completed` |
| 15 | Feature flag desligada | **estender** | `speed_diagnostics: False` em `features.py`; desligada = nenhuma rota responde (403 `feature_disabled`) e a UI não mostra a seção |
| 16 | Gate de escrita (política do FiberCore) | **estender (sem caminho novo)** | As operações entram no **catálogo de bancada** (emenda ao ADR-0030): só o CPE de bancada, autorização prévia de uso único, separação de atores, trava de resultado incerto. Qualquer outro CPE: `operation_not_homologated`. `HOMOLOGATED_WRITES` e o gate de bancada ficam intactos. Abrir para a frota exige ADR/emenda e aprovação do responsável (fora deste ciclo) |
| 17 | Timeout, stale, partial, unsupported, audit | **novo** | Estados `queued→dispatched→collecting→completed/partial/failed/timeout/unsupported`; códigos de erro estáveis do pacote; job `UNKNOWN` quando o Edge não confirma |
| 18 | UI: Core/Internet, Iniciar, status, KPIs DL/UL, confiabilidade, histórico | **novo** (componente) | `SpeedTestSection` no painel; sem percentual fictício, `—` no lugar de zero, no máximo 2 KPIs, aviso "Mede a WAN da ONT, não Wi-Fi/LAN" |
| 19 | Copiloto só leitura | **fora de escopo** | Copiloto segue bloqueado (ADR-0015/ADR-SD-006); a interpretação fica como texto determinístico do próprio histórico, sem LLM |
| 20 | Capturas reais e how-to em `/ajuda` | **estender** | Artigo `rede/testar-banda` + manifesto; capturas reais do LAB dos estados que existem de verdade (indisponível/bloqueado); estados de execução/resultado só como cenário de teste E2E **rotulado** até a homologação |
| 21 | Test Node (GET/PUT) | **fora de escopo** (opcional) | Não será implantado nem exposto; `reference-test-node` fica só como referência; usar nó homologado do provedor |
| 22 | Homologação em ONT real | **bloqueado** | Precisa de autorização do responsável (ONT de bancada), nó de teste e janela; entrega traz guia e planilha, sem simular evidência |
| 23 | ERP/plano nominal | **fora de escopo** | Não é dependência; nenhum campo de plano no MVP |
| 24 | TR-369/USP, TR-471, agendamento, jitter/perda, iperf | **fora de escopo** | Backlog documentado |
| 25 | Não regredir 2.2 | **existe** | Mudanças aditivas (migração, flag, permissão, operação, seção de UI); testes de regressão dos módulos existentes rodam em cada PR |
