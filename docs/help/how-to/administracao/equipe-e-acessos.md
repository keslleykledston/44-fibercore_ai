---
title: "Como convidar, gerenciar e remover pessoas da equipe"
slug: "administracao/equipe-e-acessos"
role: [isp_admin, access_manager]
status: draft
product_version: "0.1.0"
last_verified: "2026-10-30"
help_owner: "Plataforma FiberCore"
ui_route: "/administracao/equipe"
---

# Como convidar, gerenciar e remover pessoas da equipe

**Objetivo:** colocar uma pessoa na equipe, escolher o que ela pode fazer, e depois mudar a função, redefinir a senha ou remover.

**Antes de começar:** só o Administrador do provedor e o Gestor de acesso gerenciam pessoas. O código da verificação em duas etapas é pedido ao **entrar** na plataforma, não a cada ação. (Se o seu provedor ligou a confirmação por ação, o painel pede o código no meio da ação.)

## Convidar uma pessoa

1. Em **Administração → Equipe e acessos**, clique em **Convidar pessoa**.
2. Digite o e-mail (o nome é opcional) e escolha a **função**. Cada cartão diz o que a pessoa pode e não pode fazer.
3. Clique em **Criar convite**. Aparece um **link**: clique em **Copiar link** e envie por WhatsApp ou e-mail. O painel não envia nada sozinho.
4. A pessoa abre o link, escolhe o nome e uma senha (mínimo de 12 caracteres) e entra. Você nunca vê a senha dela.

O link vale por 72 horas e funciona uma vez. Ele só aparece na hora; se perder, use **Gerar novo link** (o anterior para de valer) ou **Cancelar convite**. Se a pessoa já tem conta (por exemplo, em outro provedor), ela digita a senha que já tem para aceitar.

## Gerenciar uma pessoa

Na linha da pessoa, clique em **Gerenciar**:

- **Mudar a função:** escolha a nova função, leia **O que muda** e escreva o motivo. A pessoa é desconectada e entra de novo com a nova função.
- **Redefinir a senha:** gera um link de 24 horas para ela escolher outra senha. Não vale para quem também faz parte de outro provedor (essa pessoa troca a própria senha em Conta → Segurança da conta).
- **Redefinir a verificação em duas etapas:** para quem perdeu o celular. Confirme com a sua senha e o seu código.
- **Remover da equipe:** a pessoa perde o acesso na hora. É preciso informar o motivo.

## Ver funções e atividade

- Aba **Funções:** cartões com o que cada função faz e uma tabela "quem pode o quê". Os nomes técnicos das permissões ficam em **Ver detalhes técnicos**.
- Aba **Atividade:** quem convidou, mudou, removeu ou redefiniu, em frases, com o motivo.

## Regras importantes

- Você não gerencia a si mesmo aqui. Para a sua senha, use **Conta → Segurança da conta**.
- O Gestor de acesso convida, remove e muda quase todas as funções, mas não mexe em Administrador nem em outro Gestor de acesso.
- O último Administrador não pode ser removido nem rebaixado.
- **Suporte da plataforma:** na seção recolhida da aba Pessoas, o Administrador concede acesso temporário (1 a 8 horas, com motivo) e pode encerrar quando quiser.

## Se algo não funcionar

- **“Esta conta também pertence a outro provedor”:** só a própria pessoa troca a senha dela.
- **“Já faz parte da equipe”:** não precisa de convite.
- **“Confirme o segundo fator”:** digite o código do autenticador no aviso e a ação continua.
- **Convite vencido:** use **Gerar novo link**.
