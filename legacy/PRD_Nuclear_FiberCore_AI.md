# PRD Nuclear - SaaS de Inteligencia, Automacao e Gestao FTTH para ISPs

**Nome provisório:** FiberCore AI  
**Categoria:** SaaS B2B para ISPs, NOC, operacao FTTH e automacao de OLT/ONU  
**Versao:** 1.0  
**Objetivo:** transformar a gerencia de OLT/ONU em um centro de comando operacional, comercial e inteligente para provedores de internet.

---

## 1. Resumo executivo

O produto deve deixar de ser apenas um "gerenciador de OLT" e se posicionar como o **nucleo operacional FTTH do ISP**.

Ele deve conectar, em uma unica plataforma:

- OLTs, ONUs, PONs, CTOs e splitters.
- Clientes, contratos, planos, status financeiro e ERP.
- NOC, atendimento, campo, engenharia e diretoria.
- Alarmes, incidentes, automacoes, auditoria e inteligencia de negocio.

A proposta nuclear e responder rapidamente:

- Qual cliente esta atras dessa ONU?
- Esse problema e individual, CTO, PON, OLT, energia ou uplink?
- Quantos clientes foram afetados?
- Quanto de receita esta impactada?
- Qual acao segura resolve?
- O que o atendente deve falar?
- O que o tecnico de campo deve verificar?
- Onde a engenharia deve expandir primeiro?

O valor de mercado nao esta apenas em provisionar ONUs, mas em transformar dados tecnicos e comerciais em **decisao operacional automatizada**.

---

## 2. Tese nuclear do produto

A OLT conhece a rede.  
O ERP conhece o cliente.  
O NOC conhece o alarme.  
O campo conhece a CTO.  
A diretoria quer impacto, SLA e receita.  

Hoje essas informacoes ficam separadas.

O FiberCore AI deve unir tudo em uma unica verdade operacional:

> **Cliente -> Contrato -> Plano -> Login -> ONU -> Serial -> OLT -> PON -> CTO -> Localizacao -> Receita -> SLA -> Incidente -> Acao.**

Essa cadeia e o coracao do produto.

---

## 3. Posicionamento de mercado

O produto deve ser vendido como uma plataforma de inteligencia FTTH, nao como mais uma tela de ONU.

### Mensagem principal

**"O cerebro FTTH do seu provedor: OLT, ONU, cliente, ERP, NOC, campo e receita em uma unica verdade operacional."**

### Promessas comerciais

- Reduzir tempo de diagnostico.
- Reduzir erro de provisionamento.
- Reduzir chamados repetidos.
- Detectar falhas massivas automaticamente.
- Identificar receita impactada.
- Eliminar ONUs orfas.
- Descobrir clientes ativos sem servico.
- Descobrir clientes suspensos ainda online.
- Guiar equipe de campo com precisao.
- Priorizar manutencao e expansao por impacto real.

---

## 4. Publico-alvo

### ISPs pequenos - 500 a 5.000 assinantes

Dores principais:

- Dependencia de planilha.
- Pouca equipe tecnica.
- Provisionamento manual.
- Falta de associacao confiavel entre ONU e cliente.
- NOC informal ou inexistente.

### ISPs medios - 5.000 a 50.000 assinantes

Dores principais:

- Muitas OLTs e cidades.
- ERP ja implantado, mas desconectado da rede.
- Atendimento sobrecarregado.
- Dificuldade de correlacionar PON, CTO e cliente.
- Necessidade de automacao segura.

### ISPs grandes - acima de 50.000 assinantes

Dores principais:

- Multi-regiao.
- Multi-vendor.
- Governanca.
- Auditoria.
- SLA.
- BI executivo.
- Reducao de churn tecnico.
- Padronizacao operacional.

### Consultorias e NOCs terceirizados

Dores principais:

- Gerenciar varios ISPs.
- Isolamento por tenant.
- Relatorios executivos.
- Operacao segura com permissao por cliente.
- Padronizacao de troubleshooting.

---

## 5. Pilares do produto

## 5.1 Fonte da verdade FTTH

Consolidar OLT, ONU, PON, CTO, cliente, contrato, plano, ERP e localizacao em um unico modelo.

## 5.2 NOC inteligente

