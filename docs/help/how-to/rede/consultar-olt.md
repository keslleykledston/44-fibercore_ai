---
title: "Como consultar a OLT (somente leitura)"
slug: "rede/consultar-olt"
role: [isp_admin, engineer, noc_n2]
status: draft
product_version: "0.1.0"
last_verified: "2026-10-30"
help_owner: "Plataforma FiberCore"
ui_route: "/rede"
---

# Como consultar a OLT (somente leitura)

**Objetivo:** pedir à OLT uma informação que o painel ainda não mostra (versão do software e tempo ligada; placas e estado; hora da OLT; sincronismo das controladoras; temperatura das placas), sem abrir login a mais e sem alterar nada no equipamento.

**Antes de começar:** permissão para pedir consultas à OLT (administrador, engenheiro ou NOC N2) e o recurso **consultas à OLT** ligado para o provedor. Sem isso, a janela explica por que nada está disponível.

## Passo a passo

1. Acesse **Rede** e, no cartão da OLT, clique em **Consultar a OLT…**.
2. Escolha a consulta (hoje: **Software, patch e uptime**, **Placas e estado**, **Hora e fuso da OLT**, **Sincronismo de controladoras** e **Temperatura**) e clique em **Pedir consulta**.
3. A tela mostra **Aguardando a próxima coleta da OLT**. A consulta roda na **mesma sessão** da coleta periódica, depois dos comandos dela; por isso pode levar **até uns 18 minutos**. Você pode fechar a janela e voltar; a tela confere a cada 10 segundos enquanto está aberta.
4. Quando termina, o resultado aparece resumido: produto, versão, patch e há quanto tempo a OLT está ligada; ou a tabela de placas com o estado de cada uma e os slots vazios.

## Dado guardado: a OLT nem sempre é consultada

Cada resultado fica guardado com a hora em que chegou. Se você pedir a mesma consulta de novo dentro do prazo dela (a hora da OLT, 2 min; temperatura e sincronismo, 15 min; versão e placas, 1 h), a tela responde na hora com o dado guardado e diz **“Dado guardado, há N min. A OLT não foi consultada agora”**: o equipamento não é incomodado. Passado o prazo, a consulta vai à OLT como de costume. O botão **Atualizar agora** força uma consulta nova; há um limite de 3 por hora por OLT, e acima disso a tela continua mostrando o último dado guardado.

## O que isso garante

- É **somente leitura**: nada é alterado na OLT.
- A **saída bruta** do equipamento nunca sai do Edge. O painel só recebe um resumo fechado (campos conhecidos, com tamanho e alfabeto limitados); qualquer coisa fora desse formato é descartada.
- Há limites por hora (por pessoa, por provedor e por OLT) para não competir com o monitoramento do provedor. Passando do limite, o pedido é recusado com um aviso.

## Se algo não funcionar

- **“Desligada para este provedor”:** o recurso ainda não foi ligado; peça ao responsável.
- **“A consulta venceu antes de a janela da coleta abrir”:** a coleta atrasou; peça de novo.
- **“A OLT estava ocupada ou em espera”:** a OLT estava em pausa depois de uma falha (a proteção da OLT vale também para consultas). Nada foi repetido; tente depois.
- **“Resultado desconhecido”:** o Edge reiniciou durante a consulta; ela **não** é repetida automaticamente. Peça de novo.
