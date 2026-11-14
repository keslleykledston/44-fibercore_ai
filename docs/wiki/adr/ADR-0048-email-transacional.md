# ADR-0048: E-mail transacional (convite, troca de senha, avisos de segurança e de suspensão)

Status: **Accepted e construída** (fatia C do ADR-0047) | Data: 2026-11-14 | Owner: Claude Code (implementação), Codex (revisão)

Origem: ADR-0047 D4 ("o link de uso único por e-mail precisa de decisão de risco própria") e a ordem do responsável de 2026-11-14 ("faça a fatia B e as demais sem me perguntar"). Migrações **0056**. Não altera o ADR-0031 nem o ADR-0017 (MFA).

## Contexto
- Hoje **nada sai por e-mail**: convite e link de troca de senha aparecem **uma vez** na tela de quem os cria e a pessoa repassa por fora (`/v1/team/invites`, `/v1/team/members/{id}/password-reset`). O primeiro administrador de uma organização recebe o convite do mesmo jeito (ADR-0046 D1).
- O que falta para o produto ser usável por mais de uma equipe: o convite chegar sem o administrador copiar e colar um link, e a pessoa saber quando algo sobre a conta dela mudou (segundo fator redefinido) ou quando a organização inteira foi suspensa (ADR-0047 D1).

## Decisão
**D1 — Só existe com configuração da plataforma.** SMTP é do **ambiente** (`SMTP_HOST`, `SMTP_FROM`, `PUBLIC_BASE_URL`, mais `SMTP_PORT/SECURITY/USER/PASSWORD/FROM_NAME`), nunca de uma organização. Falta qualquer um dos três obrigatórios ⇒ o e-mail **não existe**: a API se comporta como antes (link na tela) e responde `409 email_not_configured` a quem pedir envio. TLS sempre (STARTTLS ou SSL implícito, certificado verificado); **não há opção sem TLS**. `PUBLIC_BASE_URL` só aceita `https://host[:porta]` (ou `http://localhost` para máquina de desenvolvimento).

**D2 — O que sai, e quando.**

| Tipo | Quando | Para | Carrega segredo? |
|---|---|---|---|
| `member_invite` | administrador marca "enviar por e-mail" ao convidar ou renovar | a pessoa convidada | **link de uso único** (72 h) |
| `password_reset` | administrador marca "enviar por e-mail" ao gerar a troca | a própria conta do membro | **link de uso único** (24 h) |
| `mfa_reset_notice` | administrador redefine o segundo fator de alguém | a pessoa | não |
| `organization_suspended` / `organization_reactivated` | operador suspende ou reativa a organização | administradores ativos (`isp_admin`) | não |

Os dois com link são **ato explícito** do administrador (`send_email=true`), **nunca automáticos**; a tela continua mostrando o link (o e-mail é um canal a mais, não o único). Os avisos sem segredo saem sozinhos quando o e-mail existe. **Sem alerta por e-mail** de rede/OLT/ONU (precisa antes de política de ruído) e **sem texto livre**: cada tipo é um modelo fixo em PT-BR (`app/core/mail.py`), com só o nome da organização e o de quem agiu (limpos de caracteres de controle e cortados). Nenhum dado de cliente final, credencial de equipamento, motivo digitado pelo operador ou senha entra em mensagem.

**D3 — Decisão de risco do link por e-mail (o que o ADR-0047 pediu).** Mandar o link por e-mail aceita que **quem lê a caixa postal da pessoa pode usá-lo** (o mesmo risco de qualquer produto com "esqueci minha senha"). Aceito porque: o link já era um segredo de uso único com TTL e só o hash SHA-256 fica no banco; a pessoa convidada já era a destinatária natural; a conta com MFA continua pedindo o segundo fator no login; troca de senha de conta que pertence a **outra** organização continua recusada (ADR-0031). Mitigações que o código impõe:
- O **endereço do link** vem de `PUBLIC_BASE_URL`, **nunca** de `Host`/`Origin`/`X-Forwarded-Host`: um cabeçalho forjado não leva o link a outro domínio (teste).
- O link vive em `email_queue.body` **só até o envio**: enviado, expirado (1 h sem entrega) ou desistido (5 tentativas), `body` vira NULL e uma restrição do banco impede corpo em linha terminada. A **aplicação não lê** `body` (grant por coluna) e não altera nem apaga linha; o registro (tipo, destinatário, resultado) fica 30 dias sem corpo.
- A **trilha de auditoria** registra "enviado por e-mail" com o endereço, **nunca o link** (teste).
- O destinatário da troca de senha é o **e-mail da própria conta do membro**, lido do banco; o pedido não informa endereço. O do convite é o mesmo e-mail do convite (validado pelo banco).
- Cabeçalhos só recebem valores validados (endereço no formato do banco, assunto com caracteres de controle removidos): sem injeção de `Bcc`.
- Falha de SMTP é registrada pela **classe** da exceção (nunca endereço, assunto, corpo ou link nos logs nem na linha).
- **Falha de aviso nunca desfaz a mudança pedida**: o aviso de suspensão roda em *savepoint*; se falhar, a suspensão fica (teste).

**D4 — Entrega.** Fila no banco (`email_queue`, RLS por organização) + worker `mailer` (serviço novo; role `fibercore_worker`, **sem grant na tabela**, três funções `SECURITY DEFINER`: `app_mail_claim` com lease de 2 min, `app_mail_finish` com recuo linear e máximo de 5 tentativas, `app_mail_sweep` para expirar e limpar). Sem SMTP o worker só mantém o batimento. Escolhido em vez de enviar dentro da requisição: SMTP lento ou fora do ar não trava a tela, e a mensagem só existe se a transação da mudança confirmar. Não usa o outbox/NATS: o corpo (com link) **não pode** passar por um barramento de eventos que outros consumidores leem.

**D5 — Fora desta decisão.** SMTP por organização, modelo editável, anexo, HTML, rastreio de abertura, e-mail de marketing, reenvio automático de link, e-mail para cliente final.

## Riscos declarados
- **R-C1:** uma caixa postal comprometida vira conta comprometida (D3). Aceito; o administrador pode preferir não marcar "enviar" e repassar por outro canal, como hoje.
- **R-C2:** SMTP comprometido ou mal configurado lê os links em trânsito se a rota até ele não for confiável. Mitigação: TLS obrigatório com verificação de certificado; o link vale uma vez e por tempo limitado.
- **R-C3:** o corpo fica em claro no banco por até 1 h (fila). Mitigação: sem leitura pela aplicação, apagado ao enviar, expiração por relógio; quem lê o banco como dono já leria o hash e as chaves.

## Provas exigidas e feitas
`tests/test_email.py` (17): modelos fixos e sem injeção de cabeçalho; link só de `PUBLIC_BASE_URL` e cabeçalho forjado ignorado; sem SMTP nada na fila e `409`; convite, renovação e troca com e-mail; destinatário da troca é o da conta; avisos de suspensão/reativação só aos administradores, idempotentes, sem o motivo; falha de aviso não desfaz a suspensão; aviso de redefinição de segundo fator; worker entrega e apaga o corpo; falha com recuo e desistência apagando o corpo; expiração e limpeza; role do worker sem acesso à tabela; aplicação sem acesso às funções do worker e sem leitura do corpo; outra organização não lê a fila.
- Reversão: `alembic downgrade 0055` (apaga a fila); desligar = esvaziar `SMTP_HOST`.
