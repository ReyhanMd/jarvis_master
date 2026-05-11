"""SuperMemory sidecar FastAPI service (Phase 4).

Standalone microservice on port 8005.
SHAIL calls this; it abstracts local-vs-global retrieval and ingest.

Start:
    cd jarvis_master
    uvicorn services.supermemory.service:app --port 8005 --reload

Or via the included shell script:
    ./services/supermemory/start.sh
"""
from __future__ import annotations

import logging
import os
import sys

# Ensure monorepo root is on path when run standalone
_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from services.supermemory.router import router

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s — %(message)s")
logger = logging.getLogger(__name__)

app = FastAPI(
    title="SHAIL SuperMemory Sidecar",
    description="Decoupled memory retrieval + ingest microservice (Phase 4)",
    version="1.0.0",
    docs_url="/docs",
    redoc_url="/redoc",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(router)


@app.on_event("startup")
async def _startup() -> None:
    logger.info("SuperMemory sidecar starting on port 8005")
    try:
        from shail.observability.metrics import init_metrics
        init_metrics()
    except Exception:
        pass


@app.get("/", include_in_schema=False)
def root():
    return {"service": "shail-supermemory-sidecar", "version": "1.0.0", "status": "running"}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("services.supermemory.service:app", host="0.0.0.0", port=8005, reload=True)
