# Backlog — ideias de frontend, visual e funcionalidades (aplicação de referência) — 2026-10-31

**Estado: análise e plano para ação FUTURA. Nada aqui está implementado, aprovado nem priorizado pelo responsável.** Origem: 5 capturas de tela de uma aplicação de gestão de OLTs enviadas pelo responsável (painel, lista de OLTs, autorização de ONUs, seletor de OLT, backups). As capturas contêm endereços, nomes de OLTs e números de uma operação real de terceiros: **não foram versionadas nem devem ser enviadas ao Lovable, a MCP ou ao ai-memory**; este documento descreve só os padrões, sem nenhum dado delas.

## 1. O que a referência faz (observado)
- **Painel:** faixa de indicadores (OLTs respondendo X/Y, ONUs online de N, ONUs fora do ar, sinal em atenção, sinal crítico, quedas nas últimas 24 h); tabela de OLTs (ONUs online/total, última coleta); cartão "Por que as ONUs estão fora" (Offline, LOS, Sem energia); alças de arrastar nos cartões (layout personalizável); contador de ONUs offline no menu lateral.
- **Lista de OLTs:** um cartão por OLT com estado de resposta, etiqueta de site e de fabricante, endereço e protocolo de acesso, selo de frescor ("tempo real · aviso há 2 h"), modelo/firmware/serial, ONUs online de N, **última coleta e "sinal em" (dois horários separados)**, **uplinks como pastilhas com a velocidade negociada e cor por estado**, **ladrilhos de PON com online/total e barra de ocupação**, e botões Sincronizar, Coletar sinal, Backup e Saída bruta; botão global "Sincronizar todas" com a frequência de coleta explicada.
- **Autorizar ONUs:** escolher a OLT, buscar ONUs não autorizadas (auto-find), escolher perfil, nomear o cliente, aplicar a VLAN de serviço; cadastro por SN ou MAC.
- **Backups:** histórico por OLT (arquivo, tipo automático/manual, tamanho, data) com Ver, Comparar (diferença) e Baixar; "Fazer backup" e "Backup de todas"; rotina noturna.
- **Navegação e visual:** menu lateral de operação (Painel, OLTs, ONUs, Autorizar ONUs, ONUs offline, Sinal óptico, VLANs e perfis, Buscar SN, Buscar MAC, Eventos, Backups); tema escuro com realce âmbar; chip do papel ("Operador"); alternador de tema; botões flutuantes de ajuda e assistente; rodapé com versão.

## 2. Classificação para o FiberCore
Legenda: **Adotar** (cabe no que já decidimos), **Adaptar** (a ideia sim, o modo não), **Evitar** (conflita com uma regra do projeto), **Futuro/gated** (depende de decisão, ADR ou homologação).

