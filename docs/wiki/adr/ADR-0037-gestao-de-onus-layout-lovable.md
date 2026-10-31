# ADR-0037: Gestão de ONUs — layout mestre–detalhe no padrão do protótipo Lovable

Status: Accepted (atrás da flag `onu_quick_inspector`, desligada por padrão) | Data: 2026-10-31 | Substitui o painel fixo à direita do ADR-0035 (a decisão de dados do ADR-0035 não muda).

## Contexto
O painel do Quick Inspector (ADR-0035) e o sidebar de configuração (ADR-0034) eram sobrepostos à tela: em 1440 px escondiam colunas da lista (Rx e Dado ficavam atrás do painel) e a tela da ONU 360° ficava com o sidebar por cima dos cartões. A lista mostrava só 200 ONUs (a OLT real tem 775) sem avisar. O responsável pediu repensar o layout e seguir o padrão do protótipo Lovable ("FiberCore Command Center", `docs/UX-PROPOSTA.md`), que é o modelo de design correto.

## Decisão
1. **Rede = Gestão de ONUs, em três colunas lado a lado** (≥ 1024 px): árvore OLT › PON (240 px) · lista com filtros · painel de detalhes (320 px; 380 px em ≥ 1536). O painel **nunca sobrepõe** a lista (coluna própria, rolagem fixa/`sticky`), existe vazio ("Selecione uma ONU") antes da escolha e vira gaveta modal abaixo de 1024 px.
2. **Matriz de PONs (painel frontal da OLT)** no topo: uma célula por PON com o resumo em TEXTO ("Perda de sinal óptico (LOS) · 10 ONUs, 10 fora"), derivado do estado das ONUs coletadas (prioridade LOS > energia > fora > ok > sem leitura). PON só com dado velho é "sem leitura", nunca "fora". Cada célula leva à PON (`/rede?olt=&pon=`); a seleção vive na URL (recarregar ou compartilhar mantém o recorte); trilha Rede › OLT › PON.
3. **Lista**: filtro por serial + estado (Todas, Fora do ar, Defasadas, Desconhecido) com contagens, total anunciado (`aria-live`), linhas de 48 px, coluna OLT só na busca por serial (várias OLTs). A leitura passa a ser **por OLT** (`olt_id`, até 1000 ONUs, o teto da API) e a tela **avisa** quando a lista é parcial. A busca por serial atravessa as OLTs e esconde matriz e árvore.
4. **Painel de detalhes com abas**: Resumo (PON × ACS separados, Rx sem cor de severidade, cliente conforme o papel), **Aparelho** (a mesma configuração somente leitura do ADR-0034, agora inline; só existe com roteador de vínculo confirmado e `ont_config` ligada) e **Histórico** (30 dias; novo BFF `GET /bff/onus/{id}/history`, que apenas repassa a rota existente sob a flag).
5. **Painéis frontais (faceplates)** vetoriais e conceituais substituem a miniatura genérica: biblioteca fechada (EG8145V5, HG8010H, genérico), LEDs **derivados só do que o estado reportado implica** (online = registrada e sincronizada, logo energizada; LOS = sem sincronismo com falha de sinal, energia desconhecida; dying gasp = sem energia; LAN, Wi-Fi e WPS ficam sempre "sem leitura", pois a OLT não os lê; Codex r1 recusou a versão que inferia tráfego e Wi-Fi), rótulo "conceitual", legenda em texto, dado velho = anel tracejado ("sem leitura"), nunca "apagado"; só `dying_gasp` apaga tudo. Modelos fora da biblioteca ou sem roteador vinculado usam o painel neutro, dito como tal. Na ONU 360° o painel e a óptica ficam no alto, mais a trilha até a PON.
6. **Regras que o protótipo não tinha e o produto mantém**: sem limiar de Rx homologado não há cor de severidade nem "limite/margem" (o protótipo usava −27 dBm); PON (OLT) e ACS são fontes separadas; ACS sem contato não é ONU offline; nenhum botão de escrita (continua tudo bloqueado).
7. **Sem rota nova na API.** Flag desligada: a tela é exatamente a anterior (caminho legado). Rollback: desligar a flag.

## Consequências
- A tela da ONU 360° mantém todos os cartões (sem abas) nesta entrega; abas ali ficam para depois (os testes e a ajuda dependem dos cartões).
- A matriz resume só as ONUs lidas (até 1000 por OLT); o aviso de lista parcial cobre o resto. Uma rota de agregação por PON na API seria o próximo passo para OLTs maiores.
- Ajuda: capturas dos artigos de Rede precisam ser refeitas no novo layout.
- Testes e2e reorganizados: o painel agora é coluna, o filtro é `radiogroup`, a seleção da OLT é pela árvore.

- **Janela de dado recente do inventário: 15 → 35 min** (emenda de 2026-10-31). Observado no LAB: a OLT real só é consultada a cada 15 min (piso de proteção do equipamento), então com janela de 15 min o inventário ficava "defasado" na metade do tempo mesmo com o Edge saudável e a matriz de PONs inteira virava "sem leitura". Nova regra: 2 coletas + 5 min de folga (`OLT_COLLECT_INTERVAL`). Não muda a avaliação de incidentes do NOC (`EVAL_FRESH_FOR` segue 15 min: ponto em aberto, mesmo problema, decisão à parte).

## Alternativas descartadas
Manter o painel fixo à direita (esconde a lista); abas na ONU 360° já (reescrita ampla dos testes sem como validar com o seed completo); virtualizar a lista (775 linhas renderizam bem; fica para quando houver OLT maior); copiar o código do Lovable (stack diferente: TanStack Router + Radix; o padrão foi reproduzido com os componentes e tokens do app).
