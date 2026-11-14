"""Encerrar uma organização (ADR-0050): exportar e apagar, SÓ pelo dono, no host. Nada daqui roda pela API.

Descoberta, não lista à mão: as tabelas de dados da organização são TODAS as tabelas do esquema `public` que têm a coluna `tenant_id` (menos o registro permanente
`organization_closures`); a ordem de exclusão vem das chaves estrangeiras (filhas antes das mães). Uma tabela nova é coberta sem mudar este arquivo, e uma exclusão que esbarrar numa chave
que a ordem não resolveu falha e desfaz TUDO (uma transação).

Exportação: um `.tar.gz` (0600) com um `.jsonl` por tabela e um `manifest.json` (contagens e sha256 por arquivo), lido num instantâneo consistente (REPEATABLE READ). NUNCA entram as colunas de
segredo (`SECRET_COLUMNS`: hashes de senha/segredo/token, blobs selados, corpo de e-mail, token de lease) nem as tabelas internas que não são dado da organização (`SKIP_TABLES`). O arquivo CONTÉM dado
pessoal de cliente final da organização (é a portabilidade dele): o dono o entrega a quem de direito e o guarda como guardaria um backup.
"""
from __future__ import annotations

import hashlib
import io
import json
import os
import tarfile
import tempfile
from collections import defaultdict, deque
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy import Connection, text

SECRET_COLUMNS = frozenset({"secret_hash", "token_hash", "password_hash", "sealed", "body", "lease_token", "mfa_secret"})
SKIP_TABLES = frozenset({"email_queue", "events_outbox", "processed_events"})   # not the organization's data: queue/bus internals (the outbox is derived from the rows that ARE exported)
LEDGER = "organization_closures"


def data_tables(conn: Connection) -> list[str]:
    rows = conn.execute(text(
        "SELECT c.relname FROM pg_class c JOIN pg_attribute a ON a.attrelid = c.oid AND a.attname = 'tenant_id' AND NOT a.attisdropped "
        "WHERE c.relkind = 'r' AND c.relnamespace = 'public'::regnamespace AND c.relname NOT IN ('tenants', :ledger) ORDER BY c.relname"), {"ledger": LEDGER}).scalars().all()
    return list(rows)


def delete_order(conn: Connection, tables: list[str]) -> list[str]:
    """Children before parents among `tables`, from the foreign keys between them (Kahn); whatever a cycle leaves is appended (the delete then fails loudly and rolls back)."""
    names = set(tables)
    fk = conn.execute(text("SELECT c.conrelid::regclass::text AS child, c.confrelid::regclass::text AS parent FROM pg_constraint c WHERE c.contype = 'f' AND c.connamespace = 'public'::regnamespace")).all()
    parents_of: dict[str, set[str]] = defaultdict(set)   # parent -> children that reference it
    indeg = {t: 0 for t in tables}
    for child, parent in fk:
        child, parent = child.split(".")[-1].strip('"'), parent.split(".")[-1].strip('"')
        if child in names and parent in names and child != parent and child not in parents_of[parent]:
            parents_of[parent].add(child)
            indeg[parent] += 1          # a parent can go only after ALL its children are gone
    queue = deque(sorted(t for t, d in indeg.items() if d == 0))
    order: list[str] = []
    children_of: dict[str, set[str]] = defaultdict(set)   # child -> parents it references
    for parent, kids in parents_of.items():
        for k in kids:
            children_of[k].add(parent)
    while queue:
        t = queue.popleft()
        order.append(t)
        for parent in sorted(children_of.get(t, ())):
            indeg[parent] -= 1
            if indeg[parent] == 0:
                queue.append(parent)
    order += sorted(t for t in tables if t not in order)
    return order


def count_rows(conn: Connection, tenant_id: str, tables: list[str]) -> dict[str, int]:
    conn.execute(text("SELECT set_config('app.tenant_id', :t, true)"), {"t": tenant_id})
    return {t: int(conn.execute(text(f'SELECT count(*) FROM "{t}" WHERE tenant_id = :t'), {"t": tenant_id}).scalar_one()) for t in tables}   # noqa: S608 - names come from pg_class


def _columns(conn: Connection, table: str) -> list[str]:
    cols = conn.execute(text("SELECT column_name FROM information_schema.columns WHERE table_schema = 'public' AND table_name = :t ORDER BY ordinal_position"), {"t": table}).scalars().all()
    return [c for c in cols if c not in SECRET_COLUMNS]


def _jsonl(conn: Connection, table: str, tenant_id: str, cols: list[str]):
    """The rows of one table exactly as the export writes them (ONE definition: the export and the content check of `org-close` cannot drift apart)."""
    sel = ", ".join(f'"{c}"' for c in cols)
    stmt = text(f'SELECT row_to_json(x)::text FROM (SELECT {sel} FROM "{table}" WHERE tenant_id = :t ORDER BY 1) x').execution_options(stream_results=True)  # noqa: S608 - names come from pg_class
    for r in conn.execute(stmt, {"t": tenant_id}):
        yield (r[0] + "\n").encode()


