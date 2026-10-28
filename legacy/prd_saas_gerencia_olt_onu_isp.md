# PRD - SaaS de Gerência OLT/ONU para ISPs

**Plataforma Cloud para monitoramento, provisionamento e gestão operacional FTTH integrada a ERPs**

**Versão:** v1.0  
**Data:** 25 de junho de 2026  
**Idioma:** Português Brasil

## Resumo executivo

Este PRD descreve um SaaS para ISPs gerenciarem OLTs, ONUs, portas PON, CTOs, splitters, clientes e eventos FTTH em uma única plataforma cloud. O diferencial é conectar a rede óptica ao assinante real do ERP, permitindo que NOC, suporte, campo, engenharia e diretoria trabalhem com a mesma verdade operacional.


## 1. Visão do produto

Criar uma plataforma SaaS para provedores de internet gerenciarem OLTs, ONUs, portas PON, CTOs, splitters, clientes e eventos operacionais de rede FTTH em uma única interface web.

O produto deve funcionar como uma evolução de soluções como SmartOLT, OLT Cloud e UISP, mas com foco mais forte no mercado brasileiro: integração com ERPs, associação confiável ONU x assinante, operação NOC, auditoria, automação segura, inventário PON e diagnóstico inteligente.

A proposta é transformar a gerência de OLT/ONU em uma camada de verdade operacional: rede óptica, cliente, financeiro, suporte, campo e engenharia olhando para a mesma informação.


## 2. Problema

ISPs normalmente possuem múltiplas OLTs, fabricantes diferentes, cadastros incompletos, planilhas paralelas e pouca ligação confiável entre a ONU configurada e o assinante real do ERP.

Com isso, o NOC vê uma ONU offline, mas nem sempre sabe se o cliente está ativo, suspenso, cancelado, inadimplente, em OS ou em troca de equipamento. O atendimento fica lento, a operação de campo perde contexto e o provisionamento manual aumenta o risco de erro.

Outro problema comum é a falta de visão consolidada por porta PON, CTO, cidade e região. Quedas massivas viram centenas de alarmes individuais, dificultando identificar se a causa provável é rompimento, splitter, CTO, placa, energia ou uplink.


## 3. Objetivos

- Centralizar a gerência de OLTs e ONUs em uma plataforma SaaS multi-tenant.
- Associar ONUs aos assinantes reais do ERP com alto grau de confiança.
- Monitorar status, potência, distância, eventos, flapping e alarmes de ONUs.
- Permitir provisionamento com templates seguros e auditáveis.
- Gerar visão NOC por OLT, PON, CTO, cidade, cliente e severidade.
- Reduzir tempo de atendimento, erros de ativação e inconsistências entre OLT e ERP.
- Criar base para automação e copiloto de IA operacional em fases futuras.

## 4. Público-alvo

ISPs de pequeno, médio e grande porte que operam redes FTTH GPON/EPON/XPON.

Consultorias ou NOCs terceirizados que gerenciam OLTs de múltiplos provedores.

Equipes internas: NOC N1/N2, engenharia, provisionamento, suporte, campo, comercial, atendimento e diretoria técnica.


## 5. Benchmark e posicionamento

- SmartOLT se posiciona como plataforma cloud para OLTs Huawei e ZTE, com provisionamento, monitoramento e troubleshooting GPON/EPON/XPON, incluindo ativação rápida de ONTs.
- OLT Cloud se posiciona para mapear, monitorar e gerenciar OLTs, CTOs e ONUs, com alertas em tempo real, diagnósticos inteligentes e integração com ERPs.
- UISP se posiciona como solução de gestão para ISPs combinando monitoramento centralizado e gestão de negócio/rede.
- O diferencial proposto é unir esses conceitos em uma plataforma orientada ao ISP brasileiro, com ERP em primeiro plano, associação confiável cliente x ONU, mapa PON/CTO, operação NOC e automação segura.

## 6. Proposta de valor

