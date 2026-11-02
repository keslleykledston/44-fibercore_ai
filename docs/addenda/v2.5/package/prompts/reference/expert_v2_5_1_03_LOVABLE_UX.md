# PROMPT — Lovable UX v2.5.1

Produza apenas handoff de UX/React reutilizável do Profile Expert Editor dentro do Profile Studio v2.5; preserve layout iOS-like minimalista, acessibilidade e design tokens existentes.

Fluxos-chave: OLT → Profiles → Importar referência; Catálogo → Editar em Modo Especialista; seleciona fonte; clona draft; altera campos de capability; compara semanticamente e por OLT; preview; aprovação/migração em jornada separada.

Desktop: fonte/versões à esquerda, editor central, diff/impacto à direita. Mobile: Fonte / Editar / Diferenças. Views N1/N2 não mostram complexidade N3.

Demonstre estados: snapshot stale, dado não observável, profile compartilhado, ID em conflito, incompatibilidade firmware, capability desconhecida, drift, dry-run bloqueado, execução PARTIAL/UNKNOWN. Mostrar referência atual e futura sem copiar CLI proprietária para campo executável.

Handoff com componentes, validações, tokens, acessibilidade, states e exemplos sintéticos; não produzir screenshots fingindo ser da UI em execução. Preparar roteiros Playwright para screenshots verdadeiras e manuais `/ajuda` após implementação.
