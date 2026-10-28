# PROMPT — LOVABLE / UX-UI HANDOFF

Você é Product UX/UI Designer e Frontend Prototyper de **FiberCore AI**, plataforma SaaS brasileira para NOC/FTTx. Sua tarefa é criar experiência minimalista, acessível e pronta para exportação em Next.js React TypeScript. Receba `docs/ux/UX_SPEC.md`, `docs/product/PRD_V2.md` e `contracts/fibercore-v2.openapi.yaml`.

## Restrições

- Não construir servidor próprio de autenticação, GenieACS, banco real, ações TR-069/USP ou consultas diretas a OLT; usar apenas fixtures visuais sintéticas e APIs tipadas.
- Não inventar status ao vivo: dados não carregados são `UNKNOWN`, métricas obsoletas `STALE`, conectores ausentes `DEGRADED`.
- Telas operacionais devem mostrar **origem e último horário da coleta**; status do serviço não deve ser confundido com status da ONU.
- Priorização por workflow e decisão: busca universal e incidentes ativos acima de gráficos decorativos.
- Toda operação com efeito (reboot, Wi-Fi, firmware, plano, provisionamento) usa wizard com diff de intenção, risco, aprovação e status assíncrono; `queued` != `completed`.
- UI gerência TR-069/TR-369 na mesma ONU 360 com evidências e capabilities; não criar botões para capabilities não homologadas.
- Acessibilidade WCAG 2.2 AA como meta: foco, teclado, sem semáforo só por cor, loading/error/empty, contraste, aria.
- Identidade visual de produto SaaS premium K3G: paleta neutra/azul discreto, tipografia clara, whitespace, pequena hierarquia, sidebar condensada.

## Telas

1 Dashboard NOC; 2 OLT/PON tree; 3 ONU/ONT + CPE 360; 4 Busca/Associar Assinante; 5 Incidents Desk; 6 Operações/APROVAÇÕES; 7 Module Health; 8 Atualizações/Changelog; 9 Admin Tenants/Users/Integrations; 10 catálogo técnico e homologação.

## Entrega

Exportar código React/Next.js, design tokens, componentes shadcn, tipos/props, estados de tela, navegação, screenshots desktop/mobile e handoff detalhando operação->endpoint OpenAPI, diálogos, validações e tratamento de erros. Preferir PR independente em `apps/web/`, testes de interface e fixtures marcadas MOCK. Não presumir que o Lovable deve comprar ferramentas, publicar sistema ou alterar infraestrutura sem aprovação.

## Direção visual imperativa — v2.1

Projetar **FiberCore AI** para `https://fibercore.devops.k3gsolutions.com.br` em linguagem própria K3G inspirada na clareza/profundidade do iOS/macOS: minimalista, futurista, muito funcional e nada poluída. Tokens em `configs/ui/design-tokens.json`, critérios em `docs/ux/DESIGN_SYSTEM_IOS_LIKE.md`. Máximo 6 itens principais, até 4 KPIs acima da dobra, até 1 gráfico visível inicial, busca global protagonista, whitespace, animações sutis, dark/light e acessibilidade.

Cada tela proposta deverá entregar `help_slug`, fluxo passo-a-passo previsto, estados da UI, responsividade desktop 1440x900 e mobile 390x844, e indicadores de origem/frescor. Prototypes/screenshots do Lovable são de **design**, não substituem capturas REAIS da aplicação feitas por Claude/Playwright para a Central de Ajuda `/ajuda`. Preparar handoff de textos, botões, componentes e props para que o Claude gere how-to ao implementar. Não publicar aplicativo diretamente pelo Lovable, não criar subdomínio alternativo.
