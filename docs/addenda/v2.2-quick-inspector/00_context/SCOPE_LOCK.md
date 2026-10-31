# ESCOPO TRAVADO — ONU Quick Inspector

## In scope (P0)
- `EntityDetailDrawer` direito existente (ou equivalente real), reaproveitado para ONU/ONT.
- Abrir por seleção de linha/cartão/árvore; trocar ONU sem sair da página; fechar/recolher; teclado e responsivo.
- `DeviceSummary`, `DataFreshness`, `StatusPill`, breadcrumb, tokens atuais; sem um segundo shell ou roteador.
- Miniatura SVG genérica local e leve; fabricante/modelo conhecido só se existir template **homologado**.
- Resumo: identificador (serial parcialmente mascarado quando pertinente), status PON, estado do ACS, último dado, OLT/PON, potência RX quando disponível, cliente quando autorizado e associação confiável.
- `Abrir ONU 360°` com navegação contextual e preservação de busca/filtros.
- Read-only; uso das APIs/seletores/cache e modelo de permissão preexistentes; testes, ajuda contextual e capturas reais.

## Outside scope explícito
- Nova plataforma, novo microserviço, nova tabela para uma feature de UI, novo banco ou novo sistema de eventos.
- Nova tela ONU 360°, nova arquitetura ACS/USP, novo conector HubSoft/ERP, módulo completo de Device Visual Library.
- Inventário físico 3D, digital twin, configuração SSID/LAN/firmware, reboot, provisionamento ou execução de ações remotas.
- LLM analisando/acionando CPE: só botão de navegação contextual **quando** fluxo real estiver implementado/autorizado.
- Promessa de tempo real quando a coleta disponível é polling; não inventar status, tempos, métricas, cliente ou suporte do modelo.

## Reuso obrigatório
- Next.js/React/TypeScript/shadcn/Tailwind e tokens do projeto.
- `AppShell`, `CompactSidebar`, `EntityDetailDrawer`, `DeviceSummary`, `StatusPill`, `DataFreshness`, `HelpContextLink` (ou equivalentes confirmados por grep).
- Fontes: OLT via Edge/driver, ACS via GenieACS NBI Edge, futuro USP por adapter, associação cliente/ERP HubSoft apenas quando homologado.
- Auth/RBAC/RLS server side e filtragem por tenant *no servidor*.

## Regra de não regressão
1. Inventário, árvore PON, filtros, ordenação, paginação, scroll virtual, links e Visão 360° seguem funcionando.
2. O drawer NÃO captura navegação global nem bloqueia fluxos de NOC no desktop.
3. O usuário não verá ações de escrita novas. Tudo write continua no fluxo existente de autorização/auditoria.
4. Falha de ACS/ERP não implica ONU offline e não derruba o inventário.
5. Dados sem frescor/sem observação não se convertem em verde/online.

## Baseline pesquisada
Documentos de contexto: `01_CLAUDE_CODE_MASTER.md` e `DESIGN_SYSTEM_IOS_LIKE.md` do acervo do projeto; documentação PRD nuclear. GitHub `keslleykledston/120-OLT_SaaS` consultado em 2026-10-30: repo público **vazio** na consulta (não comprova inexistência de código local/privado). A primeira tarefa do agente é **verificar o código REAL**.
