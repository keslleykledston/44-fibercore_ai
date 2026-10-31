# UX/UI spec — sidebar contextual

## Espaço no shell
- Usar região do `EntityDetailDrawer` existente. **Não criar coluna fixa adicional** ao menu esquerdo atual nem segundo drawer.
- Desktop >=1440px: preferir painel não modal (360–400px), lado direito, redimensionando apenas a área de conteúdo se continuar confortável. Min workspace de 650px; caso contrário, overlay.
- Entre 1024–1439px: overlay lateral de 360–400px por padrão, sem scroll horizontal.
- <=1023px: drawer modal adaptativo, largura plena em celular; manter botão fechar sempre alcançável e impedir scroll de fundo.
- Transição 120–220ms; sombras mínimas, borda neutra, spacing grid 8pt; light/dark. Reaproveitar `configs/ui/design-tokens.json`.

## Padrão estrutural
```text
[AppShell | filtros/lista ou árvore de ONU | Quick Inspector à direita]
                                       ┌──────────────────────────┐
                                       │ ONU 00123    Online   [x]│
                                       │ Fabricante · Modelo      │
                                       │ ┌ miniatura SVG ───────┐ │
                                       │ │ representação compact│ │
                                       │ └──────────────────────┘ │
                                       │ PON: Registrada · OLT    │
                                       │ ACS: sem contato recente │
                                       │ RX ONU: -22.4 dBm        │
                                       │ OLT/PON: POP / 0/1/1     │
                                       │ Cliente: (se permitido)  │
                                       │ Dados: idade / origem    │
                                       │ [Abrir Visão ONU 360°]   │
                                       └──────────────────────────┘
```

## Regras de microinteração
- Clique na linha ou entrada da árvore abre o drawer e destaca ONU. Segundo clique na ONU selecionada não fecha por acidente.
- Alterar seleção no mesmo contexto mantém drawer aberto e substitui conteúdo (skeleton curto; nunca manter antigo como se fosse novo).
- Fechar via botão, ESC, botão voltar móvel; desktop não fecha ao clicar no conteúdo central se não modal.
- Abrir 360° preserva busca/filters; `returnTo` validado apenas em rotas internas seguras.
- Header da ONU e botão fechar ficam sticky; corpo do sidebar scrolla. Footer com 1 CTA primário e 1 secundário condicional.
- Miniatura: altura 100–145px, SVG escalável, sem zoom pesado. Tooltip/legenda quando indicador representa telemetria real.
- Feedback: estados `loading`, `empty`, `forbidden`, `error`, `stale`, `partial` e `not_supported` com copy próprio.
- Sem gráficos no Quick Inspector por padrão; métricas e séries ficam na ONU 360°.
- Ação write não faz parte deste sidebar nesta entrega.

## Conteúdo mínimo e variáveis
**Sempre:** dispositivo selecionado e botão fechar; `status desconhecido` se ausência.  
**Quando autorizado/disponível:** fabricante/modelo, serial/ONU ID, PON status, ACS status, RX, OLT/PON, relação cliente com confiança.  
**Quando dado desatualizado:** usar última observação com selo `Dados defasados`, NUNCA mostrar online como estado atual sem ressalva.

## Hierarquia e confiança
- Ver estados das camadas isoladas: `Registro PON` e `Comunicação ACS` distintos.
- `Cliente associado` apenas confiança confirmada conforme política; `Baixa confiança` e `Conflito` sem nome conclusivo.
- `RX` sem limiar homologado fica neutro, não crítico/vermelho por regra arbitrária.
- Estado global não deve ser calculado diretamente no frontend a partir de ACS.

## Link contextual
`Abrir Visão 360°` deve usar rota canônica encontrada no código em runtime. Não codificar caminho presumido sem conferir. `Investigar` só se existir capability + permissão.

## Estética
Navegação estilo iOS/macOS inspirada em clareza, densidade moderada e transições discretas; sem replicar assets/propriedades Apple. A cor precisa representar severidade real, não decoração.
