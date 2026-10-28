# Proposta de UX do Lovable (DEMO) — referência de revisão

- Projeto Lovable: `13aaf09e-023f-464e-8651-190d6d928dfc` (workspace do proprietário; preview: https://id-preview--13aaf09e-023f-464e-8651-190d6d928dfc.lovable.app). Commit da proposta: `dcdc11d82b951ce0c76a313108e844b6308f6134`. Custo: 18,8 créditos.
- Escopo recebido: 9 telas (Login/workspace, Visão Geral, Rede, ONU 360, NOC, Assinantes, Operações, Módulos, Ajuda), tema claro/escuro, seletor global de estado DEMO (normal/carregando/vazio/defasado/erro/403), componentes `AppShell`, `GlobalSearch (⌘K)`, `StateGate`, `WriteActionButton` (sempre bloqueado com motivo "Operação não homologada"), `ApprovalTimeline`, `IncidentQueue`, `ModuleHealthTable`, etc. Documento do Lovable: `docs/UX-PROPOSTA.md` no projeto deles.
- **Verificação do próprio Lovable:** só Visão Geral, Rede, NOC e Operações (desktop/mobile) e busca Ctrl+K; **tema escuro, demais telas, estados alternativos e WCAG AA NÃO verificados** — nada disso foi aceito por nós como evidência.
- Nada do código Lovable foi importado ao repositório (é uma proposta; screenshots finais vêm da aplicação integrada).

## Decisões de integração
| Item da proposta | Decisão |
|---|---|
| Ordenação da fila NOC por (não reconhecido, severidade, impacto); edge silencioso nunca acima de queda crítica | **Adotado** em `apps/web/src/app/noc/page.tsx` |
| Edge silencioso ≠ offline; "último estado conhecido" | Já implementado (E2E cobre) |
| Escrita sempre bloqueada com motivo visível | Adotar nas telas de Operações/ONU 360 (W8) |
| ⌘/Ctrl+K busca global | Pendente (W10: atalho; hoje a busca da topbar é por serial) |
| ONU 360, Assinantes, Operações, Login multi-passo | Pendentes (W8); usar a proposta como referência visual |
| Seletor de estado DEMO | Não adotar em produção (somente fixture de teste) |
