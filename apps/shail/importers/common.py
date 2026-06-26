"""Common import pipeline shared by all providers.

A parser yields a list of `ParsedConversation` dicts:

    {
        "title": str,
        "created_at": Optional[str],   # ISO-8601 or None
        "source_id": str,              # provider-side conversation id
        "pairs": [(user_text, assistant_text), ...],
    }

`import_conversation_payload` walks those, creates sessions + messages, and
returns a summary. Backfill is enqueued by the caller (HTTP endpoint or CLI)
so this module stays free of FastAPI / async-job coupling.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from apps.shail import chat_store


@dataclass
class ImportResult:
    source: str
    conversations_seen: int = 0
    sessions_created: int = 0
    messages_inserted: int = 0
    session_ids: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "source": self.source,
            "conversations_seen": self.conversations_seen,
            "sessions_created": self.sessions_created,
            "messages_inserted": self.messages_inserted,
            "session_ids": self.session_ids,
            "errors": self.errors,
        }


def import_conversation_payload(
    *,
    user_id: str,
    source: str,
    conversations: list[dict],
    provider_label: Optional[str] = None,
) -> ImportResult:
    """Insert parsed conversations into chat_store. Backfill enqueued by caller.

    Each conversation dict shape: {title, created_at, source_id, pairs}.
    Skips empty conversations. Tags each session with `source` (in title prefix
    for now — proper `source` column would be a chat_sessions schema change).
    """
    result = ImportResult(source=source)
    label = provider_label or source

    for conv in conversations:
        result.conversations_seen += 1
        pairs = conv.get("pairs") or []
        if not pairs:
            continue
        title = conv.get("title") or f"Imported {label} chat"
        # Sprint 6: provenance stored on chat_sessions.source column.
        # Title kept clean — UI consumes `session.source` for a badge.
        try:
            sess = chat_store.create_session(user_id, title=title, source=label)
            sid = sess["id"]
            result.session_ids.append(sid)
            result.sessions_created += 1
            for user_text, asst_text in pairs:
                if user_text:
                    chat_store.append_message(
                        sid, user_id, "user", user_text,
                        provider=label, model=None,
                    )
                    result.messages_inserted += 1
                if asst_text:
                    chat_store.append_message(
                        sid, user_id, "assistant", asst_text,
                        provider=label, model=None,
                    )
                    result.messages_inserted += 1
        except Exception as exc:
            result.errors.append(
                f"conversation {conv.get('source_id', '?')}: {type(exc).__name__}: {exc}"
            )
    return result