Transformar eventos isolados em incidentes correlacionados, com causa provavel, severidade e impacto.

## 5.3 Automacao segura

Executar acoes tecnicas com governanca: dry-run, validacao, aprovacao, execucao, pos-check, auditoria e rollback quando possivel.

## 5.4 Inteligencia de negocio

Mostrar receita impactada, SLA em risco, churn tecnico, regioes criticas, PONs saturadas e prioridades de expansao.

## 5.5 Copiloto operacional

Usar IA para diagnosticar, resumir, priorizar, gerar laudos, gerar mensagens e orientar NOC, campo e atendimento.

---

## 6. Escopo nuclear do MVP

O MVP deve provar a tese central:

> **Unificar OLT + ONU + cliente + ERP + alarme + acao segura.**

### Entregas obrigatorias do MVP

1. Multi-tenant.
2. Cadastro de OLT.
3. Agente local seguro.
4. Coleta read-only por SSH/SNMP/API.
5. Inventario de ONUs.
6. Status online/offline.
7. Potencia optica.
8. Historico de potencia.
9. Importacao CSV de clientes.
10. Integracao ERP generica.
11. Associacao ONU x cliente.
12. Score de confianca da associacao.
13. Dashboard FTTH.
14. Pagina ONU 360 graus.
15. Pagina tecnica do cliente.
16. Pagina da OLT.
17. Alarmes basicos.
18. Correlacao de queda massiva por PON.
19. Diagnostico automatico simples.
20. Reboot de ONU com permissao.
21. Provisionamento basico com template.
22. Auditoria.
23. API inicial.
24. Webhooks.

---

## 7. Funcionalidades nucleares

## 7.1 Identidade unica ONU x cliente

O sistema deve criar uma associacao operacional entre:

- Cliente.
- Contrato.
- Plano.
- Status financeiro.
- Login PPPoE/IPoE.
- Serial da ONU.
- MAC.
- OLT.
- PON.
- CTO.
- Porta CTO.
- Endereco.
- Receita mensal.
- SLA.

### Estados de associacao

- Associado com confianca alta.
- Associado com confianca media.
- Associado com conflito.
- Nao associado.
- ONU online sem cliente.
- Cliente ativo sem ONU.
- Cliente suspenso com ONU online.
- Cliente cancelado com ONU ativa.
- Serial duplicado.
- Cliente em PON divergente.

## 7.2 Score de confianca

Cada vinculo ONU x cliente deve ter score de 0 a 100.

Exemplo de regras:

- 100: serial no ERP bate com serial na OLT.
- 90: login PPPoE bate com contrato.
- 80: CTO e endereco batem com PON.
- 60: nome parcial aparece na descricao da ONU.
- 40: sugestao por proximidade ou historico.
- 0: sem evidencia.

## 7.3 Pagina ONU 360 graus

A pagina da ONU deve reunir dados tecnicos e comerciais.

### Dados tecnicos

- Serial.
- MAC.
- Fabricante.
- Modelo.
- OLT.
- Slot/PON.
- ONU ID.
- Status.
- Potencia RX.
- Potencia TX.
- Potencia recebida na OLT.
- Distancia.
- Uptime.
- Ultima queda.
- Ultimo retorno.
- Causa de queda, quando disponivel.
- VLAN.
- GEM.
- T-CONT.
- DBA.
- Line profile.
- Service profile.
- Firmware.
- Portas LAN.
- Wi-Fi, quando disponivel.
- CATV, quando disponivel.

### Dados comerciais

- Cliente.
- Contrato.
- Plano.
- Mensalidade.
- Status financeiro.
- Status do contrato.
- Telefone/WhatsApp.
- Endereco.
- Cidade.
- Bairro.
- Link para ERP.
- OS aberta.
- Segmento: residencial, empresarial, VIP, governo.

### Inteligencia

- Score de saude.
- Score de risco.
- Comparacao com vizinhos da mesma PON.
- Comparacao com vizinhos da mesma CTO.
- Diagnostico sugerido.
- Proxima melhor acao.
- Risco de churn tecnico.

## 7.4 Pagina tecnica do cliente

A plataforma deve oferecer uma visao tecnica do assinante, independente do ERP.

Campos:

