---
title: "Como criar tokens de API e webhooks"
slug: "administracao/integracoes"
role: [isp_admin]
status: draft
product_version: "0.1.0"
last_verified: "2026-11-14"
help_owner: "Plataforma FiberCore"
ui_route: "/administracao/integracoes"
---

# Como criar tokens de API e webhooks

**Objetivo:** ligar outro sistema (BI, painel, script) à sua organização, para **ler** dados de rede (token) ou **receber avisos** de incidente (webhook).

## Token de API (só leitura)

1. **Administração → Integrações → Tokens de API.**
2. Dê um **nome**, marque o que ele pode **ler** e escolha a **validade** (1 a 365 dias). Clique em **Criar token**.
3. O token (`fcat_…`) aparece **uma única vez**. Copie e guarde num cofre de senhas. Depois só o começo (prefixo) fica visível.
4. O outro sistema usa o cabeçalho `Authorization: Bearer fcat_…`.
5. Para encerrar: **Revogar** (vale na hora). Um token nunca escreve, nunca vê clientes, equipe nem auditoria, e só vê a sua organização.

## Webhook (avisos de incidente)

1. **Administração → Integrações → Webhooks.** Se a tela disser que a chave de cifra não está configurada, peça a quem opera a plataforma.
2. Informe um **nome**, a **URL** (https, com o **nome** do servidor: endereço IP, “localhost” e nomes internos não são aceitos) e os **eventos**.
3. O **segredo** aparece uma vez. Use-o para **conferir a assinatura** de cada chamada (a tela mostra um exemplo em **Como conferir a assinatura**).
4. **Testar** envia um aviso de teste; **Entregas recentes** mostra o resultado.
5. O seu servidor deve responder **2xx** em até 10 segundos. Sem isso a plataforma tenta de novo; **10 falhas seguidas desligam** o webhook (use **Religar**).
6. **Girar segredo** troca o segredo (o antigo para de valer na hora). O aviso traz só ids e contagens, nunca dados de cliente.

> Rascunho (sem capturas de tela ainda).
