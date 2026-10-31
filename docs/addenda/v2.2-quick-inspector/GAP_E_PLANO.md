# ONU Quick Inspector × repositório real (2026-10-31)

O pacote cita um GitHub público vazio; o código real verificado é **este repositório** (`44-FiberCore`, branch `main`). Precedência do pacote respeitada: segurança/contratos > ADRs > PRD > API > este adendo.

| Requisito do handoff | O que já existe | Mudança |
|---|---|---|
| Drawer direito reaproveitado | `EntityDetailDrawer` (modal), aberto pelo serial em `OnuTable` com resumo de 4 campos | novo painel `OnuQuickInspector`; `EntityDetailDrawer` continua para a gaveta estreita e para os outros usos |
| Não modal em tela larga, sobreposição média, modal no celular | só modal | ≥1024 px: painel direito não modal (≥1440 px a lista cede 400 px); <1024 px: a gaveta modal existente |
| Trocar a ONU sem fechar | cada clique reabria o resumo | a seleção troca o conteúdo; pedido anterior cancelado; o resumo de outra ONU nunca é mostrado |
| PON (OLT) e ACS separados | ONU 360° mostra OLT e `cpe.provenance` | `buildQuick` (servidor) deriva `pon` da OLT e `acs` da observação do CPE vinculado, sem misturar; ACS sem contato nunca vira ONU offline |
| RX com origem; sem limiar não pinta severidade | `rx_dbm` + `observed_at` | `severity: "unknown"` sempre (não há limiar homologado), `null` = "RX não disponível" |
| Cliente só se autorizado e confiável | `/v1/onus/{id}/customer` (`customers:read`, auditado; 403 para papéis sem acesso) | aprovado = nome; sugerido = "Vínculo de cliente sem confirmação" sem nome; 403 = "Dados do cliente restritos"; falha do cliente não derruba o resto |
| Miniatura SVG genérica | nenhuma | `DeviceThumbnail` (compartilhada com o sidebar de configuração do aparelho); pontos de luz = PON/ACS, rotulados como não sendo LEDs reais; sem template de fabricante (nenhum homologado) |
| Link para a ONU 360° preservando contexto | rota `/rede/onu/[id]` | botão "Abrir Visão 360°"; lista, busca e filtros ficam (painel é da página) |
| Sem endpoint novo (D-08) | `/v1/onus/{id}` + `/customer` | **nenhum endpoint novo na API**: o BFF `GET /bff/onus/[id]/quick` compõe os dois (1 ONU por clique, sem N+1) |
| Feature flag desligada por padrão (D-09) | `tenant_features` | `onu_quick_inspector` (código: desligada); desligada = resumo antigo idêntico (verificado) |
| Ajuda e capturas reais | pipeline Playwright de capturas | rascunho `rede/resumo-da-onu`; captura real fica para quando a flag for ligada em produção |
| Investigar (IA) | nenhum fluxo | **não renderizado** (D-10) |

## Entrega
Um único PR (os três do plano cabem juntos porque não há endpoint novo): UI + composição read-only + miniatura/navegação/ajuda em rascunho. Gates: tsc, build, Playwright (projeto `inspetor`: painel largo, troca/Esc/foco, corrida de respostas, falha parcial, BFF por fonte, celular) + prova com a flag desligada, Codex.
**Limites:** associação `medium/conflict` do handoff não existe no modelo atual (só aprovado/sugerido/nenhum); estado "ACS conector indisponível" e `unsupported` não existem como dado hoje; o caso "papel sem `customers:read`" (restrito) é coberto pela lógica do mapeamento, mas o e2e usa o administrador (o seed não tem papel N1).
