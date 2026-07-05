"""Sprint 5 PR1: browser-capture chunking under SHAIL_CAPTURE_CHUNKING.

Tests the pure helper `_build_capture_records` directly so no Ollama,
no Chroma, no FastAPI server is required.
"""
from __future__ import annotations

import types

import pytest

from apps.shail import browser_api, telemetry


def _make_req(custom_id: str = "mem-1", content_len: int = 5000):
    """Construct the minimal subset of CaptureRequest fields the helper reads."""
    return types.SimpleNamespace(
        customId=custom_id,
        conversationId="conv-1",
        eventType="ai_conversation",
        sourceApp="chatgpt",
        sourceUrl="https://example.com/c/abc",
        title="Test capture",
        timestamp="2025-01-01T00:00:00Z",
    )


# ── flag OFF (legacy single record) ─────────────────────────────────────────


def test_unchunked_emits_single_record() -> None:
    req = _make_req()
    content = "x" * 5000
    out = browser_api._build_capture_records(
        req=req, content=content, summary="s", namespace="ns", chunked=False,
    )
    assert len(out) == 1
    rec = out[0]
    assert rec["id"] == "mem-1"
    assert rec["content"] == content
    assert rec["metadata"]["customId"] == "mem-1"
    # Chunk-only fields must NOT appear when chunking is OFF.
    assert "parent_memory_id" not in rec["metadata"]
    assert "chunk_index" not in rec["metadata"]


# ── flag ON (chunked path) ──────────────────────────────────────────────────


def test_chunked_emits_multiple_records() -> None:
    req = _make_req()
    # Force enough content to require chunking under default 800/120.
    content = "Para. " * 600
    out = browser_api._build_capture_records(
        req=req, content=content, summary="s", namespace="ns", chunked=True,
    )
    assert len(out) >= 2
    for i, rec in enumerate(out):
        assert rec["id"] == f"mem-1#{i:03d}"
        assert rec["metadata"]["parent_memory_id"] == "mem-1"
        assert rec["metadata"]["chunk_index"] == i
        assert rec["metadata"]["chunk_total"] == len(out)
        assert rec["metadata"]["customId"] == "mem-1"
        # chunk_hash must be present and short.
        h = rec["metadata"]["chunk_hash"]
        assert isinstance(h, str) and len(h) == 16


def test_chunked_short_content_falls_back_to_single() -> None:
    """Empty/whitespace content → single legacy record (chunker returns [])."""
    req = _make_req()
    out = browser_api._build_capture_records(
        req=req, content="", summary="s", namespace="ns", chunked=True,
    )
    assert len(out) == 1
    assert out[0]["id"] == "mem-1"
    assert "parent_memory_id" not in out[0]["metadata"]


def test_chunk_ids_deterministic_across_calls() -> None:
    """Same content twice → identical chunk ids (Chroma upsert idempotent)."""
    req = _make_req()
    content = "Para. " * 600
    a = browser_api._build_capture_records(
        req=req, content=content, summary="s", namespace="ns", chunked=True,
    )
    b = browser_api._build_capture_records(
        req=req, content=content, summary="s", namespace="ns", chunked=True,
    )
    assert [r["id"] for r in a] == [r["id"] for r in b]
    assert [r["metadata"]["chunk_hash"] for r in a] == \
           [r["metadata"]["chunk_hash"] for r in b]


def test_chunk_hash_changes_when_content_changes() -> None:
    req = _make_req()
    a = browser_api._build_capture_records(
        req=req, content=("A" * 2000), summary="s", namespace="ns", chunked=True,
    )
    b = browser_api._build_capture_records(
        req=req, content=("B" * 2000), summary="s", namespace="ns", chunked=True,
    )
    a_hashes = {r["metadata"]["chunk_hash"] for r in a}
    b_hashes = {r["metadata"]["chunk_hash"] for r in b}
    assert a_hashes.isdisjoint(b_hashes)


def test_telemetry_histogram_records_chunk_count() -> None:
    telemetry.reset()
    req = _make_req()
    out = browser_api._build_capture_records(
        req=req, content=("Para. " * 600), summary="s", namespace="ns", chunked=True,
    )
    snap = telemetry.snapshot()["histograms"]
    assert snap[telemetry.INGEST_CHUNKS_PER_CAPTURE] == [len(out)]


# ── conversationId still threads ────────────────────────────────────────────


def test_chunked_records_retain_conversation_id() -> None:
    req = _make_req()
    out = browser_api._build_capture_records(
        req=req, content=("Para. " * 600), summary="s", namespace="ns", chunked=True,
    )
    for rec in out:
        assert rec["metadata"]["conversationId"] == "conv-1"
