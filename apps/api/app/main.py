from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.responses import JSONResponse

from app import __version__
from app.api.context import router as context_router
from app.api.cpe_state import router as cpe_state_router
from app.api.diagnostic_jobs import router as diagnostic_jobs_router
from app.api.diagnostics import router as diagnostics_router
from app.api.erp import router as erp_router
from app.api.inventory import router as inventory_router
from app.api.jobs import router as jobs_router
from app.api.bench_authorizations import router as bench_auth_router
from app.api.delegations import router as delegations_router
from app.api.device_actions import router as device_actions_router
from app.api.members import router as members_router
from app.api.team import router as team_router
from app.api.noc import router as noc_router
from app.api.routes import router
from app.api.session import router as session_router
from app.core.settings import get_settings, required_mfa_roles

logging.basicConfig(level=logging.INFO, format='{"ts":"%(asctime)s","level":"%(levelname)s","logger":"%(name)s","msg":"%(message)s"}')



@asynccontextmanager
async def lifespan(_app: FastAPI):
    # fail closed: a typo in MFA_REQUIRED_ROLES stops the API from booting instead of silently weakening the policy
    required_mfa_roles(get_settings())
    if not get_settings().mfa_recent_enforce:  # an explicit, visible exception (ADR-0031): the default is ON
        logging.getLogger("fibercore.security").warning("MFA_RECENT_ENFORCE is off: critical actions do not ask for a recent second factor")
    yield


app = FastAPI(title="FiberCore AI API", version=__version__, docs_url=None, redoc_url=None, lifespan=lifespan)
MAX_BODY_BYTES = 8 * 1024 * 1024


@app.middleware("http")
async def limit_body(request, call_next):
    # Cheap DoS guard; Content-Length is mandatory for bodies (chunked uploads are refused).
    if request.method in ("POST", "PUT", "PATCH"):
        length = request.headers.get("content-length")
        if length is None and request.headers.get("transfer-encoding"):
            return JSONResponse({"detail": "chunked bodies not accepted"}, status_code=411)
        if length is not None and (not length.isdigit() or int(length) > MAX_BODY_BYTES):
            return JSONResponse({"detail": "payload too large"}, status_code=413)
    return await call_next(request)


app.include_router(router)
app.include_router(session_router)
app.include_router(inventory_router)
app.include_router(erp_router)
app.include_router(noc_router)
app.include_router(jobs_router)
app.include_router(members_router)
app.include_router(team_router)
app.include_router(delegations_router)
app.include_router(bench_auth_router)
app.include_router(device_actions_router)
app.include_router(context_router)
app.include_router(diagnostics_router)
app.include_router(diagnostic_jobs_router)
app.include_router(cpe_state_router)
