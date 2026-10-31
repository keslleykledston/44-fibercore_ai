# SD-001 Speed Diagnostics (TR-143) — estado atual do repositório (Etapa 0, somente leitura)

Data: 2026-10-31 | Base: `main` @ `0206006`+ (Alembic 0033) | Pacote: `FiberCore_2.2_SD001_Speed_Diagnostics_TR143_Handoff_v1` (checksums conferidos; cópia de referência em `reference/`, sem o `preview/` nem o `reference-test-node/`).

> **Colisão de nome:** o repositório já usa "SD-001" para o *Feature Pack Smart Diagnostics & Remediation* (ADR-0025, `docs/feature-packs/SD-001/`, flags `smart_diagnostics_*`). Este adendo é outro assunto (teste de banda TR-143). Para não misturar, neste repositório ele se chama **Speed Diagnostics (`speed_diagnostics`)**; "SD-001" aparece só como referência ao pacote.

## 1. O que existe e será reutilizado

| Peça | Onde está (caminhos reais) | O que já faz | Relevância |
|---|---|---|---|
| Motor de jobs | `apps/api/app/api/jobs.py`, `0008_jobs.py`, `app/core/jobsign.py` | Máquina de estados `PREVIEWED→…→SUCCEEDED/FAILED/UNKNOWN`, aprovação por job, envelope assinado (Ed25519) com nonce/expiração, resultado com pós-verificação, `idempotency_key`, auditoria. `OPERATIONS` é um dicionário fechado (R0..R3). **Escritas ficam bloqueadas** (`HOMOLOGATED_WRITES` vazio) | O teste de banda é um job novo; escrever `DiagnosticsState=Requested` é uma escrita no CPE, logo cai no gate de escrita |
| Gate de bancada | `app/core/bench.py`, ADR-0030, Edge `internal/bench`, `internal/nbi/bench*.go`, `internal/jobs/{claims,lease}.go` | Segundo caminho que abre escrita: flag + alvo de bancada + registro de capacidades com evidência + autorização prévia do dono (uso único) + `claim` durável + `lease` + confirmação do dispositivo no ACS | Modelo a seguir para um **terceiro caminho** (`speed`), mais amplo que bancada mas com o mesmo rigor |
| Edge outbound | `agents/edge/` (`internal/agent`, `jobs`, `nbi`, `collector`, `config`, `queue`) | Único ponto que fala com o GenieACS NBI (GET de dispositivos, `getParameterValues` por job `refresh`, DELETE de tarefa; escritas só no caminho de bancada). Verifica assinatura, nonce, lease, ritmo persistido | Executor do teste; **o NBI nunca é exposto** (ADR-0008, ADR-SD-002) |
| Cliente NBI | `agents/edge/internal/nbi/{nbi,params,refresh,bench,bench_ssid}.go` | Lista fechada de folhas legíveis (`params.go`), reconciliação de tarefa ambígua, limpeza de tarefa, `setParameterValues` apenas para SSID de bancada | Base para `DownloadDiagnostics`/`UploadDiagnostics`; um teste varre o fonte atrás de nomes de tarefa fora da lista (será ampliado) |
| Registro de capacidades | `app/api/inventory.py` (`/v1/olts/{id}/capabilities`, `_capabilities`), `0015_device_capabilities.py`, `app/core/ont_config.py` (descoberta por campo) | `(vendor, model, firmware, protocol, operation) → status/certificação/evidência`; `supported`/`observed|certified` exigem `evidence_ref` + `verified_at` (CHECK). CLI `capability-set`. **Informa e condiciona; por si só não abre escrita** (ADR-0019, ADR-0030 item 4) | Onde vive "SUPPORTED/PARTIAL/UNSUPPORTED/UNKNOWN" por modelo+firmware |
| Estado e configuração do CPE | `app/api/cpe_state.py`, `0016`, `app/api/ont_config.py` (`cpe_config_fields`: `wan.type/status/vlan_id`), ADR-0034 | Observações tipadas de WAN/Wi-Fi com hora do dispositivo | Pistas auxiliares para "WAN de serviço" (tipo ppp/ip/bridge, VLAN); **não** identificam a WAN de serviço (ADR-0027: inferência não substitui confirmação) |
| Vínculo ONU↔CPE e PON | `0017_onu_cpe_links.py` (`status='confirmed'`), `onus.pon_id → pon_ports` (`0005`) | CPE→ONU confirmada→PON | Única forma de saber a PON do CPE para o limite "1 teste por PON" |
| RBAC | `app/core/permissions.py`, `app/core/security.py`, ADR-0031, `tests/test_rbac_inventory.py`, `scripts/gen_rbac_matrix.py` | Catálogo fechado de permissões; `devices:act:*`, `jobs:request/approve`, `diagnostics:run` (R0); MFA recente por permissão (`MFA_RECENT_ENFORCE`) | Nova permissão precisa entrar no catálogo, nos papéis, em `team_info` e na matriz gerada |
| Flags por provedor | `app/core/features.py` (`FEATURES`, `tenant_features`) | Padrão desligado; só o dono liga (`feature-set`) | `speed_diagnostics` entra aqui, `False` |
| Diagnósticos | `app/api/diagnostics.py` (`diagnostic_runs`, ADR-0024), `diagnostic_jobs` (ADR-0028), Visão 360 | Motor de regras passivo; testes ativos "bloqueados até ADR-SD-003" (ADR-0025 item 8) | O teste de banda é um **teste ativo**: precisa de ADR próprio (será o ADR-0038, que cumpre o papel do "SD-003" para esta fatia) |
| Frescor e proveniência | ADR-0020, `_prov`/`_fresh` em `inventory.py` | Todo bloco diz fonte, hora e qualidade | Resultado do teste usa o mesmo envelope |
| UI | `apps/web/src/components/{OnuQuickInspector,OnuWorkspace,OntConfigView,OntSidebar,EntityDetailDrawer,CpeActions}.tsx`, `app/rede/onu/[id]/page.tsx`, ADR-0035/0037 | Painel de detalhes da ONU com abas (Resumo/Aparelho/Histórico) e sidebar da ONU 360°; BFF same-origin `/bff/*`; flags lidas no servidor | O "Teste de banda" entra como seção/aba do painel já existente, sem página nova |
| Ajuda | `docs/help/**`, `docs/help/screenshot-manifest.yaml`, `tests/validate_help.py`, capturas reais do LAB (usuário de coleta noc_n1) | Artigos com capturas reais e manifesto validado | How-to novo com capturas reais |
| Auditoria / eventos | `audit()` em `app/api/routes.py`, outbox (ADR-0007) | Linha por ação, evidência redigida | Auditoria do teste |
| Limites do Edge | ADR-SD-002 (ritmo persistido, 1 dispositivo por job, retenção 24 h após limpeza falha), ADR-0029/0032 (fila, cota, lease) | Padrão de proteção do equipamento | Modelo para limites do teste |