- Para o NOC: identificar rapidamente quem é o cliente afetado e se o problema é individual, por CTO, por PON, por OLT ou por região.
- Para o suporte: consultar cliente, status financeiro, status da ONU, potência, histórico de quedas e diagnóstico em uma única tela.
- Para o provisionamento: ativar ONUs com templates padronizados, evitando comandos manuais e divergência entre plano comercial e perfil técnico.
- Para a engenharia: analisar ocupação de PON, degradação óptica, flapping, capacidade e recorrência de falhas.
- Para a diretoria: acompanhar indicadores de rede FTTH, disponibilidade, impacto em clientes, produtividade e qualidade operacional.

## 7. Escopo do MVP

| Módulo | Entrega no MVP |
|---|---|
| Tenants | Isolamento por ISP, usuários, permissões e auditoria. |
| OLT | Cadastro, credenciais, status, coleta e página detalhada. |
| ONU | Descoberta, status, potência, histórico básico e associação a cliente. |
| ERP | Importação CSV e conector REST genérico. |
| NOC | Dashboard, alarmes, filtros, correlação inicial por PON. |
| Provisionamento | Templates básicos, dry-run, execução auditada. |
| API | Endpoints iniciais para OLT, ONU, cliente, alarmes e eventos. |

- Multi-tenant com isolamento de dados por ISP.
- Cadastro de OLTs e credenciais seguras.
- Agente local para acesso às OLTs em redes privadas.
- Descoberta automática de ONUs autorizadas e não autorizadas.
- Monitoramento de status online/offline, potência, distância e eventos básicos.
- Associação manual e semi-automática de ONU x cliente.
- Importação CSV de clientes e integração ERP genérica via API REST.
- Dashboard operacional com OLTs, ONUs, alarmes e clientes impactados.
- Página detalhada da OLT, porta PON, ONU e cliente.
- Alarmes básicos e correlação inicial por PON.
- Provisionamento básico por template para pelo menos um fabricante prioritário.
- Auditoria de ações e controle de permissões.
- API pública inicial e webhooks básicos.

## 8. Fora do MVP

- App mobile completo.
- IA avançada de diagnóstico.
- Billing próprio.
- CRM próprio.
- Gestão completa de ordens de serviço.
- Mapa geográfico avançado de rotas de fibra.
- Inventário físico completo de rede externa.
- Integração nativa com todos os ERPs do mercado.
- Provisionamento multi-vendor completo em todos os firmwares.
- Alta disponibilidade enterprise multi-região.

## 9. Funcionalidades principais


## 9.1 Multi-tenant

Cada ISP deve possuir dados isolados. Consultorias podem operar múltiplos tenants com permissões separadas.

Cada tenant pode possuir múltiplas OLTs, agentes, integrações ERP, perfis de provisionamento e usuários.

Deve haver trilha de auditoria por tenant, usuário, ação e origem.


## 9.2 Cadastro e inventário de OLTs

Campos: nome, fabricante, modelo, firmware, IP de gerência, método de acesso, site/POP, cidade, região, credencial, agente responsável, status e tags.

Fabricantes prioritários para MVP/fase inicial: Huawei MA56xx/MA58xx, ZTE C300/C320/C600, FiberHome, Datacom e VSOL.

A plataforma deve suportar drivers por fabricante para normalizar comandos, SNMP e saídas diferentes.


## 9.3 Agente conector local

O agente local é obrigatório para ambientes onde as OLTs não são acessíveis diretamente pela nuvem.

Deve operar com conexão outbound segura, TLS, token por tenant, fila local, logs e modo read-only por padrão.

Deve executar coletas SNMP/SSH/API e somente aceitar comandos de escrita quando houver permissão e política de aprovação.


## 9.4 Descoberta de ONUs

A plataforma deve descobrir ONUs autorizadas e não autorizadas, coletando serial, MAC, fabricante, modelo, OLT, slot, porta PON, ONU ID, status, potência, distância, uptime, firmware, profiles, VLANs e service-port.

A descoberta deve rodar de forma agendada e também sob demanda.

ONUs não autorizadas devem aparecer em uma fila de provisionamento.


## 9.5 Associação ONU x cliente

