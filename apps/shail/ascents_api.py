"""
Ascents API — hierarchical goal system (Ascent → Deliverables → Todos).

An "ascent" is a user goal generated and structured by Gemma (or whichever
LLM the user has configured). The model reads the user's goal text plus
recent relevant memories and outputs:

    {
      "deliverables": [
        { "text": "...", "description": "...",
          "todos": [{"text": "..."}, ...],
          "memory_refs": ["<memory-id>", ...]
        },
        ...
      ]
    }

The plan is persisted across three SQLite tables (see auth_store.py):
ascents, deliverables, todos. Memory references are stored separately
in `ascent_memory_links` so the post-v1 inject-suggestion widget can
ask "for this todo, what memories did Gemma cite?"

Endpoints (all require Bearer auth):
    POST   /browser/ascents                 → create + plan via LLM
    GET    /browser/ascents                 → list user's ascents w/ progress
    GET    /browser/ascents/{id}            → full tree (deliverables + todos)
    PUT    /browser/ascents/{id}/todos/{todo_id}    → toggle complete
    DELETE /browser/ascents/{id}            → cascade delete

Free tier: 5 active ascents max. The 6th attempt returns 402 with a
"Upgrade to pro" payload — the dashboard uses this to drive the soft
"+1 teaser" UX (the 6th ascent is shown but locked).
"""

from __future__ import annotations

import json
import logging
import re
import sqlite3
import uuid
from datetime import datetime, timezone
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel, Field

from apps.shail.auth_store import (
    _conn,
    get_user_by_api_key,
    get_user_tier,
    touch_api_key_last_used,
    touch_user_last_seen,
)
from apps.shail.capture_log import write_event
from apps.shail.llm import call_llm
from shail.memory.rag import search as rag_search

logger = logging.getLogger(__name__)

ascents_router = APIRouter()
_bearer = HTTPBearer(auto_error=False)

FREE_TIER_LIMIT = 5
PRO_TIER_LIMIT = 999  # effectively unlimited

# Tag pattern that Gemma is asked to emit when citing a memory inline.
_MEM_REF_RE = re.compile(r"\[mem:([a-zA-Z0-9_\-]{4,})\]")


# ── Auth helper ─────────────────────────────────────────────────────────────

def _require_user(credentials: Optional[HTTPAuthorizationCredentials]) -> str:
    if not credentials:
        raise HTTPException(status_code=401, detail="Authentication required")
    user_id = get_user_by_api_key(credentials.credentials)
    if not user_id:
        raise HTTPException(status_code=401, detail="Invalid API key")
    touch_api_key_last_used(credentials.credentials)
    touch_user_last_seen(user_id)
    return user_id


# ── Pydantic models ─────────────────────────────────────────────────────────

class TodoItem(BaseModel):
    id: str
    text: str
    order_index: int
    completed: bool
    completed_at: Optional[str] = None


class DeliverableItem(BaseModel):
    id: str
    text: str
    description: Optional[str] = ""
    order_index: int
    completed: bool
    todos: List[TodoItem] = Field(default_factory=list)
    memory_ids: List[str] = Field(default_factory=list)


class AscentSummary(BaseModel):
    id: str
    name: str
    description: Optional[str] = ""
    status: str = "active"
    created_at: str
    updated_at: str
    deliverable_count: int = 0
    todo_count: int = 0
    todos_completed: int = 0
    progress: float = 0.0   # 0.0 → 1.0


class AscentDetail(AscentSummary):
    deliverables: List[DeliverableItem] = Field(default_factory=list)


class AscentCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=120)
    description: Optional[str] = ""


class AscentListResponse(BaseModel):
    items: List[AscentSummary]
    active_count: int
    limit: int
    tier: str


class TodoToggleRequest(BaseModel):
    completed: bool


# ── Plan generation ─────────────────────────────────────────────────────────

