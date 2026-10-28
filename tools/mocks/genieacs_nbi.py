"""Mock GenieACS NBI (READ-ONLY). For contract tests only; never point at / replace a real GenieACS.

Supports GET /devices with `projection` (top-level keys) and an equality-only Mongo-style `query`.
Any non-GET method returns 405, mirroring the Edge's read-only policy.
"""
from __future__ import annotations

import json
from pathlib import Path

from fastapi import FastAPI, HTTPException, Query, Request

FIXTURE = Path(__file__).resolve().parents[2] / "tests" / "fixtures" / "genieacs" / "devices.json"


def create_app(devices: list[dict] | None = None) -> FastAPI:
    data = devices if devices is not None else json.loads(FIXTURE.read_text(encoding="utf-8"))
    app = FastAPI(docs_url=None, redoc_url=None)

    @app.api_route("/{path:path}", methods=["POST", "PUT", "PATCH", "DELETE"])
    def deny_writes(path: str, request: Request):
        raise HTTPException(405, "mock NBI is read-only")

    @app.get("/devices")
    def devices_ep(query: str | None = None, projection: str | None = Query(default=None)) -> list[dict]:
        rows = data
        if query:
            q = json.loads(query)
            rows = [d for d in rows if all(d.get(k) == v for k, v in q.items())]
        if projection:
            keys = {k.strip().split(".")[0] for k in projection.split(",")}
            rows = [{k: v for k, v in d.items() if k in keys} for d in rows]
        return rows

    return app


app = create_app()
