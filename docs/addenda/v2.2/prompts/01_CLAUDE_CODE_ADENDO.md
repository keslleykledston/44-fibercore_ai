# PROMPT PARA CLAUDE CODE — ADENDO EVOLUTIVO v2.2

Você continuará o projeto **FiberCore AI** exatamente do checkpoint atual do repositório. Este material é um **incremento de roadmap**, NÃO uma ordem para recriar a plataforma, substituir arquivos atuais ou abandonar a sprint em andamento.

Leia `README.md` deste adendo e as especificações em `docs/`. Compare com `CLAUDE.md`, `AGENTS.md`, PRD v2.1, ADRs, OpenAPI real, backlog, status e componentes existentes. Antes de qualquer alteração, faça `git status`, identifique branch/commit e registre numa matriz `requisito novo | já existe | parcialmente existe | falta | conflitos | dependências | decisão`.

## Objetivo
Adicionar progressivamente os diferenciais observados no benchmark: Subscriber 360, Diagnóstico Guiado N1, NOC Command Center, Device Capability Registry, Network Explorer, Wi-Fi Experience, workflows declarativos/Automation Studio, Health/Update Center, camada API Customer Context, QoE Scores e contratos de copiloto read-only.

## Ordem obrigatória de implementação
1. **Sem interromper a sprint atual**: converter adendo em ADR(s), issues FC22-001...FC22-018 e backlog com dependências; não marcar features como prontas.
2. Priorizar `Capability Registry` + `Data Freshness` + `Customer Context API` e `Subscriber 360`: dados com fonte, timestamp, confiabilidade e escopo tenant.
3. Criar `Diagnostics Rule Engine` determinístico + UI Guided Troubleshooting e NOC Command Center.
4. Adicionar Network Explorer, Wi-Fi Experience/QoE e catálogo de intenções por capability; declarar como `unknown` quando faltarem medições.
5. Workflow Studio versão 1 com templates versionados, simulação, políticas e approval; firmware massivo, alteração Wi-Fi e provisionamento real continuam bloqueados sem homologação por modelo+firmware.
6. Expor APIs de leitura/documentação úteis para integrações ERP e ferramenta de copiloto no futuro, sem LLM com escrita direta.

## Regras técnicas
- Monólito modular FastAPI nos domínios atuais; novos deployables apenas quando houver requisito de isolamento/escala provado. Docker modular com readiness, métricas e degradação isolada.
- GenieACS segue como ACS TR-069; TR-369 por controlador distinto. A mesma ONT dual-stack deve ter identidade única e bloqueio de comandos concorrentes.
- Nunca invente parâmetros TR-181, OIDs, comandos Huawei/ZTE etc. Capability depende de autodetecção, docs, fixture e homologação; status `identified`, `observed`, `certified`.
- Não confundir perda de contato com Edge/GenieACS/USP e ONU offline. Scores só publicados com cobertura mínima, fórmula versionada e dados frescos; caso contrário `insufficient_data`.
- Erros, falta de dados, incidentes e recomendações devem conservar evidências e provenance. Correlação é hipótese até confirmação.
- Reutilize schemas, auth, RBAC, job engine e filas atuais. A spec `contracts/fibercore-v2.2-additive.openapi.yaml` é aditiva/proposta; reconciliar caminhos com API atual, evitar duplicar endpoints.
- Frontend oficial `fibercore.devops.k3gsolutions.com.br`; UX premium iOS-like própria, minimalista, sem excesso de cards/gráficos; navegação com até seis grupos.

## Help-by-construction obrigatório
Cada tela implementada deve incluir `help_slug`, manual How-to em PT-BR, capturas Playwright **REAIS da aplicação integrada** em desktop 1440x900 e mobile 390x844 com dados sintéticos, manifesto de imagens atualizado e revisão Codex. Nunca usar screenshot do protótipo Lovable como captura operacional. Mudanças em telas exigem atualização de prints/manual no mesmo PR.

## Controle de agentes e memória
- Claude Code implementa; Codex supervisiona com revisão por diff, testes e bloqueios; Lovable desenha/entrega componentes exportáveis, sem back-end próprio.
- Registre progresso e limitações em `docs/wiki/` ou wiki vigente, ADR, CHANGELOG, `memory/CURRENT` ou `.agent-context`, runbooks e guia de usuário; mantenha links para commits.
- Sem credenciais nos prompts, screenshots, exemplos ou logs. Sem deploy público enquanto autenticação/RLS/TLS não estiverem homologados.

## Sua primeira entrega nesta solicitação
Produza **um PR de planejamento de integração v2.2**: inventário de estado atual, matriz de gaps, ADR(s), backlog, contrato API reconciliado, mapa de telas/componentes e desenho de testes. Depois execute a **menor vertical slice P0 compatível com a sprint atual**, com mock, teste, wiki e parecer Codex. Informe commit, testes realmente executados, pendências e próximo passo. Não declare pronto o que foi apenas especificado.