ASCENT_SYSTEM_PROMPT = """You are SHAIL's planning model. The user gives you a goal.
Your job is to break it down hierarchically:

  GOAL (ascent)
    └─ DELIVERABLES — outcome-level chunks (3-7 of them)
        └─ TODOS — atomic, independent actions (2-6 per deliverable)

Each deliverable is one self-contained outcome that, once achieved, moves
the user materially closer to the goal. Each todo is one action a person
can do in a single sitting. Do NOT use vague verbs like "research" or
"think about" — write concrete steps.

You will be given a list of the user's recent relevant memories. If a
memory is genuinely useful for a specific deliverable, reference it
inline using the tag [mem:<memory_id>]. Do not invent memory IDs — only
reference the IDs actually provided. It is fine to reference zero memories
if none are relevant; do not force connections.

Return STRICT JSON only — no prose, no markdown, no code fences.
Schema:
{
  "deliverables": [
    {
      "text": "<short title — under 80 chars>",
      "description": "<one-sentence why-it-matters>",
      "todos": [
        { "text": "<atomic action under 100 chars>" }
      ],
      "memory_refs": ["<memory_id>", "..."]
    }
  ]
}

Output ONLY the JSON object. No preamble. No trailing text."""


def _format_memory_context(memories: list) -> str:
    """Convert rag_search results into a numbered block for the LLM prompt."""
    if not memories:
        return "(no relevant memories found)"
    lines = []
    for content, _score, meta in memories:
        mid = meta.get("customId") or meta.get("id") or meta.get("memory_id") or ""
        title = meta.get("title", "(untitled)")
        snippet = (content or "").strip().replace("\n", " ")[:240]
        if mid:
            lines.append(f"[mem:{mid}] {title} — {snippet}")
        else:
            lines.append(f"- {title} — {snippet}")
    return "\n".join(lines)


def _strip_code_fence(text: str) -> str:
    """Some LLMs ignore the no-fence instruction. Strip ```json ... ``` wrappers."""
    t = text.strip()
    if t.startswith("```"):
        # remove first fence line
        first_nl = t.find("\n")
        if first_nl != -1:
            t = t[first_nl + 1:]
        if t.endswith("```"):
            t = t[:-3]
    return t.strip()


async def _generate_plan(
    user_id: str,
    name: str,
    description: str,
) -> tuple[list, list]:
    """Run the LLM to generate the deliverables/todos tree.
    Returns (deliverables, retrieved_memories) so the caller can
    persist memory links + write capture-log events.
    """
    namespace = f"user_{user_id}"
    query_text = (description or "").strip() or name
    try:
        memories = rag_search(query_text, k=8, namespace=namespace)
    except Exception as e:
        logger.warning("ascent memory search failed: %s", e)
        memories = []

    user_msg = (
        f"GOAL: {name}\n"
        + (f"DETAILS: {description}\n" if description else "")
        + "\nRELEVANT MEMORIES:\n"
        + _format_memory_context(memories)
        + "\n\nGenerate the JSON plan now."
    )

    answer, _meta = await call_llm(
        messages=[{"role": "user", "content": user_msg}],
        user_id=user_id,
        system_prompt=ASCENT_SYSTEM_PROMPT,
    )

    cleaned = _strip_code_fence(answer)
    try:
        parsed = json.loads(cleaned)
        deliverables = parsed.get("deliverables") or []
    except json.JSONDecodeError:
        # One regeneration attempt with a stricter nudge.
        retry_msg = user_msg + "\n\nIMPORTANT: respond with VALID JSON only — no prose."
        answer2, _ = await call_llm(
            messages=[{"role": "user", "content": retry_msg}],
            user_id=user_id,
            system_prompt=ASCENT_SYSTEM_PROMPT,
        )
        cleaned2 = _strip_code_fence(answer2)
        try:
            parsed = json.loads(cleaned2)
            deliverables = parsed.get("deliverables") or []
        except json.JSONDecodeError as e:
            logger.error("Plan JSON parse failed twice: %s. Output: %s", e, cleaned2[:400])
            raise HTTPException(
                status_code=502,
                detail="LLM returned invalid plan JSON. Try again or rephrase your goal.",
            )

    if not isinstance(deliverables, list) or not deliverables:
        raise HTTPException(
            status_code=502,
            detail="LLM returned an empty plan. Try a more specific goal.",
        )

    return deliverables, memories


def _resolve_memory_refs(refs: list, retrieved_ids: set[str]) -> list[str]:
    """Filter memory refs to those Gemma was actually given. Anything else
    is a hallucination and discarded."""
    out: list[str] = []
    for r in refs or []:
        if not isinstance(r, str):
            continue
        # Strip surrounding [mem:...] if Gemma included the wrapper.
        m = _MEM_REF_RE.search(r)
        cid = m.group(1) if m else r.strip()
        if cid and cid in retrieved_ids and cid not in out:
            out.append(cid)
    return out


# ── DB helpers ──────────────────────────────────────────────────────────────

