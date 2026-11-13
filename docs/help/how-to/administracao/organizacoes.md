---
title: "Como criar e gerir organizações (provedores) da plataforma"
slug: "administracao/organizacoes"
role: [platform_operator]
status: draft
product_version: "0.1.0"
last_verified: "2026-11-13"
help_owner: "Plataforma FiberCore"
ui_route: "/plataforma/organizacoes"
---

# Como criar e gerir organizações (provedores) da plataforma

**Objetivo:** criar uma organização nova (um provedor, com seus próprios dados isolados dos demais) e entregar o convite ao primeiro administrador dela.

**Antes de começar:**
- Esta tela é só da **conta operadora da plataforma** (marcada pelo dono do sistema, com acesso ao servidor). Nenhum papel de provedor, nem o de Administrador, a vê: para quem não é operador o item não aparece e o endereço responde **Página não encontrada**.
- Você precisa ter o **MFA ativado** (em **Conta → Segurança**) e tê-lo confirmado nos **últimos 10 minutos**. Entrar com o código já conta. Se passar de 10 minutos a tela pede o código de novo antes de qualquer coisa.

## Passo a passo

1. Em **Administração**, clique na aba **Organizações** (ela só existe para o operador).
2. Se aparecer **Confirme o segundo fator**, digite o código do autenticador (ou um código de recuperação) e clique em **Confirmar**.
3. Em **Nova organização**, preencha:
   - **Nome da organização:** de 2 a 60 caracteres. Não pode repetir o de outra organização (maiúsculas e espaços repetidos não contam como diferença).
   - **E-mail do primeiro administrador:** para onde vai o convite.
   - **Nome do primeiro administrador:** opcional.
4. Clique em **Criar organização**. A tela mostra **Organização criada**, o estado do convite (**pendente**), a validade (**72 horas**) e o **link do convite**. **O link aparece uma única vez** (e some em 2 minutos ou quando você clica em **Ocultar o link**): copie-o agora (botão **Copiar link**) e envie à pessoa por um canal seguro. **Nada é enviado por e-mail.** O endereço do link é o que o **seu navegador** está usando; sem JavaScript a tela mostra só o caminho (`/convite/...`) e você junta o endereço da plataforma antes de enviar.
5. A pessoa abre o link, escolhe o nome e uma senha (mínimo de 12 caracteres) e entra como **Administrador** da organização nova. A partir daí é ela quem convida a equipe.

## O que a lista mostra

A tabela **Organizações** traz, para cada uma: o nome, o estado (**Ativa** ou **Suspensa**), a quantidade de **Edges**, **OLTs** e **ONUs**, a **Saúde** (Edges online sobre o total, OLTs sem coleta e recursos ligados), **quando e por quem foi criada** e o **estado do convite** do primeiro administrador (**Pendente**, **Aceito**, **Expirou** ou **Revogado**). Só aparecem contagens e rótulos: **nenhum dado de assinante, de OLT, de ONU ou de Edge** de uma organização é mostrado aqui.

- **“por <nome> (alegado)”** significa que a criação foi feita pela tela por essa conta. O banco registra a conta informada pela chamada; ela é conferida (operador ativo, MFA recente), mas não é uma prova independente de quem clicou. Por isso, **revise a lista de tempos em tempos**.
- **“Sem o par de auditoria da API: revisar”** aparece quando uma organização foi criada **fora da tela** (chamada direta ao banco). Avise o responsável pela segurança.
- **“pela linha de comando do dono”**: organizações criadas antes desta tela ou pelo dono do sistema.

## Gerir uma organização (detalhe)

Na lista, clique no **nome** da organização. O detalhe mostra o **estado**, a **saúde** (Edges online, OLTs sem coleta, último batimento), os blocos de ação, a tabela **Recursos** e o **Histórico**. Toda ação exige o segundo fator recente e um **motivo** de 3 a 200 caracteres, que fica no histórico.

- **Suspender:** informe o motivo e clique em **Suspender organização**. Enquanto suspensa, **os usuários e o Edge da organização recebem bloqueio**: a pessoa que entra vê **Organização suspensa** (sem o motivo) e pode trocar de workspace; o Edge guarda a fila e volta sozinho. **Nada é apagado.**
- **Reativar:** informe o motivo e clique em **Reativar organização**. O acesso volta **na hora, sem novo login**.
- **Renomear:** altere o nome (2 a 60 caracteres, sem repetir outro) e clique em **Renomear**.
- **Recursos:** em cada linha escolha **Ligar**, **Desligar** ou **Voltar ao padrão**, escreva o motivo e clique em **Aplicar**. Os recursos que **escrevem na rede ou usam IA** só podem ser **desligados** aqui: quem os liga é o dono do sistema, pela linha de comando. Alguns recursos dependem da configuração local do Edge (a tela avisa); ligá-los aqui não a cria.
- **Histórico:** quando, quem (conta alegada) e o que mudou, com o motivo.

Se você tentar repetir o estado atual, a tela responde **Nada mudou** e não grava histórico novo.

## Limites e cuidados

- **No máximo 5 organizações por hora.** Na sexta a tela responde: “Limite de 5 organizações por hora atingido”. Nada é criado.
- Você **não vira membro** da organização que criou. Se precisar entrar nela, use o **acesso temporário de suporte** (o Administrador da organização concede por até 8 horas, com motivo).
- **Se o convite expirar** (72 horas) sem ser usado, não há como gerar outro por esta tela: peça ao dono do sistema para incluir o administrador pela linha de comando.
- **Suspender, reativar, renomear e mudar recursos** são feitos no detalhe da organização (próxima seção).
- Uma organização nova nasce **vazia**: sem OLT, sem Edge, sem assinantes e com **todos os recursos opcionais desligados**. Os recursos de cada provedor são ligados no detalhe da organização (os que escrevem na rede, só pelo dono).

## Resultado esperado

- A organização aparece na lista com 0 Edges, 0 OLTs e 0 ONUs e convite **Pendente**.
- Depois que a pessoa aceita o convite, o estado muda para **Aceito** e a organização tem exatamente um membro: ela, como Administrador.
- Uma organização nunca enxerga dados de outra; a evidência está em `docs/operations/ISOLAMENTO_ORGANIZACOES.md`.
