import asyncio
import bisect
import time
from dataclasses import dataclass
from typing import Callable, Dict, List, Optional, Tuple

from shail.core.types import (
    AccessibilityEvent,
    FrameRequest,
    FrameResponse,
    NarrativeSegment,
    ThumbnailFrame,
    UserGuidanceRequest,
)


@dataclass
class BufferQueryResult:
    events: List[AccessibilityEvent]
    frames: List[ThumbnailFrame]


class GroundingBuffer:
    """
    Rolling buffer for accessibility events and low-res thumbnails.
    Provides temporal and lightweight semantic queries.
    """

    def __init__(
        self,
        window_seconds: int = 300,
        thumbnail_interval: float = 5.0,
        consent_required: bool = True,
        retention_seconds: Optional[int] = None,
        encrypt_at_rest: bool = False,
    ):
        self.window = window_seconds
        self.thumbnail_interval = thumbnail_interval
        self.retention_seconds = retention_seconds or window_seconds
        self.consent_required = consent_required
        self.consent_granted = not consent_required
        self.encrypt_at_rest = encrypt_at_rest

        self._ax_events: List[Tuple[float, AccessibilityEvent]] = []
        self._frames: List[Tuple[float, ThumbnailFrame]] = []
        self._lock = asyncio.Lock()

    async def request_consent(self) -> bool:
        """
        Placeholder for user-consent flow.
        In production, this should prompt the user and persist the decision.
        """
        self.consent_granted = True
        return self.consent_granted

    async def add_accessibility_event(self, event: AccessibilityEvent):
        if self.consent_required and not self.consent_granted:
            return

        masked_event = self._mask_pii(event)
        async with self._lock:
            bisect.insort(self._ax_events, (masked_event.ts, masked_event))
            self._prune_locked()

    async def add_thumbnail(self, frame: ThumbnailFrame):
        if self.consent_required and not self.consent_granted:
            return

        async with self._lock:
            bisect.insort(self._frames, (frame.ts, frame))
            self._prune_locked()

    def query_temporal_range(self, start_ts: float, end_ts: float) -> BufferQueryResult:
        events = self._slice_range(self._ax_events, start_ts, end_ts)
        frames = self._slice_range(self._frames, start_ts, end_ts)
        return BufferQueryResult(events=events, frames=frames)

    def query_semantic(
        self,
        query: str,
        time_range: Optional[Tuple[float, float]] = None,
        keywords: Optional[List[str]] = None,
    ) -> List[NarrativeSegment]:
        """
        Simple keyword/pattern search across accessibility events.
        Returns NarrativeSegments synthesized from matching events.
        """
        query_lower = query.lower()
        keywords = keywords or ["error", "exception", "traceback", "failed", "red"]

        start_ts, end_ts = (
            time_range if time_range else (time.time() - self.window, time.time())
        )
        events = self._slice_range(self._ax_events, start_ts, end_ts)

        matches: List[Tuple[int, AccessibilityEvent]] = []
        for ev in events:
            text_parts = [
                ev.app_name or "",
                ev.role or "",
                ev.label or "",
                ev.value or "",
                " ".join([f"{k}:{v}" for k, v in (ev.metadata or {}).items()]),
            ]
            combined = " ".join(text_parts).lower()
            score = 0
            for kw in keywords + query_lower.split():
                if kw and kw in combined:
                    score += 1
            if score > 0:
                matches.append((score, ev))

        matches.sort(key=lambda m: m[0], reverse=True)
        segments: List[NarrativeSegment] = []
        for score, ev in matches:
            segments.append(
                NarrativeSegment(
                    start_time=ev.ts,
                    end_time=ev.ts,
                    story=f"[{ev.app_name}] {ev.role} {ev.label or ''} {ev.value or ''}".strip(),
                    raw_logs=[f"score={score}", f"metadata={ev.metadata}"],
                    thumbnail_path=None,
                )
            )
        return segments

    # ------------------------------
    # Internal helpers
    # ------------------------------
    def _slice_range(self, items: List[Tuple[float, object]], start_ts: float, end_ts: float):
        # Items are kept sorted by timestamp
        ts_list = [ts for ts, _ in items]
        start_idx = bisect.bisect_left(ts_list, start_ts)
        end_idx = bisect.bisect_right(ts_list, end_ts)
        return [item for _, item in items[start_idx:end_idx]]

    def _prune_locked(self):
        cutoff = time.time() - self.retention_seconds
        while self._ax_events and self._ax_events[0][0] < cutoff:
            self._ax_events.pop(0)
        while self._frames and self._frames[0][0] < cutoff:
            self._frames.pop(0)

    def _mask_pii(self, event: AccessibilityEvent) -> AccessibilityEvent:
        # Lightweight PII masking: redacts obvious email-like patterns
        import re

        def redact(text: Optional[str]) -> Optional[str]:
            if not text:
                return text
            return re.sub(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}", "[redacted-email]", text)

        return AccessibilityEvent(
            ts=event.ts,
            app_name=event.app_name,
            role=event.role,
            label=redact(event.label),
            value=redact(event.value),
            focused=event.focused,
            metadata=event.metadata,
        )

    def _encrypt_at_rest(self, data: bytes) -> bytes:
        """
        Placeholder for encryption-at-rest. Wire in a real cipher (e.g., AES-GCM)
        before persisting frames to disk or shared storage.
        """
        return data