Este é o núcleo do produto. Cada ONU deve poder ser vinculada ao assinante do ERP usando serial, login PPPoE/IPoE, contrato, nome, CPF/CNPJ, endereço, CTO, porta CTO, MAC ou descrição configurada na OLT.

O sistema deve indicar score de confiança: alto, médio, baixo, conflito ou não associado.

Deve destacar inconsistências: ONU online sem cliente, cliente ativo sem ONU, cliente suspenso online, cliente cancelado com ONU ativa e cliente ativo offline.


## 9.6 Integração com ERP

Integrações prioritárias: IXC, SGP, MK Solutions, HubSoft, Voalle, RadiusNet, Topsapp e API genérica.

Dados a importar: ID do cliente, nome, CPF/CNPJ, contrato, plano, velocidade, status do contrato, status financeiro, endereço, cidade, bairro, coordenadas, login PPPoE/IPoE, CTO, porta CTO, telefone, e-mail e ordens de serviço abertas.

Em fases futuras, a plataforma deve abrir OS, registrar evento técnico, atualizar serial da ONU, atualizar porta CTO, atualizar observações técnicas e sincronizar troca de plano.


## 9.7 Dashboard operacional

O dashboard deve mostrar total de OLTs, OLTs offline, total de ONUs, ONUs online/offline, ONUs com sinal crítico, ONUs com flapping, ONUs sem cliente, clientes ativos offline, clientes suspensos online, portas PON críticas e alarmes ativos.

Deve haver rankings: top PONs com mais quedas, top ONUs com pior potência, top regiões com maior indisponibilidade e top OLTs com maior criticidade.

Deve permitir filtros por tenant, cidade, OLT, PON, CTO, status e severidade.


## 9.8 Monitoramento de OLT

Métricas: disponibilidade, CPU, memória, temperatura, uptime, fontes, fans, placas, uplinks, tráfego, alarmes ativos, versão, quantidade de ONUs por PON, ocupação por PON e erros de interface.

Deve haver visão por OLT, por placa, por porta PON e por uplink.

Deve identificar OLT inacessível, placa offline, uplink down e porta PON com queda massiva.


## 9.9 Monitoramento de ONU

Métricas: online/offline, RX ONU, TX ONU, RX na OLT, distância, uptime, última causa de queda, histórico de queda, tempo offline, flapping, temperatura, voltagem, CATV, portas LAN e firmware quando disponíveis.

Classificação inicial de sinal: excelente acima de -20 dBm; bom de -20 a -24 dBm; atenção de -24 a -27 dBm; crítico de -27 a -30 dBm; muito crítico abaixo de -30 dBm.

Os thresholds devem ser configuráveis por fabricante, modelo e política do ISP.


## 9.10 Alarmes e correlação

Tipos: ONU offline, ONU flapping, sinal crítico, PON com queda massiva, OLT offline, uplink down, placa down, cliente VIP offline, cliente ativo sem ONU, ONU online sem cliente e cliente suspenso online.

Correlação: se muitas ONUs da mesma PON caírem juntas, gerar incidente único de PON crítica. Se várias ONUs de uma CTO caírem, sugerir problema em CTO/splitter. Se múltiplas PONs da mesma OLT caírem, sugerir placa, energia ou uplink.

O objetivo é reduzir ruído operacional e transformar alarmes em incidentes acionáveis.


## 9.11 Provisionamento de ONU

Fluxo: detectar ONU não autorizada, selecionar cliente do ERP, selecionar plano, selecionar template, validar porta PON/VLAN/perfil, aplicar configuração, testar status, registrar auditoria e atualizar ERP quando habilitado.

Templates iniciais: internet bridge, internet router, internet + VoIP, internet + CATV, empresarial com VLAN dedicada, PPPoE, IPoE e dual-stack IPv4/IPv6.

Proteções: preview, dry-run, aprovação opcional, rollback quando possível, bloqueio de comandos destrutivos e logs detalhados.


## 9.12 Gestão de planos e perfis

O produto deve mapear planos comerciais do ERP para perfis técnicos da OLT: DBA profile, line profile, service profile, VLAN, GEM, T-CONT, QoS e IPv6.

