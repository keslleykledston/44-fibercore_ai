"""Module registry with real runtime probes.

Status vocabulary (contract ModuleHealth): healthy | degraded | unhealthy | disabled | unknown.
A module is `healthy` only if it has a runtime implementation in this build AND its
probes pass. Manifest-only modules are reported `unknown` (reason: not implemented), never faked healthy.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

import httpx
import yaml
from sqlalchemy import text
from sqlalchemy.engine import Engine

# Modules with code in this build. Extend as each module lands (and add a probe/test).
IMPLEMENTED = {"identity-access", "platform-manager", "edge-fleet"}


@dataclass(frozen=True)
class Infra:
    postgres: bool
    nats: bool | None  # None = not configured


def load_manifest(path: Path) -> list[dict]:
    return yaml.safe_load(path.read_text(encoding="utf-8")).get("modules", [])


def probe_postgres(engine: Engine | None) -> bool:
    if engine is None:
        return False
    try:
        with engine.connect() as c:
            return c.execute(text("SELECT 1")).scalar() == 1
    except Exception:
        return False


def probe_nats(monitor_url: str) -> bool | None:
    if not monitor_url:
        return None
    try:
        return httpx.get(monitor_url.rstrip("/") + "/healthz", timeout=2.0).status_code == 200
    except httpx.HTTPError:
        return False


def evaluate(manifest: list[dict], infra: Infra) -> list[dict]:
    now = datetime.now(UTC).isoformat()
    by_id = {m["id"]: m for m in manifest}
    out: list[dict] = []

    def infra_state(dep: str) -> bool | None:
        return {"postgres": infra.postgres, "nats": infra.nats}.get(dep)

    def status_of(m: dict) -> tuple[str, str]:
        if m.get("feature_flag") is False:
            return "disabled", "feature flag off"
        if m["id"] not in IMPLEMENTED:
            return "unknown", "not implemented: declared in manifest, no runtime in this build"
        for dep in m.get("requires", []):
            if dep in by_id:
                st, _ = status_of(by_id[dep])
                if st != "healthy":
                    return "unhealthy", f"required module {dep} is {st}"
            elif infra_state(dep) is not True:
                return "unhealthy", f"required dependency {dep} unavailable"
        for dep in m.get("optional_dependencies", []):
            if dep in by_id:
                continue  # optional modules degrade only via explicit infra signals
            if infra_state(dep) is False:
                return "degraded", f"optional dependency {dep} unavailable (failure_mode={m.get('failure_mode')})"
        return "healthy", "probes passed"

    for m in manifest:
        st, reason = status_of(m)
        out.append(
            {
                "id": m["id"],
                "version": m["version"],
                "status": st,
                "capabilities": m.get("capabilities", []),
                "checked_at": now,
                "reason": reason,
            }
        )
    return out
