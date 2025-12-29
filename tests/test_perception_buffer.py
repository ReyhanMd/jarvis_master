import time

from shail.perception.buffer import GroundingBuffer
from shail.core.types import AccessibilityEvent, ThumbnailFrame


def test_buffer_add_and_prune():
    buf = GroundingBuffer(window_seconds=1, consent_required=False)
    now = time.time()
    ev = AccessibilityEvent(
        ts=now - 0.5,
        app_name="TestApp",
        role="AXStaticText",
        label="Error",
        value="Failed",
        focused=True,
        metadata={},
    )
    buf._ax_events = []
    buf._frames = []
    # Use sync helper for test
    import asyncio
    asyncio.get_event_loop().run_until_complete(buf.add_accessibility_event(ev))
    result = buf.query_temporal_range(now - 1, now)
    assert len(result.events) == 1


def test_semantic_query_matches_error():
    buf = GroundingBuffer(window_seconds=10, consent_required=False)
    now = time.time()
    ev = AccessibilityEvent(
        ts=now,
        app_name="Terminal",
        role="AXStaticText",
        label="Traceback",
        value="TimeoutError",
        focused=True,
        metadata={},
    )
    import asyncio
    asyncio.get_event_loop().run_until_complete(buf.add_accessibility_event(ev))
    matches = buf.query_semantic("error")
    assert len(matches) >= 1
    assert "Traceback" in matches[0].story

