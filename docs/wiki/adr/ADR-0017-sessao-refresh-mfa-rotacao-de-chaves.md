# ADR-0017: Refresh token rotativo, MFA TOTP e rotação de chave JWT (`kid`)

Status: Proposed | Data: 2026-10-28 | Owner: Claude Code | Estende: ADR-0004, ADR-0014

## Contexto
O site está publicado em estado LAB (ADR-0016) com access token de 15 min e sem refresh, sem segundo fator e com uma única chave JWT. Qualquer troca de segredo derrubava todas as sessões, e não havia revogação de sessão no servidor.

## Decisão
1. **Refresh token opaco e rotativo** (`refresh_tokens`): 256 bits aleatórios, só o SHA-256 é armazenado. Uso único: `/v1/auth/refresh` consome o token e emite outro na mesma *família*. Reapresentar um token já consumido é tratado como vazamento e **revoga a família inteira**, exceto dentro de uma janela de tolerância de 10 s (`REFRESH_REUSE_GRACE_SECONDS`), em que **uma** reapresentação (a requisição concorrente legítima, duas abas) recebe um token irmão; uma segunda reapresentação do mesmo token, mesmo dentro da janela, é tratada como roubo e revoga a família (inclusive o irmão). Refresh e logout são serializados por família (lock consultivo), então um logout nunca perde um sucessor criado em paralelo. Janela deslizante de 8 h por token, teto absoluto de 7 dias por família (a rotação não o estende). Usuário desativado perde o refresh. `/v1/auth/logout` revoga a família.
2. **MFA TOTP** (RFC 6238, SHA-1, 6 dígitos, janela ±1): segredo cifrado em repouso (Fernet, `MFA_ENCRYPTION_KEY`; sem a chave o cadastro responde 503, fail closed). Proteção contra replay por `last_step`. 8 códigos de recuperação de uso único (80 bits, só hash armazenado), mostrados uma vez. Login com MFA devolve `mfa_required` + desafio JWT de 5 min com audiência própria (`fibercore:mfa`), que não serve como access token. Verificação, ativação e desativação passam pelo mesmo throttle do login (chave `mfa:<user>`); cadastro e desativação exigem a senha atual.
3. **Rotação de chave JWT**: o token leva `kid`. `JWT_SECRET`/`JWT_KID` assinam; `JWT_SECRET_PREVIOUS`/`JWT_KID_PREVIOUS` apenas verificam. `kid` desconhecido nunca cai para a chave atual; token legado sem `kid` é verificado com a chave atual e, se a assinatura não bater, com a anterior.
4. **BFF**: cookies HttpOnly `fc_token` (TTL do access), `fc_refresh` (8 h) e `fc_mfa` (5 min, só entre senha e código). Um `middleware` renova o access token quando ele expira ou está a menos de 20 s de expirar (lê `exp` do JWT sem verificar assinatura; só decide quando renovar), apenas em navegações (prefetch, inclusive `Next-Router-Segment-Prefetch`, não consome o refresh). Requisições simultâneas com o mesmo cookie compartilham uma única chamada de refresh dentro do processo web (mapa em memória por 5 s); medido: 30 execuções do teste E2E de renovação, 30 passes e exatamente 1 chamada de refresh por execução (antes: 2 a 6 chamadas e 8 falhas em 25). **Restrição de implantação:** o `web` deve rodar com uma única réplica; com mais de uma, requisições simultâneas roteadas a réplicas diferentes não são coalescidas e três ou mais com o mesmo cookie revogam a sessão. Escalar o web exige coordenação compartilhada (ex.: Redis) ou rotação idempotente na API antes.

## Procedimento de rotação de chave
1. Gerar novo segredo (≥ 32 caracteres) e novo `kid` (ex.: `k2`).
2. No `.env`: `FIBERCORE_JWT_SECRET=<novo>`, `FIBERCORE_JWT_KID=k2`, `FIBERCORE_JWT_SECRET_PREVIOUS=<antigo>`, `FIBERCORE_JWT_KID_PREVIOUS=k1`; recriar `api-core`. Tokens antigos continuam válidos até expirar (≤ 15 min); novos saem com `k2`.
3. Após 15 min, esvaziar `FIBERCORE_JWT_SECRET_PREVIOUS`/`KID_PREVIOUS` e recriar. Refresh tokens não dependem da chave JWT e sobrevivem à rotação.
4. Vazamento da chave: pular o passo 2 (não manter a anterior) — todas as sessões de access caem; os usuários renovam via refresh sem novo login.

## Consequências / limites conhecidos
- **MFA não é obrigatório** para nenhum papel ainda, e **não há tela de cadastro** (apenas API). Próximo passo: tela "Segurança da conta" e política `mfa_required` para `isp_admin`.
- Janela de tolerância de 10 s: um atacante com um refresh roubado e já consumido pode obter UM token irmão se for o primeiro a reapresentá-lo dentro da janela; o uso legítimo seguinte (ou qualquer segunda reapresentação) revoga a família e expõe o roubo. Três ou mais abas simultâneas com o mesmo cookie derrubam a sessão. Aceito em troca de não derrubar a sessão em corrida de duas abas.
- Eventos de autenticação (login, MFA, refresh, reuso) ainda não vão para `audit_log` (que é por tenant); falta um registro global de eventos de segurança.
- A chave MFA em `.env` não é um cofre; trocá-la invalida os cadastros existentes (exige recadastro). Cofre/KMS segue como pendência do W9.
- HS256 simétrico mantido; migração para RS256/JWKS continua ligada à adoção de OIDC (ADR-0004).
