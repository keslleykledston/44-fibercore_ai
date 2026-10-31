> **Referência recebida (2026-10-31), mantida como veio. Onde divergir do repositório, vale `docs/addenda/v2.2-qos/{CURRENT_STATE,GAP_MAP,IMPLEMENTATION_PLAN}.md` e a tabela de divergências em `docs/addenda/v2.2-qos/README.md` (lock compartilhado, ADR-0030, WAN de serviço, tabela de suite).**

# FiberCore 2.2 — SD-001 / ADENDO QOS-001 v1.1

**Natureza:** complemento incremental, não projeto novo. **Data:** 2026-10-31. **Status:** especificação/handoff, NÃO aplicada a um repositório.

**Base obrigatória:** `FiberCore_2.2_SD001_Speed_Diagnostics_TR143_Handoff_v1.zip` (SHA-256 `45566db816fcc87772f04cf21582db4655d439aed016e384305e893730b4a9c2`). Este pacote **NÃO** contém cópia nem substituição do SD-001. Deve ser enviado junto do pacote de base, ou aplicado quando o agente já o possuir.

## Propósito
Acrescentar **Diagnóstico de Qualidade do Serviço (QoS/QoE)** à ação de diagnóstico já prevista na ONT: consultas de WAN/PPPoE, PON/óptico, Ethernet, Wi-Fi e CPU; testes leves de ping e DNS; traceroute opcional; **reuso integral** dos downloads/uploads TR-143 do SD-001. Um painel compacto no sidebar existente, dois modos (`RÁPIDO`, `COMPLETO`), sem novo ACS, sem nova página, sem serviços paralelos e sem refatorar funcionalidades da 2.2.

## Ordem de leitura para o agente
1. `prompts/CLAUDE_CODE_ADENDO.md` (instrução mestre)
2. `docs/01_DELTA_E_NAO_REGRESSAO.md` (o que preservar)
3. `docs/02_PRD_PRIORIDADES.md`
4. `docs/03_MATRIZ_TR069_TR181_TR098.md` + `catalog/capability-catalog.json`
5. `docs/04_ORQUESTRACAO_E_INTEGRACAO.md`
6. `docs/05_NORMALIZACAO_E_FRESCOR.md`
7. `docs/06_UX_E_COPILOTO.md`
8. `docs/07_SEGURANCA_OPERACAO.md`
9. `docs/08_HOMOLOGACAO_E_ACEITE.md`
10. `docs/09_ROADMAP_PULL_REQUESTS.md`, `contracts/*` e `checklists/*`

## Árvore do adendo
- `docs/`: PRD, matriz técnica, orquestração, normalização, UI, segurança, aceite, rollout e fontes.
- `catalog/capability-catalog.json`: nomes/raízes de objetos de referência, com status condicional e escalonamento de compatibilidade. Não realizar escrita automática a partir deste catálogo.
- `contracts/openapi.quality-addon.yaml`: fragmento de API **apenas para adaptar/mesclar**, NÃO sobrescrever OpenAPI atual.
- `contracts/quality-run.schema.json`: JSON Schema de resultado normalizado do *novo* adendo.
- `contracts/edge-task-examples.json`: exemplos sintéticos de tarefas **somente para leitura/laboratório**.
- `fixtures/`: resultados sintetizados e cenários de teste.
- `preview/quality-addon.html`: mock clicável para alinhar UX, não substitui screenshot do produto.
- `prompts/`: mensagens para Claude Code, Codex, Lovable e envio.
- `scripts/validate_bundle.py`: checagem local estática, sem acesso a dispositivos ou rede.

## Condições antes de editar produção
- Descobrir arquitetura real do repositório e registrar `CURRENT_STATE`, `GAP_MAP`, `PLAN` com caminhos.
- Conferir estágio real de SD-001 e não duplicar implementação se já existe.
- Tudo sob feature flag independente/subfeature do diagnóstico existente; por padrão OFF até homologação.
- Qualquer ação ativa de diagnóstico exige RBAC e autorização; testar em laboratório primeiro.
- Se não há interface de **serviço** identificada, não atribuir testes na VLAN de gerência à conexão do assinante.
- Sem cifra/score universal de qualidade ou afirmação de cumprimento de SLA com base em teste isolado.

## Critério de pronto
Operador abre ONT → Diagnóstico → Rápido/Completo → vê progresso, evidências por camada, ausências fundamentadas, hipóteses não definitivas, fonte, horário, histórico; COMPLETO utiliza execuções SD-001 existentes. Sem regressões, sem acessos NBI no browser, screenshots reais e changelog/documentação atualizados.
