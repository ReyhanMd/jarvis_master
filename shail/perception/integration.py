import asyncio
import json
from typing import Any, Callable, Optional

import websockets
from websockets.client import WebSocketClientProtocol

from shail.core.types import FrameRequest


class PerceptionServiceConnector:
    """
    Manages WebSocket connections to native services with retry/backoff.
    Provides helpers to subscribe to accessibility events and request frames.
    """

    def __init__(self):
        self.ax_uri = "ws://localhost:8766/accessibility"
        self.capture_uri = "ws://localhost:8765/capture"
        self._ax_ws: Optional[WebSocketClientProtocol] = None
        self._capture_ws: Optional[WebSocketClientProtocol] = None
        self._reconnect_delay = 1.0
        self._max_reconnect_delay = 30.0
        self._lock = asyncio.Lock()

    async def connect_all(self):
        await asyncio.gather(self._ensure_ax(), self._ensure_capture())

    async def subscribe_accessibility(self, callback: Callable[[dict], Any]):
        """
        Subscribe to accessibility event stream and invoke callback for each message.
        """
        while True:
            await self._ensure_ax()
            if not self._ax_ws:
                await asyncio.sleep(self._reconnect_delay)
                continue
            try:
                async for msg in self._ax_ws:
                    try:
                        data = json.loads(msg)
                        await callback(data)
                    except json.JSONDecodeError:
                        continue
            except Exception:
                await self._reconnect_with_backoff("ax")

    async def request_frames(self, request: FrameRequest) -> dict:
        """
        Send frame request to CaptureService and await response.
        """
        await self._ensure_capture()
        if not self._capture_ws:
            return {"status": "error", "frames": []}

        payload = request.dict()
        payload["type"] = "request_frames"
        await self._capture_ws.send(json.dumps(payload))

        try:
            msg = await asyncio.wait_for(self._capture_ws.recv(), timeout=5)
            return json.loads(msg)
        except Exception:
            await self._reconnect_with_backoff("capture")
            return {"status": "error", "frames": []}

    def request_frames_sync(self, start_ts: float, end_ts: float, max_frames: int = 5) -> dict:
        """
        Synchronous helper that wraps the async frame request.
        """
        req = FrameRequest(
            request_id="req-buffered",
            start_ts=start_ts,
            end_ts=end_ts,
            max_frames=max_frames,
        )
        return asyncio.get_event_loop().run_until_complete(self.request_frames(req))

    # ------------------------------
    # Internal helpers
    # ------------------------------
    async def _ensure_ax(self):
        if self._ax_ws and not self._ax_ws.closed:
            return
        await self._connect_ax()

    async def _ensure_capture(self):
        if self._capture_ws and not self._capture_ws.closed:
            return
        await self._connect_capture()

    async def _connect_ax(self):
        try:
            self._ax_ws = await websockets.connect(self.ax_uri)
            self._reconnect_delay = 1.0
        except Exception:
            await self._reconnect_with_backoff("ax")

    async def _connect_capture(self):
        try:
            self._capture_ws = await websockets.connect(self.capture_uri)
            self._reconnect_delay = 1.0
        except Exception:
            await self._reconnect_with_backoff("capture")

    async def _reconnect_with_backoff(self, service: str):
        await asyncio.sleep(self._reconnect_delay)
        self._reconnect_delay = min(self._reconnect_delay * 2, self._max_reconnect_delay)
        if service == "ax":
            await self._connect_ax()
        else:
            await self._connect_capture()

