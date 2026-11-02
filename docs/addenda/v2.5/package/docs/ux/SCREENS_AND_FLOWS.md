# Especificação de telas e fluxos — Lovable e Next.js

**Design:** minimalista iOS-like, visual limpo, elementos de alto contraste e ações explícitas. Priorizar semântica e acessibilidade, não animações excessivas. Reutilizar sidebar direito com miniatura ONU do v2.4.

## Navegação
`Rede → ONUs pendentes` (N1/campo), `Rede → Templates e Profiles` (wizard), `Rede → OLTs → [OLT] → Profiles existentes`, `Operações → Jobs/Aprovações` (módulos existentes). `Modo Especialista` aparece apenas para N3 autorizado.

## T1 — Fila de ONUs pendentes
Filtros por POP/OLT/PON/idade, serial com mascaramento por papel, detecção duplicada, associação HubSoft/OS, `STALE`, last seen, indicação `Aguardando associação`, `Pronta para revisão`. Ação `Preparar autorização`, não executar diretamente. Lateral com miniatura do equipamento e detalhes observados, nunca inferidos.

## T2 — Wizard de autorização
Passos: 1 Identificar OLT/PON/ONU; 2 Associar cliente/OS; 3 Escolher serviço/template certificado; 4 Revisar diff/impacto e riscos; 5 Solicitar autorização e monitorar job. Sem CTA ativo quando driver, dados ou associação desconhecidos.

## T3 — Studio assistido
Cartões: Internet Bridge, ONT roteada, Empresarial, IPTV/VoIP (suporte por firmware). Campos: VLAN, marcação, porta, PPPoE/IPoE, QoS owner, velocidade *referência*; modelo ONU e destinos. Avisos de capacidades por alvo. `Salvar rascunho`, `Comparar existentes`, `Simular`.

## T4 — Profile Expert Editor (N3)
- Header: `Perfil / Revisão`, fonte e estado, firmware/placa, data da observação, CTA `Voltar ao assistido`.
- Esquerda: seletor de OLT, profiles nativos, templates catalogados, histórico e contagem de ONUs vinculadas.
- Centro: abas `Formulário` / `YAML-JSON` do objeto tipado; grupos DBA, T-CONT/GEM, VLAN/QinQ, service-port, QoS, ONU ports e driver extension. Foco em campos disponíveis.
- Direita: **diff semântico e impacto**, classificação por alvo (Reuse/Clone/Blocked), reasons, preview. Código nativo gerado é opcional e **read-only** para engenharia.
- Footer: `Importar referência`, `Criar variante`, `Salvar rascunho`, `Comparar`, `Simular` e `Solicitar publicação`. Nenhum CTA `Aplicar em todas`.
- Mobile: `Fonte | Editor | Diferenças` sequenciais. Gate de aplicação de alto risco conforme RBAC.

## T5 — Resolução de conflitos e migração
Diferença entre templates, profiles já em uso, contagem de assinantes impactados; opções `Reutilizar` / `Vincular como referência` / `Criar nova variante` / `Planejar migração separada`. Destaque: **não alterar profile compartilhado**.

## T6 — Job e pós-verificação
Timeline `PREVIEW → APPROVED → QUEUED → PREPARING → APPLYING → VERIFYING → VERIFIED/FAILED/PARTIAL/UNKNOWN`. Relatório por OLT, evidência, tentativas autorizadas, avisos e recomendações de reconciliação.

## Estados obrigatórios de todas as telas
Loading, Empty, ERROR, STALE, UNKNOWN, Edge offline, permissões insuficientes, conflito firmware/placa, snapshot divergente, profiles em uso, quantidade de referências desconhecida, ações bloqueadas. Erro tem causa compreensível e próxima ação. Não usar semáforo verde só porque dispositivo não respondeu.

## Central de ajuda
Documentar: descoberta de ONU, vinculação HubSoft, autorização, criar template, importar profile, comparar, clonar, editar avançado, publicar versão, simular e planejar migração. Playwright com fixtures, capturas reais desktop 1440×900 e mobile 390×844, blur/redação de dados, rotas `/ajuda`, versionamento e atualização no mesmo PR de UI.
