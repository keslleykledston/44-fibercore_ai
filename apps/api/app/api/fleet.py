"""Fleet Manager (ADR-0041, PR2 part A): register and edit OLTs and POPs. NOTHING here talks to an OLT.

A registered OLT is a row the provider names BEFORE the Edge first reads it: name, the Edge that will collect it, the expected vendor, a POP, a label and `credential_ref`, the NAME of the secret in
the Edge's own local store (D3: the Cloud never holds, receives or echoes a credential or an address; the name itself is write-only here: no response returns it, a reader sees only `has_credential_ref`). When the Edge's first snapshot arrives it adopts the row by name and fills in the real
vendor/model/firmware/level; the registration fields are left alone. There is no delete here: removing an OLT is a separate, deliberate step. The whole router answers 403 `feature_disabled`
while the tenant flag `fleet_manager` is off.

ADR-0046 (migration 0051): the registration also says HOW the OLT is reached (protocol ssh|telnet, port, transport cli|snmp, SNMP port, SSH host-key fingerprint, ssh mode, legacy ssh).
None of it is a secret and the fingerprint may be returned; the address still comes back only masked. Telnet is inventory only (no credential, no connection is ever delivered for it).
`edge_trust_state` is what the EDGE reports and cannot be written
here. Changing how the OLT is reached voids the connection already delivered (the database demotes the trust) and cancels the deliveries still waiting.
"""
from __future__ import annotations

import ipaddress
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from sqlalchemy import Connection, text

from app.api.deps import TENANT_CONN, Principal, require
from app.api.routes import audit
from app.core import features, fleet, limits, olt_secrets

router = APIRouter()
LIST_LIMIT = 500


def _flag(conn: Connection, p: Principal) -> None:
    features.ensure(conn, p.tenant_id, "fleet_manager")


class PopIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(min_length=2, max_length=60)
    code: str | None = Field(None, pattern=fleet.POP_CODE_RE.pattern)
    note: str | None = Field(None, max_length=200)