def content_differences(conn: Connection, tenant_id: str, manifest: dict, counts: dict[str, int]) -> list[str]:
    """Tables whose CONTENT is no longer what the archive holds (Codex r1, MEDIUM: equal row counts do not prove equal rows). Exported tables are compared by the sha256 of their
    rows; the tables the export skips (queue/bus internals) by count only."""
    bad = []
    for t, info in manifest["tables"].items():
        h = hashlib.sha256()
        for line in _jsonl(conn, t, tenant_id, info["columns"]):
            h.update(line)
        if h.hexdigest() != info["sha256"]:
            bad.append(t)
    bad += [t for t in SKIP_TABLES if t in counts and counts[t] != manifest.get("skipped_counts", {}).get(t, counts[t])]
    return sorted(bad)


def export_archive(conn: Connection, tenant_id: str, out_path: str) -> dict:
    """Write the archive; return {sha256, bytes, rows (per table, ALL data tables), manifest}. `conn` must be a REPEATABLE READ read of the organization (the caller opens it)."""
    row = conn.execute(text("SELECT id, name FROM tenants WHERE id = :t"), {"t": tenant_id}).first() if _set_tenant(conn, tenant_id) else None
    if row is None:
        raise ValueError("no such organization")
    tables = data_tables(conn)
    counts = count_rows(conn, tenant_id, tables)
    manifest: dict = {"format": 1, "tenant_id": str(row.id), "name": row.name, "exported_at": datetime.now(UTC).isoformat(), "secret_columns_never_exported": sorted(SECRET_COLUMNS),
                      "skipped_tables": sorted(SKIP_TABLES), "skipped_counts": {t: counts[t] for t in SKIP_TABLES if t in counts}, "tables": {}}
    out = Path(out_path)
    fd = os.open(out, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)   # never overwrite, never world-readable
    with os.fdopen(fd, "wb") as raw, tarfile.open(fileobj=raw, mode="w:gz") as tar, tempfile.TemporaryDirectory() as tmp:
        for t in tables:
            if t in SKIP_TABLES:
                continue
            cols = _columns(conn, t)
            path = Path(tmp) / f"{t}.jsonl"
            h, n = hashlib.sha256(), 0
            with open(path, "wb") as f:
                for line in _jsonl(conn, t, tenant_id, cols):
                    f.write(line)
                    h.update(line)
                    n += 1
            manifest["tables"][t] = {"rows": n, "sha256": h.hexdigest(), "columns": cols}
            tar.add(path, arcname=f"{t}.jsonl")
        mbytes = json.dumps(manifest, indent=1, ensure_ascii=False).encode()
        info = tarfile.TarInfo("manifest.json")
        info.size = len(mbytes)
        info.mtime = int(datetime.now(UTC).timestamp())
        tar.addfile(info, io.BytesIO(mbytes))
    data = out.read_bytes()
    return {"sha256": hashlib.sha256(data).hexdigest(), "bytes": len(data), "rows": counts, "manifest": manifest}


def _set_tenant(conn: Connection, tenant_id: str) -> bool:
    conn.execute(text("SELECT set_config('app.tenant_id', :t, true)"), {"t": tenant_id})
    return True


def read_manifest(path: str) -> dict:
    with tarfile.open(path) as tar:
        member = tar.extractfile("manifest.json")
        if member is None:
            raise ValueError("the archive has no manifest")
        return json.load(member)


def file_sha256(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def delete_everything(conn: Connection, tenant_id: str, tables: list[str]) -> dict[str, int]:
    """Delete every row of the organization, then the organization. ONE transaction (the caller's): any failure leaves everything as it was. Returns rows deleted per table."""
    deleted: dict[str, int] = {}
    conn.execute(text("SELECT set_config('app.tenant_id', :t, true)"), {"t": tenant_id})
    # the last-administrator guard (0024) would refuse to delete the final isp_admin membership: it protects an organization that EXISTS; this one is being closed on purpose
    conn.execute(text("ALTER TABLE tenant_memberships DISABLE TRIGGER keep_one_isp_admin"))
    try:
        for t in delete_order(conn, tables):
            deleted[t] = conn.execute(text(f'DELETE FROM "{t}" WHERE tenant_id = :t'), {"t": tenant_id}).rowcount   # noqa: S608 - names come from pg_class
    finally:
        conn.execute(text("ALTER TABLE tenant_memberships ENABLE TRIGGER keep_one_isp_admin"))
    conn.execute(text("DELETE FROM tenants WHERE id = :t"), {"t": tenant_id})
    return deleted


def deactivate_orphans(conn: Connection, user_ids: list) -> int:
    """People who belonged ONLY to the closed organization lose the account (deactivated, sessions ended). An account that still belongs elsewhere, or that is a platform operator, is untouched."""
    if not user_ids:
        return 0
    rows = conn.execute(text(
        "UPDATE users_global u SET is_active = false, tokens_valid_after = clock_timestamp() WHERE u.id = ANY(:ids) AND NOT u.is_platform_operator AND u.is_active "
        "AND NOT EXISTS (SELECT 1 FROM tenant_memberships m WHERE m.user_id = u.id) RETURNING u.id"), {"ids": user_ids}).scalars().all()
    if rows:
        conn.execute(text("UPDATE refresh_tokens SET revoked_at = now() WHERE user_id = ANY(:ids) AND revoked_at IS NULL"), {"ids": list(rows)})
    return len(rows)