| # | Ideia | Decisão | Por quê / como encaixa |
|---|---|---|---|
| I1 | Faixa de indicadores no topo da Visão Geral/NOC (OLTs respondendo, ONUs online/total, fora, quedas 24 h) | **Adotar** | Todos os números já existem (`onus`, `olts`, `onu_state_events`, `GET /v1/onus/unstable`). "Sinal em atenção/crítico" só com faixa homologada por classe de ONU; sem ela mostrar "sem faixa de referência" (mesma regra do QoS-001). |
| I2 | "Por que as ONUs estão fora" (Offline / LOS / Sem energia) | **Adotar** | O modelo já distingue `offline`, `los` e `dying_gasp`. É um cartão de contagem com link para a lista filtrada. Barato. |
| I3 | Contador de ONUs offline no item de menu | **Adotar** | Distintivo no item Rede (o limite de 6 áreas do design system continua). Contagem vem do relatório de offline. |
| I4 | Dois horários por OLT: "coleta do estado" e "sinal em" | **Adotar** | Combina com a regra de frescor por grupo (TTL óptico ≠ estado). Mostrar cada um com idade e fonte. |
| I5 | Ladrilhos de PON com online/total e barra | **Adotar** | Já temos a matriz de PONs (ADR-0037); acrescentar a barra de ocupação e o contador. |
| I6 | Pastilhas de uplink com velocidade negociada | **Futuro/gated** | Exige coletar uplinks (consulta de OLT nova no catálogo do ADR-0032, captura supervisionada → fixture → parser → `Validated`). Valor alto: detecta uplink negociado abaixo do esperado. |
| I7 | Selo "tempo real × cache" | **Adaptar** | Já mostramos fonte e frescor; padronizar um selo único (`Atualizado · há N min` / `Cache`) em toda tela. |
| I8 | Cartões do painel reordenáveis por usuário | **Futuro (P2)** | Preferência por usuário guardada no servidor; sem dado sensível. Só depois dos indicadores. |
| I9 | Busca por MAC além de SN | **Futuro** | O modelo atual não guarda MAC de ONU; avaliar PII e se a fonte (OLT/ACS) o entrega. SN já existe. |
| I10 | Tela de Eventos (linha do tempo) | **Adotar (P1)** | `onu_state_events` e incidentes já guardam as transições; falta a tela com filtros por OLT/PON/tipo e exportação CSV. |
| I11 | "Sincronizar todas" / "Coletar sinal" sob demanda | **Evitar como está** | A coleta da OLT tem piso de 15 min, uma sessão por vez e orçamento por classe; SNMP real é frágil. Mostrar "próxima coleta em…" e oferecer consulta pontual pela fila `olt_query` com cota. Nunca um botão global. |
| I12 | "Saída bruta" | **Evitar** | Regra do projeto: nunca exibir saída crua da OLT (pode ter nome de cliente e segredos); o cru fica só no Edge (0700, autoapagado em 24 h). Substituir por resultado tipado e validado. |
| I13 | Mostrar endereço e porta de acesso da OLT no cartão | **Evitar** | Endereço de OLT nunca vai à tela, a repositório ou a mensagens; mostrar nome lógico, site e Edge. |
| I14 | Lista de "ONUs não autorizadas" (auto-find), somente leitura | **Futuro/gated** | Depende do lote 1 da captura (`olt.autofind`) estar `Validated`. Leitura apenas. |
| I15 | Autorizar ONU (perfil, VLAN, nome do cliente) | **Futuro/gated, escrita** | É escrita na OLT: política + prévia + aprovação por outra pessoa + pós-checagem + auditoria (R3), com `HOMOLOGATED_WRITES` hoje vazio. Exige ADR próprio e homologação do driver; cliente real nunca em fixture. |
| I16 | Catálogo "VLANs e perfis" | **Futuro (leitura)** | Só leitura do que a OLT lista; escrita fora de escopo. |
| I17 | Backups de configuração da OLT com Ver/Comparar/Baixar | **Futuro/gated** | Configuração da OLT contém segredos e nomes de clientes. Exige: consulta de OLT no catálogo (uma sessão, guarda de 15 min), saneamento antes de guardar, permissão própria (R3), diferença só sobre o texto saneado, retenção e hash, sem download do bruto. Não confundir com o backup da nuvem, que já existe. |
| I18 | Botões flutuantes de ajuda/assistente | **Adaptar** | Já temos a Central de Ajuda (`/ajuda`) e o link "Ajuda desta tela"; um atalho flutuante único é aceitável (acessibilidade, foco e teclado). Assistente: fora de escopo. |
| I19 | Tema escuro com realce âmbar | **Adaptar** | O design system é iOS-like, com tema claro/escuro por tokens; adotar a densidade e a hierarquia, não a paleta. Contraste mínimo e estado nunca só por cor (rótulo + ícone). |

## 3. Plano de ação futura (ordem sugerida, cada item com testes, Codex e evidência)
1. **P0 (só leitura, sem dependência):** I1 + I2 + I3 + I4 + I5 + I7 na Visão Geral/NOC e na tela de OLTs. Aceite: números idênticos aos da API, frescor e fonte em cada indicador, estado vazio honesto ("sem leitura", nunca zero), e2e com dados sintéticos, capturas reais da ajuda (a tela muda), Lovable só para o visual (sem dado real).
2. **P1:** I10 (tela de Eventos com filtros e CSV).
3. **P1/P2 dependentes de captura da OLT (ADR-0032):** I6 (uplinks), I14 (auto-find em leitura), I16 (catálogo de perfis em leitura).
4. **P2:** I8 (layout personalizável), I9 (busca por MAC, depois de decidir PII e fonte).
5. **Gated, só com ADR e autorização do responsável:** I15 (autorização de ONU) e I17 (backups de configuração da OLT com saneamento).

## 4. Guardas que valem para tudo acima
- Somente leitura por padrão; escrita em OLT/ONU só por job (R3) com todas as travas do ADR-0030.
- Nada de endereço de OLT, credencial, saída crua ou nome de cliente em tela, fixture, log ou captura de ajuda.
- Faixas de sinal só de perfil homologado; sem perfil, mostrar o valor sem julgá-lo.
- Cada tela nova: flag por provedor desligada até a homologação, RBAC no catálogo, teste de inventário de rotas, artigo de ajuda com capturas reais (sintéticas, rotuladas), changelog e Codex até approve.

## 5. Perguntas em aberto para o responsável
Prioridade entre o P0 (painel) e a tela de Eventos; se uplinks (I6) justificam uma janela de captura na OLT real; se a autorização de ONU (I15) entra no roteiro do produto e em que fase; se backups de configuração (I17) são requisito ou desejo.
