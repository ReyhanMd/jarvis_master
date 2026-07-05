"""Grok (X.AI) conversation export parser.

Grok doesn't ship an official JSON export, so this importer accepts two paths:

1. **Saved HTML page** (`Cmd+S` "Save Page As" from grok.com): we strip tags
   via `shail.memory.rag._extract_text_from_file`-style logic, then heuristic-
   split on "You" / "Grok" prefixes that appear in the rendered DOM.

2. **JSON line stream** captured via the browser extension's
   conversation-extractor (one turn per record). Shape:
       {"conversations": [
         {"id": "...", "title": "...", "messages": [
           {"role": "user"|"assistant", "text": "..."}, ...
         ]}
       ]}

The browser extension is the primary capture path for Grok; this importer
exists so users can paste a Save-Page-As HTML or JSON export and SHAIL still
ingests it cleanly.
"""

from __future__ import annotations

import json
import re
from html.parser import HTMLParser
from typing import Optional


def _pair_messages(messages: list[dict]) -> list[tuple[str, str]]:
    pairs: list[tuple[str, str]] = []
    pending_user: Optional[str] = None
    for msg in messages:
        role = (msg.get("role") or msg.get("sender") or "").lower()
        text = (msg.get("text") or msg.get("content") or "").strip()
        if not text:
            continue
        if role in ("user", "human", "you"):
            if pending_user is not None:
                pairs.append((pending_user, ""))
            pending_user = text
        elif role in ("assistant", "grok", "model"):
            pairs.append((pending_user or "", text))
            pending_user = None
    if pending_user is not None:
        pairs.append((pending_user, ""))
    return pairs


def _parse_json(data: dict | list) -> list[dict]:
    if isinstance(data, dict):
        convs = data.get("conversations") or [data]
    elif isinstance(data, list):
        convs = data
    else:
        return []
    out: list[dict] = []
    for conv in convs:
        if not isinstance(conv, dict):
            continue
        messages = conv.get("messages") or conv.get("turns") or []
        if not isinstance(messages, list):
            continue
        pairs = _pair_messages(messages)
        if not pairs:
            continue
        out.append({
            "title": conv.get("title") or conv.get("name") or "Untitled Grok conversation",
            "created_at": conv.get("createdAt") or conv.get("created_at"),
            "source_id": str(conv.get("id") or ""),
            "pairs": pairs,
        })
    return out


class _HTMLStripper(HTMLParser):
    """Same skip-list as rag._extract_text_from_file's HTML path."""
    _SKIP = {"script", "style", "head", "meta", "link", "noscript", "svg"}

    def __init__(self) -> None:
        super().__init__()
        self._depth_skip = 0
        self._parts: list[str] = []

    def handle_starttag(self, tag, attrs):
        if tag in self._SKIP:
            self._depth_skip += 1

    def handle_endtag(self, tag):
        if tag in self._SKIP and self._depth_skip > 0:
            self._depth_skip -= 1
        # Tag boundary → newline so we don't smash adjacent texts together
        self._parts.append("\n")

    def handle_data(self, data):
        if self._depth_skip == 0 and data.strip():
            self._parts.append(data)


_USER_PREFIX_RE  = re.compile(r"^\s*(You|User)\s*[:\-—]\s*", re.IGNORECASE | re.MULTILINE)
_GROK_PREFIX_RE  = re.compile(r"^\s*(Grok|Assistant)\s*[:\-—]\s*", re.IGNORECASE | re.MULTILINE)


def _parse_html(raw: str) -> list[dict]:
    stripper = _HTMLStripper()
    try:
        stripper.feed(raw)
    except Exception:
        return []
    text = "\n".join(p for p in stripper._parts if p.strip())
    if not text.strip():
        return []

    # Split on user/grok marker lines. Tokens: ("user", text) | ("grok", text).
    # We record (start, prefix_end, role) so we can slice OUT the prefix
    # without nuking the whole first line — earlier impl wiped the user text.
    markers: list[tuple[int, int, str]] = []
    for m in _USER_PREFIX_RE.finditer(text):
        markers.append((m.start(), m.end(), "user"))
    for m in _GROK_PREFIX_RE.finditer(text):
        markers.append((m.start(), m.end(), "grok"))
    markers.sort()
    if not markers:
        # No structure detected — entire blob as a single "context" turn
        return [{
            "title": "Grok page (HTML)",
            "created_at": None,
            "source_id": "grok-html",
            "pairs": [("", text[:50_000])],
        }]
    tokens: list[tuple[str, str]] = []
    for idx, (_start, prefix_end, role) in enumerate(markers):
        next_start = markers[idx + 1][0] if idx + 1 < len(markers) else len(text)
        chunk = text[prefix_end:next_start].strip()
        if chunk:
            tokens.append((role, chunk))
    messages = [{"role": r, "text": t} for r, t in tokens]
    pairs = _pair_messages(messages)
    if not pairs:
        return []
    return [{
        "title": "Grok page (HTML)",
        "created_at": None,
        "source_id": "grok-html",
        "pairs": pairs,
    }]


def parse(payload: bytes | str) -> list[dict]:
    if isinstance(payload, (bytes, bytearray)):
        raw = payload.decode("utf-8", errors="replace")
    else:
        raw = payload if isinstance(payload, str) else json.dumps(payload)
    raw = raw.strip()
    if raw.startswith("{") or raw.startswith("["):
        try:
            return _parse_json(json.loads(raw))
        except (json.JSONDecodeError, TypeError):
            pass
    # Fall through to HTML parsing
    return _parse_html(raw)
