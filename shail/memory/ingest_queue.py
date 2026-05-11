"""Async ingest queue (Phase 3).

Fire-and-forget queue that drains in a background worker coroutine.
Never blocks the main request path. Overflow silently drops (logged).

Usage:
    from shail.memory.ingest_queue import get_ingest_queue
    await get_ingest_queue().enqueue(result, request)
"""
from __future__ import annotations

import asyncio
import logging
from typing import Any, Optional, Tuple

logger = logging.getLogger(__name__)

# (result, request) pair
_QueueItem = Tuple[Any, Any]


class IngestQueue:
    """Single-consumer asyncio queue with background drain worker."""

    def __init__(self, max_size: int = 100) -> None:
        self._q: asyncio.Queue[Optional[_QueueItem]] = asyncio.Queue(maxsize=max_size)
        self._worker_task: Optional[asyncio.Task] = None
        self._started = False

    # ------------------------------------------------------------------ #
    # Lifecycle                                                             #
    # ------------------------------------------------------------------ #

    def start(self) -> None:
        """Start background drain worker. Call once at app startup."""
        if self._started:
            return
        self._started = True
        try:
            loop = asyncio.get_event_loop()
            self._worker_task = loop.create_task(self._drain_loop())
            logger.info("IngestQueue drain worker started")
        except RuntimeError:
            # No running loop yet — will start on first enqueue
            pass

    async def stop(self) -> None:
        """Graceful shutdown — drain remaining items then stop."""
        if self._worker_task is None:
            return
        await self._q.put(None)  # sentinel
        try:
            await asyncio.wait_for(self._worker_task, timeout=10.0)
        except (asyncio.TimeoutError, asyncio.CancelledError):
            self._worker_task.cancel()
        self._started = False
        logger.info("IngestQueue stopped")

    # ------------------------------------------------------------------ #
    # Public API                                                            #
    # ------------------------------------------------------------------ #

    async def enqueue(self, result: Any, request: Any) -> bool:
        """Enqueue (result, request) pair. Returns False if queue full."""
        if not self._started:
            self.start()
        try:
            self._q.put_nowait((result, request))
            return True
        except asyncio.QueueFull:
            logger.warning(
                "IngestQueue full (max=%d) — dropping result %r",
                self._q.maxsize,
                getattr(result, "task_id", "?"),
            )
            return False

    @property
    def qsize(self) -> int:
        return self._q.qsize()

    # ------------------------------------------------------------------ #
    # Internal drain loop                                                   #
    # ------------------------------------------------------------------ #

    async def _drain_loop(self) -> None:
        from shail.memory.output_ingestion import OutputIngestor
        ingestor = OutputIngestor()
        logger.debug("IngestQueue drain loop running")
        while True:
            item = await self._q.get()
            if item is None:  # sentinel
                self._q.task_done()
                break
            result, request = item
            try:
                await ingestor.maybe_ingest(result, request)
            except Exception as exc:
                logger.warning("IngestQueue: ingestor error for task %r: %s",
                               getattr(result, "task_id", "?"), exc)
            finally:
                self._q.task_done()


# ── Singleton ─────────────────────────────────────────────────────────── #

_queue: Optional[IngestQueue] = None


def get_ingest_queue() -> IngestQueue:
    global _queue
    if _queue is None:
        from apps.shail.settings import get_settings
        s = get_settings()
        _queue = IngestQueue(max_size=s.ingest_max_queue_size)
    return _queue
