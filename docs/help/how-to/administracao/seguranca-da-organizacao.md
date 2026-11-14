---
title: "Como exigir a verificação em duas etapas de mais funções"
slug: "administracao/seguranca-da-organizacao"
role: [isp_admin]
status: draft
product_version: "0.1.0"
last_verified: "2026-11-14"
help_owner: "Plataforma FiberCore"
ui_route: "/administracao/seguranca"
---

# Como exigir a verificação em duas etapas de mais funções

**Objetivo:** fazer a sua organização exigir a verificação em duas etapas (MFA) de funções que a plataforma ainda não exige.

**Antes de começar:**
- Só o **Administrador do provedor** muda esta política (os demais só consultam).
- Você precisa ter a **sua** verificação ativa se a mudança alcançar a sua própria função.

## Passo a passo

1. Em **Administração**, abra **Segurança da organização**.
2. Veja o quadro **O que a plataforma já exige**: essas funções aparecem marcadas e **travadas**. A política da organização só **acrescenta**; nunca tira o que a plataforma exige.
3. Marque as funções que você quer acrescentar. Ao lado de cada uma aparece quantas pessoas ainda não ativaram a verificação.
4. Clique em **Salvar política**. A tela diz quantas pessoas serão levadas a cadastrar a verificação e pede **Confirmar**.
5. No próximo acesso, quem ainda não tem a verificação só consegue abrir a tela de segurança da conta até cadastrá-la.

## Se algo der errado
- **“O servidor não consegue cadastrar a verificação”:** a plataforma ainda não está configurada para MFA; fale com quem a opera.
- **“Ative a sua própria verificação primeiro”:** você está exigindo a sua própria função sem ter ativado a sua.

> Rascunho (sem capturas de tela ainda).
