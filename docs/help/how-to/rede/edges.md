---
title: "Como acompanhar os Edges"
slug: "rede/edges"
role: [isp_admin, engineer, noc_n2]
status: draft
product_version: "0.1.0"
last_verified: "2026-10-30"
help_owner: "Plataforma FiberCore"
ui_route: "/dispositivos/edges"
---

# Como acompanhar os Edges

**Objetivo:** ver os agentes que coletam dentro da rede do provedor: versão, estado e último batimento.

**Antes de começar:** permissão `edge:read`. Somente leitura.

## Passo a passo

1. Acesse **Rede** e abra a aba **Edges**.
2. Confira **Estado** e **Último batimento** de cada Edge e a coluna **Versão** (mais de uma versão em uso aparece no indicador acima da tabela).

## Como ler

- **Sem sinal do Edge** não diz que a rede do provedor caiu: o Edge pode estar parado ou sem conexão com a nuvem; os dados dele ficam defasados.
- **Sem batimento** é um Edge que ainda não se comunicou.

## Se algo não funcionar

- **Sem permissão:** seu papel não permite ver os Edges.
- **Nenhum Edge:** registre um Edge para começar a coletar.
