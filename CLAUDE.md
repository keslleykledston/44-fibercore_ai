# FiberCore AI — contexto do projeto (44-FiberCore)

K3G OLT SaaS / FiberCore AI. Stack alvo: FastAPI + PostgreSQL + NATS + Edge Go + Next.js.
Estado: kit de planejamento v2 (2026-10-27). Nada de produção. Hardware não validado.
Repo remoto alvo: `keslleykledston/120-OLT_SaaS` (esta pasta ainda NÃO é repo git).

## Ler ao iniciar (ordem)
1. `.agent-context/PROJECT_STATE.md`
2. `.agent-context/NEXT_ACTIONS.md`
3. `.agent-context/WORK_SESSION_LOG.md`
4. Kit completo: `FiberCoreAI_BuildKit_v2_Claude_Codex_Lovable.zip` (extrair em pasta própria; não executar nada dele sem ler).

## Caveman (PT-BR)
- Respostas curtas, diretas, sem preâmbulo, sem recap. Comando pronto > explicação.
- Português com acentuação correta sempre. Cortar artigos/enchimento, não diacríticos.
- Código, comandos, paths, identificadores: intactos, nunca "encurtados".
- Formato: `[problema] → [causa] → [ação]`. Bullets > parágrafos. Tabela só se comparar.
- Sair do caveman (prosa clara) em: aviso de ação destrutiva/irreversível, confirmação "CONFIRMO", segurança, instrução em múltiplos passos onde ambiguidade causa erro. Depois volta.
- Testes e evidência mandam. Sem "PASS" sem rodar. Incerteza declarada, estado não inventado.
- Commits/PRs/código: escrever normal, sem caveman.

## Segurança
- `.env` tem credencial GenieACS. Nunca ler/ecoar valores, nunca enviar a Lovable/MCP/ai-memory.
- Dispositivos reais: read-only por padrão. Escrita = política + preview + aprovação + pós-check + auditoria.
- Sem push, sem tag, sem comando destrutivo sem ordem explícita.
- GenieACS existente: só via NBI por Edge privado. Não instalar outro.

## Memória (ai-memory)
- Hooks já capturam prompts/tools. Não escrever notas de rotina.
- Antes de decisão de arquitetura/subsistema: `memory_query` primeiro.
- Decisão durável (ADR, regra, gotcha) → `memory_write_page` (H1 na 1ª linha do body).
- Fim de sessão / pedido de salvar contexto → `memory_handoff_begin` (resumo curto; detalhe em `next_steps`/`open_questions`).
- Estado vivo do projeto: atualizar `.agent-context/*.md` ao fim de cada marco (arquivo = fonte local; ai-memory = histórico).

## Compactação (Compact Instructions)
Ao compactar, PRESERVAR obrigatoriamente:
- Objetivo atual e sprint/fase; decisões tomadas e motivo.
- Arquivos criados/alterados (paths) e comandos que funcionaram ou falharam (com erro curto).
- Regras de segurança acima e modo caveman PT-BR.
- Pendências abertas e próxima ação exata.
- Resultados de testes (comando + PASS/FAIL).
DESCARTAR: saídas longas de ferramentas, listagens, conteúdo de arquivos já salvos em disco.
Antes de compactar manualmente (`/compact`): atualizar `.agent-context/WORK_SESSION_LOG.md`.

## Fluxo
Claude implementa → Codex revisa (read-only; CRITICAL/HIGH bloqueia) → Lovable só UX (nunca segredos).
Backend/API/DB/segurança/infra: local com Claude. Lovable: UI/dashboards em lote.