class PopPatch(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str | None = Field(None, min_length=2, max_length=60)
    code: str | None = Field(None, pattern=fleet.POP_CODE_RE.pattern)
    note: str | None = Field(None, max_length=200)


def _pop_view(r) -> dict:
    return {"id": str(r.id), "name": r.name, "code": r.code, "note": r.note, "created_at": r.created_at.isoformat(), "olts": getattr(r, "olts", None)}


@router.get("/v1/pops")
def list_pops(p: Principal = Depends(require("fleet:read")), conn: Connection = TENANT_CONN) -> dict:
    _flag(conn, p)
    rows = conn.execute(text("SELECT p.id, p.name, p.code, p.note, p.created_at, (SELECT count(*) FROM olts o WHERE o.pop_id = p.id) AS olts FROM pops p ORDER BY lower(p.name) LIMIT :n"),
                        {"n": LIST_LIMIT}).all()
    return {"items": [_pop_view(r) for r in rows]}


@router.post("/v1/pops", status_code=201)
def create_pop(body: PopIn, p: Principal = Depends(require("fleet:manage")), conn: Connection = TENANT_CONN) -> dict:
    _flag(conn, p)
    r = conn.execute(text("INSERT INTO pops (tenant_id, name, code, note, created_by) VALUES (:t,btrim(:n),:c,:o,:by) ON CONFLICT DO NOTHING RETURNING id, name, code, note, created_at"),
                     {"t": p.tenant_id, "n": body.name, "c": body.code, "o": body.note, "by": p.id}).first()
    if r is None:
        raise HTTPException(409, "pop_name_taken")
    audit(conn, p, "fleet.pop.created", "pop", str(r.id), {"name": r.name})
    return _pop_view(r)


@router.patch("/v1/pops/{pop_id}")
def update_pop(pop_id: UUID, body: PopPatch, p: Principal = Depends(require("fleet:manage")), conn: Connection = TENANT_CONN) -> dict:
    _flag(conn, p)
    sent = body.model_fields_set
    if not sent:
        raise HTTPException(422, "nothing to change")
    cur = conn.execute(text("SELECT id, name, code, note, created_at FROM pops WHERE id = :i FOR UPDATE"), {"i": pop_id}).first()
    if cur is None:
        raise HTTPException(404, "pop not found")
    if "name" in sent and body.name is None:
        raise HTTPException(422, "name cannot be cleared")
    new = {k: (getattr(body, k) if k in sent else getattr(cur, k)) for k in ("name", "code", "note")}
    r = conn.execute(text("UPDATE pops SET name = btrim(:n), code = :c, note = :o WHERE id = :i AND NOT EXISTS (SELECT 1 FROM pops x WHERE x.id <> :i AND lower(x.name) = lower(btrim(:n))) "
                          "RETURNING id, name, code, note, created_at"), {"n": new["name"], "c": new["code"], "o": new["note"], "i": pop_id}).first()
    if r is None:
        raise HTTPException(409, "pop_name_taken")
    audit(conn, p, "fleet.pop.updated", "pop", str(pop_id), {"fields": sorted(sent)})
    return _pop_view(r)


def _address(v: str | None) -> str | None:
    why = None if v is None else fleet.address_problem(v)
    if why:
        raise ValueError(why)   # never echoes the value
    return None if v is None else str(ipaddress.ip_address(v.strip()))


def _snmp(v: str | None) -> str | None:
    if v is not None and v not in fleet.SNMP_VERSIONS:
        raise ValueError(f"snmp_version must be one of: {', '.join(fleet.SNMP_VERSIONS)}")
    return v


def _choice(v: str | None, allowed: tuple[str, ...], name: str) -> str | None:
    if v is not None and v not in allowed:
        raise ValueError(f"{name} must be one of: {', '.join(allowed)}")
    return v


class _ConnectionFields(BaseModel):
    """How the OLT is reached (ADR-0046 D3). Format only here; the rules BETWEEN the fields (port by protocol, v2c for SNMP, no ssh fields for Telnet)
    are `fleet.merge_connection`, on the merged state."""
    mgmt_protocol: str | None = None
    mgmt_port: int | None = Field(None, strict=True, ge=1, le=65535)
    mgmt_transport: str | None = None
    snmp_port: int | None = Field(None, strict=True, ge=1, le=65535)
    host_key_sha256: str | None = Field(None, max_length=64)
    ssh_mode: str | None = None
    legacy_ssh: bool | None = Field(None, strict=True)

    @field_validator("mgmt_protocol")
    @classmethod
    def _protocol(cls, v: str | None) -> str | None:
        return _choice(v, fleet.PROTOCOLS, "mgmt_protocol")

    @field_validator("mgmt_transport")
    @classmethod
    def _transport(cls, v: str | None) -> str | None:
        return _choice(v, fleet.TRANSPORTS, "mgmt_transport")

    @field_validator("ssh_mode")
    @classmethod
    def _ssh_mode(cls, v: str | None) -> str | None:
        return _choice(v, fleet.SSH_MODES, "ssh_mode")

    @field_validator("host_key_sha256")
    @classmethod
    def _host_key(cls, v: str | None) -> str | None:
        if v is not None and not fleet.HOST_KEY_RE.match(v):
            raise ValueError("host_key_sha256 must be SHA256: followed by 43 base64 characters (ssh-keygen -lf)")   # never echoes the value
        return v


def _merged(cur: dict, body: BaseModel, snmp_version: str | None) -> dict:
    sent = {k: getattr(body, k) for k in fleet.CONN_FIELDS if k in body.model_fields_set}
    try:
        return fleet.merge_connection(cur, sent, snmp_version)
    except fleet.ConnectionRuleError as exc:
        raise HTTPException(422, exc.code) from exc


class OltIn(_ConnectionFields):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(min_length=2, max_length=60)
    edge_id: UUID
    vendor: str
    pop_id: UUID | None = None
    pop_name: str | None = Field(None, min_length=2, max_length=60)   # a site typed by the person: found by name (case-insensitive) or created in the same transaction
    credential_ref: str | None = Field(None, max_length=64)
    label: str | None = Field(None, min_length=1, max_length=80)
    mgmt_address: str | None = Field(None, max_length=45)
    snmp_version: str | None = None

    @field_validator("mgmt_address")
    @classmethod
    def _addr(cls, v: str | None) -> str | None:
        return _address(v)

    @field_validator("snmp_version")
    @classmethod
    def _snmpv(cls, v: str | None) -> str | None:
        return _snmp(v)

    @model_validator(mode="after")
    def _one_pop(self):
        if self.pop_id is not None and self.pop_name is not None:
            raise ValueError("send pop_id or pop_name, not both")
        return self

    @field_validator("name")
    @classmethod
    def _name(cls, v: str) -> str:
        why = fleet.olt_name_problem(v)
        if why:
            raise ValueError(why)
        return v

    @field_validator("vendor")
    @classmethod
    def _vendor(cls, v: str) -> str:
        if v not in fleet.VENDORS:
            raise ValueError(f"vendor must be one of: {', '.join(fleet.VENDORS)}")
        return v

    @field_validator("credential_ref")
    @classmethod
    def _ref(cls, v: str | None) -> str | None:
        why = None if v is None else fleet.credential_ref_problem(v)
        if why:
            raise ValueError(why)   # never echoes the value
        return v


class OltPatch(_ConnectionFields):
    model_config = ConfigDict(extra="forbid")
    pop_id: UUID | None = None
    pop_name: str | None = Field(None, min_length=2, max_length=60)
    credential_ref: str | None = Field(None, max_length=64)
    label: str | None = Field(None, min_length=1, max_length=80)
    mgmt_address: str | None = Field(None, max_length=45)
    snmp_version: str | None = None

    @field_validator("mgmt_address")
    @classmethod
    def _addr(cls, v: str | None) -> str | None:
        return _address(v)

    @field_validator("snmp_version")
    @classmethod
    def _snmpv(cls, v: str | None) -> str | None:
        return _snmp(v)

    @model_validator(mode="after")
    def _one_pop(self):
        if self.pop_id is not None and self.pop_name is not None:
            raise ValueError("send pop_id or pop_name, not both")
        return self

    @field_validator("credential_ref")
    @classmethod
    def _ref(cls, v: str | None) -> str | None:
        why = None if v is None else fleet.credential_ref_problem(v)
        if why:
            raise ValueError(why)
        return v


_OLT_SQL = ("SELECT o.id, o.name, o.vendor, o.model, o.firmware, o.support_level, o.observed_at, (o.credential_secret_ref IS NOT NULL) AS has_ref, o.label, o.pop_id, p.name AS pop_name, "
            "o.registered_at, host(o.mgmt_address) AS mgmt_address, o.snmp_version, o.edge_id, e.name AS edge_name, "
            "o.mgmt_protocol, o.mgmt_port, o.mgmt_transport, o.snmp_port, o.host_key_sha256, o.ssh_mode, o.legacy_ssh, o.edge_trust_state, o.conn_applied_at, "
            "(SELECT max(d.finished_at) FROM olt_secret_deliveries d WHERE d.olt_id = o.id AND d.kind = 'ssh_login' AND d.status = 'APPLIED') AS ssh_cred_at, "
            "(SELECT max(d.finished_at) FROM olt_secret_deliveries d WHERE d.olt_id = o.id AND d.kind = 'snmp_community' AND d.status = 'APPLIED') AS snmp_cred_at, "
            "EXISTS (SELECT 1 FROM olt_query_latest l WHERE l.olt_id = o.id AND l.query_id = 'olt.connection' AND l.source = 'job' AND l.owner_epoch = o.owner_epoch "
            "AND o.conn_applied_at IS NOT NULL AND l.asked_at >= o.conn_applied_at) AS tested, "
            "e.last_heartbeat_at, (SELECT count(*) FROM onus n WHERE n.olt_id = o.id) AS onu_count "
            "FROM olts o JOIN edges e ON e.id = o.edge_id LEFT JOIN pops p ON p.id = o.pop_id ")


def _olt_view(r) -> dict:
    return {"id": str(r.id), "name": r.name, "vendor": r.vendor, "model": r.model, "firmware": r.firmware, "support_level": r.support_level,
            "observed_at": r.observed_at.isoformat() if r.observed_at else None,
            "has_credential_ref": r.has_ref,   # the NAME of the secret is never returned (least exposure): a reader sees only that one is set
            "mgmt_address_masked": fleet.mask_address(r.mgmt_address), "snmp_version": r.snmp_version,   # the address is write-only: a reader only ever gets the masked form
            "label": r.label, "pop": {"id": str(r.pop_id), "name": r.pop_name} if r.pop_id else None, "registered": r.registered_at is not None,
            "registered_at": r.registered_at.isoformat() if r.registered_at else None, "edge": {"id": str(r.edge_id), "name": r.edge_name},
            "edge_last_heartbeat_at": r.last_heartbeat_at.isoformat() if r.last_heartbeat_at else None, "onu_count": r.onu_count,
            "collected": r.observed_at is not None,
            # ADR-0046: how it is reached (none of this is a secret; the host-key fingerprint is public) and how far the OLT is on the way to being usable
            "connection": {"protocol": r.mgmt_protocol, "port": r.mgmt_port, "transport": r.mgmt_transport, "snmp_port": r.snmp_port, "host_key_sha256": r.host_key_sha256, "ssh_mode": r.ssh_mode,
                           "legacy_ssh": r.legacy_ssh, "trust_state": r.edge_trust_state, "applied": r.conn_applied_at is not None,
                           "applied_at": r.conn_applied_at.isoformat() if r.conn_applied_at else None},
            "readiness": fleet.readiness(protocol=r.mgmt_protocol, transport=r.mgmt_transport, conn_applied=r.conn_applied_at is not None, trust=r.edge_trust_state,
                                         ssh_cred=r.ssh_cred_at is not None, snmp_cred=r.snmp_cred_at is not None, tested=bool(r.tested))}


@router.get("/v1/fleet/olts")
def list_olts(p: Principal = Depends(require("fleet:read")), conn: Connection = TENANT_CONN) -> dict:
    _flag(conn, p)
    rows = conn.execute(text(_OLT_SQL + "ORDER BY lower(o.name) LIMIT :n"), {"n": LIST_LIMIT}).all()
    return {"items": [_olt_view(r) for r in rows], "truncated": len(rows) >= LIST_LIMIT}


@router.get("/v1/fleet/olts/{olt_id}")
def get_olt(olt_id: UUID, p: Principal = Depends(require("fleet:read")), conn: Connection = TENANT_CONN) -> dict:
    _flag(conn, p)
    r = conn.execute(text(_OLT_SQL + "WHERE o.id = :i"), {"i": olt_id}).first()
    if r is None:
        raise HTTPException(404, "olt not found")
    return _olt_view(r)


def _cancel_waiting(conn: Connection, olt_id: UUID, kind: str | None, code: str) -> int:
    """PENDING/DISPATCHED deliveries of the OLT (all kinds, or one) become CANCELLED with the blob erased. The caller holds the OLT row lock (the same one `create_delivery` takes)."""
    return conn.execute(text("UPDATE olt_secret_deliveries SET status = 'CANCELLED', code = :c, sealed = NULL, updated_at = now() "
                             "WHERE olt_id = :o AND status IN ('PENDING', 'DISPATCHED') AND (CAST(:k AS text) IS NULL OR kind = :k)"), {"c": code, "o": olt_id, "k": kind}).rowcount


def _check_pop(conn: Connection, pop_id: UUID | None) -> None:
    if pop_id is not None and conn.execute(text("SELECT 1 FROM pops WHERE id = :i"), {"i": pop_id}).first() is None:   # RLS: another tenant's POP is simply not found
        raise HTTPException(404, "pop not found")


def _resolve_pop(conn: Connection, p: Principal, pop_id: UUID | None, pop_name: str | None) -> UUID | None:
    """The POP an OLT is filed under. `pop_name` finds the site by name (case-insensitive) or creates it in THIS transaction, so a refused OLT never leaves a stray site behind."""
    if pop_name is None:
        _check_pop(conn, pop_id)
        return pop_id
    made = conn.execute(text("INSERT INTO pops (tenant_id, name, created_by) VALUES (:t,btrim(:n),:by) ON CONFLICT DO NOTHING RETURNING id"),
                        {"t": p.tenant_id, "n": pop_name, "by": p.id}).scalar_one_or_none()
    if made is not None:
        audit(conn, p, "fleet.pop.created", "pop", str(made), {"name": pop_name.strip(), "via": "olt_form"})
        return made
    return conn.execute(text("SELECT id FROM pops WHERE lower(name) = lower(btrim(:n))"), {"n": pop_name}).scalar_one()


@router.post("/v1/fleet/olts", status_code=201)
def register_olt(body: OltIn, p: Principal = Depends(require("fleet:manage")), conn: Connection = TENANT_CONN) -> dict:
    _flag(conn, p)
    if conn.execute(text("SELECT 1 FROM edges WHERE id = :i"), {"i": body.edge_id}).first() is None:
        raise HTTPException(404, "edge not found")
    cx = _merged({}, body, body.snmp_version)   # 422 with a stable code when the fields contradict each other (e.g. a fingerprint for Telnet)
    pop_id = _resolve_pop(conn, p, body.pop_id, body.pop_name)
    limits.enforce(conn, p.tenant_id, "olts")   # ADR-0047 D3: 409 limit_reached; what already exists is never touched
    new_id = conn.execute(
        text("INSERT INTO olts (tenant_id, edge_id, name, vendor, support_level, credential_secret_ref, pop_id, label, mgmt_address, snmp_version, registered_by, registered_at, "
             "mgmt_protocol, mgmt_port, mgmt_transport, snmp_port, host_key_sha256, ssh_mode, legacy_ssh) "
             "VALUES (:t,:e,:n,:v,'identified',:c,:pop,:l,CAST(:a AS inet),:sv,:by,:at,:mp,:mport,:mt,:sp,:hk,:sm,:ls) ON CONFLICT (tenant_id, name) DO NOTHING RETURNING id"),
        {"t": p.tenant_id, "e": body.edge_id, "n": body.name, "v": body.vendor, "c": body.credential_ref, "pop": pop_id, "l": body.label, "a": body.mgmt_address, "sv": body.snmp_version,
         "by": p.id, "at": datetime.now(UTC), "mp": cx["mgmt_protocol"], "mport": cx["mgmt_port"], "mt": cx["mgmt_transport"], "sp": cx["snmp_port"], "hk": cx["host_key_sha256"], "sm": cx["ssh_mode"],
         "ls": cx["legacy_ssh"]}).scalar_one_or_none()
    if new_id is None:
        raise HTTPException(409, "olt_name_taken")
    audit(conn, p, "fleet.olt.registered", "olt", str(new_id), {"name": body.name, "vendor": body.vendor, "pop": str(pop_id) if pop_id else None,
                                                                "has_credential_ref": body.credential_ref is not None, "has_mgmt_address": body.mgmt_address is not None,
                                                                "snmp_version": body.snmp_version, "mgmt_protocol": cx["mgmt_protocol"], "mgmt_transport": cx["mgmt_transport"],
                                                                "has_host_key": cx["host_key_sha256"] is not None})   # no secret NAME, address, port or fingerprint is logged
    return _olt_view(conn.execute(text(_OLT_SQL + "WHERE o.id = :i"), {"i": new_id}).one())


@router.patch("/v1/fleet/olts/{olt_id}")
def update_olt(olt_id: UUID, body: OltPatch, p: Principal = Depends(require("fleet:manage")), conn: Connection = TENANT_CONN) -> dict:
    _flag(conn, p)
    sent = body.model_fields_set
    if not sent:
        raise HTTPException(422, "nothing to change")
    old = conn.execute(text("SELECT host(mgmt_address) AS mgmt_address, snmp_version, mgmt_protocol, mgmt_port, mgmt_transport, snmp_port, host_key_sha256, ssh_mode, legacy_ssh "
                            "FROM olts WHERE id = :i FOR UPDATE"), {"i": olt_id}).first()
    if old is None:
        raise HTTPException(404, "olt not found")
    sets, args = [], {"i": olt_id}
    new_cx = _merged(dict(old._mapping), body, body.snmp_version if "snmp_version" in sent else old.snmp_version)   # the rules between the fields hold on the state the OLT WILL have
    conn_changed = False
    for k in fleet.CONN_FIELDS:
        if new_cx[k] != (bool(old._mapping[k]) if k == "legacy_ssh" else old._mapping[k]):
            sets.append(f"{k} = :{k}")
            args[k] = new_cx[k]
            conn_changed = True
    if "mgmt_address" in sent and (None if body.mgmt_address is None else ipaddress.ip_address(body.mgmt_address)) != (None if old.mgmt_address is None else ipaddress.ip_address(old.mgmt_address)):
        conn_changed = True
    if "pop_name" in sent and body.pop_name is not None:
        sets.append("pop_id = :pop_id")
        args["pop_id"] = _resolve_pop(conn, p, None, body.pop_name)
    elif "pop_id" in sent:
        _check_pop(conn, body.pop_id)
        sets.append("pop_id = :pop_id")
        args["pop_id"] = body.pop_id
    for field, col in (("credential_ref", "credential_secret_ref"), ("label", "label"), ("snmp_version", "snmp_version")):
        if field in sent:   # an explicit null clears the field
            sets.append(f"{col} = :{field}")
            args[field] = getattr(body, field)
    if "mgmt_address" in sent:
        sets.append("mgmt_address = CAST(:mgmt_address AS inet)")
        args["mgmt_address"] = body.mgmt_address
    if not sets:   # only a null pop_name was sent
        raise HTTPException(422, "nothing to change")
    goes_telnet = new_cx["mgmt_protocol"] == "telnet" and old.mgmt_protocol != "telnet"
    if goes_telnet or conn_changed:
        # What is already IN FLIGHT (leased to the Edge, answer pending) cannot be recalled: the Edge may apply it. So the change waits for it (409): the lease lasts at most 5 minutes.
        # A connection leased to the Edge blocks any change of how the OLT is reached; going to Telnet is blocked by a lease of ANY kind.
        # What is merely waiting is cancelled below, under the OLT row lock `next` also takes (Codex r1).
        busy = conn.execute(text("SELECT 1 FROM olt_secret_deliveries WHERE olt_id = :o AND status = 'DISPATCHED' AND lease_until > now() AND (CAST(:all AS boolean) OR kind = :k) LIMIT 1"),
                            {"o": olt_id, "all": goes_telnet, "k": olt_secrets.CONNECTION_KIND}).first()
        if busy is not None:
            raise HTTPException(409, "delivery_in_flight")
    conn.execute(text(f"UPDATE olts SET {', '.join(sets)} WHERE id = :i"), args)  # noqa: S608  (column names come from a fixed list)  the trigger of migration 0051 demotes the trust when how-it-is-reached changed
    cancelled = 0
    if goes_telnet:   # ADR-0046 D3(b): Telnet is inventory: whatever waited for the Edge (any kind) is cancelled and its blob erased
        cancelled = _cancel_waiting(conn, olt_id, None, "protocol_changed")
    elif conn_changed:   # a connection sealed for the OLD way of reaching it must not reach the Edge
        cancelled = _cancel_waiting(conn, olt_id, olt_secrets.CONNECTION_KIND, "connection_changed")
    ev = {"fields": sorted(sent), "cancelled_deliveries": cancelled} if cancelled else {"fields": sorted(sent)}   # field NAMES and a count only, never the address, a port or the secret name
    audit(conn, p, "fleet.olt.updated", "olt", str(olt_id), ev)
    return _olt_view(conn.execute(text(_OLT_SQL + "WHERE o.id = :i"), {"i": olt_id}).one())


# ---- PR2 part B: the connection test. It is NOT a channel of its own: it is the closed read `olt.connection` (the same `display version` already validated) asked through the existing
# `olt_query` job engine, so it keeps every gate, the Edge lease/queue and the cache-first rule. On top, the budget the owner approved (ADR-0041 §4.1): ONE test per OLT every 15 minutes and
# FOUR per hour, counted here (and again at the Edge). A fresh stored identity answers without touching the equipment and spends nothing.
TEST_QUERY = "olt.connection"
TEST_GAP = timedelta(minutes=15)
TEST_PER_HOUR = 4


def _norm(v: str | None) -> str:
    return "".join(ch for ch in (v or "").lower() if ch.isalnum())


def _identity(olt, data: dict) -> dict:
    """What the OLT said about itself (typed, from the read) next to what the registration/collection already knew. `vendor` is the registered one: `display version` does not name it."""
    known = olt.model is not None and olt.firmware is not None
    return {"vendor": olt.vendor, "model": data["product"], "firmware": data["version"], "patch": data["patch"], "uptime_seconds": data["uptime_seconds"],
            "matches_collected": (_norm(olt.model) == _norm(data["product"]) and _norm(olt.firmware) == _norm(data["version"])) if known else None}


def _budget(conn: Connection, olt_id: UUID) -> dict:
    now = conn.execute(text("SELECT now()")).scalar()
    ts = [r[0] for r in conn.execute(text("SELECT requested_at FROM olt_connection_tests WHERE olt_id = :o AND outcome = 'submitted' AND requested_at > now() - interval '1 hour' "
                                          "ORDER BY requested_at DESC"), {"o": olt_id}).all()]
    wait = 0.0
    if ts and now - ts[0] < TEST_GAP:
        wait = max(wait, (ts[0] + TEST_GAP - now).total_seconds())
    if len(ts) >= TEST_PER_HOUR:
        wait = max(wait, (ts[TEST_PER_HOUR - 1] + timedelta(hours=1) - now).total_seconds())
    return {"used_last_hour": len(ts), "max_per_hour": TEST_PER_HOUR, "gap_minutes": int(TEST_GAP.total_seconds() // 60), "wait_seconds": int(wait) + (1 if wait > 0 else 0)}


@router.post("/v1/fleet/olts/{olt_id}/connection-test")
def connection_test(olt_id: UUID, idempotency_key: str | None = Header(None, alias="Idempotency-Key", min_length=8, max_length=128, pattern=r"^[A-Za-z0-9_.:-]+$"),
                    p: Principal = Depends(require("fleet:test")), conn: Connection = TENANT_CONN) -> dict:
    from app.api import jobs
    from app.core import olt_cache, olt_query
    _flag(conn, p)
    if not (p.can("jobs:request") and p.can("jobs:read")):
        raise HTTPException(403, "forbidden")
    olt = conn.execute(text("SELECT id, vendor, model, firmware, mgmt_protocol FROM olts WHERE id = :i"), {"i": olt_id}).first()
    if olt is None:
        raise HTTPException(404, "olt not found")
    if olt.mgmt_protocol == "telnet":   # ADR-0046 D3 (Codex r4): Telnet is inventory, nothing operational is asked of it (no protocol = the Edge's own config: still testable)
        raise HTTPException(422, "protocol_not_supported")
    reason = jobs._query_gate(conn, p.tenant_id, {"query_id": TEST_QUERY})   # the very gates of any olt_query: flag, rollout, Edge channel
    if reason is not None:
        raise HTTPException(409, reason)
    hit = olt_cache.latest(conn, olt_id, TEST_QUERY, "")
    if hit is not None and not hit["stale"] and hit.get("source") == "job" and olt_query.check_result(TEST_QUERY, hit["data"]):
        conn.execute(text("INSERT INTO olt_connection_tests (tenant_id, olt_id, outcome, requested_by) VALUES (:t,:o,'cached',:by)"), {"t": p.tenant_id, "o": olt_id, "by": p.id})
        return {"outcome": "cached", "identity": _identity(olt, hit["data"]), "asked_at": hit["asked_at"], "age_seconds": hit["age_seconds"]}
    conn.execute(text("SELECT pg_advisory_xact_lock(hashtextextended(:k, 0))"), {"k": f"fleet-test:{olt_id}"})   # the count below and the row that spends the budget are one step
    if idempotency_key is not None and conn.execute(text("SELECT 1 FROM jobs WHERE idempotency_key = :k"), {"k": idempotency_key}).first() is not None:
        # a retry of a request already accepted: answered from the job it created BEFORE the budget (which that very request raised), and refused if the key was used for another intent
        view = jobs.create_preview(jobs.PreviewIn(operation="olt_query", target_id=olt_id, params={"query_id": TEST_QUERY}), idempotency_key, p, conn, fleet_test=True)
        return {"outcome": "existing", "job_id": view["id"], "job_status": view["status"], "budget": _budget(conn, olt_id)}
    b = _budget(conn, olt_id)
    if b["wait_seconds"] > 0:
        raise HTTPException(429, "test_budget", headers={"Retry-After": str(b["wait_seconds"])})
    view = jobs.create_preview(jobs.PreviewIn(operation="olt_query", target_id=olt_id, params={"query_id": TEST_QUERY}), idempotency_key or f"fleet-{uuid4().hex}", p, conn, fleet_test=True)
    if view["status"] != "PREVIEWED":   # the same key again: nothing new is created and nothing is spent
        return {"outcome": "existing", "job_status": view["status"], "budget": b}
    view = jobs.submit(UUID(view["id"]), p, conn)
    conn.execute(text("INSERT INTO olt_connection_tests (tenant_id, olt_id, job_id, outcome, requested_by) VALUES (:t,:o,:j,'submitted',:by)"),
                 {"t": p.tenant_id, "o": olt_id, "j": view["id"], "by": p.id})
    audit(conn, p, "fleet.olt.connection_test", "olt", str(olt_id), {"job_id": view["id"]})
    return {"outcome": "submitted", "job_status": view["status"], "budget": _budget(conn, olt_id)}


@router.get("/v1/fleet/olts/{olt_id}/connection-tests")
def connection_tests(olt_id: UUID, p: Principal = Depends(require("fleet:read")), conn: Connection = TENANT_CONN) -> dict:
    from app.core import olt_cache, olt_query
    _flag(conn, p)
    olt = conn.execute(text("SELECT id, vendor, model, firmware FROM olts WHERE id = :i"), {"i": olt_id}).first()
    if olt is None:
        raise HTTPException(404, "olt not found")
    rows = conn.execute(text("SELECT t.id, t.outcome, t.requested_at, j.status AS job_status FROM olt_connection_tests t LEFT JOIN jobs j ON j.id = t.job_id "
                             "WHERE t.olt_id = :o ORDER BY t.requested_at DESC LIMIT 10"), {"o": olt_id}).all()
    hit = olt_cache.latest(conn, olt_id, TEST_QUERY, "")
    latest = None
    if hit is not None and hit.get("source") == "job" and olt_query.check_result(TEST_QUERY, hit["data"]):
        latest = {"identity": _identity(olt, hit["data"]), "asked_at": hit["asked_at"], "age_seconds": hit["age_seconds"], "stale": hit["stale"]}
    return {"items": [{"id": str(r.id), "outcome": r.outcome, "requested_at": r.requested_at.isoformat(), "job_status": r.job_status} for r in rows], "latest": latest, "budget": _budget(conn, olt_id)}