- Dados do contrato.
- Plano e velocidade.
- Receita mensal.
- Status financeiro.
- ONU atual.
- Historico de ONUs anteriores.
- Ultimas quedas.
- Ultimas reclamacoes.
- Ultimas OS.
- PON/CTO/regiao.
- SLA.
- Diagnostico atual.
- Risco de cancelamento por falha tecnica.

## 7.5 NOC Command Center

O dashboard principal deve responder:

- Onde esta o maior problema agora?
- Quem esta afetado?
- Quanto de receita esta impactada?
- Qual e a causa provavel?
- O que o NOC deve fazer primeiro?
- O que precisa de campo?
- O que pode ser automatizado?
- O que e falha individual?
- O que e falha massiva?

Cards principais:

- Saude geral FTTH.
- ONUs online/offline.
- Clientes ativos offline.
- Clientes suspensos online.
- ONUs sem cliente.
- OLTs criticas.
- PONs criticas.
- CTOs criticas.
- Receita impactada.
- SLA em risco.
- Clientes VIP afetados.
- Incidentes abertos.
- Acoes recomendadas.
- Status dos agentes.

---

## 8. Correlação de incidentes

O sistema deve transformar eventos em incidentes acionaveis.

## 8.1 ONU individual offline

Cenario:

- Apenas uma ONU caiu.
- Vizinhos da mesma PON estao online.
- Vizinhos da mesma CTO estao online.

Diagnostico provavel:

- Problema individual no cliente.
- Queda de energia local.
- ONU desligada.
- Fibra drop rompida.

Acoes sugeridas:

- Verificar historico.
- Orientar atendimento.
- Abrir OS individual, se recorrente.

## 8.2 PON massiva

Cenario:

- Muitas ONUs da mesma PON caem em janela curta.

Diagnostico provavel:

- Rompimento.
- Splitter primario.
- Porta PON.
- Problema fisico na rota.

Acoes sugeridas:

- Criar incidente P1/P2.
- Listar clientes afetados.
- Calcular receita impactada.
- Acionar campo.
- Gerar mensagem para atendimento.

## 8.3 CTO suspeita

Cenario:

- Algumas ONUs caem na mesma CTO.
- Outras ONUs da PON continuam online.

Diagnostico provavel:

- CTO.
- Splitter secundario.
- Conectorizacao.
- Falha localizada.

Acoes sugeridas:

- Enviar equipe para CTO especifica.
- Levar lista de clientes e portas.
- Analisar potencia historica.

## 8.4 OLT critica

Cenario:

- Varias PONs ou placas afetadas.
- Uplink ou energia com alarme.

Diagnostico provavel:

- Falha de OLT.
- Placa.
- Energia.
- Uplink.
- POP.

Acoes sugeridas:

- Incidente P1.
- Escalonar engenharia.
- Avisar atendimento.
- Monitorar retorno.

---

## 9. Automacoes nucleares

## 9.1 Ativacao inteligente

Fluxo:

1. ONU aparece como nao autorizada.
2. Sistema busca serial no ERP.
3. Se encontrar OS de instalacao, sugere ativacao.
4. Seleciona template pelo plano.
5. Valida PON, CTO, VLAN, profile e cliente ativo.
6. Executa dry-run.
7. Solicita aprovacao, se configurado.
8. Provisiona.
9. Valida se a ONU ficou online.
10. Confirma potencia minima aceitavel.
11. Atualiza ERP com serial, OLT, PON e ONU ID.
12. Registra auditoria.

## 9.2 Troca de ONU

Fluxo:

1. Nova ONU aparece na PON.
2. Sistema busca OS de troca no ERP.
3. Sugere cliente provavel.
4. Desassocia ONU antiga.
5. Provisiona nova ONU.
6. Mantem historico da troca.
7. Atualiza ERP.
8. Registra evento.

## 9.3 Suspensao por inadimplencia

Fluxo:

1. ERP informa cliente suspenso.
2. Sistema identifica ONU.
3. Aplica profile de bloqueio ou servico de suspensao.
4. Mantem gerencia da ONU ativa.
5. Valida estado final.
6. Registra auditoria.

## 9.4 Desbloqueio automatico

Fluxo:

