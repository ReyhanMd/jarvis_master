import asyncio
import hashlib
import json
import os
import time
from datetime import datetime
from typing import Any, Callable, Optional

import websockets
from websockets.client import WebSocketClientProtocol

from shail.core.types import AccessibilityEvent, FrameRequest, ThumbnailFrame
from shail.perception.buffer import GroundingBuffer


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
        self._frame_dir = "/Users/reyhan/jarvis_master/logs/grounding_frames"

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

    async def subscribe_to_grounding_buffer(
        self,
        buffer: GroundingBuffer,
        frame_interval: float = 2.0,
    ):
        """
        Subscribe to both accessibility and capture streams and populate GroundingBuffer.
        """
        async def handle_accessibility_event(data: dict):
            event = self._parse_accessibility_event(data)
            if event:
                await buffer.add_accessibility_event(event)

        async def capture_loop():
            last_frame_ts = 0.0
            while True:
                await self._ensure_capture()
                if not self._capture_ws:
                    await asyncio.sleep(self._reconnect_delay)
                    continue
                try:
                    async for msg in self._capture_ws:
                        if isinstance(msg, bytes):
                            now = time.time()
                            if now - last_frame_ts < frame_interval:
                                continue
                            last_frame_ts = now
                            frame = self._store_frame(msg, now)
                            await buffer.add_thumbnail(frame)
                        else:
                            # JSON heartbeat or control message
                            continue
                except Exception:
                    await self._reconnect_with_backoff("capture")

        await asyncio.gather(
            self.subscribe_accessibility(handle_accessibility_event),
            capture_loop(),
        )

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

    def _parse_accessibility_event(self, data: dict) -> Optional[AccessibilityEvent]:
        if data.get("type") != "accessibility_event":
            return None

        ts = self._parse_timestamp(data.get("timestamp"))
        app_name = data.get("app_name") or "unknown"
        role = data.get("role") or "unknown"
        label = data.get("title") or data.get("label") or data.get("description")
        value = data.get("text") or data.get("value")
        focused = data.get("notification_type") in (
            "focus_changed",
            "kAXFocusedUIElementChangedNotification",
        )

        metadata = {
            "bundle_id": data.get("bundle_id"),
            "window_title": data.get("window_title"),
            "notification_type": data.get("notification_type"),
            "bbox": data.get("bbox"),
        }
        return AccessibilityEvent(
            ts=ts,
            app_name=app_name,
            role=role,
            label=label,
            value=value,
            focused=focused,
            metadata=metadata,
        )

    def _parse_timestamp(self, value: Optional[str]) -> float:
        if not value:
            return time.time()
        try:
            return datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp()
        except Exception:
            return time.time()

    def _store_frame(self, frame_bytes: bytes, ts: float) -> ThumbnailFrame:
        os.makedirs(self._frame_dir, exist_ok=True)
        frame_hash = hashlib.sha256(frame_bytes).hexdigest()[:16]
        filename = f"frame_{int(ts * 1000)}_{frame_hash}.jpg"
        path = os.path.join(self._frame_dir, filename)
        with open(path, "wb") as f:
            f.write(frame_bytes)
        return ThumbnailFrame(ts=ts, path=path, width=0, height=0, hash=frame_hash)
