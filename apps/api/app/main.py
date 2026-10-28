from __future__ import annotations

import logging

from fastapi import FastAPI
from fastapi.responses import JSONResponse

from app import __version__
from app.api.erp import router as erp_router
from app.api.inventory import router as inventory_router
from app.api.noc import router as noc_router
from app.api.routes import router

logging.basicConfig(level=logging.INFO, format='{"ts":"%(asctime)s","level":"%(levelname)s","logger":"%(name)s","msg":"%(message)s"}')

app = FastAPI(title="FiberCore AI API", version=__version__, docs_url=None, redoc_url=None)
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
app.include_router(inventory_router)
app.include_router(erp_router)
app.include_router(noc_router)
