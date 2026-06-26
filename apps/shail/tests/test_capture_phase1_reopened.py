from __future__ import annotations

import asyncio

import pytest


def _run(coro):
    return asyncio.run(coro)


def test_blueprint_only_retention_waits_then_redacts_without_deleting_blueprint(isolated_db):
    from apps.shail import raw_transcripts as rt
    from apps.shail.blueprints import get_blueprint, init_blueprint_db, save_blueprint

    init_blueprint_db()
    rt.save(
        memory_id="cap_phase1",
        user_id="u1",
        namespace="user_u1",
        content_type="ai_conversation",
        content="User: keep this until blueprint exists\n\nAssistant: the useful answer",
        metadata={
            "sourceApp": "chatgpt",
            "sourceUrl": "https://chatgpt.com/c/abc",
            "conversationId": "abc",
            "title": "Phase 1 retention",
        },
    )

    pending = rt.set_retention_policy("cap_phase1", "blueprint_only")
    assert pending["ok"] is True
    assert pending["retention_policy"] == "blueprint_only"
    assert pending["redacted"] is False
    assert rt.get("cap_phase1")["content"]

    refused = rt.redact_if_blueprinted("cap_phase1", reason="manual")
    assert refused["ok"] is False
    assert refused["reason"] == "no_blueprint_stored"
    assert rt.get("cap_phase1")["content"], "raw text must remain until blueprint exists"

    save_blueprint(
        "cap_phase1",
        {"summary": "stored blueprint", "facts": [{"entity": "SHAIL", "attribute": "phase", "value": "1"}]},
        user_id="u1",
        namespace="user_u1",
        content_type="ai_conversation",
    )
    rt.mark_blueprinted("cap_phase1", True)

    row = rt.get("cap_phase1")
    assert row is not None
    assert row["content"] == ""
    assert row["segment_count"] == 0
    assert row["retention_policy"] == "transcript_deleted"
    assert row["transcript_deleted_at"]
    assert row["metadata"]["conversationId"] == "abc"
    assert get_blueprint("cap_phase1") is not None

    rt.save(
        memory_id="cap_phase1",
        user_id="u1",
        namespace="user_u1",
        content_type="ai_conversation",
        content="Assistant: later active recapture must not restore raw text",
        metadata={"sourceApp": "chatgpt", "conversationId": "abc"},
    )
    still_redacted = rt.get("cap_phase1")
    assert still_redacted["content"] == ""
    assert still_redacted["content_chars"] == 0


class FakeProc:
    def __init__(self):
        self.signals: list[int] = []
        self.killed = False
        self.alive = True

    def poll(self):
        return None if self.alive else 0

    def send_signal(self, sig):
        self.signals.append(sig)
        self.alive = False

    def kill(self):
        self.killed = True
        self.alive = False


@pytest.fixture
def clean_system_api_state(monkeypatch):
    from apps.shail import system_api

    system_api._managed_procs.clear()
    system_api._managed_proc_owners.clear()
    system_api._blueprint_ollama_idle_since = None
    yield system_api
    system_api._managed_procs.clear()
    system_api._managed_proc_owners.clear()
    system_api._blueprint_ollama_idle_since = None


def test_blueprint_queue_start_does_not_take_ownership_of_existing_ollama(clean_system_api_state, monkeypatch):
    system_api = clean_system_api_state
    monkeypatch.setattr(system_api, "_http_ok", lambda *a, **k: asyncio.sleep(0, result=True))

    class PopenShouldNotRun:
        def __init__(self, *a, **k):
            raise AssertionError("should not start a new Ollama process")

    monkeypatch.setattr(system_api.subprocess, "Popen", PopenShouldNotRun)

    assert _run(system_api.start_ollama_for_blueprint_queue()) is True
    assert system_api._managed_proc_owners.get("ollama") is None


def test_blueprint_queue_auto_stop_only_stops_blueprint_owned_ollama(clean_system_api_state, monkeypatch):
    system_api = clean_system_api_state
    manual_proc = FakeProc()
    system_api._managed_procs["ollama"] = manual_proc
    system_api._managed_proc_owners["ollama"] = "manual"

    assert _run(system_api.stop_blueprint_queue_ollama_if_idle()) is False
    assert manual_proc.signals == []
    assert system_api._managed_proc_owners["ollama"] == "manual"

    blueprint_proc = FakeProc()
    system_api._managed_procs["ollama"] = blueprint_proc
    system_api._managed_proc_owners["ollama"] = "blueprint_queue"
    monkeypatch.setattr("apps.shail.blueprint_queue.stats", lambda: {"pending": 0, "running": 0})
    monkeypatch.setattr(system_api, "BLUEPRINT_OLLAMA_IDLE_SECONDS", 120)

    times = iter([1000.0, 1121.0])
    monkeypatch.setattr(system_api.time, "time", lambda: next(times))

    assert _run(system_api.stop_blueprint_queue_ollama_if_idle()) is False
    assert blueprint_proc.signals == []
    assert _run(system_api.stop_blueprint_queue_ollama_if_idle()) is True
    assert blueprint_proc.signals


class EmptyVectorCollection:
    def get(self, *args, **kwargs):
        return {"ids": [], "documents": [], "metadatas": []}


class EmptyVectorStore:
    collection = EmptyVectorCollection()


