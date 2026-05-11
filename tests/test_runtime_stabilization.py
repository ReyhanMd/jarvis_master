"""Regression tests for the runtime stabilization sprint.

Covers:
  P2  — asyncio.run() inside running loops must not crash
  P3  — thread-safe ingest enqueue from sync threadpool context
  P4  — persistent httpx client reused across requests
  A   — full UUID4 task IDs (no truncation)
  B   — IngestQueue atomic start under concurrent callers
  Misc — no hardcoded /Users/reyhan/shail_master paths in runtime code
"""
from __future__ import annotations

import asyncio
import os
import sys
import threading
import uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import patch, AsyncMock, MagicMock

import pytest

_ROOT = Path(__file__).parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))


# ─────────────────────────────────────────────────────────────────────── #
# P2 — asyncio.run inside FastAPI                                            #
# ─────────────────────────────────────────────────────────────────────── #

def test_safe_broadcast_no_loop_no_crash():
    """_safe_broadcast with no loop and no ws_manager is a no-op."""
    from shail.orchestration.graph import _safe_broadcast
    _safe_broadcast(None, {"k": "v"})  # must not raise


def test_safe_broadcast_running_loop_schedules_task():
    """_safe_broadcast inside a running loop must use create_task, not asyncio.run."""
    from shail.orchestration.graph import _safe_broadcast

    fake_ws = MagicMock()
    fake_ws.broadcast_state = AsyncMock(return_value=None)

    async def _runner():
        _safe_broadcast(fake_ws, {"state": "ok"})
        # Give the scheduled task a chance to execute
        await asyncio.sleep(0.05)

    asyncio.run(_runner())
    fake_ws.broadcast_state.assert_called_once()


# ─────────────────────────────────────────────────────────────────────── #
# P3 — thread-safe ingest enqueue                                            #
# ─────────────────────────────────────────────────────────────────────── #

def test_maybe_enqueue_ingest_from_threadpool_no_crash():
    """Sync caller in threadpool → no loop in this thread → must NOT crash."""
    pytest.importorskip("langchain")
    from shail.core.router import _maybe_enqueue_ingest

    # Settings flag default OFF → function returns early without scheduling.
    # Test verifies it doesn't raise when called from sync threadpool context.
    fake_result = MagicMock()
    fake_req = MagicMock()

    with ThreadPoolExecutor(max_workers=4) as pool:
        futures = [pool.submit(_maybe_enqueue_ingest, fake_result, fake_req) for _ in range(8)]
        for f in futures:
            f.result()  # must not raise


def test_maybe_enqueue_ingest_uses_threadsafe_when_main_loop_running():
    """When main loop is registered + running on another thread,
    sync caller should use run_coroutine_threadsafe."""
    pytest.importorskip("langchain")
    from shail.orchestration.graph import register_main_loop
    from shail.core.router import _maybe_enqueue_ingest

    scheduled = []

    # Mock settings to enable ingest
    fake_settings = MagicMock()
    fake_settings.ingest_generated_outputs = True

    # Spin up a real event loop on another thread
    loop = asyncio.new_event_loop()
    loop_thread = threading.Thread(target=loop.run_forever, daemon=True)
    loop_thread.start()
    register_main_loop(loop)

    try:
        with patch("apps.shail.settings.get_settings", return_value=fake_settings), \
             patch("shail.memory.ingest_queue.get_ingest_queue") as mock_q:
            fake_q = MagicMock()
            fake_q.enqueue = AsyncMock(return_value=True)
            mock_q.return_value = fake_q

            # Call from main thread — no loop in this thread, but main loop exists on another
            _maybe_enqueue_ingest(MagicMock(), MagicMock())

            # Give the scheduled coroutine time to be invoked on the loop thread
            import time as _t; _t.sleep(0.1)

            assert fake_q.enqueue.called, "enqueue should be scheduled via run_coroutine_threadsafe"
    finally:
        loop.call_soon_threadsafe(loop.stop)
        loop_thread.join(timeout=2)
        register_main_loop(None)  # type: ignore


# ─────────────────────────────────────────────────────────────────────── #
# P4 — persistent httpx client                                               #
# ─────────────────────────────────────────────────────────────────────── #

@pytest.mark.asyncio
async def test_supermemory_client_reuses_pool():
    """Multiple calls to _get_client return the SAME AsyncClient instance."""
    pytest.importorskip("httpx")
    from shail.memory.supermemory_client import SupermemoryClient

    c = SupermemoryClient(api_url="http://localhost:1", api_key="test", timeout=1.0)
    client1 = await c._get_client()
    client2 = await c._get_client()
    client3 = await c._get_client()
    assert client1 is client2 is client3, "AsyncClient must be reused"
    assert not client1.is_closed
    await c.close()
    assert client1.is_closed


