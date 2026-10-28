from __future__ import annotations

import logging

from fastapi import FastAPI

from app import __version__
from app.api.routes import router

logging.basicConfig(level=logging.INFO, format='{"ts":"%(asctime)s","level":"%(levelname)s","logger":"%(name)s","msg":"%(message)s"}')

app = FastAPI(title="FiberCore AI API", version=__version__, docs_url=None, redoc_url=None)
app.include_router(router)