1. ERP informa pagamento ou reativacao.
2. Sistema identifica ONU e plano correto.
3. Restaura profile original.
4. Valida status online e potencia.
5. Atualiza ERP.
6. Notifica atendimento.

## 9.5 Correcao de plano divergente

Cenario:

- ERP indica plano 700 Mb.
- OLT esta com profile 300 Mb.

Acoes:

- Marcar divergencia.
- Sugerir correcao.
- Permitir aplicar individual ou em lote.
- Exigir aprovacao para lote.
- Registrar auditoria.

## 9.6 Higienizacao de base

Detectar automaticamente:

- ONU online sem cliente.
- Cliente ativo sem ONU.
- Cliente suspenso online.
- Cliente cancelado com ONU ativa.
- Serial duplicado.
- Descricao errada.
- PON divergente.
- ONU offline ha muitos dias.
- ONU autorizada sem contrato.

## 9.7 Prevencao de reclamacao

Detectar clientes com:

- Potencia degradando.
- Muitas quedas curtas.
- Flapping.
- Chamados repetidos.
- CTO problematica.
- Plano alto com qualidade ruim.
- Cliente VIP em risco.

Acoes:

- Criar lista preventiva.
- Sugerir visita tecnica.
- Abrir OS preventiva.
- Notificar equipe.

## 9.8 Pos-incidente automatico

Quando incidente fechar:

- Calcular tempo de indisponibilidade.
- Listar clientes afetados.
- Calcular receita impactada.
- Gerar timeline.
- Gerar resumo para diretoria.
- Gerar texto para atendimento.
- Marcar reincidencia.

---

## 10. Inteligencia de negocio

## 10.1 Receita impactada

Todo incidente deve calcular:

- Clientes afetados.
- Receita mensal afetada.
- Clientes empresariais afetados.
- Clientes VIP afetados.
- SLA em risco.
- Possivel churn tecnico.

## 10.2 Churn tecnico

Calcular risco de cancelamento baseado em:

- Quedas repetidas.
- Sinal critico.
- Chamados recorrentes.
- Falhas em horario nobre.
- Cliente novo com problema.
- Cliente de alto valor.
- Baixa qualidade historica da CTO.

## 10.3 Ranking de prioridades

O sistema deve dizer onde agir primeiro.

Exemplo:

1. CTO 17-B: 32 clientes, alta recorrencia, sinal medio ruim, R$ 4.800/mês.
2. PON 0/2/4: 89 clientes, muitos flappings, 3 clientes VIP.
3. Bairro Nova Cidade: crescimento de quedas de 37% nos ultimos 7 dias.

## 10.4 BI de expansao

Recomendar:

- Divisao de PON.
- Instalacao de nova CTO.
- Troca de splitter.
- Nova placa de OLT.
- Nova OLT.
- Revisao de rota.
- Substituicao de modelos de ONU problematicos.
- Reforco de backbone.

---

## 11. Copiloto IA

## 11.1 Papel da IA

A IA deve ser copiloto, nao executor livre.

Ela deve:

- Explicar alarmes.
- Resumir incidentes.
- Sugerir causa provavel.
- Gerar checklist para campo.
- Gerar texto para atendimento.
- Gerar laudo tecnico.
- Priorizar acoes.
- Comparar com historico.
- Identificar recorrencia.
- Recomendar expansao.

Ela nao deve:

- Executar comando critico sem aprovacao.
- Acessar credenciais.
- Inventar dados.
- Ignorar permissoes.

## 11.2 Modos de IA

### Modo NOC

Foco em alarmes, incidentes, severidade e prioridade.

### Modo Atendimento

Foco em diagnostico simples, cliente e texto pronto.

### Modo Engenharia

Foco em capacidade, PON, OLT, CTO, firmware e recorrencia.

### Modo Diretoria

Foco em SLA, receita, churn, eficiencia e expansao.

### Modo Campo

Foco em mapa, CTO, checklist e clientes afetados.

---

## 12. Arquitetura e uso de Golang

## 12.1 Decisao arquitetural

Golang deve fazer parte da arquitetura, principalmente nos componentes de alto desempenho, alta concorrencia e missao critica.

A recomendacao e uma arquitetura hibrida:

