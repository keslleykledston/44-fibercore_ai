---
title: "Como acompanhar um incidente no NOC"
slug: "noc/acompanhar-incidente"
role: [isp_admin, engineer, noc_n2, noc_n1]
status: published
product_version: "0.1.0"
last_verified: "2026-10-29"
help_owner: "Plataforma FiberCore"
ui_route: "/noc"
---

# Como acompanhar um incidente no NOC

**Objetivo:** acompanhar quedas em massa por PON e entender as evidências sem tirar conclusões precipitadas.

**Antes de começar:** Permissão `incidents:read`. Um incidente só é aberto quando a PON foi lida por completo, tem pelo menos 5 ONUs e 80% ou mais fora.

## Passo a passo

1. Acesse **NOC** no menu lateral.
2. Leia os 4 indicadores do topo: **Incidentes abertos**, **Não reconhecidos**, **Clientes afetados** (distintos, via associações aprovadas) e **Edges silenciosos**.
3. A fila já vem **priorizada**: abertos primeiro; não reconhecidos antes dos reconhecidos; queda confirmada antes de "Edge silencioso"; maior número de clientes afetados; mais ONUs fora; mais recente. Use **Só não reconhecidos** para focar no que ainda ninguém assumiu.
4. Em cada incidente, leia o título (OLT e PON), as evidências (ONUs fora, LOS, falta de energia) e o **impacto**: "N cliente(s) afetado(s) · fonte: associações aprovadas".
5. Clique no título para abrir o **painel lateral** com as evidências, o impacto e as ONUs do incidente (**Abrir** leva à ONU 360). **Esc** ou **Fechar** volta para a fila, sem trocar de tela.
6. Leia a **causa suspeita**: é uma hipótese, não um diagnóstico.
7. Se aparecer o aviso **Edge silencioso**, o estado exibido é o último conhecido e não está confirmado agora.

![Tela em desktop 1440×900 — Como acompanhar um incidente no NOC](../../assets/noc/acompanhar-incidente/desktop.png)

![Tela em mobile 390×844 — Como acompanhar um incidente no NOC](../../assets/noc/acompanhar-incidente/mobile.png)

## Resultado esperado

Incidentes abertos aparecem primeiro, com o estado, a contagem de evidências e o impacto. Incidentes se resolvem sozinhos quando a PON se recupera (abaixo de 50%).

## Como ler o impacto
- O indicador **Clientes afetados** não inclui incidentes atrás de **Edge silencioso**: ali o estado é o último conhecido, não uma queda confirmada agora (o indicador de abertos informa quantos são).
- O número conta **clientes distintos** ligados às ONUs do incidente por associações **aprovadas** por uma pessoa; sugestões ainda não aprovadas não contam.
- **"Impacto indisponível para o seu papel":** seu papel não tem `customers:read`. Isso **não** significa que ninguém foi afetado.
- **"Impacto desconhecido":** o incidente é antigo e não tem as ONUs registradas; o número não é zero, é desconhecido.

## Permissões necessárias

`incidents:read`; o impacto (clientes afetados) exige também `customers:read`; reconhecer incidente exige `incidents:ack` (isp_admin, engineer, noc_n2).

## Se algo não funcionar

- **Edge silencioso:** a falta de dados não abre nem fecha incidentes; verifique o Edge.
- **Incidente não aparece:** PON com menos de 5 ONUs ou leitura parcial não gera incidente.
- **Sem permissão:** seu papel não permite ver incidentes.

## Evidências de documentação

- Build/commit: 1d9fb94 (árvore de trabalho do PR)
- Browser/viewport: Chromium; desktop 1440×900 e mobile 390×844
- Caso de teste E2E: help-screenshots.spec.ts › noc/acompanhar-incidente; app.spec.ts › dados defasados
- Dados: fictícios (seed `scripts/seed_demo.py`); sem informações reais de clientes
