# FiberCore AI — Construction Build Kit v2.1

**Data-base:** 2026-10-28 · **Projeto:** K3G OLT SaaS / FiberCore AI · **Estado:** pacote de planejamento, especificação e bootstrap (não é SaaS pronto).

## Como usar (ordem)

1. Disponibilizar **todo este diretório** ao Claude Code no repositório `keslleykledston/120-OLT_SaaS`; manter os documentos legados em `legacy/` apenas como referência.
2. Colar **`prompts/01_CLAUDE_CODE_MASTER.md`** no Claude Code. Claude deve conferir o repositório, executar Sprint 0 e registrar evidências, sem inventar validação real.
3. A cada checkpoint de PR, enviar ao Codex **`prompts/02_CODEX_SUPERVISOR.md`**, acompanhado do diff, testes, logs sanitizados e ADRs.
4. Fornecer ao Lovable **`prompts/03_LOVABLE_UX.md`** + `docs/ux/UX_SPEC.md` + contratos OpenAPI. UX mock primeiro; integrar depois através da API real.
5. Solicitar integração somente com **GenieACS já instalado**, preservando dados, MongoDB, presets, scripts, credenciais e serviços atuais. A NBI deve ser alcançável pelo Edge Connector de forma privada. Não instalar outro GenieACS por padrão.
6. O controlador USP TR-369 será um módulo plugin atrás de API, selecionado após prova de compatibilidade. **OB-USPC é candidato de laboratório, não presumir prontidão/HA de produção**.

## Decisões centrais

- Cloud: **FastAPI + Python 3.12+, SQLAlchemy/Alembic, PostgreSQL, Next.js/React/TypeScript**; agente de borda **Go**.
- Infra piloto: **Docker Compose** com healthchecks, testes de falha, segregação de redes, modo `profiles`; **K3s/Kubernetes** quando exigidos rolling updates, múltiplas réplicas e HA.
- Jobs piloto: **NATS JetStream + outbox transacional + estado de job em PostgreSQL**; para workflows prolongados pode-se avaliar Temporal posteriormente, não fazer duas orquestrações desde o começo.
- Conectividade: Edge por conexão **outbound mTLS**, com autorização server-side e validações locais, sem túnel NBI de acesso irrestrito.
- Protocolos: **TR-069/GenieACS**, **TR-369/USP Controller**, **OLT via drivers**. Um mesmo dispositivo pode ser dual-stack, com política por capacidade e exclusão mútua em ações.
- Segurança: read-only por padrão; toda escrita com política, pré-visualização, aprovação, pós-check, evidência e auditoria.
- LLM: interface de provedores com rotas Gemini, Claude, Codex (quando API/licença permitir) e `llama.cpp` OpenAI-compatible, sempre ferramentas limitadas, aprovação humana e proteção de dados.
- Catálogo multivendor é **seed de reconhecimento**; nenhum comando de escrita ou OID não homologado pode ser assumido válido em todos os firmwares.

## Índice

| Documento | Uso |
|---|---|
| `docs/product/PRD_V2.md` | escopo completo, fases, critérios de aceite |
| `docs/architecture/ARCHITECTURE.md` | padrões, runtime, separação de módulos, HA e Edge |
| `docs/architecture/MODULE_CONTRACT.md` | contrato e governança de módulos |
| `docs/operations/SRE_ORCHESTRATION.md` | saúde, orquestração, deploy, rollback, DR |
| `docs/security/SECURITY_AND_APPROVALS.md` | tenants, LGPD, write gate, supply chain |
| `docs/engineering/DEVICE_CATALOG.md` | catálogo FTTx, drivers e matrizes de homologação |
| `docs/engineering/DRIVER_SDK_INTERFACE.md` | SDK de drivers e ensaios por firmware |
| `docs/architecture/TR069_TR369_INTEROP.md` | regras dual stack e controlador USP |
| `docs/operations/RELEASE_CENTER.md` | release/changelog de módulos, Edge e firmware |
| `contracts/postgres_baseline_draft.sql` | modelo PostgreSQL inicial sujeito a migrações revisadas |
| `docs/engineering/DEVELOPMENT_MEMORY.md` | wiki, memória local, ADRs, ciclos de agentes |
| `docs/erp/ERP_INTEGRATIONS.md` | integrações ERP em plug-ins |
| `docs/ai/COPILOT_SPEC.md` | roteamento LLM, RAG e supervisão |
| `docs/ux/UX_SPEC.md` | telas, personas, acessibilidade, tokens visuais |
| `docs/product/ROADMAP_BACKLOG.md` | sprints, épicos, DoD, milestones |
| `contracts/fibercore-v2.openapi.yaml` | contrato REST mínimo evolutivo |
| `configs/modules.yaml` | catálogo declarativo de módulos |
| `configs/catalog/` | templates de identificação e serviços |
| `infra/compose/compose.yaml` | compose do bootstrap API + banco + NATS |
| `starter/` | serviço API mínimo e testes demonstrativos |
| `legacy/` | materiais precedentes preservados sem alteração |

## Limites deste pacote

- O bootstrap incluído **não implementa** autenticação completa, controle real de tenants, conectividade GenieACS ou drivers de produção. Essas implementações são entregas das sprints e têm testes obrigatórios.
- Catálogo é projeto de perfil/capacidades; perfis de comandos reais exigem firmware, CLI/OIDs comprovados e fixtures de laboratório.
- Versões/imagens do Compose são **exemplos a congelar por digest após validação**.
- Metas de SLA, capacidade e cronograma são propostas a validar por benchmark. Compose não oferece sozinho atualização sem downtime nem recuperação automática ao estado healthy após toda falha.

## Adendo v2.1 — hostname público, design e ajuda por tela

- **Frontend oficial:** `https://fibercore.devops.k3gsolutions.com.br` (URL **planejada**, não confirma DNS/TLS/deploy). Help integrado `/ajuda`; API same-origin `/api/v1`.
- **UI:** minimalista, futurista, iOS-like, sem poluição. Regras completas em `docs/ux/DESIGN_SYSTEM_IOS_LIKE.md` e tokens em `configs/ui/design-tokens.json`.
- **Entrega funcional de qualquer tela = manual + capturas reais.** Gerar Playwright 1440×900 / 390×844, imagens em `docs/help/assets/`, how-to por funcionalidade e link contextual na UI. Testar `python tests/validate_help.py`. Não usar screenshot do mock Lovable como documentação final.
- **Deployment:** `docs/architecture/PUBLIC_ENDPOINTS.md`, `infra/deploy/Caddyfile.example`, `infra/deploy/PRODUCTION_CHECKLIST.md`. Publicação bloqueada enquanto scaffold `DEMO_MODE=true`/auth pendente.
- Leia também `prompts/05_FRONTEND_HELP_DELIVERY.md` para execução visual integrada ao Claude + Lovable + Codex.