## 2. O que NÃO existe (lacunas reais)

1. **Nenhuma referência a TR-143** em código (`DownloadDiagnostics`, `UploadDiagnostics`, `DiagnosticsState`, `BOMTime/EOMTime`, `TestBytesReceived`, `TestFileLength`). Só há menção em documentação do pacote.
2. **Nenhuma operação de job para teste ativo** nem gate de escrita que não seja o de bancada.
3. **Nenhum catálogo de destinos de teste** (Core/Internet) nem nó de teste (servidor GET/PUT) no ambiente.
4. **Nenhuma descoberta de capacidade TR-143** (presença do objeto, `_writable`, root Device:2 × IGD:1, interface WAN de serviço).
5. **Nenhum limite de concorrência por PON/tenant** para jobs de CPE (existem trava por dispositivo e por alvo de bancada).
6. **Nenhuma tabela de resultados de medição** nem seção de UI de teste de banda.
7. **Nenhum evento `8 DIAGNOSTICS COMPLETE`** exposto ao Edge: o NBI não entrega o evento; só há polling controlado do cache (e a leitura ativa de parâmetros do ADR-SD-002).
8. O `ReadOnlyOps`/lista de tarefas do cliente NBI do Edge proíbe `setParameterValues` fora do caminho de bancada: o teste precisa de um caminho de escrita **fechado e próprio**.

## 3. Restrições do ambiente que condicionam a entrega

- `HOMOLOGATED_WRITES` vazio e `bench_writes` restrito ao CPE de bancada (Huawei EG8145V5, `00259E-EG8145V5-48575443E2247AA5`): qualquer teste real em ONT exige **nova autorização do responsável** (manobra de bancada) e um nó de teste que não existe. Sem isso a entrega fica com mocks e a flag desligada.
- O GenieACS é o já instalado (NBI privado, só via Edge). Não há Mongo/GenieACS novos a criar.
- TR-369/USP continua separado (ADR-0015); nada de USP aqui.
- ERP (HubSoft) segue só leitura; plano nominal **não** é dependência.
- `docs/help` já tem capturas reais do LAB com usuário de leitura; o teste de banda só terá captura real de estados "indisponível/bloqueado" até a homologação (estados "em teste/resultado" seriam de cenário mock e serão marcados como tal).
