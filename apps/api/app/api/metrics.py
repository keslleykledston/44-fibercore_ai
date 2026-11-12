"""GET /metrics: Prometheus scrape of the API's own RED metrics (ADR-0042).

Off unless METRICS_TOKEN is set (>= 32 chars): without it the route answers 404, like any path that does not exist. With it, the scraper must send `Authorization: Bearer <token>`.
The reverse proxies also refuse `/metrics` and `/api/metrics`; the token is the second lock, not the only one. Nothing here touches the database.
"""
from __future__ import annotations

import hmac
import time

from fastapi import APIRouter, Depends, Request
from fastapi.responses import PlainTextResponse

from app import __version__
from app.core.metrics import Registry
from app.core.settings import Settings, get_settings

router = APIRouter()
REGISTRY = Registry()
STARTED_AT = time.time()
CONTENT_TYPE = "text/plain; version=0.0.4; charset=utf-8"


@router.get("/metrics", include_in_schema=False)
def metrics(request: Request, settings: Settings = Depends(get_settings)) -> PlainTextResponse:
    token = settings.metrics_token
    if not token:
        return PlainTextResponse("not found", status_code=404)
    scheme, _, presented = request.headers.get("authorization", "").partition(" ")
    if scheme.lower() != "bearer" or not hmac.compare_digest(presented.strip().encode(), token.encode()):
        return PlainTextResponse("unauthorized", status_code=401, headers={"WWW-Authenticate": "Bearer"})
    return PlainTextResponse(REGISTRY.render(version=__version__, started_at=STARTED_AT), media_type=CONTENT_TYPE, headers={"Cache-Control": "no-store"})
