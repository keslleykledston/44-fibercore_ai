"""Escopo por site/OLT (ADR-0049 D2, cumpre o ADR-0031 item 3).

O escopo NÃO é um filtro de tela: é um predicado de RLS (migração 0058) lendo `app.scope`, definido pela API na MESMA conexão do `app.tenant_id`. Aqui ficam as três peças de código:
quem pode ter escopo, o que um principal com escopo ainda pode pedir (lista fechada, SÓ leitura) e como o conjunto de OLTs é resolvido a cada requisição (nada viaja no token: revogar ou
mudar vale na hora). Sem linha em `member_scopes` = provedor inteiro, como sempre.

Por que a lista de permissões é fechada: o escopo recorta DADOS DE REDE; recursos sem vínculo com uma OLT (clientes, membros, auditoria, ERP, políticas, equipe) não são escopáveis (ADR-0031),
e escrita/ações em equipamento ficam fora desta primeira entrega. Um papel com escopo é, portanto, o papel RECORTADO ao que está nesta lista (interseção), nunca mais do que o papel dá.
"""
from __future__ import annotations

from uuid import UUID

from sqlalchemy import Connection, text

# Roles that can carry a scope. isp_admin, access_manager and auditor cannot: their function is the whole provider (and a scoped administrator would be locked out of its own work).
SCOPABLE_ROLES = frozenset({"engineer", "noc_n2", "noc_n1", "support"})

# What a scoped principal may still ask for: read-only, network data, every one of them backed by RESTRICTIVE policies on the tables its routes read (see the table inventory in
# tests/test_member_scope.py). `tenant:read` is the provider's own name and flags, not network data. Anything else answers 403, whatever the role.
SCOPED_ALLOWED_PERMISSIONS = frozenset({"tenant:read", "inventory:read", "incidents:read", "fleet:read", "discovery:read"})


def resolve(conn: Connection, tenant_id: UUID, user_id: UUID) -> frozenset[UUID] | None:
    """None = the whole provider. Otherwise the set of OLT ids the person may see: the OLTs listed plus every OLT now in a listed site (a site that gains an OLT widens the scope at once).
    A connection scoped to the tenant and the user. A row with nothing left to match is an EMPTY set (sees nothing), never None."""
    row = conn.execute(text("SELECT pop_ids, olt_ids FROM member_scopes WHERE tenant_id = :t AND user_id = :u"), {"t": tenant_id, "u": user_id}).first()
    if row is None:
        return None
    ids: set[UUID] = set(row.olt_ids or ())
    if row.pop_ids:
        ids |= set(conn.execute(text("SELECT id FROM olts WHERE tenant_id = :t AND pop_id = ANY(:p)"), {"t": tenant_id, "p": list(row.pop_ids)}).scalars())
    return frozenset(ids)


def to_setting(scope: frozenset[UUID] | None) -> str:
    """The value of `app.scope`: '' = unrestricted; otherwise a uuid[] literal built ONLY from UUID objects (never from text of the request)."""
    if scope is None:
        return ""
    return "{" + ",".join(sorted(str(i) for i in scope)) + "}"