def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _count_active_ascents(user_id: str) -> int:
    with _conn() as con:
        row = con.execute(
            "SELECT COUNT(*) AS c FROM ascents WHERE user_id = ? AND status = 'active'",
            (user_id,),
        ).fetchone()
    return int(row["c"]) if row else 0


def _insert_ascent_tree(
    user_id: str,
    name: str,
    description: str,
    deliverables_json: list,
    retrieved_memories: list,
) -> str:
    """Single transaction: ascent + deliverables + todos + memory links."""
    ascent_id = str(uuid.uuid4())
    now = _now()

    # Build a set of memory IDs Gemma was given (so we can validate refs).
    retrieved_ids: set[str] = set()
    for _content, _score, meta in retrieved_memories:
        mid = meta.get("customId") or meta.get("id") or meta.get("memory_id")
        if mid:
            retrieved_ids.add(mid)

    with _conn() as con:
        con.execute(
            "INSERT INTO ascents (id, user_id, name, description, status, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, 'active', ?, ?)",
            (ascent_id, user_id, name, description, now, now),
        )

        for d_idx, d in enumerate(deliverables_json):
            d_id = str(uuid.uuid4())
            d_text = (d.get("text") or "").strip()[:200]
            d_desc = (d.get("description") or "").strip()[:500]
            if not d_text:
                continue
            con.execute(
                "INSERT INTO deliverables (id, ascent_id, text, description, order_index, completed, created_at) "
                "VALUES (?, ?, ?, ?, ?, 0, ?)",
                (d_id, ascent_id, d_text, d_desc, d_idx, now),
            )

            todos = d.get("todos") or []
            for t_idx, t in enumerate(todos):
                t_text = (t.get("text") or "").strip()[:300] if isinstance(t, dict) else str(t).strip()[:300]
                if not t_text:
                    continue
                con.execute(
                    "INSERT INTO todos (id, deliverable_id, text, order_index, completed, created_at) "
                    "VALUES (?, ?, ?, ?, 0, ?)",
                    (str(uuid.uuid4()), d_id, t_text, t_idx, now),
                )

            for mid in _resolve_memory_refs(d.get("memory_refs"), retrieved_ids):
                con.execute(
                    "INSERT INTO ascent_memory_links (ascent_id, deliverable_id, memory_id, created_at) "
                    "VALUES (?, ?, ?, ?)",
                    (ascent_id, d_id, mid, now),
                )
                write_event("LINK", f"memory linked to deliverable: {d_text[:60]}",
                            user_id=user_id, ref_id=mid)

    return ascent_id


