# Mensagem única para o agente

Estou enviando o **ADENDO QoS-001 v1.1** ao SD-001 do FiberCore 2.2. Ele **não substitui** nem reinicia a implementação do Speed Diagnostics TR-143 já em andamento.

Leia o `README.md` e `prompts/CLAUDE_CODE_ADENDO.md`, confira o pacote base SD-001 e inventarie o repositório ANTES de alterar o código.

A melhoria adiciona: diagnósticos RÁPIDO (status WAN/PPPoE, IP, óptica, LAN, Wi-Fi, CPU, ping/DNS); COMPLETO reutilizando SD-001 para Core/Internet, com traceroute opcional; mapeamento TR-181/IGD e compatibilidade por firmware; resultados com fonte/frescor; hipóteses determinísticas; sidebar recolhível atual e histórico.

Não construir outro ACS, motor de banda, orquestrador, microserviço ou tela paralela. Preservar Edge, Capability Registry, ONU 360, RBAC, multi-tenant, segurança, versionamento 2.2 e feature flags. Não executar testes/alterações reais na rede sem autorização. Entregar GAP_MAP, PRs pequenos, testes Q01–Q22, revisão Codex, screenshots reais, how-to/changelog e rollback.
