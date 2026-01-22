import asyncio
from fastapi import FastAPI
import websockets


async def _check_ws(uri: str, timeout: float = 1.5) -> bool:
    try:
        async with websockets.connect(uri, ping_interval=None, open_timeout=timeout) as ws:
            await ws.close()
        return True
    except Exception:
        return False


def register_native_health(app: FastAPI):
    @app.get("/health/native")
    async def native_health():
        capture_ok, accessibility_ok = await asyncio.gather(
            _check_ws("ws://localhost:8765/capture"),
            _check_ws("ws://localhost:8766/accessibility"),
        )
        return {
            "capture": "connected" if capture_ok else "disconnected",
            "accessibility": "connected" if accessibility_ok else "disconnected",
        }
