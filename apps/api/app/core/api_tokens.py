"""Tokens de API por organização (ADR-0051 D1): integrações de LEITURA, sem ser uma pessoa.

Formato `fcat_<8 letras/dígitos do prefixo>_<43 do segredo>`; só o SHA-256 do token inteiro é guardado (migração 0060) e o token é mostrado UMA vez. O token carrega a lista de permissões
que lhe foi dada, escolhidas de `API_TOKEN_PERMISSIONS` (lista FECHADA, só leitura, nada de cliente final, equipe, auditoria, escrita ou segredo): nunca herda um papel.
"""
from __future__ import annotations

import hashlib
import re
import secrets

PREFIX = "fcat_"
TOKEN_RE = re.compile(r"^fcat_[A-Za-z0-9]{8}_[A-Za-z0-9_-]{43}$")
# keep in step with ALLOWED in migration 0060 (a test compares the two)
API_TOKEN_PERMISSIONS = ("inventory:read", "incidents:read", "fleet:read", "discovery:read", "diagnostics:quality_read")
MAX_ACTIVE_PER_ORGANIZATION = 20
MAX_DAYS = 365
DEFAULT_PER_MINUTE = 120
DEFAULT_BURST = 60


def new_token() -> tuple[str, str, bytes]:
    """(token, prefix, sha256 digest). The token is shown once and never stored."""
    prefix = "".join(secrets.choice("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789") for _ in range(8))
    token = f"{PREFIX}{prefix}_{secrets.token_urlsafe(32)}"
    assert TOKEN_RE.match(token), "token shape"
    return token, prefix, digest(token)


def digest(token: str) -> bytes:
    return hashlib.sha256(token.encode()).digest()


def looks_like_token(bearer: str) -> bool:
    """Cheap test used to route the Authorization header BEFORE trying it as a JWT; the full shape is checked again by the regex."""
    return bearer.startswith(PREFIX)
