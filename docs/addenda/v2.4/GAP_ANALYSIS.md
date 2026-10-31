# GAP v2.4 — ONT Configuration Manager × repositório (2026-10-31)

Base: HEAD `main` (migração 0031). O adendo v2.4 é aditivo: nada abaixo reinicia a sprint nem substitui o que existe. Cópias de referência do pacote em `docs/addenda/v2.4/`
(PRD, mapeamento de campos, matriz de risco, UX, backlog e contratos OpenAPI/JSON Schema); os caminhos TR-098/TR-181 ali listados são **candidatos**, não mapeamento universal.

| Tema do adendo | Existe | Falta | Conflito | Ação proposta |
|---|---|---|---|---|
| Registro de capacidades (ADR-0019) | `device_capabilities` (operação × perfil vendor/model/firmware × protocolo), `GET /v1/cpes/{id}/capabilities`, porta de escrita `HOMOLOGATED_WRITES` vazia + caminho de bancada (ADR-0030) | capacidades **semânticas por campo** (`wifi.ssid.read` …) com instâncias reais | nome: o adendo usa `/ont-config/onts/{id}/capabilities`; no repo `/capabilities` já é o registro por operação | rotas novas **aditivas** sob `/v1/cpes/{id}/ont-config/*` (ADR-0034); o registro existente é reutilizado, não duplicado |
| Leitura de configuração (SSID, rádio, LAN, WAN) | `cpe_state` (5 métricas fechadas: link/conexão WAN, uptime, rádio ligado, canal), ingestão do Edge por NBI com projeção fixa | tabela de campos de configuração, catálogo fechado, rota de ingestão tipada, leitura | `cpe_state` proíbe SSID/PSK de propósito | tabela e rota **novas** (`cpe_config_fields`, `POST /v1/edge/cpe-config`); `cpe_state` não muda |
| Formulário dinâmico por capacidade | nenhum | `form-schema` derivado do que foi OBSERVADO | — | `GET /v1/cpes/{id}/ont-config/form-schema` (somente leitura; `editable=false`) |
| Instâncias reais (rádio↔SSID↔banda) | nenhum | resolução por vínculo informado pelo aparelho | — | `instances_of`: banda do SSID = banda do rádio ao qual o aparelho o ligou; sem vínculo, "banda não informada" (nunca por posição) |
| Sidebar direito recolhível da ONU/ONT + miniatura | `EntityDetailDrawer`, ONU 360, miniatura/fixtures de UX, `OltQueries` | aba de configuração | — | **FC24-02** (próximo PR): usa estes endpoints, sem escrita |
| Segredos (PSK/PPPoE) | regra "nunca em log/tela"; `pii_hmac_key` para documentos | campo de senha só como "definida?" | — | catálogo permite apenas `*.password.set` booleano; CHECK no banco proíbe nome com `password` fora disso |
| Pré-visualização, aprovação, execução, pós-verificação, auditoria | motor de jobs (preview→submit→approve→envelope assinado→Edge→pós-checagem), `device_actions` (`set_wifi_ssid` só 2,4 GHz, bancada), auditoria | change-set por capacidade, `If-Match`/revisão, diff redigido | — | **FC24-03** reutilizando `jobs`; a `revision` (hash estável da configuração observada) já é devolvida |
| Adaptador GenieACS seguro (escrita) | Edge: NBI somente leitura + caminho de bancada (`set_wifi_ssid` H3) | mapeamento path↔campo canônico, leitura ampla da árvore, escrita por capacidade | — | **FC24-04** (no Edge; só com laboratório autorizado) |
| TR-369 / USP Controller | nada (GenieACS não é controlador USP) | adaptador, lock dual-stack | — | **FC24-07**, atrás de flag; sem controller real = indisponível na UI |
| LAN / WAN | leitura nos campos canônicos (esta entrega); nenhuma escrita | OOB recovery, janela, dupla aprovação | — | **FC24-06** (R3), desligado até homologação |
| Potência óptica | `onus.rx_dbm` (OLT) | exibição na configuração | — | leitura apenas; vem do vínculo ONU↔CPE confirmado; sem capacidade de escrita no catálogo |
| Central de Ajuda `/ajuda/ont/...` | pipeline de capturas reais (Playwright) | artigos de ONT | — | rascunho no FC24-02, captura real após a UI integrada |
| Feature flags / rollback | `tenant_features` | flag do módulo | — | flag `ont_config` (desligada); migração 0032 aditiva (`DROP TABLE` reverte) |
| HubSoft primeiro | ADR-0033 (HS-01/HS-02) | — | — | inalterado |

## Entrega 1 (FC24-00 + FC24-01, este PR)
ADR-0034, GAP, backlog; migração 0032; catálogo fechado e validação; ingestão `POST /v1/edge/cpe-config`; `GET .../ont-config/{configuration,capabilities,form-schema}` e `/v1/ont-config/health`;
perfis SINTÉTICOS (`ont-config-mock`: dualband, multi_ssid, no_wifi, inactive_5g) rotulados como sintéticos; testes de estado desconhecido/obsoleto/sem rádio/multi-SSID/ACS silencioso, segredo nunca devolvido, óptica somente leitura, isolamento por tenant e Edge. **Nada escreve em equipamento.**
Ainda NÃO feito: leitura real no Edge (o Edge ainda não envia `cpe-config`), sidebar, preview/jobs, escrita, LAN/WAN, USP.
