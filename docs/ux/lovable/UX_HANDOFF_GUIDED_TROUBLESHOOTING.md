# Handoff de UX — Diagnóstico guiado (FC22-007)

Segundo e último pedido em lote ao Lovable desta fase (dados sintéticos, sem segredos). O código do Lovable é só referência visual.

## Objetivo
Tela `/assinantes/diagnostico/[id]`: conduzir o atendente, passo a passo, do sintoma "cliente sem conexão" até uma conclusão **honesta**, usando só evidência já coletada (somente leitura). Minimalista, estilo iOS, claro/escuro, pt-BR, WCAG 2.2 AA, alvos ≥ 44 px.

## Layout
- Coluna de passos (stepper vertical; em mobile vira lista empilhada) + painel de evidências do passo selecionado.
- Cada passo tem: título, **rótulo de confiança** (texto + ícone, nunca só cor): `Confirmado` (fato medido), `Hipótese` (derivada de fatos; exige confirmação humana), `Indisponível` (dado velho ou ausente: nada é afirmado).
- **Uma** ação por passo, sempre de leitura ("Ver ONU 360", "Abrir incidente no NOC", "Reexecutar a leitura"). Nunca botão de escrita; se mostrar um, bloqueado com "Operação ainda não homologada".
- Botão "Gerar resumo para ticket": mostra um texto copiável (cliente, ONU, OLT/PON, estado, achado, idade de cada dado, "nenhuma alteração foi feita na rede").

## Passos (nesta ordem)
1. Cliente e contrato (fonte ERP, idade)
2. ONU aprovada (serial, OLT/PON)
3. Estado e óptica da ONU (status, Rx, fonte OLT, idade)
4. Padrão coletivo na PON — regra R-D001 v1: `Hipótese` (queda coletiva suspeita; causa sugerida fibra/LOS ou energia, "não é diagnóstico"), `Confirmado` (as quedas recentes não atingem o padrão; contagens), `Indisponível` (dado velho)
5. Roteador (CPE): vínculo confirmado por uma pessoa → fabricante/modelo/protocolo; sugerido → "indício, não prova"; nenhum → indisponível

## Estados a mostrar (desktop 1440×900 e mobile 390×844, claro e escuro)
Conclusão com hipótese; conclusão sem padrão; dado defasado (tudo Indisponível, sem conclusão); cliente sem ONU aprovada; sem permissão para executar diagnóstico (passos 1-3 e 5 visíveis, passo 4 Indisponível "seu papel não permite executar"); recurso desligado; erro de carregamento; resumo para ticket aberto.

## Regras
Nunca score nem percentual de "saúde". Nenhum dado pessoal além de nome de exibição e "documento final 1234". Defasado ≠ offline. Sem backend, sem autenticação, sem persistência.
