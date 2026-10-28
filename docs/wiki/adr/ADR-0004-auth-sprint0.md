# ADR-0004: Autenticação Sprint 0: JWT HS256 local + Argon2id; OIDC depois

Status: Proposed (aguarda Codex gate) | Data: 2026-10-27 | Owner: Claude Code (implementação)

## Contexto

Sem IdP definido pelo cliente. `users_global.oidc_subject` já reserva a migração.

## Decisão

Login e-mail+senha (Argon2id), access token curto (15 min), `iss/aud/exp/iat/sub` obrigatórios, algoritmo fixo (rejeita `alg=none`). Token NÃO carrega tenant de usuário; tenant e papel vêm de `tenant_memberships` a cada request. Service accounts: token fixo ao tenant da conta, secret exibido uma vez e guardado com hash. Sem refresh token, MFA ou rate-limit ainda (pendência explícita).

## Consequências

Trocar emissor por OIDC mantendo `get_principal`; HS256 → RS256/JWKS. Segredo JWT via env/Docker secret, mínimo 32 chars.
