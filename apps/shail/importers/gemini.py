"""Google Gemini conversation export parser.

Two formats supported:

1. **Google Takeout `My Activity.json`** — Gemini activity entries appear as
   per-prompt records:
       [
         {"title": "Said \"...\"", "header": "Gemini", "time": "<iso>",
          "details": [...]},
         {"title": "Asked \"...\"", "header": "Gemini Apps", "time": "<iso>",
          "details": [{"name": "From Google Bard"}]},
         ...
       ]
   Each record is a single user prompt OR a single Gemini reply (separate
   entries). We pair adjacent entries by chronological order: user prompts
   match the next assistant entry within the same conversation window.

2. **Native Gemini export JSON** (chat conversations exported via the share
   link "Save to Drive" path):
       {
         "conversations": [
           {
             "id": "...",
             "name": "...",
             "createTime": "<iso>",
             "messages": [
               {"role": "user", "text": "..."},
               {"role": "model", "text": "..."},
               ...
             ]
           }
         ]
       }

We detect format by looking at the top-level shape.
"""

from __future__ import annotations

import json
from typing import Optional


def _pair_messages(messages: list[dict]) -> list[tuple[str, str]]:
    """Pair user → model messages sequentially. Mirrors claude._pair_messages."""
    pairs: list[tuple[str, str]] = []
    pending_user: Optional[str] = None
    for msg in messages:
        role = (msg.get("role") or msg.get("sender") or "").lower()
        text = (msg.get("text") or msg.get("content") or "").strip()
        if not text:
            continue
        if role in ("user", "human"):
            if pending_user is not None:
                pairs.append((pending_user, ""))
            pending_user = text
        elif role in ("model", "assistant", "gemini", "bard"):
            pairs.append((pending_user or "", text))
            pending_user = None
    if pending_user is not None:
        pairs.append((pending_user, ""))
    return pairs


def _parse_native(data: dict) -> list[dict]:
    """Native Gemini JSON: {conversations: [...]}"""
    convs = data.get("conversations") or []
    if not isinstance(convs, list):
        return []
    out: list[dict] = []
    for conv in convs:
        if not isinstance(conv, dict):
            continue
        messages = conv.get("messages") or []
        if not isinstance(messages, list):
            continue
        pairs = _pair_messages(messages)
        if not pairs:
            continue
        out.append({
            "title": conv.get("name") or "Untitled Gemini conversation",
            "created_at": conv.get("createTime") or conv.get("created_at"),
            "source_id": str(conv.get("id") or ""),
            "pairs": pairs,
        })
    return out


def _parse_takeout(entries: list) -> list[dict]:
    """Google Takeout My Activity records — one prompt OR reply per row.

    Strategy: filter to Gemini-related entries (header contains "Gemini",
    "Bard", or "Gemini Apps"), sort by time, then pair adjacent user/assistant
    entries. The activity log doesn't preserve conversation IDs, so we group
    everything into a single synthetic "Gemini activity" session.
    """
    relevant = []
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        header = (entry.get("header") or "").lower()
        if "gemini" not in header and "bard" not in header:
            continue
        title = entry.get("title") or ""
        time = entry.get("time") or ""
        # Heuristics: Takeout titles look like "Said "<text>"" (user) or
        # "Asked: <text>" or just the model reply prefixed differently.
        # We treat lines starting with Said/Asked as user; others as model.
        is_user = title.startswith("Said ") or title.startswith("Asked ")
        # Strip the prefix + quotes
        text = title
        for prefix in ("Said \"", "Asked \"", "Said '", "Asked '"):
            if text.startswith(prefix):
                text = text[len(prefix):]
                if text.endswith("\"") or text.endswith("'"):
                    text = text[:-1]
                break
        if not text.strip():
            continue
        relevant.append({
            "time": time,
            "text": text.strip(),
            "role": "user" if is_user else "model",
        })
    if not relevant:
        return []
    relevant.sort(key=lambda r: r.get("time") or "")
    pairs = _pair_messages(relevant)
    if not pairs:
        return []
    return [{
        "title": "Gemini activity (Takeout)",
        "created_at": relevant[0]["time"] if relevant else None,
        "source_id": "gemini-takeout",
        "pairs": pairs,
    }]


def parse(payload: bytes | str) -> list[dict]:
    if isinstance(payload, (bytes, bytearray)):
        data = json.loads(payload.decode("utf-8", errors="replace"))
    elif isinstance(payload, str):
        data = json.loads(payload)
    else:
        data = payload

    if isinstance(data, dict) and "conversations" in data:
        return _parse_native(data)
    if isinstance(data, list):
        return _parse_takeout(data)
    return []
