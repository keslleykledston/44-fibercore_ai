# FiberCore 2.2 — SD-001 Speed Diagnostics TR-143 (handoff v1.0)

**Objetivo:** habilitar teste de download e upload originado na ONT, em direção a um destino aprovado no Core do provedor ou na Internet, preservando o projeto FiberCore 2.2 e seu stack existente.

**IMPORTANTE:** isto é um ADENDO INCREMENTAL. Não substituir GenieACS, Edge Connector, modelos, serviços, telas, banco, registry, rotas ou fluxos existentes. Fazer inventário e reaproveitar antes de criar código. O pacote **não foi aplicado** ao repositório do usuário.

## Decisões fechadas

- UX: ação `Testar banda` no **sidebar direito recolhível** da ONU/ONT, dentro do `EntityDetailDrawer`/ONU 360° existente; sem tela nova.
- TR-069: **GenieACS existente**, via **Edge Connector outbound**; nenhum acesso público ao NBI/Mongo. TR-369: manter controller independente; usar abstração de diagnóstico existente e NÃO implementar USP do zero neste incremento.
- Método MVP: **TR-143 HTTP DownloadDiagnostics / UploadDiagnostics**; usar somente o perfil realmente exposto e validado pela ONT/firmware.
- Destinos: **CORE** (servidor aprovado dentro da rede) e **INTERNET** (servidor externo controlado pelo provedor ou explicitamente autorizado, que suporte GET e PUT). Ambos precisam ser acessíveis pela WAN de serviço da ONT.
- Compatibilidade: classificar `SUPPORTED`, `PARTIAL`, `UNSUPPORTED`, `UNKNOWN`, sem inventar suporte nem provocar testes na VLAN de gerência como prova da banda do assinante.
- Resultado: taxa de download, upload, qualidade/confiabilidade da leitura, método, interface, destino, timestamps, status e histórico. **Sem prometer medida do Wi-Fi/LAN.**
- Operação: uma direção por vez; apenas testes manuais neste MVP; fila e limites simples, permissões e auditoria.
- Documentação: capturas **reais** da UI implementada na Central de Ajuda (`/ajuda`), nunca substituir por screenshot fictício.
- Homologação inicial: um modelo/firmware piloto, depois expansão através de Capability Registry; ERP HubSoft é contexto opcional (plano nominal se já disponível), **não é dependência do MVP**.

## Leitura sugerida

1. `docs/01_PRD_E_ESCOPO.md`
2. `docs/02_ARQUITETURA_E_FLUXO.md`
3. `docs/03_TR143_MAPEAMENTO.md`
4. `docs/04_CONTRATOS_E_DADOS.md`
5. `docs/05_UX_E_COPILOTO.md`
6. `docs/06_SEGURANCA_OPERACAO.md`
7. `docs/07_TESTES_HOMOLOGACAO.md`
8. `docs/08_EXECUCAO_INCREMENTAL.md`
9. `prompts/CLAUDE_CODE_EXECUTAR.md`
10. `prompts/CODEX_GATE.md` e `prompts/LOVABLE_UX.md`

## Estrutura

- `contracts/openapi.fragment.yaml`: contrato de referência; **mesclar**, não sobrescrever API existente.
- `contracts/schema_reference.sql`: referência para persistência; adaptar ao schema/migrações e RLS existentes.
- `contracts/task-examples.json`: payloads TR-143 exemplificativos; **não executar em produção sem homologação**.
- `fixtures/*.json`: dados sintéticos de capacidade, jobs e respostas.
- `preview/index.html`: protótipo estático navegável do drawer (não conectado ao backend).
- `reference-test-node/`: **implementação de referência opcional** de endpoint GET/PUT para laboratório/piloto; nenhum deploy automático. A rede pode usar um serviço de medição já homologado.
- `checklists/`: checklist de rollout e revisão de PR.

## Fontes oficiais para validação

- Broadband Forum — TR-143 CWMP data model: https://cwmp-data-models.broadband-forum.org/tr-143-1-0-1.html
- Broadband Forum — TR-143 Amendment 1: https://cwmp-data-models.broadband-forum.org/tr-143-1-1-0.html
- GenieACS — NBI API reference: https://docs.genieacs.com/en/latest/api-reference.html
- Broadband Forum — Test procedures: https://cwmp-data-model-test.broadband-forum.org/06-index-test-procedures.html

**Regra de ouro:** sem capacidades comprovadas e interface WAN correta, o estado é `Não suportado`/`Não homologado`, nunca velocidade 0 Mbps ou `Falha de banda`.
