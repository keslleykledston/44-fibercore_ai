# FiberCore Copilot — arquitetura provider-agnostic e humano no comando

## Objetivo

Acelerar diagnóstico de colaborador de NOC, atendimento e campo **sem** privilegiar Gemini, Claude, Codex ou `llama.cpp`. A escolha depende de capacidade real de tool calling, custo, latência, dados, contexto e disponibilidade; modelos substituíveis via `LLMProvider` com adaptadores e testes.

## Modelo de execução

`Human intent -> Intent Classifier (determinístico) -> Auth/Tenant -> Retrieval (RAG: runbooks, wiki e dados operacionais) -> LLM Gateway -> Proposed Plan + cited evidence -> Policy Engine -> Approval -> Typed Job Executor`.

O modelo **nunca** conecta diretamente a OLT, NBI, USP ou banco com privilégios; usa ferramentas API com schema tipado. Inicialmente **somente ferramentas read-only**: `get_customer_context`, `get_onu_snapshot`, `get_pon_peer_summary`, `get_active_incidents`, `search_runbooks`, `explain_association`, `get_module_health`. Tools de escrita entram em catálogo apenas para formular proposta, não podem executá-la sem Gate humano separado.

## Providers

- `LlamaCppOpenAICompatible`: endpoint local de `llama.cpp`, fallback OFF por padrão; verificar resposta JSON/tool schema por modelo; limite de contexto/admissão e desativação se tool calling falhar.
- `AnthropicClaude`: credenciais do tenant/plataforma sob política, uso por consentimento e finalidade.
- `GoogleGemini`: adapter com schemas e política equivalente.
- `OpenAI/Codex`: adapter quando houver API apropriada e autorização; *Codex como supervisor de desenvolvimento é papel diferente do copiloto runtime*.
- Model registry por capability: `tool_call`, `structured_json`, `context_window`, `privacy_tier`, `cost`, `latency`, `enabled_for_tenant`, `last_eval`.

## RAG e memória

- Fonte oficial: runbooks versionados, catálogo homologado, ADRs e documentação técnica do próprio tenant; nunca indexar segredos nem dados brutos sensíveis.
- Chunk com `tenant_id`, tipo, revisão, autor, timestamp, ACL e URL interna; retrieval com filtro por tenant e papel antes de ranqueamento.
- Resposta traz citações internas e fresco timestamp, separa `observed`, `inferred`, `unknown`; prompt injection de logs, descrições ONU, tickets e webhooks é conteúdo não confiável.
- Memória conversacional operacional por ticket/tenant com retenção configurada, sem reutilização entre tenants e sem acesso ao memory de desenvolvimento (que é outra coisa).

## Guardrails, fallback e métricas

- Falha LLM mantém funções NOC e diagnóstico determinístico.
- Redação PII, segredos e Wi-Fi passwords antes do prompt; eventual modelo remoto somente com aprovação contratual/política de dados.
- Rate limit, quotas/cost budget por tenant, kill switch, tracing sem prompt sensível em logs, revisão humana para decisões críticas.
- Avaliações: groundedness, citações válidas, falsas causas prováveis, tool-call accuracy, leakage de tenant, prompt injection, latência, custo, satisfação colaborador.

## 4 modos iniciais

NOC: sumarizar alarmes/incidentes; Suporte: explicar diagnóstico e produzir texto para CRM; Campo: checklist de CTO/PON; Engenharia: comparar thresholds/firmware/capacidade. O usuário recebe sempre causa provável com indicador de confiança, não certeza fabricada.
