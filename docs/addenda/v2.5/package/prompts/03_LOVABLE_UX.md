# PROMPT LOVABLE — UX OLT Profile Studio + Expert Mode

Desenhe handoff UX (componentes exportáveis React/shadcn/Tailwind) para FiberCore AI em `https://fibercore.devops.k3gsolutions.com.br`.

Consolide **um só módulo** com caminhos:
- `Rede → ONUs pendentes`: tabela elegante com OLT/PON/SN/last seen/status, filtros, vínculo cliente HubSoft e drawer direito com miniatura ONU.
- `Rede → Profiles`: catálogo, wizard assistido de 5 passos e cards por serviço; campos liberados por capability, feedback simples e default somente leitura/dry-run.
- `Rede → Profiles → Modo Especialista`: N3 importa profile nativo (somente leitura), visualiza contagem de ONUs vinculadas, clona, edita por formulário avançado ou YAML/JSON tipado, compara versão antiga/nova por semântica e impacto por OLT. Incluir fonte/revision/status, ETag collision, blocked/unknown, `reuse/adopt/clone/migration` e prévia dos comandos só leitura.
- `Operações → Jobs`: timeline approval, apply, verify, partial/unknown e evidências (reusar existente).

Visual iOS-like minimalista, sem efeitos gratuitos. Navegação progressiva N1→N3 por permissão, responsivo, acessível teclado, temas claro/escuro, compactação de campos complexos por acordeões. Não oferecer botão `Aplicar em todas OLTs` e nem terminal livre. Priorizar: Importação de profile → Clone → Editor → Diff → Preview → Publicar no catálogo. Publicar ≠ executar.

Entregar wireframes desktop/mobile, mapa de componentes, states loading/error/stale/unknown/conflict/blocked, texto em pt-BR e critérios Playwright. Não alegar que telas são capturas reais até implementadas. Handoff deve integrar no Next.js existente, sem refazer shell global.
