"""ChatGPT conversations.json export parser.

Format: top-level JSON array; each conversation has:
    {
      "title": str,
      "create_time": float,
      "id": str,
      "mapping": {
        "<node_id>": {
          "message": {
            "id": str,
            "author": {"role": "user" | "assistant" | "system" | "tool"},
            "content": {"parts": [str, ...]},
            "create_time": float | null,
          },
          "parent": str | null,
          "children": [str, ...],
        },
        ...
      },
    }

We linearize the mapping tree by following children from the root node, then
emit (user, assistant) pairs in chronological order. System and tool messages
are skipped; assistant messages without a preceding user message are kept as
orphan answers (paired with empty string).
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Iterable, Optional


def _walk_current_path(mapping: dict, current_node_id: str) -> list[dict]:
    """Walk parent → root from `current_node_id`, collect messages, reverse.

    This is the actual conversation the user sees — the linear chain ending
    at `current_node`. Regenerated alternate branches share the same parent
    but live in sibling subtrees we deliberately don't visit.
    """
    nodes = mapping or {}
    chain: list[dict] = []
    nid: Optional[str] = current_node_id
    seen: set[str] = set()
    while nid and nid not in seen:
        seen.add(nid)
        node = nodes.get(nid) or {}
        msg = node.get("message")
        if msg:
            chain.append(msg)
        nid = node.get("parent")
    chain.reverse()
    return chain


def _linearize_mapping(mapping: dict, current_node: Optional[str] = None) -> list[dict]:
    """Linearize a ChatGPT conversation mapping into chronological messages.

    Preferred path: walk backwards from `current_node` (the leaf the user is
    looking at) via parent pointers. This picks exactly the linear chain
    visible in the UI, excluding any regenerated alternate branches.

    Fallback (no current_node): the legacy BFS-then-sort behaviour. This
    can mix branches but is the only option when the export doesn't include
    a current_node pointer.
    """
    nodes = mapping or {}
    if current_node and current_node in nodes:
        return _walk_current_path(nodes, current_node)
    # Legacy fallback
    roots = [nid for nid, n in nodes.items() if not n.get("parent")]
    out: list[dict] = []
    queue: list[str] = list(roots)
    seen: set[str] = set()
    while queue:
        nid = queue.pop(0)
        if nid in seen:
            continue
        seen.add(nid)
        node = nodes.get(nid) or {}
        msg = node.get("message")
        if msg:
            out.append(msg)
        for child in node.get("children", []) or []:
            queue.append(child)
    out.sort(key=lambda m: m.get("create_time") or 0)
    return out


def _extract_text(msg: dict) -> str:
    content = msg.get("content") or {}
    parts = content.get("parts") or []
    chunks: list[str] = []
    for p in parts:
        if isinstance(p, str):
            chunks.append(p)
        elif isinstance(p, dict):
            # Multimodal — keep text part if present
            t = p.get("text") or p.get("content") or ""
            if isinstance(t, str):
                chunks.append(t)
    return "\n".join(c for c in chunks if c).strip()


def _role(msg: dict) -> Optional[str]:
    author = msg.get("author") or {}
    return author.get("role")


def _pair_messages(messages: list[dict]) -> list[tuple[str, str]]:
    pairs: list[tuple[str, str]] = []
    pending_user: Optional[str] = None
    for msg in messages:
        role = _role(msg)
        text = _extract_text(msg)
        if not text:
            continue
        if role == "user":
            # If we already have a pending user message with no assistant reply,
            # emit it as orphan (empty assistant) and start fresh.
            if pending_user is not None:
                pairs.append((pending_user, ""))
            pending_user = text
        elif role == "assistant":
            pairs.append((pending_user or "", text))
            pending_user = None
        # system / tool messages skipped
    if pending_user is not None:
        pairs.append((pending_user, ""))
    return pairs


def parse(payload: bytes | str) -> list[dict]:
    """Parse a ChatGPT export. Returns a list of conversation dicts.

    Accepts either bytes (uploaded file) or already-decoded str / list.
    """
    if isinstance(payload, (bytes, bytearray)):
        data = json.loads(payload.decode("utf-8"))
    elif isinstance(payload, str):
        data = json.loads(payload)
    else:
        data = payload  # already parsed

    if isinstance(data, dict):
        # Some exports wrap conversations under a key
        data = data.get("conversations") or [data]
    if not isinstance(data, list):
        return []

    conversations: list[dict] = []
    for conv in data:
        if not isinstance(conv, dict):
            continue
        title = conv.get("title") or "Untitled ChatGPT conversation"
        mapping = conv.get("mapping") or {}
        # `current_node` is the leaf of the active branch in the UI; ChatGPT
        # exports include it. Walking parent links from there gives the
        # actual conversation shown to the user, skipping regenerated
        # alternate paths.
        current_node = conv.get("current_node")
        messages = _linearize_mapping(mapping, current_node=current_node)
        pairs = _pair_messages(messages)
        if not pairs:
            continue
        created = conv.get("create_time")
        created_iso: Optional[str] = None
        if isinstance(created, (int, float)) and created > 0:
            created_iso = datetime.fromtimestamp(created, tz=timezone.utc).isoformat()
        conversations.append({
            "title": title,
            "created_at": created_iso,
            "source_id": str(conv.get("id") or title),
            "pairs": pairs,
        })
    return conversations
