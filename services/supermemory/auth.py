"""API key middleware for SuperMemory sidecar (Phase 4).

Key checked against SUPERMEMORY_SIDECAR_API_KEY env var.
If unset, auth is disabled (development mode).
"""
from __future__ import annotations

import os
from fastapi import HTTPException, Security
from fastapi.security import APIKeyHeader

_API_KEY_HEADER = APIKeyHeader(name="X-API-Key", auto_error=False)
_SIDECAR_KEY = os.getenv("SUPERMEMORY_SIDECAR_API_KEY", "")


def verify_api_key(api_key: str | None = Security(_API_KEY_HEADER)) -> None:
    if not _SIDECAR_KEY:
        return  # auth disabled
    if api_key != _SIDECAR_KEY:
        raise HTTPException(status_code=401, detail="Invalid or missing API key")