def _load_ascent_summary(user_id: str, row: sqlite3.Row) -> AscentSummary:
    aid = row["id"]
    with _conn() as con:
        d = con.execute(
            "SELECT COUNT(*) AS c FROM deliverables WHERE ascent_id = ?",
            (aid,),
        ).fetchone()
        deliverable_count = int(d["c"])

        t = con.execute(
            """SELECT
                  COUNT(*) AS total,
                  SUM(CASE WHEN completed = 1 THEN 1 ELSE 0 END) AS done
               FROM todos WHERE deliverable_id IN
                 (SELECT id FROM deliverables WHERE ascent_id = ?)""",
            (aid,),
        ).fetchone()
        todo_count = int(t["total"] or 0)
        todos_done = int(t["done"] or 0)

    progress = (todos_done / todo_count) if todo_count else 0.0

    return AscentSummary(
        id=aid,
        name=row["name"],
        description=row["description"] or "",
        status=row["status"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
        deliverable_count=deliverable_count,
        todo_count=todo_count,
        todos_completed=todos_done,
        progress=round(progress, 4),
    )


def _load_ascent_detail(user_id: str, ascent_id: str) -> AscentDetail:
    with _conn() as con:
        a_row = con.execute(
            "SELECT * FROM ascents WHERE id = ? AND user_id = ?",
            (ascent_id, user_id),
        ).fetchone()
        if not a_row:
            raise HTTPException(status_code=404, detail="Ascent not found")

        d_rows = con.execute(
            "SELECT * FROM deliverables WHERE ascent_id = ? ORDER BY order_index ASC",
            (ascent_id,),
        ).fetchall()

        deliverables: list[DeliverableItem] = []
        for d in d_rows:
            t_rows = con.execute(
                "SELECT * FROM todos WHERE deliverable_id = ? ORDER BY order_index ASC",
                (d["id"],),
            ).fetchall()
            mem_rows = con.execute(
                "SELECT memory_id FROM ascent_memory_links WHERE deliverable_id = ?",
                (d["id"],),
            ).fetchall()

            todos = [
                TodoItem(
                    id=t["id"],
                    text=t["text"],
                    order_index=t["order_index"],
                    completed=bool(t["completed"]),
                    completed_at=t["completed_at"],
                )
                for t in t_rows
            ]

            deliverables.append(
                DeliverableItem(
                    id=d["id"],
                    text=d["text"],
                    description=d["description"] or "",
                    order_index=d["order_index"],
                    completed=bool(d["completed"]),
                    todos=todos,
                    memory_ids=[m["memory_id"] for m in mem_rows],
                )
            )

    summary = _load_ascent_summary(user_id, a_row)
    return AscentDetail(
        **summary.model_dump(),
        deliverables=deliverables,
    )


def _recompute_progress(ascent_id: str) -> None:
    """Update completed flag on each deliverable based on its todos, then
    flip ascent status to 'completed' if every deliverable is done."""
    now = _now()
    with _conn() as con:
        d_rows = con.execute(
            "SELECT id FROM deliverables WHERE ascent_id = ?", (ascent_id,)
        ).fetchall()
        all_done = bool(d_rows)
        for d in d_rows:
            t_rows = con.execute(
                "SELECT completed FROM todos WHERE deliverable_id = ?", (d["id"],)
            ).fetchall()
            if not t_rows:
                # No todos → deliverable not completable, treat as not-done.
                done = 0
                all_done = False
            else:
                done = 1 if all(int(r["completed"]) == 1 for r in t_rows) else 0
                if not done:
                    all_done = False
            con.execute(
                "UPDATE deliverables SET completed = ? WHERE id = ?",
                (done, d["id"]),
            )
        new_status = "completed" if all_done else "active"
        con.execute(
            "UPDATE ascents SET status = ?, updated_at = ? WHERE id = ?",
            (new_status, now, ascent_id),
        )


# ── Endpoints ───────────────────────────────────────────────────────────────

@ascents_router.post("", response_model=AscentDetail)
async def create_ascent(
    body: AscentCreate,
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(_bearer),
) -> AscentDetail:
    user_id = _require_user(credentials)
    tier = (get_user_tier(user_id) or "free").lower()
    limit = PRO_TIER_LIMIT if tier == "pro" else FREE_TIER_LIMIT

    active = _count_active_ascents(user_id)
    if active >= limit:
        raise HTTPException(
            status_code=402,
            detail={
                "error": "free_tier_limit",
                "active": active,
                "limit": limit,
                "tier": tier,
                "message": f"Free tier is limited to {FREE_TIER_LIMIT} active ascents. "
                           f"Upgrade to Pro for unlimited.",
            },
        )

    deliverables, memories = await _generate_plan(user_id, body.name, body.description or "")
    ascent_id = _insert_ascent_tree(
        user_id=user_id,
        name=body.name,
        description=body.description or "",
        deliverables_json=deliverables,
        retrieved_memories=memories,
    )
    write_event(
        "CAPTURE",
        f"new ascent: {body.name[:80]}",
        user_id=user_id,
        ref_id=ascent_id,
    )
    return _load_ascent_detail(user_id, ascent_id)


@ascents_router.get("", response_model=AscentListResponse)
async def list_ascents(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(_bearer),
) -> AscentListResponse:
    user_id = _require_user(credentials)
    tier = (get_user_tier(user_id) or "free").lower()
    limit = PRO_TIER_LIMIT if tier == "pro" else FREE_TIER_LIMIT

    with _conn() as con:
        rows = con.execute(
            "SELECT * FROM ascents WHERE user_id = ? ORDER BY created_at DESC",
            (user_id,),
        ).fetchall()

    items = [_load_ascent_summary(user_id, r) for r in rows]
    active = sum(1 for i in items if i.status == "active")
    return AscentListResponse(items=items, active_count=active, limit=limit, tier=tier)


@ascents_router.get("/{ascent_id}", response_model=AscentDetail)
async def get_ascent(
    ascent_id: str,
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(_bearer),
) -> AscentDetail:
    user_id = _require_user(credentials)
    return _load_ascent_detail(user_id, ascent_id)


@ascents_router.put("/{ascent_id}/todos/{todo_id}", response_model=AscentDetail)
async def toggle_todo(
    ascent_id: str,
    todo_id: str,
    body: TodoToggleRequest,
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(_bearer),
) -> AscentDetail:
    user_id = _require_user(credentials)

    # Verify ownership through the join chain todo → deliverable → ascent → user.
    with _conn() as con:
        owner = con.execute(
            """SELECT a.user_id AS uid, a.id AS aid
               FROM todos t
               JOIN deliverables d ON d.id = t.deliverable_id
               JOIN ascents a ON a.id = d.ascent_id
               WHERE t.id = ?""",
            (todo_id,),
        ).fetchone()
        if not owner or owner["uid"] != user_id or owner["aid"] != ascent_id:
            raise HTTPException(status_code=404, detail="Todo not found")

        completed_at = _now() if body.completed else None
        con.execute(
            "UPDATE todos SET completed = ?, completed_at = ? WHERE id = ?",
            (1 if body.completed else 0, completed_at, todo_id),
        )

    _recompute_progress(ascent_id)
    return _load_ascent_detail(user_id, ascent_id)


@ascents_router.delete("/{ascent_id}")
async def delete_ascent(
    ascent_id: str,
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(_bearer),
) -> dict:
    user_id = _require_user(credentials)
    with _conn() as con:
        existing = con.execute(
            "SELECT id FROM ascents WHERE id = ? AND user_id = ?",
            (ascent_id, user_id),
        ).fetchone()
        if not existing:
            raise HTTPException(status_code=404, detail="Ascent not found")
        # ON DELETE CASCADE handles deliverables/todos/memory_links
        con.execute("DELETE FROM ascents WHERE id = ? AND user_id = ?", (ascent_id, user_id))
    write_event("PRUNE", f"ascent deleted: {ascent_id[:8]}", user_id=user_id, ref_id=ascent_id)
    return {"ok": True, "id": ascent_id}


# ── Suggested memories endpoint ─────────────────────────────────────────────

class SuggestedMemory(BaseModel):
    id: str
    customId: str
    title: str
    summary: str
    sourceApp: str
    timestamp: str
    eventType: str
    relevance_score: float
    deliverable_hint: str   # which deliverable triggered this suggestion


class AscendSuggestionsResponse(BaseModel):
    suggestions: list[SuggestedMemory]
    ascent_id: str
    ascent_name: str


@ascents_router.get("/{ascent_id}/suggestions", response_model=AscendSuggestionsResponse)
async def get_ascent_suggestions(
    ascent_id: str,
    limit: int = 8,
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(_bearer),
) -> AscendSuggestionsResponse:
    """
    Return the top semantically-relevant memories for a given ascent.

    Strategy:
    1. Load all deliverable texts for this ascent as query terms.
    2. Run a RAG search per deliverable (k=4) in the user's namespace.
    3. Merge, deduplicate by customId, sort by highest relevance score.
    4. Return top `limit` suggestions, each tagged with which deliverable
       triggered it (used as a hint in the UI).
    """
    user_id = _require_user(credentials)
    detail = _load_ascent_detail(user_id, ascent_id)
    namespace = f"user_{user_id}"

    seen_ids: set[str] = set()
    candidates: list[dict] = []

    for deliverable in detail.deliverables:
        query = deliverable.text
        if deliverable.description:
            query = f"{query}. {deliverable.description}"
        try:
            hits = rag_search(query, k=4, namespace=namespace)
        except Exception as exc:
            logger.warning("RAG search failed for deliverable %s: %s", deliverable.id[:8], exc)
            hits = []

        for content, score, meta in hits:
            cid = meta.get("customId") or meta.get("id") or ""
            if not cid or cid in seen_ids:
                continue
            seen_ids.add(cid)
            title = meta.get("title", "")
            if not title:
                # derive title from first line of content
                title = (content or "").split("\n")[0][:60] or "Untitled"
            summary = meta.get("summary") or (content or "")[:200]
            candidates.append({
                "id": cid,
                "customId": cid,
                "title": title,
                "summary": summary,
                "sourceApp": meta.get("sourceApp", "web"),
                "timestamp": meta.get("timestamp", ""),
                "eventType": meta.get("eventType", "page_visit"),
                "relevance_score": round(1.0 - float(score), 4),  # invert cosine distance
                "deliverable_hint": deliverable.text[:60],
            })

    # Sort by relevance descending
    candidates.sort(key=lambda x: x["relevance_score"], reverse=True)
    top = candidates[:limit]

    return AscendSuggestionsResponse(
        suggestions=[SuggestedMemory(**c) for c in top],
        ascent_id=ascent_id,
        ascent_name=detail.name,
    )

