# PROMPT MESTRE — INTEGRAR QoS-001 AO SD-001 JÁ EM EXECUÇÃO

Você é o agente implementador do projeto **FiberCore 2.2**. Recebeu o **adendo QoS-001 v1.1** junto do pacote SD-001 base (ou o pacote já está no projeto). **NÃO reconstrua nada**: esta é uma melhoria incremental do diagnóstico já sendo feito. O escopo anterior do Speed Diagnostics TR-143 permanece integralmente vigente. Este adendo só acrescenta monitoramento e diagnósticos de qualidade.

## Ordem imperativa
1. Leia `README.md`, `docs/01_DELTA_E_NAO_REGRESSAO.md` e todos os arquivos deste adendo. Identifique o pacote SD-001 de base (hash no README) e leia os materiais dele.
2. Faça **inspeção somente leitura** do repositório, incluindo `CLAUDE.md`, `AGENTS.md`, migrations, testes, API, Edge Connector, GenieACS, Capability Registry, SD-001, ONU 360/EntityDetailDrawer, workers e Central de Ajuda. Não presuma paths nem estágio de implementação.
3. Gere `CURRENT_STATE.md`, `GAP_MAP.md` e `IMPLEMENTATION_PLAN.md` com evidências de caminhos. Classifique cada requisito `já implementado / estender / bloqueado / fora de escopo`.
4. Planeje no máximo **2 PRs de código**: (A) capabilities/Edge/backend + testes; (B) pequeno adendo no drawer + help/changelog. PR0 só documentação/inventário. Aplique a menor mudança possível.

## Requisitos inegociáveis
- **RÁPIDO**: ler WAN/PPPoE, IPv4/IPv6, LAN, óptica, Wi-Fi, CPU/memória e uptime somente se existirem, e executar PING/DNS **homologados** com destino autorizado e WAN de serviço conferida. Nenhum teste de saturação de banda.
- **COMPLETO**: RÁPIDO + invocação do serviço **SD-001 já previsto** (Core/Internet escolhidos e autorizados) + traceroute opcional se suportado. Usar o mesmo job engine, lock de ONT/PON, controle RBAC, histórico e flags. Não criar outro TR-143.
- Mapeamento de TR-181 e TR-098 conforme documento 03; capability por fabricante/modelo/firmware; todos os paths de instância descobertos. `UNKNOWN` e `not_supported` são saídas legítimas.
- Se ONT só reporta pela VLAN ACS/gestão ou está em bridge, **não** vender resultado como medição de qualidade WAN serviço. Telemetria pode ser mostrada com escopo e ressalvas.
- `NBI HTTP 200/202` nunca equivale a teste terminado; não usar `Complete`/contadores antigos como execução nova. Seguir `docs/04_ORQUESTRACAO_E_INTEGRACAO.md`.
- Cada métrica contém valor com unidade correta, status, origem (`TR069` vs `OLT` vs `SD001`), interface/escopo e timestamp; sem preencher valor 0 se não medido.
- Regras de hipóteses simples, explicáveis, sem score artificial; Copilot SOMENTE interpretação read-only de resultados existentes, sem manobra automática.
- Manter a UX minimalista no **sidebar direito recolhível atual**, sem nova tela; `RÁPIDO` e `COMPLETO`, quatro métricas principais, detalhes recolhíveis e histórico. Proteger PII e segredos.
- Não alterar GenieACS, Mongo, USP, OLT, Wi-Fi do cliente, rede operacional, Docker nem executar comandos em dispositivos reais sem autorização.
- Flags OFF até homologação/canário aprovado.

## Implementação/testes
- Ajuste `contracts/openapi.quality-addon.yaml` e o JSON Schema aos tipos e rotas **existentes**; não copie/cole endpoint duplicado se já houver API genérica. Os contratos aqui são de referência.
- Use `catalog/capability-catalog.json` como checklist de descoberta, não como autorização de escrita.
- Reproduza cenários Q01–Q22 de `docs/08_HOMOLOGACAO_E_ACEITE.md`, com fake ACS/Edge e fixtures; teste segurança, locks, freshness, partial, bridge, source e regressão em SD-001/ONU 360.
- Mostre screenshots capturados da **aplicação implementada**, nunca mock estático, e insira how-to na Central de Ajuda existente.
- Solicite revisão Codex pelo `prompts/CODEX_REVIEW.md`; Lovable (`prompts/LOVABLE_UX.md`) só se necessário ao ajuste visual.

## Saída obrigatória
1. Inventário com paths reais, GAP_MAP e etapas concluídas vs pendentes.
2. Arquivos alterados, por que cada mudança é aditiva, PRs/commits e migrations.
3. Tests com comandos/logs, evidência de reaproveitamento de SD-001 (mesmo runId/service), demonstração de dados frescos e origem WAN/OLT.
4. Screenshots reais, help/changelog, matriz homologação vendor/model/firmware.
5. Riscos, limitações, feature flags, rollback e pontos que exigem autorização de equipamento/produção.

**Pare** qualquer alteração arriscada se não puder confirmar integração/identidade/segurança no repositório real; mantenha a melhoria em flag OFF e informe bloqueio específico em vez de criar serviço paralelo.