Deve detectar divergência entre plano contratado e perfil aplicado na ONU.

Deve permitir alteração de plano com validação e auditoria.


## 9.13 Inventário PON, CTO e topologia

Entidades: POP, OLT, slot, porta PON, splitter primário, splitter secundário, CTO, porta CTO, ONU, cliente, endereço, região e coordenadas.

Visões: OLT > Slot > PON > ONUs; Cidade > POP > OLT; CTO > clientes; Cliente > ONU > OLT; ocupação por CTO; ocupação por PON.

O MVP pode começar com topologia lógica e evoluir para mapa geográfico com rotas de fibra.


## 9.14 Busca global

A busca global deve aceitar nome do cliente, CPF/CNPJ, código do contrato, serial da ONU, MAC, login PPPoE, IP da OLT, nome da OLT, porta PON e CTO.

O resultado deve exibir cliente, contrato, plano, status financeiro, ONU vinculada, status da ONU, OLT, PON, CTO, último evento e ações rápidas.

Essa busca deve ser uma das telas mais usadas pelo suporte.


## 9.15 Página da ONU

Deve exibir informações técnicas: serial, modelo, fabricante, OLT, PON, ONU ID, potência, histórico, quedas, distância, profiles, VLANs, service-port, firmware e logs.

Deve exibir informações comerciais: cliente, contrato, plano, status financeiro, status do contrato, telefone, endereço, OS aberta e link para ERP.

Ações: atualizar, reboot, reprovisionar, trocar plano, suspender, desbloquear, desautorizar, abrir OS, copiar diagnóstico e gerar laudo.


## 9.16 Página da OLT

Abas: resumo, placas, portas PON, uplinks, ONUs, alarmes, configurações, templates, eventos, auditoria, capacidade e diagnóstico.

Deve permitir navegar da OLT para a PON, da PON para ONUs e da ONU para o cliente.

Deve mostrar ocupação, criticidade e histórico por porta PON.


## 9.17 NOC operacional

Tela em tempo real com alarmes ativos, incidentes abertos, quedas massivas, clientes VIP afetados, ranking de criticidade, timeline de eventos e status por cidade/OLT/PON.

Priorização: P1 para OLT offline ou grande impacto; P2 para PON inteira ou placa; P3 para CTO/grupo pequeno; P4 para ONU individual.

Deve permitir filtrar, reconhecer, atribuir, comentar e fechar incidentes.


## 9.18 Diagnóstico automático

O sistema deve gerar um diagnóstico textual com causa provável e próxima ação recomendada.

Exemplo: “Cliente João Silva está offline desde 08:43. A ONU perdeu comunicação na porta GPON 0/1/7 da OLT MA5800-MNS-01. Outras 31 ONUs da mesma PON também ficaram offline no mesmo horário. Causa provável: falha na PON, splitter ou rompimento. Recomendado acionar equipe de campo para verificar CTO 128-B e cabo alimentador.”

Esse diagnóstico deve poder ser copiado para atendimento, OS ou WhatsApp.


## 9.19 Integração com Zabbix, Prometheus e Grafana

A plataforma deve poder operar sozinha, mas também integrar com NOCs existentes.

Zabbix: importar hosts, exportar alarmes, receber webhooks, sincronizar status e expor métricas.

Prometheus/Grafana: exportar métricas, criar dashboards e permitir visão de séries temporais por OLT, PON e ONU.


## 9.20 API pública e webhooks

API REST para OLTs, ONUs, clientes, alarmes, incidentes, templates, provisionamento, eventos, métricas e integrações ERP.

Webhooks para ONU offline/online, OLT offline/online, PON massiva, sinal crítico, cliente VIP afetado, provisionamento concluído/falhou e incidente aberto/resolvido.

Segurança: API key por tenant, escopos, rate limit, assinatura de webhook e auditoria.


## 10. Segurança e LGPD

MFA, RBAC, isolamento multi-tenant, criptografia de credenciais, logs imutáveis, redação de senhas em logs, tokens revogáveis, rate limit e backup.