- **Go** para agente, coletores, workers, automacao, correlacao e processamento de eventos.
- **FastAPI/Python ou NestJS/Node.js** para API de negocio, integracoes e velocidade de desenvolvimento.
- **Python** para IA, RAG, diagnosticos e parsers avancados.
- **React/Next.js** para frontend.

## 12.2 Onde usar Go desde o inicio

### Agente local

O agente local deve ser preferencialmente em Go.

Motivos:

- Binario unico.
- Baixo consumo.
- Boa concorrencia.
- Facil distribuicao.
- Bom para SSH/SNMP/API.
- Excelente para ambientes de ISP.

Funcoes:

- Conexao outbound TLS.
- SSH/SNMP/API nas OLTs.
- Fila local.
- Retry.
- Cache local.
- Auditoria.
- Allowlist de comandos.
- Execucao de automacoes aprovadas.

### Collector service

Go deve coordenar coletas massivas:

- Agendamento por tenant.
- Rate limit por OLT.
- Timeout.
- Retry.
- Controle de concorrencia.
- Normalizacao inicial.
- Publicacao no event bus.

### Event workers

Go deve processar alto volume de eventos:

- ONU online/offline.
- Potencia alterada.
- Queda massiva.
- Flapping.
- Divergencia de perfil.
- Eventos do ERP.
- Webhooks.

### Motor de correlacao

Go deve detectar padroes em janelas curtas:

- PON massiva.
- CTO suspeita.
- OLT critica.
- Sinal degradando.
- Receita impactada.
- Incidente recorrente.

### Motor de automacao

Go deve executar automacoes com seguranca:

- Validacao.
- Dry-run.
- Aprovacao.
- Execucao.
- Pos-check.
- Rollback.
- Auditoria.

## 12.3 Diagrama logico

```text
Frontend Next.js/React
        |
API Core - FastAPI/NestJS/Go
        |
        +-- Inventory Service
        +-- ERP Integration Service
        +-- Customer/Contract Service
        +-- Auth/RBAC Service
        |
Event Bus - NATS/RabbitMQ/Kafka
        |
        +-- Collector Service - Go
        +-- Event Worker - Go
        +-- Correlation Engine - Go
        +-- Automation Engine - Go
        +-- Notification Worker
        |
Databases
        +-- PostgreSQL - estado atual, tenants, clientes, OLTs, ONUs
        +-- TimescaleDB - metricas e historico
        +-- Redis - cache e locks
        +-- Object Storage - evidencias, logs e relatorios
        |
ISP Site
        +-- Fiber Agent - Go
              +-- OLT Huawei/ZTE/FiberHome/Datacom/etc.
              +-- SSH/SNMP/API/Telnet legado
```

## 12.4 Fases de adocao do Go

### Fase 1 - MVP

Usar Go em:

- Agente local.
- Executor de comandos.
- Coletor basico.
- Gateway agente/SaaS.

### Fase 2 - Escala

Adicionar Go em:

- Workers de eventos.
- Motor de correlacao.
- Webhook dispatcher.
- Automacao segura.

### Fase 3 - Alta escala

Adicionar Go em:

- Pipeline massivo de telemetria.
- Agregadores por tenant.
- Streaming de eventos.
- Multi-regiao.
- Servicos de baixa latencia.

---

## 13. Integracoes ERP

## 13.1 ERPs prioritarios

- IXC.
- SGP.
- MK Solutions.
- HubSoft.
- Voalle.
- RadiusNet.
- Topsapp.
- Integrator.
- CSV generico.
- API REST generica.
- Webhook generico.

## 13.2 Dados importados do ERP

- Cliente.
- Contrato.
- Plano.
- Velocidade.
- Mensalidade.
- Status financeiro.
- Status do contrato.
- Login PPPoE/IPoE.
- Serial da ONU.
- Endereco.
- Bairro.
- Cidade.
- CTO.
- Porta CTO.
- OS aberta.
- Historico de atendimento.
- Segmento.
- SLA.

## 13.3 Dados enviados ao ERP

- Serial provisionado.
- OLT.
- PON.
- ONU ID.
- CTO.
- Porta CTO.
- Status da ONU.
- Potencia.
- Diagnostico.
- Incidente.
- Troca de ONU.
- Alteracao de plano.
- Reboot executado.
- Laudo tecnico.

---

