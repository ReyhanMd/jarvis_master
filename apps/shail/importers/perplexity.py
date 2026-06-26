"""Perplexity thread export parser.

Perplexity's "Save as JSON" share-link export shape (2025):
    {
      "thread_id": "...",
      "title": "...",
      "created_at": "<iso>",
      "turns": [
        {
          "query": "user question",
          "answer": "perplexity reply",
          "sources": [{"url": "...", "title": "..."}, ...],
          "follow_ups": [...]
        }, ...
      ]
    }

Alternative bulk export shape:
    {"threads": [<thread>, <thread>, ...]}

Single-thread JSON returned by the share-link route is also accepted.
Sources/citations are flattened into the assistant text so RAG keeps them.
"""

from __future__ import annotations

import json
from typing import Optional


def _format_assistant(turn: dict) -> str:
    """Combine answer text + a compact source list so citations survive RAG."""
    answer = (turn.get("answer") or turn.get("text") or "").strip()
    sources = turn.get("sources") or turn.get("citations") or []
    if isinstance(sources, list) and sources:
        lines = []
        for i, s in enumerate(sources[:10], 1):
            if isinstance(s, dict):
                url = s.get("url") or s.get("link") or ""
                title = s.get("title") or s.get("name") or url
                if url:
                    lines.append(f"[{i}] {title} — {url}")
            elif isinstance(s, str):
                lines.append(f"[{i}] {s}")
        if lines:
            answer = answer + "\n\nSources:\n" + "\n".join(lines)
    return answer


def _pairs_from_turns(turns: list) -> list[tuple[str, str]]:
    out: list[tuple[str, str]] = []
    for t in turns:
        if not isinstance(t, dict):
            continue
        user = (t.get("query") or t.get("question") or t.get("user") or "").strip()
        asst = _format_assistant(t)
        if not user and not asst:
            continue
        out.append((user, asst))
    return out


def _parse_thread(thread: dict) -> Optional[dict]:
    turns = thread.get("turns") or thread.get("messages") or []
    if not isinstance(turns, list):
        return None
    pairs = _pairs_from_turns(turns)
    if not pairs:
        return None
    return {
        "title": thread.get("title") or "Untitled Perplexity thread",
        "created_at": thread.get("created_at") or thread.get("createdAt"),
        "source_id": str(thread.get("thread_id") or thread.get("id") or ""),
        "pairs": pairs,
    }


def parse(payload: bytes | str) -> list[dict]:
    if isinstance(payload, (bytes, bytearray)):
        data = json.loads(payload.decode("utf-8", errors="replace"))
    elif isinstance(payload, str):
        data = json.loads(payload)
    else:
        data = payload

    out: list[dict] = []
    if isinstance(data, dict):
        # Bulk export
        if isinstance(data.get("threads"), list):
            for thread in data["threads"]:
                if isinstance(thread, dict):
                    parsed = _parse_thread(thread)
                    if parsed:
                        out.append(parsed)
        else:
            parsed = _parse_thread(data)
            if parsed:
                out.append(parsed)
    elif isinstance(data, list):
        for thread in data:
            if isinstance(thread, dict):
                parsed = _parse_thread(thread)
                if parsed:
                    out.append(parsed)
    return out
