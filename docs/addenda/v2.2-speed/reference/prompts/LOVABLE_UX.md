# PROMPT UX — LOVABLE (ESPECIFICAÇÃO, NÃO REWRITE)

Trabalhe apenas no visual/experiência da seção `Teste de banda` do drawer direito já existente no FiberCore 2.2 (`EntityDetailDrawer` / ONU 360), no domínio `https://fibercore.devops.k3gsolutions.com.br`.

Use `docs/05_UX_E_COPILOTO.md`, `contracts/openapi.fragment.yaml`, `fixtures` e `preview/index.html` como referências de UX/contrato. NÃO alterar backend nem inventar ações, métricas ou dispositivos. Sem nova página/dashboard, sem nova identidade visual ou nova infraestrutura. Preservar design iOS-like minimalista, componentes e tokens existentes.

Objetivo visual: ao selecionar ONT mostrar seção compacta, destino Core/Internet, botão Iniciar, status sequencial download/upload, KPIs 2 colunas (DL e UL), confiabilidade, aviso `Mede WAN da ONT, não Wi-Fi`, histórico recolhível. Tratamento claro para unsupported, partial, erro, timeout, sem permissão e sem interface WAN comprovada. Drawer continua operável e recolhível, sem tomar toda tela desktop.

Entregue: mapa de estados, diferenças responsive desktop/mobile, microcopy, lista de componentes reais reutilizados e storyboard de capturas. Material visual é protótipo até o Claude Code conectá-lo à API real. Screenshots finais da ajuda devem ser gerados na implementação real, não nesta etapa.
