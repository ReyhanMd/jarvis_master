"""Disk JSON cache backend (Phase 2 — last fallback, no dependencies).

One JSON file per query hash under a configured directory.
Suitable for development or when neither Redis nor SQLite is desired.
"""
from __future__ import annotations

import json
import logging
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


class DiskCacheBackend:
    def __init__(self, cache_dir: str) -> None:
        self._dir = Path(cache_dir).expanduser()
        self._dir.mkdir(parents=True, exist_ok=True)

    def _path(self, query_hash: str) -> Path:
        return self._dir / f"{query_hash}.json"

    def get(self, query_hash: str) -> Optional[List[Dict[str, Any]]]:
        p = self._path(query_hash)
        if not p.exists():
            return None
        try:
            data = json.loads(p.read_text("utf-8"))
            if time.time() - data["created_at"] > data["ttl_sec"]:
                p.unlink(missing_ok=True)
                return None
            return data["hits"]
        except Exception as exc:
            logger.debug("DiskCacheBackend.get failed: %s", exc)
            return None

    def set(self, query_hash: str, namespace: str, hits: List[Dict[str, Any]], ttl_sec: int) -> None:
        try:
            payload = {"hits": hits, "namespace": namespace, "created_at": time.time(), "ttl_sec": ttl_sec}
            self._path(query_hash).write_text(json.dumps(payload), "utf-8")
        except Exception as exc:
            logger.debug("DiskCacheBackend.set failed: %s", exc)

    def invalidate_namespace(self, namespace: str) -> int:
        count = 0
        for p in self._dir.glob("*.json"):
            try:
                data = json.loads(p.read_text("utf-8"))
                if data.get("namespace") == namespace:
                    p.unlink(missing_ok=True)
                    count += 1
            except Exception:
                pass
        return count

    def purge_expired(self) -> int:
        count = 0
        now = time.time()
        for p in self._dir.glob("*.json"):
            try:
                data = json.loads(p.read_text("utf-8"))
                if now - data.get("created_at", 0) > data.get("ttl_sec", 3600):
                    p.unlink(missing_ok=True)
                    count += 1
            except Exception:
                p.unlink(missing_ok=True)
                count += 1
        return count

    def size_bytes(self) -> int:
        return sum(p.stat().st_size for p in self._dir.glob("*.json") if p.exists())
