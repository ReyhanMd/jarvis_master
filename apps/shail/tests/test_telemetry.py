"""Sprint 0 PR1: telemetry counter behavior."""
from __future__ import annotations

from apps.shail import telemetry


def test_counter_no_op_default() -> None:
    snap = telemetry.snapshot()
    assert snap == {"counters": {}, "histograms": {}}


def test_counter_increments() -> None:
    telemetry.incr("foo")
    telemetry.incr("foo", value=2.0)
    assert telemetry.snapshot()["counters"]["foo"] == 3.0


def test_counter_labels_keyed_separately() -> None:
    telemetry.incr(telemetry.RETRIEVAL_PATH, path="exact")
    telemetry.incr(telemetry.RETRIEVAL_PATH, path="semantic")
    telemetry.incr(telemetry.RETRIEVAL_PATH, path="exact")
    snap = telemetry.snapshot()["counters"]
    assert snap[f"{telemetry.RETRIEVAL_PATH}{{path=exact}}"] == 2.0
    assert snap[f"{telemetry.RETRIEVAL_PATH}{{path=semantic}}"] == 1.0


def test_histogram_appends() -> None:
    telemetry.observe(telemetry.INGEST_CHUNKS_PER_CAPTURE, 5)
    telemetry.observe(telemetry.INGEST_CHUNKS_PER_CAPTURE, 8)
    snap = telemetry.snapshot()["histograms"]
    assert snap[telemetry.INGEST_CHUNKS_PER_CAPTURE] == [5, 8]


def test_reset_clears_all() -> None:
    telemetry.incr("foo")
    telemetry.observe("bar", 1)
    telemetry.reset()
    assert telemetry.snapshot() == {"counters": {}, "histograms": {}}
