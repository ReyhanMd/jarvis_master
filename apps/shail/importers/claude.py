"""Claude.ai conversation export parser.

Claude.ai export format (as of 2025):
    [
      {
        "uuid": str,
        "name": str,
        "created_at": str (ISO-8601),
        "chat_messages": [
          {
            "uuid": str,
            "text": str,                 # legacy single text
            "content": [                 # newer multipart
              {"type": "text", "text": str},
              ...
            ],
            "sender": "human" | "assistant",
            "created_at": str,
          },
          ...
        ]
      },
      ...
    ]
"""

from __future__ import annotations

import json
from typing import Optional


def _extract_text(msg: dict) -> str:
    """Handle both legacy `text` and newer `content` array."""
    if isinstance(msg.get("text"), str) and msg["text"].strip():
        return msg["text"].strip()
    parts = msg.get("content") or []
    chunks: list[str] = []
    if isinstance(parts, list):
        for p in parts:
            if isinstance(p, dict):
                t = p.get("text") or ""
                if isinstance(t, str):
                    chunks.append(t)
            elif isinstance(p, str):
                chunks.append(p)
    return "\n".join(c for c in chunks if c).strip()


def _pair_messages(messages: list[dict]) -> list[tuple[str, str]]:
    pairs: list[tuple[str, str]] = []
    pending_user: Optional[str] = None
    for msg in messages:
        sender = (msg.get("sender") or "").lower()
        text = _extract_text(msg)
        if not text:
            continue
        if sender == "human":
            if pending_user is not None:
                pairs.append((pending_user, ""))
            pending_user = text
        elif sender == "assistant":
            pairs.append((pending_user or "", text))
            pending_user = None
    if pending_user is not None:
        pairs.append((pending_user, ""))
    return pairs


def parse(payload: bytes | str) -> list[dict]:
    if isinstance(payload, (bytes, bytearray)):
        data = json.loads(payload.decode("utf-8"))
    elif isinstance(payload, str):
        data = json.loads(payload)
    else:
        data = payload

    if isinstance(data, dict):
        data = data.get("conversations") or [data]
    if not isinstance(data, list):
        return []

    out: list[dict] = []
    for conv in data:
        if not isinstance(conv, dict):
            continue
        messages = conv.get("chat_messages") or conv.get("messages") or []
        if not isinstance(messages, list):
            continue
        # Sort by created_at if available
        messages.sort(key=lambda m: m.get("created_at") or "")
        pairs = _pair_messages(messages)
        if not pairs:
            continue
        out.append({
            "title": conv.get("name") or "Untitled Claude conversation",
            "created_at": conv.get("created_at"),
            "source_id": str(conv.get("uuid") or conv.get("id") or ""),
            "pairs": pairs,
        })
    return out
