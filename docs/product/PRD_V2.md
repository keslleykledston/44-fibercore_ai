# PRD v2.0 — FiberCore AI, Plataforma SaaS Inteligente FTTx

## 1. Objetivo e tese

Umificar OLT/PON/ONU/ONT/ACS/USP/cliente/contrato/ERP/CTO/NOC em visão operacional segura para ISPs brasileiros, consultorias e NOCs gerenciados. Diferencial primário: **identidade técnica de assinante** + diagnóstico multi-origem + ação controlada. *Fonte de verdade distribuída*: ERP é autoridade para dados comerciais; OLT para estado PON; GenieACS/USP Controller para parâmetros CPE; FiberCore é a autoridade de correlação, políticas e auditoria (sem sobrescrever as origens silenciosamente).

## 2. Personas

- NOC N1: localizar cliente, diagnóstico confiável, notas prontas, sem alterar rede livremente.
- NOC N2/Engenharia: PON, potência, capacidade, ações autorizadas e incidentes.
- Provisionamento/Campo: nova ONU, templates adequados a capacidade/firmware, pré-check e acompanhamento.
- ISP Admin: gerir pessoas, credenciais, integrações, catálogo por tenant e políticas.
- Superadmin K3G: suporte supervisionado multi-tenant, releases e observabilidade sem acesso invisível.
- Auditor: trilha, evidência, relatórios, sem comandos.

## 3. Casos de uso prioritários

**UC-01 Raio-X FTTH:** inventariar OLT/PON/ONU, cruzar CSV/ERP e apresentar órfãos/conflitos, anomalias ópticas, indisponibilidade e lacunas de coleta.

**UC-02 Atendimento 360:** buscar pelo ID cliente/contrato/login/serial/MAC; indicar status técnico vs financeiro; mostrar origem, `observed_at`, confiança e limitações; gerar texto para ticket.

**UC-03 PON massiva:** detectar >limiar configurável de quedas na mesma janela; suprimir duplicatas; produzir único incidente com lista de ONUs e clientes associados; nunca classificar queda geral durante indisponibilidade do coletor como rompimento comprovado.

**UC-04 Gestão remota dual-stack:** localizar CPE por `genieacs_device_id` e/ou `usp_endpoint_id`; detectar protocolo real; escolher por capacidade; solicitar refresh, reboot ou alteração de SSID com preview, aprovação, status assíncrono, pós-check e auditoria.

**UC-05 Provisionamento FTTH:** descobrir ONU não autorizada; escolher cliente, perfil técnico e driver homologado; simular; verificar VLAN/line/service-profile específicos; submeter ação somente após aprovação; registrar rollback se suportado; operador assume caso não.

**UC-06 Atualizações:** separar releases do produto/Edge, firmware OLT, imagem ONU/ONT e software CPE; exibir changelog, matriz de compatibilidade, janelas, aprovação, canário, rollback/recuperação explícita; firmware em lote não habilitado no MVP.

**UC-07 Co-piloto assistido:** sumarizar evidências e runbooks, explicar risco, sugerir próximo passo; saída com fontes e frescor; nenhuma credencial ou alteração de rede executada pelo modelo.

## 4. Módulos

1. `identity-access`: auth, MFA para ações sensíveis, RBAC/ABAC, tenant/workspace, auditoria.
2. `edge-fleet`: registros, heartbeat, certificados, capabilities, versionamento e rollout de Edge.
3. `olt-inventory`: POP, chassis, cards, PON, ONU, perfis técnicos; drivers read-only.
4. `cpe-unified`: identidade, discovery e normalização TR-098/TR-181.
5. `acs-cwmp`: integração GenieACS NBI **existente** via Edge local, sem ingestão Mongo direta.
6. `usp-tr369`: controlador USP independente via adapter, múltiplos MTPs se suportados.
7. `erp-hub`: CSV, REST genérica, IXC, SGP e demais drivers em homologação.
8. `service-association`: vínculo cliente/contrato/ONU/CPE com evidências e conflito.
9. `noc-events`: alarmes, incidentes, dedupe, correlação, supressão e frescor.
10. `automation-jobs`: RBAC, política, idempotência, approval, janelas, execução e post-check.
11. `template-catalog`: catálogos por marca/modelo/firmware, versões, assinatura e testes.
12. `platform-manager`: saúde dos módulos, versão, changelog e orquestração de releases.
13. `copilot`: consulta auditável, runbooks + LLM provider adapter (desligável).
14. `field-ops`: CTOS/topologia lógica/OS (etapa subsequente).

## 5. Guardrails funcionais

