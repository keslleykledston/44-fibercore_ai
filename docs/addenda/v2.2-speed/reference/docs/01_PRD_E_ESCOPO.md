# PRD — Speed Diagnostics SD-001 (Incremento TR-143)

## Problema
O NOC precisa diferenciar gargalo entre ONT e core, ONT e internet, e rede interna do assinante sem deslocamento e sem falsos diagnósticos. A plataforma já prevê diagnóstico, ONU 360 e copiloto; faltam execução/recolhimento confiáveis de download e upload via TR-143 e apresentação operacional.

## Objetivo e jornada
No detalhe da ONT → seção `Diagnósticos` → `Teste de banda` → escolher destino `Core` ou `Internet` → `Iniciar teste` → acompanhamento por direção → resultados com origem, método, validade, limitações e histórico → exportação básica via recurso existente (se existir).

## Escopo P0 (obrigatório)
1. Descoberta por **capacidade real** e escrita permitida dos parâmetros do dispositivo (Device:2 e InternetGatewayDevice:1), com cache por modelo+firmware e exceção por dispositivo quando necessário.
2. Validação da WAN de serviço: confirmar interface selecionada, tipo de equipamento (roteado/bridge), rota para destino; não presumir que a VLAN de gestão mede serviço.
3. Selecionar um de dois destinos cadastrados e saudáveis; URLs sempre montadas do catálogo de endpoints aprovado, não texto livre do operador.
4. Orquestração via adapter GenieACS/Edge atual, download e upload **sequenciais**, leitura de contadores e persistência da execução com feedback de fila.
5. Taxa de transferência em Mbps, com validação de timestamps/bytes e rótulo de qualidade do resultado (`válido`, `parcial`, `inconclusivo`).
6. UX mínima no sidebar direito, com estados vazios/indisponíveis/erro/reexecutar e histórico curto.
7. RBAC, tenant isolation, auditoria, feature flag, timeout e proteção de concorrência.
8. Testes automatizados com fake ACS, teste de laboratório com ONT real e central de ajuda com capturas reais.

## Fora do escopo
- Reescrever GenieACS, adicionar novo ACS, instalar Mongo novo, mudar controller USP/TR-369.
- Recriar módulo `ONU 360`, `Subscriber 360`, `Capability Registry`, `Automation Studio` ou copiloto.
- Testes automáticos 24x7, massivos, agendados, múltiplas conexões, TR-471, iPerf3 embarcado, SSH arbitrário no CPE, controle de OLT e otimização automática.
- Medir diretamente Wi-Fi/LAN do usuário partindo apenas da ONT; não usar resultado isolado como prova contratual definitiva.
- Rotas/módulos públicos para GenieACS NBI; baixar/upload de conteúdo do cliente.

## Regras de produto
- Sem modelo de dados/firmware homologado, apresentar `Não homologado neste modelo` e oferecer fluxo manual apenas se já existir.
- Se apenas download for suportado, mostrar download + `Upload não suportado`; jamais preencher 0.
- Se não houver WAN de serviço comprovada, **bloquear** `Iniciar` com explicação.
- Evitar comparação com plano se plano nominal não foi confirmado; se houver, usar apenas contextualização `medição aproximada`, não afirmar infração de SLA.
- Internet = destino externo controlado, **não** speedtest aleatório/Speedtest.net/iperf na ONT.
- Valores nunca devem ser inventados pelo copiloto; ele resume dados registrados e propõe próximos testes, sem alterar rede sem autorização.

## KPIs e critérios de sucesso
- Operador consegue executar ao menos 1 teste de download + upload válido no equipamento piloto com Core e Internet.
- Dispositivos incompatíveis não recebem comando; UI explica motivo.
- Fila/timeout não geram duplicidade nem deixam status `running` eternamente.
- Telemetria de uso do módulo não interrompe inventário, monitoramento nem gerenciamento TR-069.
- `speed diagnostics` pode ser desabilitado via feature flag sem desabilitar telas principais.

## Linguagem do produto
- `Mbps medidos pela ONT` (não `Wi-Fi entregue`).
- `Confiabilidade: válido / parcial / inconclusivo` (não selo absoluto de conformidade).
- `Destino: Core` ou `Destino: Internet`; exibir endpoint lógico e região sem vazar segredo/URL com credencial.
