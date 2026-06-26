from __future__ import annotations

import asyncio


def _run(coro):
    return asyncio.run(coro)


class EmptyVectorCollection:
    def get(self, *args, **kwargs):
        return {"ids": [], "documents": [], "metadatas": []}


class EmptyVectorStore:
    collection = EmptyVectorCollection()


def test_claude_ai_url_normalizes_web_source_to_claude():
    from apps.shail.source_normalization import is_browser_memory, normalize_browser_metadata

    meta = {
        "sourceApp": "web",
        "source": "browser_web",
        "sourceUrl": "https://claude.ai/chat/abc",
        "title": "Domain choice for AI SaaS business - Claude",
    }

    normalized = normalize_browser_metadata(meta)

    assert normalized["sourceApp"] == "claude"
    assert normalized["source"] == "browser_claude"
    assert is_browser_memory(meta, "") is True


def test_reconciliation_finds_raw_only_backup_only_and_skips_local_file():
    from apps.shail.scripts.reconcile_legacy_captures import ChromaRecord, build_reconciliation

    live = [
        ChromaRecord(
            id="live_claude",
            document="[Claude] Domain choice\n\nUseful answer",
            metadata={
                "customId": "live_claude",
                "sourceApp": "web",
                "sourceUrl": "https://claude.ai/chat/live",
                "title": "Domain choice for AI SaaS business - Claude",
                "namespace": "user_u1",
            },
            source_store="live",
        ),
        ChromaRecord(
            id="file_chunk",
            document="local file chunk",
            metadata={"source": "local_file", "namespace": "user_u1", "title": "notes.md"},
            source_store="live",
        ),
    ]
    raw = [
        {
            "memory_id": "raw_pending",
            "namespace": "user_u1",
            "content": "[Gemini] Pending\n\nRaw only",
            "content_type": "ai_conversation",
            "embedded": 0,
            "blueprinted": 0,
            "metadata": {
                "customId": "raw_pending",
                "sourceApp": "gemini",
                "sourceUrl": "https://gemini.google.com/app/abc",
                "title": "Pending Gemini",
            },
        }
    ]
    backup = [
        ChromaRecord(
            id="backup_claude",
            document="[Claude] Missing bulk capture\n\nRecovered text",
            metadata={
                "customId": "backup_claude",
                "sourceApp": "Claude",
                "sourceUrl": "https://claude.ai/chat/old",
                "title": "Recovered Claude",
                "namespace": "user_legacy",
            },
            source_store="source:backup",
        ),
        ChromaRecord(
            id="backup_file",
            document="do not import",
            metadata={"source": "local_file", "title": "local.pdf", "namespace": "user_legacy"},
            source_store="source:backup",
        ),
    ]

    report = build_reconciliation(
        live_records=live,
        raw_rows=raw,
        source_records=backup,
        blueprint_jobs=[],
        blueprint_rows={},
        canonical_namespace="user_u1",
    )

    assert report["counts"]["source_mislabel"] == 1
    assert report["raw_only"][0]["id"] == "raw_pending"
    assert report["import_candidates"][0]["id"] == "backup_claude"
    assert any(item["id"] == "backup_file" and item["classification"] == "local_file" for item in report["skipped"])


def test_dashboard_lists_raw_only_pending_capture(isolated_db, monkeypatch):
    from apps.shail import memory_dashboard_api
    from apps.shail import raw_transcripts as rt

    rt.save(
        memory_id="raw_dashboard_1",
        user_id="u1",
        namespace="user_u1",
        content_type="ai_conversation",
        content="[Claude] Raw Dashboard\n\nVisible before embedding.",
        metadata={
            "customId": "raw_dashboard_1",
            "eventType": "ai_conversation",
            "sourceApp": "web",
            "sourceUrl": "https://claude.ai/chat/raw",
            "title": "Raw Dashboard",
            "timestamp": "2026-06-22T05:00:00+00:00",
        },
    )
    monkeypatch.setattr(memory_dashboard_api, "_get_store", lambda: EmptyVectorStore())

    page = _run(memory_dashboard_api.list_memories(user_id="u1"))

    assert page.total == 1
    assert page.items[0].id == "raw_dashboard_1"
    assert page.items[0].sourceApp == "claude"