Como a plataforma trata dados pessoais de assinantes, deve haver minimização de dados, controle de acesso, logs de visualização, política de retenção, criptografia em trânsito e repouso, e separação entre dados técnicos e dados pessoais.

Ações sensíveis devem exigir permissão específica e, opcionalmente, aprovação.


## 11. Requisitos não funcionais

- Escalabilidade MVP: 10 tenants, 100 OLTs, 100.000 ONUs e coleta a cada 5 minutos.
- Escalabilidade fase 2: 100 tenants, 2.000 OLTs, 2 milhões de ONUs e coleta adaptativa.
- Performance: dashboard em até 3 segundos, busca em até 1 segundo e página da ONU em até 2 segundos.
- Disponibilidade: meta inicial de 99,5%, produção 99,9% e enterprise 99,95%.
- Observabilidade interna: logs estruturados, métricas de agentes, filas, falhas por fabricante, tempo de comandos e saúde das integrações.

## 12. Arquitetura sugerida

- Frontend: React/Next.js, Tailwind, Shadcn/ui, Leaflet ou MapLibre, ECharts/Recharts.
- Backend: FastAPI ou NestJS, PostgreSQL, TimescaleDB, Redis, filas com Celery/RQ/BullMQ/NATS/RabbitMQ.
- Agente: Go ou Python, Docker/systemd, conexão outbound, token, fila local, modo read-only default.
- Coleta: SNMP, SSH, Telnet legado opcional, APIs de fabricante e NETCONF/YANG em fase futura.
- Serviços internos: API, worker de coleta, worker de provisionamento, serviço ERP, serviço de alarmes, serviço de correlação, auditoria e webhooks.

## 13. Modelo de dados inicial

| Entidade | Campos principais |
|---|---|
| Tenant | id, nome, documento, plano, status, created_at |
| OLT | id, tenant_id, nome, fabricante, modelo, firmware, IP, POP, cidade, agente, status |
| PON Port | id, olt_id, frame, slot, porta, descrição, status, onu_count, capacidade |
| ONU | id, tenant_id, olt_id, pon_id, onu_id, serial, status, potência, distância, profiles, cliente |
| Customer | id, tenant_id, erp_id, nome, documento, contrato, plano, status, endereço, login |
| Alarm | id, tenant_id, severidade, tipo, entidade, título, descrição, status, datas |
| Event | id, tenant_id, entidade, tipo, payload, created_at |
| Audit Log | id, tenant_id, user_id, ação, alvo, antes/depois, comando, resultado, created_at |


## 14. Jornadas de usuário


## 14.1 NOC identifica cliente offline

- Alarme de ONU offline aparece.
- NOC clica na ONU.
- Sistema mostra cliente, contrato, plano e telefone.
- Sistema informa se outras ONUs da mesma PON também caíram.
- Sistema sugere causa provável.
- NOC copia diagnóstico ou abre OS no ERP.
- Evento fica registrado.

## 14.2 Provisionamento de novo cliente

- Técnico instala ONU.
- ONU aparece como não autorizada.
- Operador busca cliente no ERP.
- Seleciona plano e template.
- Sistema valida VLAN, profile e porta PON.
- Sistema provisiona e testa status.
- Sistema atualiza ERP e registra auditoria.

## 14.3 Queda massiva em PON

- Várias ONUs caem simultaneamente.
- Sistema correlaciona por OLT/PON/CTO.
- Abre incidente P1/P2.
- Lista clientes impactados.
- Mostra mapa ou resumo da área afetada.
- Permite exportar lista e acionar campo.
- Fecha incidente quando ONUs retornam.

## 15. Roadmap


## 15.1 Fase 1 - MVP

Login multi-tenant, cadastro de OLT, agente local, coleta básica, inventário de ONUs, associação ONU x cliente, importação CSV, integração ERP genérica, dashboard, alarmes básicos, página da ONU/OLT, auditoria, provisionamento básico e API inicial.


## 15.2 Fase 2 - Produto comercial

Integrações ERP nativas, mapa PON/CTO, correlação avançada, templates avançados, alteração de plano, suspensão/desbloqueio, webhooks, PWA para campo, integração Zabbix, relatórios e permissões avançadas.