## 14. Integracoes NOC e observabilidade

## 14.1 Zabbix

- Receber eventos do Zabbix.
- Enviar incidentes correlacionados.
- Criar trigger unica por incidente.
- Sincronizar hosts.
- Usar Zabbix como fonte complementar.

## 14.2 Prometheus e Grafana

- Exportar metricas por tenant.
- Expor saude das OLTs.
- Expor saude das ONUs.
- Expor incidentes.
- Criar dashboards executivos e operacionais.

## 14.3 ChatOps

Canais:

- Telegram.
- WhatsApp.
- Slack.
- Microsoft Teams.

Comandos futuros:

- Resumo FTTH agora.
- Clientes VIP offline.
- Diagnostico do contrato.
- Piores PONs da semana.
- Incidentes P1 abertos.
- Gerar relatorio do rompimento.

---

## 15. Governanca de automacao

## 15.1 Niveis de risco

| Nivel | Exemplos | Politica |
|---|---|---|
| Baixo | Atualizar coleta, gerar diagnostico, abrir incidente | Automatico |
| Medio | Reboot ONU, atualizar descricao, corrigir associacao | Permissao especifica |
| Alto | Provisionar, suspender, desbloquear, alterar plano | Aprovacao ou politica |
| Critico | Reset factory, desprovisionar em lote, alterar VLAN massiva | Aprovacao dupla ou break-glass |

## 15.2 Toda automacao deve ter

- Gatilho.
- Condicao.
- Validacao.
- Dry-run.
- Aprovacao, se necessario.
- Execucao.
- Pos-check.
- Notificacao.
- Auditoria.
- Rollback, quando possivel.

---

## 16. Modelo de dados nuclear

Entidades principais:

- Tenant.
- User.
- Role.
- OLT.
- PON Port.
- ONU.
- CTO.
- Splitter.
- Customer.
- Contract.
- Plan.
- ERP Integration.
- Alarm.
- Incident.
- Event.
- Automation Run.
- Audit Log.
- Metric Sample.
- Notification.
- Field Ticket.

Campos essenciais:

- Health score.
- Association score.
- Churn risk.
- Affected revenue.
- SLA risk.
- Probable cause.
- Automation mode.
- Risk level.
- Evidence payload.

---

## 17. Roadmap nuclear

## 17.1 Fase 1 - MVP vendavel

Objetivo: provar valor operacional rapido.

Entregas:

- Multi-tenant.
- Agente local em Go.
- Cadastro de OLT.
- Coleta Huawei/ZTE inicial.
- Inventario ONU.
- Historico de potencia.
- Importacao CSV.
- Associacao ONU x cliente.
- Score de associacao.
- Dashboard FTTH.
- Pagina ONU 360 graus.
- Alarmes basicos.
- Correlacao PON massiva.
- Reboot autorizado.
- Provisionamento basico.
- Auditoria.
- API inicial.

## 17.2 Fase 2 - Produto competitivo

Objetivo: competir diretamente com plataformas existentes.

Entregas:

- Integracoes ERP nativas.
- Mapa CTO/PON.
- Templates avancados.
- Suspensao/desbloqueio.
- Troca de plano.
- Troca de ONU.
- Webhooks.
- NOC Command Center.
- Relatorios.
- Score de saude.
- Higienizacao de base.
- PWA para campo.

## 17.3 Fase 3 - Produto nuclear

Objetivo: virar cerebro FTTH do ISP.

Entregas:

- Copiloto IA.
- Correlacao avancada.
- Receita impactada.
- Churn tecnico.
- Recomendacoes de expansao.
- Automacao com aprovacao.
- Pos-incidente automatico.
- BI executivo.
- ChatOps.
- Zabbix/Prometheus/Grafana.
- Multi-vendor expandido.

## 17.4 Fase 4 - Plataforma dominante

Objetivo: virar ecossistema.

Entregas:

- Marketplace de drivers.
- Marketplace de integracoes ERP.
- API publica completa.
- App mobile.
- Portal para tecnico.
- Benchmark anonimo de qualidade.
- Planejamento preditivo.
- Digital twin FTTH.
- Automacao cross-domain: OLT, BNG, Radius, ERP e NOC.

---

## 18. Raio-X FTTH - primeira entrega comercial

