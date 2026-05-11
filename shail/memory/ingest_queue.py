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
import threading
from typing import Any, Optional, Tuple

logger = logging.getLogger(__name__)

# (result, request) pair
_QueueItem = Tuple[Any, Any]


class IngestQueue:
    """Single-consumer asyncio queue with background drain worker.

    Thread-safe start():
      - start() is callable from any thread/context
      - Multiple concurrent calls produce ONE drain worker (lock-guarded)
      - asyncio.Queue is bound to whichever loop first calls start()
    """

    def __init__(self, max_size: int = 100) -> None:
        self._max_size: int = max_size
        self._q: Optional[asyncio.Queue] = None  # lazy-init under start lock
        self._worker_task: Optional[asyncio.Task] = None
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._started: bool = False
        self._start_lock = threading.Lock()  # cross-thread atomic start guard

    # ------------------------------------------------------------------ #
    # Lifecycle                                                             #
    # ------------------------------------------------------------------ #

    def start(self) -> None:
        """Start background drain worker. Idempotent and thread-safe.

        Concurrent calls from multiple threads → exactly ONE worker is created.
        """
        # Fast path — no lock acquisition for the common case
        if self._started:
            return
        with self._start_lock:
            if self._started:
                return
            try:
                loop = asyncio.get_running_loop()
            except RuntimeError:
                # No running loop in this thread — defer. First in-loop
                # enqueue() will trigger start via run_coroutine_threadsafe.
                logger.debug("IngestQueue.start: no running loop, deferring")
                return
            # Queue must be created under THIS loop to bind correctly
            self._q = asyncio.Queue(maxsize=self._max_size)
            self._loop = loop
            self._worker_task = loop.create_task(self._drain_loop(), name="ingest-drain")
            self._started = True
            logger.info("IngestQueue drain worker started (loop=%s, max=%d)",
                        id(loop), self._max_size)

    async def stop(self) -> None:
        """Graceful shutdown — drain remaining items then stop."""
        if self._worker_task is None or self._q is None:
            return
        try:
            await self._q.put(None)  # sentinel
            await asyncio.wait_for(self._worker_task, timeout=10.0)
        except (asyncio.TimeoutError, asyncio.CancelledError):
            self._worker_task.cancel()
        finally:
            with self._start_lock:
                self._started = False
                self._worker_task = None
        logger.info("IngestQueue stopped")

    # ------------------------------------------------------------------ #
    # Public API                                                            #
    # ------------------------------------------------------------------ #

    async def enqueue(self, result: Any, request: Any) -> bool:
        """Enqueue (result, request) pair. Returns False if queue full or no worker."""
        # Lazy-start if needed. start() is itself thread-safe and idempotent.
        if not self._started:
            self.start()
        if self._q is None:
            # Still no loop available — silently drop. Caller already in async
            # context could not have produced an unbound queue.
            logger.debug("IngestQueue.enqueue: queue not bound to a loop — dropping")
            return False
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
        return self._q.qsize() if self._q is not None else 0

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
