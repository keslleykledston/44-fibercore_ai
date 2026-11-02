# ADR-025 — Modo Especialista no mesmo Profile Studio

**Estado:** proposta a conciliar com ADRs do repositório, não aprovada automaticamente.

**Contexto:** wizard N1 reduz complexidade, mas engenharia precisa adaptar templates a profiles legados de OLTs existentes, evitando sobrescrever configurações compartilhadas.

**Decisão:** um único catálogo de service intents + um único backend de reconciliador e jobs, com duas projeções de UI: `Assistido` e `Modo Especialista`. Fonte OLT importada como snapshot imutável, edição N3 em clone tipado versionado, diff semântico por alvo, binding físico específico e clonagem em vez de alteração in-place. Parser nativo versionado pode extrair propriedades conhecidas e preservar linhas não interpretadas como dados inertes. Um preview de CLI pode ser gerado pelo driver apenas para conferência humana, **nunca usado como passthrough de execução**.

**Alternativas rejeitadas:** editar profile live por CLI arbitrária, replicar template em todos os OLTs por ID, confiar em nome, configurar o ACS em vez da OLT, gravar alterações sem aprovação, IA com permissão implícita de escrita.

**Consequências:** drivers exigem read + normalize + compile separados e testes por firmware/cartão, implementa-se gradualmente; migração de ONUs é workflow independente e pode requerer janela de manutenção.

**Critério de reversão:** feature flag de escrita OFF, read-only sempre utilizável; qualquer problema em produção congela writes e reconcilia evidências sem reexecução cega.
