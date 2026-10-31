# FiberCore 2.2 — ONU Quick Inspector | Handoff de implementação

**Tipo:** adendo UX/UI incremental, não nova versão ou mudança do núcleo.  
**Emissão:** 2026-10-30 | **Idioma:** pt-BR | **Estado:** proposta pronta para implementação, NÃO implementada.  
**Objetivo:** sidebar direito recolhível que mostra dados essenciais de ONU/ONT, miniatura com estados fundamentados e navegação para a **Visão ONU/ONT 360°** existente.

## INÍCIO RÁPIDO — agente implementador

1. Leia `00_context/SCOPE_LOCK.md` e `00_context/DECISIONS_AND_DEPENDENCIES.md`.
2. Inspecione o repositório/código REAL em execução (`git status`, árvore, rotas, componentes, design tokens, contratos, permissões, fixtures, documentação). **Não presumir** que o GitHub público indicado tem código: consulta feita em 2026-10-30 retornou repositório vazio.
3. Leia `01_product/*`, `02_ux/*`, `03_architecture/*` e `04_contracts/*`.
4. Use `07_preview/index.html` para validar a ideia (protótipo OFFLINE com dados fictícios, NÃO código de produção). Use `06_reference/*` como referência adaptável, não substitua o frontend existente.
5. Execute **PRs pequenos** conforme `09_delivery/IMPLEMENTATION_PLAN.md` e siga o prompt em `10_prompts/CLAUDE_CODE_IMPLEMENT.md`.
6. Submeta diffs ao Codex com `10_prompts/CODEX_REVIEW.md`; entregue handoff UX ao Lovable com `10_prompts/LOVABLE_UX_HANDOFF.md`.
7. Gere screenshots **reais da aplicação integrada**, manuais/how-to, changelog e evidências do PR conforme os gates atuais.

## CONTEÚDO DO PACOTE

| Pasta | Conteúdo |
|---|---|
| `00_context` | Limites de escopo, decisões e precedência |
| `01_product` | PRD, stories e aceite |
| `02_ux` | Interações, hierarquia, estados, acessibilidade, copy |
| `03_architecture` | Reuso de componentes e dados, segurança, ADR proposta |
| `04_contracts` | Schema do view model e OpenAPI *opcional* de composição |
| `05_fixtures` | Fixtures sintéticas para testes e prototipagem |
| `06_reference` | Tipos e componente React/SVG de referência sem backend fictício |
| `07_preview` | Protótipo HTML interativo e offline |
| `08_qa` | Matriz e cenários E2E, verificador de fixtures |
| `09_delivery` | Plano de PRs, QA/release, documentação |
| `10_prompts` | Prompts entregáveis aos agentes Claude Code, Codex, Lovable |

## AUTORIDADE E LIMITAÇÕES

- Precedência **já definida** no projeto: segurança/contratos > ADRs aprovadas > PRD v2 > contrato API v2 > backlog > exemplos > legado.
- Este handoff é **subordinado** aos documentos vigentes. Se houver conflito, interromper o trecho afetado, registrar divergência e propor ADR curta, sem alterar contratos arbitrariamente.
- Sem implantação, acesso a dispositivos reais, manobras, chamadas externas ou alterações em produção neste pacote.
- Os valores de status, RX, identificadores e nomes em fixtures e preview são inteiramente **fictícios**.

## Critério de sucesso

Em no máximo 1 clique na ONU de uma lista/árvore operacional, o usuário vê: **qual ONU**, **estado PON**, **estado ACS separado**, **frescor dos dados**, **cliente quando autorizado**, **referência OLT/PON**, e **caminho para ONU 360°** — sem perder filtro, seleção ou contexto.
