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

**Antes de começar:** permissão `inventory:read`. Ver é só leitura. Para pedir uma ação (reiniciar, trocar o nome do Wi-Fi) é preciso também `jobs:request` e a permissão da ação; o pedido só cria uma operação, nada é enviado ao equipamento por esta tela.

## Passo a passo

1. Acesse **Rede** e abra a aba **CPEs**.
2. Use **Serial ou ID no ACS**, **Fabricante**, **Modelo**, **Protocolo** e **Dado** e clique em **Filtrar**.
3. Clique no serial para abrir o detalhe: **Identidade**, **ONU vinculada**, **Estado lido no ACS**, **Ações** e **Capacidades**.

## Como ler

- **Dados defasados** é a idade da última leitura, não significa que o CPE caiu.
- **Estado lido no ACS** vem do cache do GenieACS; sem leitura não é “tudo certo”.
- **ONU vinculada** só aparece se uma pessoa confirmou o vínculo (revisão na ONU 360).
- **Capacidades** mostram o que está comprovado para o modelo/firmware; a aprovação e o acompanhamento das operações ficam em Operações.

## Pedir uma ação

1. No detalhe do CPE, em **Ações**, a ação só aparece como disponível se ela já foi **observada** neste modelo e firmware e o seu papel pode pedi-la. Caso contrário o motivo aparece escrito.
2. Clique em **Pedir…**, leia o aviso e, no Wi-Fi, informe o nome (na bancada, começa com `BANCADA-`). Clique em **Criar pedido**.
3. O pedido segue o fluxo de sempre: outra pessoa aprova em **Operações**. Hoje nenhuma escrita está homologada, então só o equipamento de bancada, com autorização prévia do responsável, chega a seguir; nos demais casos o pedido é cancelado na hora e a tela diz o motivo (“Nada foi enviado”).

## Se algo não funcionar

- **Lista vazia:** aguarde a primeira coleta do GenieACS pelo Edge ou limpe os filtros.
- **Sem permissão:** seu papel não permite ver o inventário.
- **“O pedido não seguiu”:** o motor de operações recusou (por exemplo, escrita não homologada ou falta de autorização do responsável). Nada foi enviado ao equipamento.