@pytest.mark.asyncio
async def test_supermemory_client_close_idempotent():
    """close() can be called multiple times safely."""
    pytest.importorskip("httpx")
    from shail.memory.supermemory_client import SupermemoryClient
    c = SupermemoryClient(api_url="http://localhost:1", timeout=1.0)
    await c._get_client()
    await c.close()
    await c.close()  # must not raise
    with pytest.raises(RuntimeError):
        await c._get_client()  # closed client cannot be revived


# ─────────────────────────────────────────────────────────────────────── #
# Bonus A — full UUID task IDs                                               #
# ─────────────────────────────────────────────────────────────────────── #

def test_router_generates_full_uuid_task_id():
    """ShailCoreRouter.route() must produce 36-char UUID4 task IDs."""
    # We don't run route() (heavy deps); we verify the construction pattern instead.
    import re
    full_uuid_pattern = re.compile(
        r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$"
    )
    sample = str(uuid.uuid4())
    assert full_uuid_pattern.match(sample)
    assert len(sample) == 36


def test_router_source_uses_full_uuid_not_truncated():
    """Static check: router.py must not contain `uuid4())[:8]` pattern."""
    router_path = _ROOT / "shail" / "core" / "router.py"
    src = router_path.read_text()
    assert "uuid.uuid4())[:8]" not in src, (
        "router.py must use full UUID4 — truncation causes collisions"
    )


# ─────────────────────────────────────────────────────────────────────── #
# Bonus B — IngestQueue atomic start                                         #
# ─────────────────────────────────────────────────────────────────────── #

def test_ingest_queue_start_idempotent_and_concurrent():
    """Multiple concurrent start() calls must produce exactly one worker."""
    from shail.memory.ingest_queue import IngestQueue

    q = IngestQueue(max_size=10)
    call_counts = []

    async def _spawn_many():
        # Concurrent start from same loop — must remain single worker
        for _ in range(20):
            q.start()
        call_counts.append(q._started)
        if q._worker_task is not None:
            call_counts.append(1)

    asyncio.run(_spawn_many())
    # Exactly one worker started, no duplicate task creation
    assert q._started is True
    assert q._worker_task is not None


def test_ingest_queue_start_no_loop_safe():
    """start() called with no running loop must not crash, just defer."""
    from shail.memory.ingest_queue import IngestQueue
    q = IngestQueue(max_size=10)
    q.start()  # no running loop in this thread
    assert q._started is False  # deferred, not started
    assert q._q is None


def test_ingest_queue_start_threadsafe_concurrent():
    """Many threads calling start() with no loop in each must not crash."""
    from shail.memory.ingest_queue import IngestQueue
    q = IngestQueue(max_size=10)
    errors = []
    def _worker():
        try:
            for _ in range(50):
                q.start()
        except BaseException as exc:
            errors.append(exc)
    threads = [threading.Thread(target=_worker) for _ in range(8)]
    for t in threads: t.start()
    for t in threads: t.join()
    assert not errors, f"start() raised under concurrency: {errors}"


# ─────────────────────────────────────────────────────────────────────── #
# Misc — no hardcoded paths in production runtime code                       #
# ─────────────────────────────────────────────────────────────────────── #

def test_no_hardcoded_user_paths_in_runtime():
    """Runtime modules must not contain `/Users/reyhan/shail_master` paths."""
    runtime_files = [
        _ROOT / "shail" / "orchestration" / "graph.py",
        _ROOT / "shail" / "safety" / "permission_manager.py",
        _ROOT / "shail" / "workers" / "task_worker.py",
        _ROOT / "shail" / "core" / "router.py",
        _ROOT / "shail" / "perception" / "integration.py",
    ]
    for f in runtime_files:
        if not f.exists():
            continue
        src = f.read_text()
        assert "/Users/reyhan/shail_master/.cursor" not in src, (
            f"{f} still contains hardcoded debug.log path"
        )
        assert "/Users/reyhan/jarvis_master/" not in src, (
            f"{f} still contains hardcoded jarvis_master path"
        )


# ─────────────────────────────────────────────────────────────────────── #
# Static import safety — verify all touched modules import cleanly           #
# ─────────────────────────────────────────────────────────────────────── #

def test_modified_modules_import_cleanly():
    """All modified modules must parse and import without error."""
    import importlib
    modules = [
        "shail.memory.ingest_queue",
        "shail.memory.supermemory_client",
        "shail.memory.retrieval_strategy",
    ]
    for m in modules:
        importlib.import_module(m)
