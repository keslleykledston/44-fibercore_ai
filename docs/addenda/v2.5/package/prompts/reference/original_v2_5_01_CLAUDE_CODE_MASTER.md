# PROMPT MESTRE — Claude Code — FiberCore AI v2.5 OLT Provisioning & Profile Studio

Você é o implementador principal. Leia `README_START_HERE.md` e o adendo v2.5 inteiro, correlacionando com v2.1/v2.2/v2.3.1 HubSoft-first/v2.4 ONT Config. **Não reinicie o projeto ou substitua o que já existe.**

1. Faça inventário do repo/sprints/código efetivo e relatório GAP com caminhos/classes; não afirme recurso existente só porque está previsto em PRD. ADRs e diff proposto antes de arquitetura compartilhada.
2. Crie bounded context `olt-provisioning` como módulo dentro do FastAPI modular e componente Next.js dentro de Rede; reaproveite Postgres+RLS, Edge Go, Capability Registry, Inventory, HubSoft-first Customer Context, Jobs/Approvals, NATS/outbox e Help.
3. Desenhe interfaces tipadas de OLT driver, extensíveis por vendor/versão/cartão PON. **Nada de executar comandos crus vindos de frontend ou LLM**.
4. Entregue primeiro Discovery Read-Only e fila de ONUs pendentes, com `STale/Unknown` distinto de `offline`, dedup, timestamps e ligação HubSoft assistida.
5. Implemente Service Profile Studio com wizard de cartões/seleções, `Simple` inicial e `Avançado` progressivo; Schema JSON versionado e validação de `compatibility`; retornos por OLT do reuso/criação de DBA/line/service etc. Via dry-run, zero writes.
6. Implemente wizard Autorizar ONU (identificar→serviço→conferir→aprovar/executar) e workflow assíncrono aprovado somente depois da certificação em LAB do driver e do equipamento. Escrever em OLT real de cliente apenas com autorização explícita e release gate independente.
7. Distinga templates comerciais, profiles lógicos e profiles físicos por OLT; nunca sobrescreva perfil compartilhado; use hash, locks, approval, TTL e compensação segura. Não suponha modelo/portas pela SN pré-registro.
8. Pilotar Huawei MA5608T V800R015 com firmware/card confirmados; drivers ZTE/FiberHome/Nokia/Datacom somente quando comprovados, sem CLI copiada de vendor diferente.
9. Trate reconciliação com HubSoft em read-only, sem bloquear leitura se ERP cair; bloqueie escrita em ambiguidade. ONT Configuration Manager/GenieACS só participam de configuração CPE e pós-check, não autorizam PON.
10. Entregue migrations, OpenAPI aditivo, mocks, testes cross-tenant/TOCTOU/drift/dual-path locks, observabilidade, help e screenshots reais Playwright. Revisor Codex deve dar PASS e Lovable revisar UX.

Primeira entrega: (A) relatório GAP; (B) ADRs; (C) backlog integrado; (D) PR de interfaces tipadas e discovery read-only + fixtures + testes. Sem claims de deployment/testes não executados. Preservar `https://fibercore.devops.k3gsolutions.com.br` e central `/ajuda`.