A primeira entrega ao cliente deve ser um diagnostico automatico chamado **Raio-X FTTH**.

Ele deve mostrar:

- Total de OLTs.
- Total de ONUs.
- ONUs online/offline.
- ONUs sem cliente.
- Clientes ativos sem ONU.
- Clientes suspensos online.
- Clientes cancelados com ONU ativa.
- PONs mais criticas.
- ONUs com pior sinal.
- CTOs mais problematicas.
- Receita em risco.
- Recomendacoes prioritarias.

Esse relatorio deve ser usado como ferramenta de venda, onboarding e prova de valor.

---

## 19. Planos comerciais sugeridos

## 19.1 Starter

Para ISPs pequenos.

- Ate 2 OLTs.
- Ate 2.000 ONUs.
- Inventario.
- Monitoramento.
- Associacao manual.
- CSV.
- Alarmes basicos.
- 3 usuarios.

## 19.2 Growth

Para ISPs em expansao.

- Ate 10 OLTs.
- Ate 15.000 ONUs.
- ERP basico.
- Provisionamento.
- Templates.
- Dashboard NOC.
- Webhooks.
- Auditoria.
- 10 usuarios.

## 19.3 Pro

Para ISPs medios.

- Ate 50 OLTs.
- Ate 75.000 ONUs.
- ERP nativo.
- Automacao.
- Mapa CTO/PON.
- Correlacao.
- BI.
- Zabbix.
- PWA campo.
- 30 usuarios.

## 19.4 Enterprise

Para grandes ISPs.

- OLTs conforme contrato.
- ONUs conforme contrato.
- Multi-regional.
- Alta disponibilidade.
- SSO.
- IA.
- SLA.
- API avancada.
- Suporte prioritario.
- Ambiente dedicado opcional.

---

## 20. Metricas de sucesso

## 20.1 Produto

- OLTs conectadas.
- ONUs monitoradas.
- Percentual de ONUs associadas.
- Tempo medio de diagnostico.
- Tempo medio de provisionamento.
- Alarmes correlacionados.
- Automacoes bem-sucedidas.
- Incidentes com causa provavel.

## 20.2 Operacao

- Reducao de chamados repetidos.
- Reducao de truck rolls desnecessarios.
- Reducao de erro de ativacao.
- Reducao de tempo de atendimento.
- Percentual de divergencias ERP x OLT corrigidas.
- Percentual de falhas massivas detectadas automaticamente.

## 20.3 Negocio

- Receita monitorada.
- Receita impactada.
- Receita preservada.
- Clientes em risco.
- Churn tecnico evitado.
- SLA por cidade.
- MRR do SaaS.
- Churn do SaaS.
- Expansao por tenant.

---

## 21. Criterios de aceite do MVP

O MVP sera considerado pronto quando:

1. Um ISP conseguir cadastrar uma OLT.
2. O agente local conseguir coletar ONUs.
3. A plataforma listar ONUs por OLT/PON.
4. A plataforma mostrar status e potencia.
5. A plataforma importar clientes via CSV.
6. A plataforma associar ONU a cliente.
7. A plataforma calcular score de associacao.
8. A plataforma detectar ONU sem cliente.
9. A plataforma detectar cliente ativo offline.
10. A plataforma gerar alarme.
11. A plataforma correlacionar queda massiva por PON.
12. A plataforma mostrar impacto por cliente.
13. A plataforma executar reboot autorizado.
14. A plataforma provisionar ONU com template.
15. A plataforma registrar auditoria.
16. A plataforma expor API basica.
17. A plataforma operar com isolamento multi-tenant.

---

## 22. Conclusao

O FiberCore AI deve nascer como uma plataforma de inteligencia operacional FTTH.

O objetivo nao e apenas gerenciar OLTs ou provisionar ONUs.

O objetivo e conectar:

> **OLT + ONU + Cliente + ERP + NOC + Campo + Receita + IA**

A vantagem competitiva esta em responder:

- Quem foi afetado.
- Por que foi afetado.
- Quanto isso custa.
- Qual acao resolve.
- Quem deve agir.
- Qual risco existe.
- Como evitar recorrencia.

Essa e a diferenca entre uma ferramenta de OLT e um produto nuclear para ISPs.