## 15.3 Fase 3 - Produto avançado

IA de diagnóstico, previsão de falhas, detecção de degradação óptica, assistente NOC, automação com aprovação, ChatOps, digital twin, app mobile completo, multi-region SaaS e alta disponibilidade enterprise.


## 16. Métricas de sucesso

- Número de OLTs cadastradas.
- Número de ONUs monitoradas.
- Percentual de ONUs associadas a clientes.
- Tempo médio de provisionamento.
- Tempo médio de identificação de cliente afetado.
- Redução de alarmes duplicados.
- Redução de erros de provisionamento.
- Uso diário por NOC.
- MRR, churn, receita por tenant, custo por ONU monitorada, tempo de implantação e NPS.

## 17. Planos comerciais sugeridos

- Starter: até 2 OLTs, até 2.000 ONUs, monitoramento básico, associação manual, importação CSV, alarmes básicos e 3 usuários.
- Pro: até 20 OLTs, até 30.000 ONUs, integração ERP, provisionamento, webhooks, mapa básico, auditoria e 15 usuários.
- Enterprise: OLTs e ONUs conforme contrato, multi-regional, API avançada, correlação, IA, SSO, SLA e suporte prioritário.
- Sugestão de cobrança: por faixa de ONUs monitoradas, com adicionais por ERP nativo, automação avançada, HA e suporte premium.

## 18. Riscos e mitigações

- Risco: diferenças grandes entre fabricantes e firmwares. Mitigação: drivers por fabricante, homologação por modelo e fallback read-only.
- Risco: provisionamento incorreto. Mitigação: dry-run, preview, allowlist de comandos, aprovação e auditoria.
- Risco: ERP com dados inconsistentes. Mitigação: score de confiança, tela de conflitos e importação flexível.
- Risco: coleta massiva sobrecarregar OLT. Mitigação: coleta adaptativa, cache, rate limit por OLT e janelas de coleta.
- Risco: excesso de escopo. Mitigação: MVP focado em inventário, monitoramento, associação e provisionamento básico.

## 19. Critérios de aceite do MVP

- Um tenant consegue cadastrar uma OLT.
- O agente local coleta dados da OLT.
- O sistema lista ONUs por OLT/PON.
- O sistema mostra status online/offline e potência óptica.
- O sistema associa ONU a cliente.
- O sistema importa clientes via CSV.
- O sistema gera alarmes básicos.
- O sistema exibe dashboard operacional.
- O sistema registra auditoria.
- O sistema executa pelo menos uma ação segura em ONU.
- O sistema provisiona uma ONU em pelo menos um fabricante.
- O sistema expõe API básica.
- O sistema mantém isolamento multi-tenant.

## 20. Conclusão

O produto deve ser construído como uma plataforma SaaS de operação FTTH, não apenas como um painel de OLT.

O grande diferencial é conectar OLT, ONU, PON, CTO e cliente real do ERP, criando uma fonte única de verdade para NOC, suporte, campo, engenharia e diretoria.

A primeira versão deve priorizar inventário, monitoramento, associação cliente x ONU e provisionamento seguro. As fases seguintes adicionam integração ERP profunda, mapa, correlação, automação e IA.


## 21. Referências públicas consultadas

- SmartOLT: plataforma cloud para provisionamento, monitoramento e troubleshooting de OLTs Huawei/ZTE em redes GPON/EPON/XPON - https://www.smartolt.com/
- OLT Cloud: plataforma para mapear, monitorar e gerenciar OLTs, CTOs e ONUs com alertas, diagnósticos e integração ERP - https://oltcloud.co/
- UISP: plataforma de gestão de rede e negócio para ISPs - https://uisp.com/uisp-overview
- Integração IXC + SmartOLT: exemplo de integração ERP com gerenciamento OLT/PON - https://wiki-erp.ixcsoft.com.br/documentacao/menu-sistema/provedor/integracoes/integracoes/smartolt.html
- Zabbix Integrations: referência de integração/observabilidade para equipamentos de rede - https://www.zabbix.com/integrations/fiberhome
