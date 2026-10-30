---
title: "Como consultar os CPEs (dispositivos)"
slug: "rede/dispositivos"
role: [isp_admin, engineer, noc_n2, noc_n1, support]
status: draft
product_version: "0.1.0"
last_verified: "2026-10-30"
help_owner: "Plataforma FiberCore"
ui_route: "/dispositivos"
---

# Como consultar os CPEs (dispositivos)

**Objetivo:** ver os CPEs coletados pelo GenieACS, filtrar por fabricante, modelo, protocolo e idade do dado, e abrir o detalhe de um CPE.

**Antes de começar:** permissão `inventory:read`. A tela é somente leitura: nada aqui altera um equipamento.

## Passo a passo

1. Acesse **Rede** e abra a aba **CPEs**.
2. Use **Serial ou ID no ACS**, **Fabricante**, **Modelo**, **Protocolo** e **Dado** e clique em **Filtrar**.
3. Clique no serial para abrir o detalhe: **Identidade**, **ONU vinculada**, **Estado lido no ACS** e **Capacidades**.

## Como ler

- **Dados defasados** é a idade da última leitura, não significa que o CPE caiu.
- **Estado lido no ACS** vem do cache do GenieACS; sem leitura não é “tudo certo”.
- **ONU vinculada** só aparece se uma pessoa confirmou o vínculo (revisão na ONU 360).
- **Capacidades** mostram o que está comprovado para o modelo/firmware; ações que alteram o equipamento ficam em Operações.

## Se algo não funcionar

- **Lista vazia:** aguarde a primeira coleta do GenieACS pelo Edge ou limpe os filtros.
- **Sem permissão:** seu papel não permite ver o inventário.
