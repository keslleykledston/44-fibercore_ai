# PROMPT MESTRE — COLAR NO CLAUDE CODE

Você é o agente implementador do **FiberCore 2.2**, no repositório existente. Recebeu o pacote `FiberCore_SD001_Speed_Diagnostics_v1` como **ADENDO INCREMENTAL**. Sua missão é construir o módulo `SD-001 — Speed Diagnostics TR-143` com arquitetura/UX existente, não reconstruir o FiberCore. Leia `README.md` e todos os arquivos em `docs`, `contracts`, `checklists`, `fixtures`, `preview` deste pacote antes de editar.

## Restrições INEGOCIÁVEIS
- Não sobrescrever arquivos existentes sem diff/revisão; preservar 2.2, status de implementação, ADRs, migrations e branches.
- Primeiro localizar repositório, `CLAUDE.md`/`AGENTS.md`, padrões, testes, migrations, endpoints, auth, tenants, `EntityDetailDrawer`, `ONU 360`, `Capability Registry`, `Diagnostic Engine`, `Edge Connector`, conector `GenieACS`, Central de Ajuda e feature flags.
- **GenieACS NBI jamais exposto na nuvem/browser.** Usar Edge outbound existente, não instalar outro GenieACS/Mongo. TR-369 continua separado; não inventar USP inacabado.
- Não criar novo microsserviço backend FiberCore nem uma nova página desnecessária. Reusar a infraestrutura de jobs.
- Não testar WAN de gestão como se fosse WAN do assinante. Não executar se interface do serviço não foi identificada/homologada.
- Não presumir suporte TR-143 em qualquer fabricante. `UNSUPPORTED/UNKNOWN` é resultado legítimo.
- Não executar `curl` contra ONT/OLT/ACS real nem publicar Docker/alterar infra sem autorização do responsável. Nenhum segredo hardcoded e nenhuma chamada de LLM que receba credenciais/PII.
- Nenhum teste deve começar automaticamente (requer ação manual e RBAC). Máximo padrão: 1 por ONT, 1 por PON, 2 por tenant.
- Não declarar entregue sem testes e capturas reais da UI rodando e how-to.

## Sequência obrigatória

### Etapa 0: inventário (READ ONLY)
1. Registrar `CURRENT_STATE.md`: arquitetura real com caminhos de arquivos, endpoint, jobs, auth/roles, Edge, registry, drawer, docs, Docker e versões.
2. Registrar `GAP_MAP.md`: `já existe / estender / novo / fora de escopo` por requisito.
3. Registrar `IMPLEMENTATION_PLAN.md`: no máximo três PRs pequenas (PR0 discovery, PR1 backend, PR2 UX+homologação). Não refatorar componentes que já atendem.
4. Se não houver infraestrutura necessária, implementar menor adaptação possível e registrar ADR; não criar produtos paralelos.

### Etapa 1: backend / integrações
1. Definir contrato interno de diagnóstico `TR143_HTTP` e mapear `Device.IP.Diagnostics` e `InternetGatewayDevice` de acordo com modelo/firmware e writable real.
2. Validar `WAN de serviço` e destino em allowlist; bloquear bridge-only/gestão-only.
3. Adicionar tarefas GenieACS NBI com `Interface + URL + DiagnosticsState=Requested` numa chamada `setParameterValues`; no upload adicionar `TestFileLength`. HTTP PUT no nó de testes.
4. Tratar NBI `200` como tarefa executada na sessão e `202` como pendente, **nunca teste concluído**. Capturar completion pelo canal Edge/Inform se já existir ou por polling de parâmetros **com verificação de frescor**, sem refazer Requested em loop.
5. Persistir resultados tenant-safe; cálculos `DL=8*TestBytesReceived/dt`, `UL=8*TestFileLength/dt` se envio todo confirmado, preferindo `TestBytesSent` homologado quando disponível; `TotalBytesSent` apenas métrica de interface com rótulo explícito.
6. Garantir partial, stale, invalid, unsupported, timeout e audit. Não inventar latency/jitter/loss.
7. Cobrir testes com mocks do Edge/NBI e simulações do Device:2/IGD/bridge.

### Etapa 2: UX / help center
1. Adicionar seção compacta ao drawer existente com `CORE/INTERNET`, `Iniciar`, status, DL/UL, validade e histórico; utilizar componentes visuais do próprio projeto.
2. A UI não expõe URL/credenciais; não mostra 0 em ausência/erro. Não criar segunda página de diagnóstico.
3. Integrar com o copiloto **somente para interpretação de registros**, sem disparo automático nem manobra.
4. Abrir UI real, realizar capturas dos estados disponíveis (reais ou cenários E2E mock explicitamente marcados), adicionar how-to com capturas reais em `/ajuda` e atualizar changelog/ADR/status.
5. Flag OFF até aceite técnico/homologação e aprovação explícita da operação.

## Testes obrigatórios
- `checklists/CODE_REVIEW.md` + `docs/07_TESTES_HOMOLOGACAO.md`.
- Verificação de tenant/RBAC/SSRF e concorrência em PON; partial e stale.
- Sem regressões em provisionamento/monitoramento ONT/OLT e Wi-Fi.
- Test Node de `reference-test-node` é **opcional** e apenas laboratório: usar serviço homologado existente quando disponível; não expor sem autorização.

## Entregáveis na resposta do agente
1. Tabela arquivo atual → alteração proposta → motivo, referenciando o repo real.
2. Lista dos PRs/commits, migrations aditivas e endpoints efetivos.
3. Testes executados com comandos e resultados, sem alegar teste real se não aconteceu.
4. Screenshots reais, caminho da documentação e limitações por firmware.
5. Planos de rollback, feature flag, lista de pendências e solicitação de review Codex.
6. Se algo depender de equipamento/credenciais reais, deixar bloqueado/flag OFF com guia de homologação, sem simular evidência de produção.

**Resultado desejado:** um diagnóstico simples e seguro, operável no sidebar, que não bagunce o FiberCore 2.2.
