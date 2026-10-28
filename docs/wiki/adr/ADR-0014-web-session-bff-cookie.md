# ADR-0014: Sessão web via BFF Next.js com cookie HttpOnly

Status: Proposed | Data: 2026-10-28 | Owner: Claude Code

## Contexto
O adendo exige same-origin e cookies `Secure`/`HttpOnly`/`SameSite`. A API autentica por Bearer JWT (15 min) e não tem refresh/MFA/rate-limit ainda.

## Decisão
O servidor Next.js (route handlers) é o único a falar a credencial: `POST /bff/login` chama `/v1/auth/token`, grava o token em cookie `HttpOnly; Secure; SameSite=Lax` (curta duração) e injeta `Authorization` nas chamadas à API; o JS do browser nunca vê o token. Seleção de workspace via cookie assinado → header `X-Workspace-ID` (continua validado por membership no servidor). CSRF: SameSite + header customizado em mutações. Logout apaga o cookie.

## Pendências (bloqueiam publicação)
Refresh, MFA, rate-limit/lockout e revogação de sessão: ver ADR-0017. Ainda abertos: MFA obrigatório para admins, tela de cadastro de MFA, CSP com nonce.
