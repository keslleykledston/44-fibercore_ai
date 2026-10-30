---
title: "Como ver as ONUs fora do ar há mais tempo"
slug: "rede/onus-offline"
role: [isp_admin, engineer, noc_n2, noc_n1, support]
status: draft
product_version: "0.1.0"
last_verified: "2026-10-30"
help_owner: "Plataforma FiberCore"
ui_route: "/rede/offline"
---

# Como ver as ONUs fora do ar há mais tempo

**Objetivo:** listar as ONUs offline há pelo menos X horas, as mais antigas primeiro (agendar retirada, contatar o cliente), sabendo de onde vem cada horário.

**Antes de começar:** permissão `inventory:read`. O relatório só usa o que o Edge coletou; ele nunca inventa o início de uma queda.

## Passo a passo

1. Acesse **Rede** e clique em **ONUs offline**.
2. Informe **Fora do ar há pelo menos (horas)** (padrão 24), escolha a **OLT** e/ou digite a **PON** (ex.: 0/0/14) e clique em **Filtrar**.
3. Leia **Fora do ar há**, **Desde** e **Base do horário** de cada linha (veja abaixo).
4. Clique no serial para abrir a ONU 360. Use **Baixar CSV** para levar a lista (até 5000 linhas) para uma planilha.

## Base do horário

| Base | Significa |
|---|---|
| Exato | O Edge viu a ONU online e depois fora do ar. |
| Informado pela OLT | Horário de queda que a própria OLT informa; o relógio da OLT pode divergir alguns minutos. |
| No máximo | A ONU foi vista online pela última vez nesse horário: a queda dura **no máximo** isso (aparece como “até X”). |

## Contagens acima da lista

- **Sem horário de início:** ONUs fora do ar sem nenhuma queda registrada nem horário da OLT (ex.: nunca vistas online). Não entram na lista porque não há início a mostrar.
- **Dados defasados:** ONUs cuja coleta da OLT está velha (mais de 15 min) ficam de fora, para uma OLT que o Edge parou de coletar não parecer uma queda longa. Marque **Incluir dados defasados** para vê-las.

## Se algo não funcionar

- **Lista vazia:** diminua as horas ou verifique **Sem horário de início** e **Dados defasados**.
- **Sem permissão:** seu papel não permite ver o inventário.