def test_browser_search_shows_raw_pending_capture_before_embedding(isolated_db, monkeypatch):
    from apps.shail import browser_api
    from apps.shail import raw_transcripts as rt

    rt.save(
        memory_id="pending_save_1",
        user_id="u1",
        namespace="user_u1",
        content_type="page_visit",
        content="[web] Pending Chart\n\nThis chart was explicitly saved and is waiting for embedding.",
        metadata={
            "customId": "pending_save_1",
            "eventType": "page_visit",
            "sourceApp": "web",
            "sourceUrl": "https://example.com/chart",
            "title": "Pending Chart",
            "summary": "This chart was explicitly saved",
            "timestamp": "2026-06-22T05:00:00+00:00",
        },
    )
    monkeypatch.setattr(browser_api, "_get_namespace", lambda _credentials: "user_u1")
    monkeypatch.setattr(browser_api, "_get_store", lambda: EmptyVectorStore())

    result = _run(browser_api.search_memories(browser_api.SearchRequest(query="", k=10), credentials=None))

    assert result.total == 1
    assert result.items[0].id == "pending_save_1"
    assert result.items[0].title == "Pending Chart"


def test_browser_get_memory_falls_back_to_raw_pending_capture(isolated_db, monkeypatch):
    from apps.shail import browser_api
    from apps.shail import raw_transcripts as rt

    rt.save(
        memory_id="pending_detail_1",
        user_id="u1",
        namespace="user_u1",
        content_type="page_visit",
        content="[web] Pending Detail\n\nFull pending raw content is still available.",
        metadata={
            "customId": "pending_detail_1",
            "eventType": "page_visit",
            "sourceApp": "web",
            "sourceUrl": "https://example.com/detail",
            "title": "Pending Detail",
            "timestamp": "2026-06-22T05:01:00+00:00",
        },
    )
    monkeypatch.setattr(browser_api, "_get_namespace", lambda _credentials: "user_u1")
    monkeypatch.setattr(browser_api, "_get_store", lambda: EmptyVectorStore())

    item = _run(browser_api.get_memory("pending_detail_1", credentials=None))

    assert item.id == "pending_detail_1"
    assert item.content and "Full pending raw content" in item.content


def test_stable_conversation_capture_merges_previous_temporary_capture(isolated_db, monkeypatch):
    from fastapi import BackgroundTasks

    from apps.shail import browser_api
    from apps.shail import raw_transcripts as rt

    temp_conv = "temp:gemini:abc"
    stable_conv = "gemini-stable-123"
    temp_id = browser_api._session_memory_id(temp_conv)
    stable_id = browser_api._session_memory_id(stable_conv)

    rt.save(
        memory_id=temp_id,
        user_id="u1",
        namespace="user_u1",
        content_type="ai_conversation",
        content="[gemini] Draft chat\n\nUser: first prompt\n\nAssistant: temporary answer",
        metadata={
            "customId": temp_id,
            "conversationId": temp_conv,
            "conversationIdTemporary": True,
            "eventType": "ai_conversation",
            "sourceApp": "gemini",
            "sourceUrl": "https://gemini.google.com/app",
            "title": "Draft chat",
        },
    )

    monkeypatch.setattr(browser_api, "_get_namespace", lambda _credentials: "user_u1")
    monkeypatch.setattr(browser_api, "_get_store", lambda: EmptyVectorStore())

    req = browser_api.CaptureRequest(
        customId=stable_id,
        conversationId=stable_conv,
        previousConversationId=temp_conv,
        eventType="ai_conversation",
        sourceApp="gemini",
        sourceUrl="https://gemini.google.com/app/gemini-stable-123",
        timestamp="2026-06-26T00:00:00+00:00",
        title="Draft chat",
        assistantText="User: second prompt\n\nAssistant: permanent answer",
        captureMode="retroactive",
        captureInitiator="manual",
    )

    result = _run(browser_api.capture_bulk(req, BackgroundTasks(), credentials=None))

    assert result.memoryId == stable_id
    merged = rt.get(stable_id)
    assert merged is not None
    assert "temporary answer" in merged["content"]
    assert "permanent answer" in merged["content"]
    assert rt.get(temp_id) is None


def test_same_source_conversation_reuses_existing_memory_and_reports_capture_source(isolated_db, monkeypatch):
    from fastapi import BackgroundTasks

    from apps.shail import browser_api
    from apps.shail import raw_transcripts as rt
    from apps.shail.blueprints import init_blueprint_db

    init_blueprint_db()
    existing_id = "existing-gemini-memory"
    conversation_id = "gemini-conv-456"
    rt.save(
        memory_id=existing_id,
        user_id="u1",
        namespace="user_u1",
        content_type="ai_conversation",
        content="[gemini] Existing\n\nAssistant: old answer",
        metadata={
            "customId": existing_id,
            "conversationId": conversation_id,
            "eventType": "ai_conversation",
            "sourceApp": "gemini",
            "sourceUrl": "https://gemini.google.com/app/gemini-conv-456",
            "title": "Existing Gemini",
        },
        capture_mode="retroactive",
    )

    monkeypatch.setattr(browser_api, "_get_namespace", lambda _credentials: "user_u1")
    monkeypatch.setattr(browser_api, "_get_store", lambda: EmptyVectorStore())

    req = browser_api.CaptureRequest(
        customId="different-incoming-id",
        conversationId=conversation_id,
        eventType="ai_conversation",
        sourceApp="gemini",
        sourceUrl="https://gemini.google.com/app/gemini-conv-456",
        timestamp="2026-06-26T00:05:00+00:00",
        title="Existing Gemini",
        assistantText="User: updated\n\nAssistant: new answer",
        captureMode="retroactive",
        captureSource="api",
        captureInitiator="manual",
    )

    result = _run(browser_api.capture_bulk(req, BackgroundTasks(), credentials=None))

    assert result.memoryId == existing_id
    assert rt.get("different-incoming-id") is None
    row = rt.get(existing_id)
    assert row is not None
    assert "new answer" in row["content"]
    assert row["metadata"]["capture_source"] == "api"

    state = _run(browser_api.get_capture_state(memory_id=existing_id, credentials=None))
    assert state["memory_id"] == existing_id
    assert state["capture_source"] == "api"
