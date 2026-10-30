"""Actions on a CPE from its screen (phase "Dispositivos", delivery 4; ADR-0031 `devices:act:*`).

This adds NO way to write to equipment. A request here is exactly the job the existing engine already knows (preview, then submit); everything after
it is unchanged: the write gate (HOMOLOGATED_WRITES stays empty, so only ADR-0030's bench path can open), another person's approval, the signed
envelope, the Edge's own refusals and the post-check. What this layer adds is the screen's contract: which actions this CPE offers to this caller,
and a request that is refused BEFORE a job exists unless the registry holds an `observed` (or better) entry for the CPE's exact profile.
"""
from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import Connection, text

from app.api import jobs
from app.api.deps import TENANT_CONN, Principal, require
from app.api.inventory import _capabilities
from app.api.routes import audit
from app.core import bench

router = APIRouter()

# the operations the CPE screen can ask for, with the label shown to people. Anything else is not offered here.
ACTIONS: dict[str, dict] = {
    "reboot_cpe": {"label": "Reiniciar o equipamento", "params": False},
    "set_wifi_ssid": {"label": "Trocar o nome do Wi-Fi (2,4 GHz)", "params": True},
}
OBSERVED = ("observed", "certified")


def _profile_entry(caps: list[dict], operation: str) -> dict | None:
    return next((c for c in caps if c["name"] == operation), None)


def _availability(p: Principal, caps: list[dict], operation: str) -> tuple[bool, str | None]:
    """(offered, reason): the same decision the request applies, so the screen never offers what the request would refuse."""
    if not (p.can(f"devices:act:{operation}") and p.can("jobs:request")):
        return False, "not_permitted"
    entry = _profile_entry(caps, operation)
    if entry is None or entry["status"] != "supported" or entry["certification"] not in OBSERVED:
        return False, "capability_not_observed"
    return True, None


def _cpe_or_404(conn: Connection, cpe_id: UUID):
    c = conn.execute(text("SELECT id, vendor, model, firmware FROM cpes WHERE id = :i"), {"i": cpe_id}).first()
    if c is None:
        raise HTTPException(404, "cpe not found")
    return c


@router.get("/v1/cpes/{cpe_id}/actions")
def list_actions(cpe_id: UUID, p: Principal = Depends(require("inventory:read")), conn: Connection = TENANT_CONN) -> dict:
    c = _cpe_or_404(conn, cpe_id)
    caps = _capabilities(conn, p.tenant_id, "cpe", c.vendor, c.model, c.firmware)
    is_bench = bool(conn.execute(text("SELECT 1 FROM bench_targets WHERE cpe_id = :c"), {"c": cpe_id}).first())
    items = []
    for op, meta in ACTIONS.items():
        offered, reason = _availability(p, caps, op)
        entry = _profile_entry(caps, op)
        items.append({
            "operation": op, "label": meta["label"], "risk": jobs.OPERATIONS[op].risk, "needs_params": meta["params"],
            "offered": offered, "reason": reason,
            "certification": entry["certification"] if entry else "identified", "status": entry["status"] if entry else "unknown",
            # what the engine will say about it when requested: homologated writes are none, so only a bench target with the owner's prior authorization opens
            "homologated": op in jobs.HOMOLOGATED_WRITES, "bench_target": is_bench,
        })
    return {"cpe_id": str(cpe_id), "items": items}


class ActionIn(BaseModel):
    params: dict = Field(default_factory=dict)


def _request(operation: str):
    perm = f"devices:act:{operation}"

    def handler(
        cpe_id: UUID, body: ActionIn,
        idempotency_key: str = Header(..., alias="Idempotency-Key", min_length=8, max_length=128, pattern=r"^[A-Za-z0-9_.:-]+$"),
        p: Principal = Depends(require(perm)), conn: Connection = TENANT_CONN,
    ) -> dict:
        if not p.can("jobs:request"):
            raise HTTPException(403, "forbidden")
        c = _cpe_or_404(conn, cpe_id)
        caps = _capabilities(conn, p.tenant_id, "cpe", c.vendor, c.model, c.firmware)
        offered, reason = _availability(p, caps, operation)
        if not offered:
            raise HTTPException(409, reason or "not_available")  # no job exists for an action the screen would not have offered
        if bench.BENCH_OPS[operation].params and not bench.params_valid(operation, body.params):
            raise HTTPException(422, "parameters outside the bench catalog")
        view = jobs.preview(jobs.PreviewIn(operation=operation, target_id=cpe_id, params=body.params), idempotency_key, p, conn)
        if view["status"] != "PREVIEWED":  # the same request again (retry after a lost answer, double click): nothing new is created
            if view["status"] in ("CANCELLED", "EXPIRED"):  # it ended without running: say so, with the reason recorded when it was blocked
                why = conn.execute(
                    text("SELECT evidence_redacted->>'reason' FROM audit_log WHERE action = 'device.action_blocked' AND target_id = :c "
                         "AND evidence_redacted->>'job_id' = :j ORDER BY created_at DESC LIMIT 1"), {"c": str(cpe_id), "j": view["id"]}).scalar()
                return {"outcome": "blocked", "reason": why or "cancelled", "job": view}
            return {"outcome": "existing", "reason": None, "job": view}
        try:
            view = jobs.submit(UUID(view["id"]), p, conn)
        except HTTPException as exc:  # the write gate (or anything the engine refuses): the request ends here, visibly, and leaves no live job
            code = str(exc.detail)
            jobs.cas(conn, UUID(view["id"]), "CANCELLED")
            audit(conn, p, "device.action_blocked", "cpe", str(cpe_id), {"operation": operation, "reason": code, "job_id": view["id"]})
            return {"outcome": "blocked", "reason": code, "job": jobs._view(jobs._load(conn, UUID(view["id"]), lock=False))}
        audit(conn, p, "device.action_requested", "cpe", str(cpe_id), {"operation": operation, "job_id": view["id"]})
        return {"outcome": "submitted", "reason": None, "job": view}

    handler.__name__ = f"request_{operation}"
    return handler


for _op in ACTIONS:
    router.add_api_route(f"/v1/cpes/{{cpe_id}}/actions/{_op}", _request(_op), methods=["POST"], status_code=200)
