# ADR-0049: Política de segurança por organização (D1) e escopo por site/OLT (D2)

Status: **Accepted e construída** (fatia D do ADR-0047) | Data: 2026-11-14 | Owner: Claude Code (implementação), Codex (revisão)

Origem: ADR-0047 D5/D6 e a ordem do responsável de 2026-11-14 ("faça a fatia B e as demais sem me perguntar"). **D2 reabre o ADR-0031 item 3** ("depois de A, B e C", agora na fila) e o cumpre sem mudar o desenho dele; papéis customizados continuam **NÃO** (ADR-0031 decisão 1). Migrações 0057 (D1) e 0058 (D2).

## D1 — Política de segurança por organização (migração 0057)
`tenant_security_policy (tenant_id PK, mfa_required_roles text[], updated_by, updated_at)`. **Só aperta, nunca afrouxa:** a regra efetiva da organização é o **piso do ambiente** (`MFA_REQUIRED_ROLES` + `ALWAYS_MFA_ROLES`) **∪** os papéis dela, calculada na leitura (`app/core/security_policy.py`); apagar a linha ou esvaziar a lista só devolve ao piso. Só papéis humanos (`CHECK`): nem `edge_agent` nem `platform_support`.
- **Imposição** a cada requisição, no mesmo ponto onde o piso já era imposto (`get_principal`, e `_mfa_required` na tela de segurança da conta): quem tem papel exigido por QUALQUER organização a que pertence e ainda não ativou o MFA recebe `403 mfa_enrolment_required` e só enxerga as rotas `/v1/auth/*` para se cadastrar. Uma leitura da política que **falha** propaga o erro (falha fechada: nunca cai para "sem política").
- **Quem muda:** nova permissão `tenant:security_policy` (R3, MFA recente), só `isp_admin`. `GET /v1/security-policy` (qualquer membro) mostra piso, política da organização, efetiva e quantos membros ainda não têm MFA. `PUT` é idempotente e grava `tenant.security_policy.changed` (de/para, nº de membros sem MFA) e evento no outbox.
- **Contra trancar gente para fora:** `409 mfa_unavailable` se o ambiente não consegue cadastrar autenticador (`MFA_ENCRYPTION_KEY` vazio); `409 enable_your_mfa_first` se a mudança alcança o papel de quem está mudando e essa pessoa ainda não tem MFA.
- **Não construído:** duração de sessão por organização (exige claim de início de sessão que o token de acesso curto não tem; fica como emenda se pedido). Registrado para não parecer coberto.

## D2 — Escopo por site/OLT (migração 0058)
_(preenchido ao construir)_
