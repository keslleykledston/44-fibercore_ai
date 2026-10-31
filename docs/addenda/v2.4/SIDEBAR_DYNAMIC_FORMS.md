# Handoff visual — sidebar recolhível à direita e formulários por capacidade

## Objetivo
Preservar o padrão UI minimalista, futurista, iOS-like próprio da K3G (sem copiar Apple) e o projeto atual. O usuário pesquisa/seleciona ONU no Subscriber 360 ou inventário e abre **painel contextual direito** sem perder a lista ao fundo. A miniatura vetorial do aparelho já prevista no projeto aparece com animação discreta de estado (ex.: indicador de LOS), **nunca** substitui status textual.

## Larguras e responsividade
- Desktop (1440px): drawer direito 380–440px; UI de lista permanece navegável; foco preso apenas em overlay modal, não em sidebar não-modal; minimizar sem perder formulário e rascunho local protegido.
- Tablet: drawer overlay ~70% viewport.
- Mobile (390px): bottom/full screen sheet navegável, resumo fixo, teclado suportado, sem overflow lateral.
- Barra de controles: `Resumo`, `Wi-Fi`, `LAN`, `Avançado`, `Histórico` (abas ausentes/inativas quando capabilities indisponíveis). Não inventar indicadores ou controles de banda.

## Componentes
`OntSidebar`, `DeviceIdentityHeader`, `DeviceThumbnail`, `CapabilityDrivenForm`, `NetworkInstancePicker`, `FreshnessStamp`, `SourceEvidence`, `ConfigDiffPreview`, `RiskAndApprovalSheet`, `ChangeProgressTimeline`, `HelpContextLink`, `NoCapabilityState`, `ReadOnlyMetricsPanel`, `ConflictBanner`, `SecretInputWithConfirmation`.

## Regras importantes
- Um único CTA principal por etapa: `Editar` → `Pré-visualizar` → `Solicitar alteração` → `Acompanhar`.
- SSIDs múltiplos (2.4/5/6 GHz) têm seletor de instância real (`SSID.3` não é label 5 GHz automaticamente); valor de bandas descoberto em profile.
- `Canal`, `Potência Wi-Fi` e `Largura` usam **somente allowedValues, unidade e ranges retornados pela API**. Sem slider visual se faixa não for conhecida; melhor select com enum homologado.
- Textos claros: `Alteração solicitada`, `Aguardando conexão da ONT`, `Executando`, `Verificando`, `Confirmado`, `Resultado incerto`; `HTTP 202` não é pronto.
- Painel óptico mostra RX/TX e fonte/frescor com `Somente leitura`, sem botão de editar TX laser.
- Se modelo desconhecido, renderizar resumo read-only e link `Solicitar homologação` para equipe de engenharia.
- Tabelas de parâmetros raw TR-181 ocultas para N1; engenharia pode consultar painel diagnóstico read-only se role permitir.

## Experiência de senhas
Input de nova senha só em contexto autorizado e HTTPS; nunca preencher com senha atual ou exibir do ACS. Preview informa `Senha: será substituída` sem hash inseguro/senha. Proibir uso da função `copiar configuração` para segredos.

## Central de Ajuda
Cada tela/etapa inclui `help_slug`, artigos `/ajuda/ont/configurar-wifi`, `/ajuda/ont/consultar-lan`, `/ajuda/ont/consultar-optica`, `/ajuda/ont/acompanhar-alteracao`. Após implementação: Playwright real desktop 1440×900 e mobile 390×844 com fixture sintética e redigida; artigos how-to e imagens criados no mesmo PR. Protótipo Lovable não substitui screenshots reais.

## Acessibilidade
WCAG 2.2 AA como meta, `prefers-reduced-motion`, foco visível, keyboard navigation, aria-labelledby no sheet/modal, mensagem de erro com ação de recuperação, estados sem depender apenas de cores. PT-BR e horários da instância com TZ explícito.
