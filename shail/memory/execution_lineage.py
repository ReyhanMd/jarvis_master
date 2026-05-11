"""Execution lineage tracker (Phase 5).

Records the agent execution chain + memory provenance per task.
Stored in SharedContextStore under key "lineage".

Usage:
    from shail.memory.execution_lineage import track_agent_step
    await track_agent_step(context_id="task-123", agent="code", wrote_keys=["plan", "output"])
"""
from __future__ import annotations

import time
from typing import Any, Dict, List, Optional


async def track_agent_step(
    context_id: str,
    agent: str,
    *,
    namespace: str = "lineage",
    wrote_keys: Optional[List[str]] = None,
    read_keys: Optional[List[str]] = None,
    metadata: Optional[Dict[str, Any]] = None,
) -> None:
    """Append a lineage entry for one agent step.

    Fire-and-forget: never raises, never blocks.
    """
    try:
        from shail.memory.shared_context import get_shared_context
        store = get_shared_context()
        if not store._enabled:
            return

        existing = await store.read(context_id, namespace, "entries") or []
        entry = {
            "agent":      agent,
            "ts":         time.time(),
            "wrote_keys": wrote_keys or [],
            "read_keys":  read_keys or [],
            "metadata":   metadata or {},
        }
        existing.append(entry)
        await store.write(context_id, namespace, "entries", existing)
    except Exception:
        pass


async def get_lineage(context_id: str) -> List[Dict[str, Any]]:
    """Retrieve full lineage for a task. Returns [] on error."""
    try:
        from shail.memory.shared_context import get_shared_context
        store = get_shared_context()
        return await store.read(context_id, "lineage", "entries") or []
    except Exception:
        return []
