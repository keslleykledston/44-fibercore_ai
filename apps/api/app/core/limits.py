"""Limites técnicos por organização (ADR-0047 D3, fatia B). Proteção do servidor e justiça de carga entre organizações; NÃO é cobrança nem plano (D0).

O padrão vive aqui (`Settings`); a linha `tenant_limits` (migração 0055) só existe quando o operador mudou algo, e uma coluna NULL volta ao padrão. A organização nunca altera o
próprio limite. Excedido ⇒ `409 limit_reached` ao CRIAR (Edge, OLT, membro); o que já existe nunca é apagado nem bloqueado (o teste é "já tenho >= máximo", então reduzir o limite abaixo do uso
só impede novos). A contagem e a decisão rodam sob uma trava consultiva por (organização, recurso): duas criações simultâneas não passam juntas do máximo.
"""
from __future__ import annotations

from uuid import UUID

from fastapi import HTTPException
from sqlalchemy import text
from sqlalchemy.engine import Connection

from app.core.settings import Settings, get_settings

# recurso -> (coluna em tenant_limits, atributo do padrão em Settings, SQL de contagem; `:t` = organização)
RESOURCES: dict[str, tuple[str, str, str]] = {
    "edges": ("max_edges", "limit_default_edges", "SELECT count(*) FROM edges WHERE tenant_id = :t AND status <> 'revoked'"),
    "olts": ("max_olts", "limit_default_olts", "SELECT count(*) FROM olts WHERE tenant_id = :t"),
    # a member, or a person already invited and still able to accept (an open invite is a reserved seat); the invite being REPLACED (same e-mail) is not counted twice
    "members": ("max_members", "limit_default_members",
                "SELECT (SELECT count(*) FROM tenant_memberships WHERE tenant_id = :t) + (SELECT count(*) FROM member_invites WHERE tenant_id = :t AND purpose = 'invite' "
                "AND accepted_at IS NULL AND revoked_at IS NULL AND expires_at > now() AND (CAST(:x AS text) IS NULL OR email <> lower(btrim(CAST(:x AS text)))))"),
}


class LimitReached(Exception):
    def __init__(self, resource: str, maximum: int, current: int) -> None:
        super().__init__(resource, maximum, current)
        self.resource, self.maximum, self.current = resource, maximum, current

    def __str__(self) -> str:   # the CLI prints it
        return f"limit_reached: {self.resource} {self.current}/{self.maximum}"


def defaults(settings: Settings | None = None) -> dict[str, int]:
    s = settings or get_settings()
    return {"max_edges": s.limit_default_edges, "max_olts": s.limit_default_olts, "max_members": s.limit_default_members,
            "ingest_per_minute": s.org_ingest_per_minute, "ingest_burst": s.org_ingest_burst}


def effective(conn: Connection, tenant_id: UUID, settings: Settings | None = None) -> dict[str, int]:
    """The limits that apply to the organization: its overrides over the code defaults."""
    out = defaults(settings)
    row = conn.execute(text("SELECT max_edges, max_olts, max_members, ingest_per_minute, ingest_burst FROM tenant_limits WHERE tenant_id = :t"), {"t": tenant_id}).mappings().first()
    if row:
        out.update({k: v for k, v in row.items() if v is not None})
    return out


def check_capacity(conn: Connection, tenant_id: UUID, resource: str, settings: Settings | None = None, *, exclude_email: str | None = None) -> None:
    """Raise `LimitReached` when the organization already has as many of `resource` as it may. Call it INSIDE the transaction that creates the row, before the insert."""
    col, _attr, count_sql = RESOURCES[resource]
    conn.execute(text("SELECT pg_advisory_xact_lock(hashtextextended(:k, 0))"), {"k": f"limit:{resource}:{tenant_id}"})
    maximum = effective(conn, tenant_id, settings)[col]
    current = int(conn.execute(text(count_sql), {"t": tenant_id, "x": exclude_email}).scalar_one())
    if current >= maximum:
        raise LimitReached(resource, maximum, current)


def enforce(conn: Connection, tenant_id: UUID, resource: str, *, exclude_email: str | None = None) -> None:
    """The API's view of `check_capacity`: 409 `limit_reached`, with the resource and the numbers in headers (the body stays a plain string like every other error)."""
    try:
        check_capacity(conn, tenant_id, resource, exclude_email=exclude_email)
    except LimitReached as exc:
        raise HTTPException(409, "limit_reached", headers={"X-Limit-Resource": exc.resource, "X-Limit-Max": str(exc.maximum), "X-Limit-Current": str(exc.current)}) from exc
