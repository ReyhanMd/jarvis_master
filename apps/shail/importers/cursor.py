"""Cursor chat log parser.

Cursor stores chat history as JSON in its workspace state. Common shapes:

    { "tabs": [ { "tabId": str, "chats": [ {"messages": [...]}, ... ] } ] }

or simpler:

    [ {"role": "user"|"assistant", "content": str, ...}, ... ]

We try a few common shapes and emit pairs. Cursor doesn't always have an
explicit conversation title — fall back to first user message.
"""

from __future__ import annotations

import json
from typing import Optional


def _extract_text(msg: dict) -> str:
    text = msg.get("text") or msg.get("content") or msg.get("message") or ""
    if isinstance(text, list):
        chunks = [p.get("text", "") if isinstance(p, dict) else str(p) for p in text]
        return "\n".join(c for c in chunks if c).strip()
    return str(text).strip()


def _role(msg: dict) -> str:
    return (msg.get("role") or msg.get("sender") or msg.get("type") or "").lower()


def _pair_messages(messages: list[dict]) -> list[tuple[str, str]]:
    pairs: list[tuple[str, str]] = []
    pending_user: Optional[str] = None
    for msg in messages:
        role = _role(msg)
        text = _extract_text(msg)
        if not text:
            continue
        if role in ("user", "human"):
            if pending_user is not None:
                pairs.append((pending_user, ""))
            pending_user = text
        elif role in ("assistant", "ai", "bot"):
            pairs.append((pending_user or "", text))
            pending_user = None
    if pending_user is not None:
        pairs.append((pending_user, ""))
    return pairs


def _normalize_to_conversations(data) -> list[dict]:
    """Best-effort shape detection. Returns a list of dicts with `messages`."""
    if isinstance(data, dict):
        # Shape: {"tabs": [{"chats": [{"messages": [...]}, ...]}]}
        if "tabs" in data and isinstance(data["tabs"], list):
            convs: list[dict] = []
            for tab in data["tabs"]:
                for chat in (tab.get("chats") or []):
                    if chat.get("messages"):
                        convs.append({
                            "id": chat.get("id") or tab.get("tabId"),
                            "title": chat.get("title") or tab.get("title"),
                            "messages": chat["messages"],
                        })
            return convs
        # Shape: {"conversations": [...]}
        if "conversations" in data:
            return data["conversations"]
        # Single conversation dict
        if "messages" in data:
            return [data]
    if isinstance(data, list):
        # Could be list of conversation dicts, or list of messages
        if data and isinstance(data[0], dict) and "messages" in data[0]:
            return data
        # Treat as a single flat message list
        return [{"id": "cursor_chat", "title": None, "messages": data}]
    return []


def parse(payload: bytes | str) -> list[dict]:
    if isinstance(payload, (bytes, bytearray)):
        data = json.loads(payload.decode("utf-8"))
    elif isinstance(payload, str):
        data = json.loads(payload)
    else:
        data = payload

    convs = _normalize_to_conversations(data)
    out: list[dict] = []
    for conv in convs:
        messages = conv.get("messages") or []
        if not isinstance(messages, list):
            continue
        pairs = _pair_messages(messages)
        if not pairs:
            continue
        title = conv.get("title")
        if not title:
            # Derive from first user message
            first_user = pairs[0][0] if pairs else ""
            title = (first_user[:60] or "Untitled Cursor chat").strip()
        out.append({
            "title": title,
            "created_at": conv.get("created_at") or conv.get("createdAt"),
            "source_id": str(conv.get("id") or title),
            "pairs": pairs,
        })
    return out
