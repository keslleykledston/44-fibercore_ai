# FiberCore AI — Adendo Incremental v2.2: Benchmark ACS / Operações FTTH

Data: 2026-10-28. **Este pacote é um PATCH de requisitos e implementação FUTURA**, não uma instalação pronta nem substituto dos materiais v2.0/v2.1.

## Objetivo
Incorporar lições do benchmark Axiros AXESS ACS, Friendly Technologies, Incognito, Adtran Mosaic One, UISP e AVSystem, sem copiar interfaces/artefatos protegidos e sem elevar o escopo da sprint atual sem revisão.

## Instrução de integração
1. Copie `docs/`, `contracts/`, `catalog/`, `examples/` e `checklists/` do adendo para `docs/addenda/v2.2/` ou uma pasta rastreável equivalente, preservando todos os documentos anteriores. Não sobrescreva `CLAUDE.md`, `AGENTS.md`, prompts e contratos existentes automaticamente.
2. Leia `prompts/01_CLAUDE_CODE_ADENDO.md` e envie ao executor.
3. Gere **diff e matriz de conflitos** com PRD v2.1, OpenAPI vigente, backlog e módulos implementados; proponha ADRs, issues e etapas antes de codificar.
4. Codex avalia cada PR com `prompts/02_CODEX_REVIEW.md`; Lovable recebe `prompts/03_LOVABLE_UX.md` e `docs/ux/UX_HANDOFF.md`.
5. Implementar em *vertical slices*: API + DB + mock + UI + teste + manual + screenshots reais + revisão. Nunca passar um benchmark declarado como capacidade já comprovada do nosso sistema.

## Constantes da plataforma
- Frontend: `https://fibercore.devops.k3gsolutions.com.br`
- API pública prevista: `/api/v1`; Central de Ajuda: `/ajuda`.
- GenieACS instalado no ISP: TR-069/CWMP via NBI privada acessada pelo Edge outbound.
- TR-369/USP: controlador independente por adaptador, homologação obrigatória.
- Cloud: FastAPI, Next.js, PostgreSQL, filas/outbox, Docker Compose inicial, K3s mediante requisitos HA reais.
- LLM nunca realiza escrita direta na rede; política read-only por padrão.
- Identidade multitenant, freshest data e source provenance são obrigatórios.

## Conteúdo
- `docs/product/BENCHMARK_TO_FEATURES.md`: rastreabilidade de diferenciais por produto.
- `docs/product/PRD_ADENDO_V2_2.md`: requisitos, jornadas, não objetivos, aceite.
- `docs/product/BACKLOG_V2_2.md`: épicos e issues incrementais, dependências e priorização.
- `docs/architecture/DOMAIN_DESIGN.md`: módulos e contratos, eventos e ownership.
- `docs/architecture/MIGRATION_PLAN.md`: integração segura com o que já existe.
- `docs/engineering/DIAGNOSTIC_AND_QOE.md`: regras determinísticas e scores explicáveis.
- `docs/ux/UX_HANDOFF.md`: fluxo, navegação, componentes, telas, documentação visual.
- `contracts/fibercore-v2.2-additive.openapi.yaml`: **contrato proposto**, não substitui a spec vigente.
- `contracts/events.v2.2.schema.json`: evento universal de mudanças observadas.
- `catalog/capability-profile.example.yaml`: template sem alegação de compatibilidade comercial.
- `examples/`: payloads estritamente sintéticos.
- `docs/help/HOWTO_SPEC.md`: how-to e captura automatizada.
- `docs/quality/ACCEPTANCE_MATRIX.md`: qualidade e testes de regressão.

## Fontes públicas para pesquisa e confirmação posterior
https://pt.axiros.com/products/axess-acs
https://friendly-tech.com/tr-069-tr-369-device-management-v2/
https://www.incognito.com/solutions/digital-experience
https://www.adtran.com/en/products-and-services/mosaic-one
https://uisp.com/
https://avsystem.com/unified-device-management-platform/features/

**Aviso:** Comparação funcional é inspiração de produto, não certificação de paridade com fornecedores. O Claude deve confirmar datasheets/APIs oficiais antes de alegar integração ou compatibilidade.
