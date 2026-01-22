import asyncio
import threading
from typing import Optional

from shail.perception.buffer import GroundingBuffer
from shail.perception.integration import PerceptionServiceConnector


class NativeBridgeService:
    """
    Background bridge that connects native macOS services to GroundingBuffer.
    Runs an internal event loop in a daemon thread to keep streams alive.
    """

    def __init__(self):
        self.buffer = GroundingBuffer()
        self.connector = PerceptionServiceConnector()
        self._thread: Optional[threading.Thread] = None
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._started = False

    def start(self):
        if self._started:
            return
        self._thread = threading.Thread(target=self._run_loop, daemon=True)
        self._thread.start()
        self._started = True

    def _run_loop(self):
        self._loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self._loop)
        self._loop.create_task(self.connector.subscribe_to_grounding_buffer(self.buffer))
        self._loop.run_forever()

    def stop(self):
        if not self._loop:
            return
        self._loop.call_soon_threadsafe(self._loop.stop)
        self._started = False


_native_bridge: Optional[NativeBridgeService] = None


def get_native_bridge() -> NativeBridgeService:
    global _native_bridge
    if _native_bridge is None:
        _native_bridge = NativeBridgeService()
    return _native_bridge
