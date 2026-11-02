# FiberCore AI — v2.5 COMPLETO | OLT Provisioning & Profile Studio + Modo Especialista

**Pacote único para Claude Code, Codex e Lovable — 02/11/2026.** Contém o adendo v2.5 completo e o módulo Expert Profile Editor (extensão funcional v2.5.1 **incluída na mesma entrega**). **Este ZIP substitui a necessidade de enviar os dois ZIPs de v2.5 e v2.5.1 separadamente.** Ele **não substitui** a base de código existente das versões anteriores; é um handoff incremental.

## O que o agente deve construir
**Módulo A — ONU Discovery & Authorization:** detectar ONUs não registradas na OLT, relacionar com HubSoft/contrato quando possível, selecionar service intent, pré-validar, aprovar, registrar e verificar.

**Módulo B — Profile Studio (assistido):** criar templates lógicos de serviço usando wizard intuitivo; compilar por tecnologia/vendor/firmware/placa; inventariar profiles da OLT; reaproveitar equivalentes; planejar criação sem alterar profiles compartilhados.

**Módulo C — Profile Expert Editor (engenharia/N3):** importar como referência profiles existentes, comparar semanticamente, editar versões de templates em formulário avançado ou YAML/JSON tipado, ajustar atributos DBA/T-CONT/GEM/VLAN/QoS conforme capabilities, vincular profiles nativos por OLT, simular diffs, publicar revisões imutáveis e, após homologação, executar por aprovação. Nenhuma edição in-place de profile compartilhado.

## Arquivos prioritários
1. `prompts/01_CLAUDE_CODE_MASTER.md` — **único prompt mestre**, cobrindo A+B+C.
2. `docs/product/PRD_INTEGRADO_v2_5.md`, `docs/product/BUILD_ORDER_AND_ACCEPTANCE.md`.
3. `docs/architecture/ARCHITECTURE_UNIFIED.md` e `docs/architecture/ADR-025-EXPERT-PROFILE-STUDIO.md`.
4. `docs/ux/SCREENS_AND_FLOWS.md`, `docs/engineering/PROFILE_RECONCILIATION.md`.
5. `docs/security/SECURITY_CONTRACT.md`, `docs/quality/END_TO_END_TEST_MATRIX.md`.
6. `contracts/` (2 OpenAPIs aditivas + 2 JSON Schemas), `examples/` e `starter/` (políticas sintéticas).
7. `prompts/02_CODEX_REVIEW.md` e `prompts/03_LOVABLE_UX.md`.

A especificação original de cada submódulo também está preservada em `docs/` e `docs/expert/`. Os prompts anteriores são apenas referência em `prompts/reference/`: **não enviar separadamente nem executá-los como instrução paralela**.

## Instruções inegociáveis
- Preservar o repo, a sprint, HubSoft-first, ONT Manager v2.4, GenieACS instalado, USP Controller previsto, Edge Connector, FastAPI/Next.js, Postgres RLS, NATS/outbox, motor único de jobs/aprovação e domínio `https://fibercore.devops.k3gsolutions.com.br`.
- **OLT via driver homologado; TR-069/USP para CPE.** Autorização PON não é tarefa GenieACS.
- **Leitura/mock/dry-run primeiro**; nunca confundir demonstrativo com integração real.
- Nenhum `run_cli`/script arbitrário enviado do navegador, agente de IA ou formulário para a OLT. Edição N3 do modelo canônico tipado; eventual texto CLI legado é referência sanitizada, não executável. Extensões nativas só com schema/allowlist e driver homologados.
- `UNKNOWN`, `STALE`, dados parciais e número desconhecido de referências = bloqueio de equivalência/aplicação (fail closed).
- Instalação/homologação real apenas com equipamento de laboratório autorizado, versão de firmware/cartão identificada, approval maker-checker, plano hash-bound, locks, canário, pós-verificação independente e registro auditável.
- Não presumir rollback transacional entre OLTs; usar compensação e reconciliação com estados `PARTIAL`/`UNKNOWN`.
- Ajuda `/ajuda`: screenshots **reais** da UI implementada com fixtures e Playwright no mesmo PR. Não fabricar capturas.

## Execução local para validar apenas materiais demonstrativos
```bash
python scripts/validate_package.py
PYTHONPATH=".:starter" python -m unittest discover -s starter/tests -v
```
Esses testes não conectam à OLT, não validam comandos de fabricantes nem certificam segurança de produção.

## Primeira entrega exigida
(A) GAP com caminhos efetivos do repo; (B) ADR e backlog integrados; (C) drivers read-only mockados e inventário de profiles/ONUs; (D) import como snapshot imutável + clone draft + diff semântico + preview; (E) testes, documentação e screenshots reais da tela. Só depois gate de escrita em LAB.
