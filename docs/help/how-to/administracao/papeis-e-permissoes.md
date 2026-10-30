---
title: "Como ver e alterar papéis e permissões"
slug: "administracao/papeis-e-permissoes"
role: [isp_admin, access_manager, auditor]
status: draft
product_version: "0.1.0"
last_verified: "2026-10-30"
help_owner: "Plataforma FiberCore"
ui_route: "/administracao/papeis"
---

# Como ver e alterar papéis e permissões

**Objetivo:** saber o que cada papel pode fazer, ver quem tem qual papel, alterar o papel de uma pessoa e conferir o histórico das mudanças.

**Antes de começar:** ver a tela exige acesso de leitura (Administrador do provedor, Gestor de Acesso ou Auditor, conforme a seção). Alterar papéis só o Administrador do provedor e o Gestor de Acesso fazem.

## Passo a passo

1. Acesse **Administração** e abra a aba **Papéis e permissões**.
2. **O que eu posso fazer** mostra o seu papel e as suas permissões, agrupadas por risco.
3. Em **Membros e papéis**, clique em **Alterar papel** na pessoa, escolha o novo papel e escreva o motivo (3 a 200 caracteres).
4. Em **Papéis do sistema** veja a matriz de permissões de cada papel. Em **Histórico de mudanças de papel** veja quem alterou o papel de quem, de qual para qual e por quê.

## Acesso temporário do suporte da plataforma

1. Em **Papéis e permissões**, abra **Acesso temporário do suporte da plataforma** (só o Administrador do provedor concede).
2. Informe o e-mail do operador, o motivo (por exemplo, o número do chamado) e o prazo de 1 a 8 horas. Só contas que a própria plataforma marcou como operadoras podem receber.
3. O operador **só consulta** dados básicos do workspace, não vê dado de cliente, e perde o acesso sozinho no prazo. Para encerrar antes, use **Encerrar agora** na linha do acesso.
4. Para renovar, conceda de novo com um novo motivo: o acesso anterior termina na hora.

## Confirmação do segundo fator

Quando a plataforma exige MFA recente, ações como alterar papéis, aprovar operações em equipamento e conceder acesso pedem o código do autenticador de novo se o último foi há mais de 10 minutos. Digite o código no aviso que aparece e a ação continua.

## Regras importantes

- Você não altera o seu próprio papel.
- O **Gestor de Acesso** atribui Engenheiro, NOC nível 1 e 2, Atendimento e Auditor. Só o **Administrador do provedor** altera quem é Administrador, Gestor de Acesso ou suporte da plataforma.
- Nunca fica um workspace sem Administrador do provedor ativo.
- Ao alterar o papel, as sessões abertas da pessoa são encerradas agora, em todos os workspaces da conta; ela entra de novo com o novo papel.
- O Gestor de Acesso não vê dados da rede nem de clientes e sempre precisa de MFA.

## Se algo não funcionar

- **“Seu papel não pode atribuir este papel”:** só o Administrador do provedor atribui esse papel.
- **“Não dá para tirar o último Administrador”:** nomeie outro Administrador antes.
- **“Outra mudança aconteceu ao mesmo tempo”:** tente de novo.
- **“Código inválido ou já usado”:** cada código do autenticador vale uma vez; espere o próximo.
- **“Esta ação exige MFA”:** ative o MFA em Conta → Segurança.
- **“Serviço indisponível”:** a conexão de troca de papéis não está configurada; avise a plataforma.