- `UNKNOWN/STALE` não é `OFFLINE`; indicar causa e último timestamp, monitorar `health` de agentes/ACS/USP.
- Identidade de dispositivo admite múltiplos protocolos; `ProtocolBinding` possui prioridade explícita por *capability*, e lock por `(tenant,physical_device,conflicting_scope)` em alterações.
- Toda coleta mantém `source`, `source_id`, `observed_at`, `ingested_at`, `confidence`, `quality`, `raw_evidence_ref` com PII minimizada.
- `capability_supported` não implica credencial/firmware testado. Três estados: `identified`, `observed`, `certified`. Escrita só se `certified` na combinação `(vendor,model,firmware,operation,transport)`.
- Alterações de Wi-Fi não mostram PSK em logs, relatórios nem outputs de LLM.
- Escritas executadas por agente apenas com `signed job envelope`, TTL, nonce, tenant/device permitidos, approval attestation e validação local; agentes não aceitam comandos shell genéricos enviados pelo Cloud.

## 6. Requisitos não funcionais e metas a comprovar

- Piloto alvo: 2 ISPs, 10 OLTs, 10k ONUs e 1 instância GenieACS existente; ampliar por teste de carga, não declarar escala demonstrada.
- Meta inicial: dashboard p95 < 3s e busca p95 < 1s em fixture representativa, excluídas atualizações de dispositivos ao vivo.
- Segurança: negar cruzamento entre tenants na aplicação, banco, mensagens e objetos; teste de RLS e testes adversariais.
- Retenção separada por telemetria, eventos, auditoria e PII, configurável por tenant e contratos.
- Infra: `/livez`, `/readyz` e `/metrics` por módulo, version info, estado dependência e breaker. Circuit-breaker, timeout, retry limitado com jitter; dead-letter queue.
- LGPD: base legal e papéis definidos com jurídico, minimização, export/exclusão contratual, segregação, notificação de incidentes e DPA.

## 7. Fluxos críticos

### Reboot CPE

`USER -> authorize -> preview -> (approval) -> persist job/outbox -> edge receive -> verify signature/scope -> adapter.execute -> queued/ack -> observe real completion -> postcheck -> audit -> UI`.

A NBI GenieACS HTTP 202 indica apenas **queued**, não sucesso. Não reexecutar `setParameterValues`/reboot automaticamente após timeout sem estado de reconciliação.

### Failover/falhas

Se `acs-cwmp` ficar indisponível: mostrar dados em cache com selo STALE; nenhum `write` novo; `olt-inventory` e `erp-hub` continuam operando. Se `edge` não responder: jobs expiram, nenhum comando é interpretado como sucesso. Se serviço LLM falhar: diagnóstico determinístico preservado.

## 8. Escopo por release

**R0 Foundation:** multitenant/auth/edge handshake, observabilidade, CI, wiki, mocks + duas fontes de dados fictícias, catálogo declarativo, API de contratos.

**R1 Operational Pilot:** Huawei MA5800 e ZTE read-only por drivers homologados, inventário, GenieACS NBI read-only via Edge, CSV, Raio-X, associação, NOC básico.

**R2 Safe Ops:** aprovação/reboot CWMP e ONU, perfis provisionamento 1 modelo validado, alarmes, rollout agente e changelog; USP controller em lab com TR-369 Agent simulado e adapter completo.

**R3 Commercial:** USP em piloto real com controlador aprovado, SGP/IXC (conforme acesso), CTO, Zabbix, BI, templates avançados, APIs públicas, opção HA via K3s.

**R4 Intelligence:** copiloto multi-provider, RAG, ações propostas e aprovadas, relatórios executivos, simulação de expansão, digital twin incremental.

## 9. Métricas de produto

- % assinantes vinculados com evidência forte, % vínculos conflitantes;
- precisão de detecção PON massiva/tempo detecção, redução de duplicidade;
- tempo de triagem por cliente; taxa de jobs pós-verificados;
- % dispositivos por estado de homologação; integrações healthy/degraded;
- p95 API, backlog DLQ, quantidade de agentes offline, atualização canário/rollback;
- custo por ONU monitorada e por tenant (após medição real).

## 10. Critérios de aceite P0

1. Duas organizações separadas sem leitura/escrita cruzada, incluindo export e mensagens.
2. Edge em rede privada comunica outbound sem exigir inbound aberto na rede ISP.
3. API da nuvem não possui acesso direto ao GenieACS NBI; consulta local pelo Edge.
4. Simulador e GenieACS de laboratório retornam dispositivos com `last_inform`, modelo e fonte; escritas bloqueadas por padrão.
5. Status ACS indisponível não se transforma em `ONUs offline`.
6. Existe pelo menos um OLT driver read-only por firmware real com fixtures e documentação de evidência.
7. Health dashboard: estado de módulos e conector separado de estado dos dispositivos.
8. Deploy, rollback e restauração de backup testados, sem alegar zero downtime antes de múltiplas réplicas.
9. Contratos REST versionados e testes automáticos executados no CI.
10. PR sem atualização de wiki/ADR/memória e parecer Codex não chega a `main`.
