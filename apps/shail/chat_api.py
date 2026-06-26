"""
Dashboard chat endpoint — RAG-augmented LLM with persistent multi-session
chat history, structured citation tokens, and unified retrieval across
memories, blueprints, past chats, and the open web.

Endpoints (all auth-required):
    GET    /browser/chat/sessions             list all sessions for user
    POST   /browser/chat/sessions             create empty session
    GET    /browser/chat/sessions/{id}        full message thread
    PATCH  /browser/chat/sessions/{id}        rename / toggle pin
    DELETE /browser/chat/sessions/{id}        cascade delete

    POST   /browser/chat                      send a message; SSE response

POST /browser/chat body:
    {
      "message": "...",
      "session_id": "<uuid>" | null,    // omit to auto-create
      "stream": true | false            // default true
    }

Streaming response is SSE with typed events:
    data: {"type":"meta","session_id":"...","provider":"...","model":"...","fellback":false}
    data: {"type":"source_status","source":"memories|web|past_chat","status":"fetching|done","count":N}
    data: {"type":"memories","items":[{id,title,score}]}
    data: {"type":"past_chats","items":[{session_id,message_id,title,score}]}
    data: {"type":"web","items":[{title,url,snippet}]}
    data: {"type":"delta","text":"..."}        // repeated
    data: {"type":"done","message_id":"..."}

The assistant is instructed to emit structured citation tokens like
{{cite:memory:abc}}, {{cite:web:1}}, {{cite:chat:xyz}} which the frontend
parses into clickable CitationLink components.
"""

from __future__ import annotations

import asyncio
import json
import logging
import math
import re
import time
from typing import AsyncIterator, List, Optional

import uuid

from fastapi import APIRouter, BackgroundTasks, Depends, File, Form, HTTPException, Query, UploadFile
from fastapi.responses import StreamingResponse
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel, Field

from apps.shail.auth_store import (
    get_user_by_api_key,
    touch_api_key_last_used,
    touch_user_last_seen,
)
from apps.shail.blueprints import (
    format_blueprint_for_context, get_blueprints_for_ids,
)
from apps.shail.capture_log import write_event
from apps.shail import chat_store
from apps.shail import session_backfill
from apps.shail.llm import call_llm, get_user_llm_config, stream_llm
from apps.shail.mcp import PROVIDERS, get_provider as get_mcp_provider
from apps.shail.mcp.routing import pick_providers
from apps.shail.mcp_store import get_connection as get_mcp_connection, get_settings as get_mcp_settings, list_connections as list_mcp_connections
from apps.shail.web_search import (
    format_for_prompt as web_format,
    needs_web_search,
    search as web_search,
)
from shail.memory.rag import _get_store, ingest, search as rag_search
from shail.memory.embeddings import embed_query as emb_q
# Sprint 3 PR3 — hybrid retrieval. Imported lazily to keep cold-start cost
# tied to actual flag activation; settings flag default OFF preserves legacy.
from shail.memory.hybrid import hybrid_search as _hybrid_search
from apps.shail.settings import get_settings

logger = logging.getLogger(__name__)

chat_router = APIRouter()
_bearer = HTTPBearer(auto_error=False)

CHAT_SYSTEM_PROMPT = (
    "You are SHAIL — a personal AI assistant with access to the user's "
    "captured memories (private notes from their browsing and AI conversations), "
    "their previous chats with you, connected sources (Drive/Notion/GitHub/Gmail), "
    "and live web results when they're relevant.\n\n"
    "MEMORY USE — read carefully:\n"
    "Memories below the AVAILABLE CITATIONS markers are FACTS the user has stored. "
    "Prefer them over generic knowledge. When a memory is relevant to the question, "
    "actually USE its content in your answer — do not just acknowledge it. "
    "If memories conflict, the most recent (highest score) wins. Local files are "
    "not memories; treat them as current device documents and cite them with "
    "local_file tokens when used.\n\n"
    "CITATION RULES — read carefully:\n"
    "When you reference any source, you MUST emit a structured citation token "
    "inline at the point of reference. Tokens look like:\n"
    "  {{cite:memory:<memory_id>}}    for captured memories\n"
    "  {{cite:chat:<message_id>}}     for past chat messages\n"
    "  {{cite:web:<index>}}           for live web results (1-based index)\n"
    "  {{cite:mcp:<provider>:<id>}}   for connected sources (drive/notion/github/gmail)\n"
    "  {{cite:local_file:<path_index_id>}} for local files on this device\n"
    "Use ONLY ids from the AVAILABLE CITATIONS block below. Never invent ids. "
    "Never use the older [Memory: title] or [1]/[2] formats. Place tokens "
    "next to the claim they support.\n\n"
    "RESPONSE FORMAT — read carefully:\n"
    "Always reply in clean GitHub-flavored Markdown. The frontend renders "
    "Markdown — raw blobs look broken.\n"
    "- Use `## Section` headings when the answer has 2+ distinct parts.\n"
    "- Use bullet lists (`- item`) for any enumeration of 3+ items.\n"
    "- Use pipe tables (`| col | col |`) when comparing things or listing rows.\n"
    "- Use fenced code blocks (```lang) for code, paths, or commands.\n"
    "- Use inline `code` for filenames, identifiers, env vars, short snippets.\n"
    "- Keep paragraphs short (max ~3 sentences). Break thoughts into bullets.\n"
    "- Lead with the direct answer; put supporting detail underneath.\n"
    "- Be concise. Do not restate the question. No filler ('Certainly!', 'Of course!').\n"
    "- If unsure, say so explicitly — do not guess."
)

# Sprint 4 PR2: structured-grounding policy. Appended to the system prompt
# ONLY when SHAIL_CONTEXT_PACKET is ON. References the packet section
# names emitted by `apps.shail.retrieval.packet.build`.
GROUNDING_POLICY_PROMPT = (
    "\n\nSTRUCTURED GROUNDING POLICY — read carefully:\n"
    "Below the AVAILABLE CITATIONS block you will see a structured packet "
    "with four sections:\n"
    "  === EXACT_FACTS ===          # canonical fact rows (entity, attribute, value)\n"
    "  === STRUCTURED_FACTS ===     # rows from blueprint tables/metrics\n"
    "  === SUPPORTING_CONTEXT ===   # supporting prose passages\n"
    "  === CITATIONS ===            # condensed list of memory_ids and titles\n\n"
    "Rules for numeric/value answers:\n"
    "1. Answer numeric values ONLY using rows present in EXACT_FACTS or "
    "   STRUCTURED_FACTS. Cite the source memory_id with the existing "
    "   {{cite:memory:<memory_id>}} token.\n"
    "2. If a value the user asks for is NOT present in EXACT_FACTS or "
    "   STRUCTURED_FACTS, reply exactly: \"not found in memory\" and STOP. "
    "   Do not fabricate or interpolate numbers.\n"
    "3. If both sections show \"(none)\", treat the value as absent.\n"
    "4. SUPPORTING_CONTEXT is for narrative framing only — never source "
    "   numeric values from it.\n"
    "5. Keep memory_id citations natural in prose (e.g., \"per "
    "{{cite:memory:abc123}}\"). Do not dump raw memory_id strings.\n"
    "6. EMPTY CONTEXT: If the AVAILABLE CITATIONS block is missing entirely, "
    "or every section reads \"(none)\", you have NO retrieved memory. Do not "
    "emit any citation token in that case. Answer from general knowledge and "
    "say briefly that nothing relevant was found in the user's memory."
)


def _system_prompt() -> str:
    """Return the active system prompt. Appends grounding policy when
    SHAIL_CONTEXT_PACKET is ON. Default OFF returns the legacy prompt
    bit-for-bit."""
    s = get_settings()
    if s.shail_context_packet and s.shail_hybrid_retrieval:
        return CHAT_SYSTEM_PROMPT + GROUNDING_POLICY_PROMPT
    return CHAT_SYSTEM_PROMPT

RAG_K               = 6
RAG_K_OVERFETCH     = 12   # fetch this many from Chroma, re-rank to RAG_K with time-decay
DECAY_HALF_LIFE_DAYS = 30  # exponential decay half-life for memory recall ranking
WEB_MAX_RESULTS = 3
WEB_TIMEOUT     = 3.0
PAST_CHAT_K     = 3


def _apply_time_decay(
    hits: List[tuple], *, k: int = RAG_K, half_life_days: float = DECAY_HALF_LIFE_DAYS,
) -> list:
    """Re-rank `(content, score, metadata)` tuples by Chroma cosine distance
    weighted by an exponential time-decay penalty on `captured_ts` epoch.

    Lower adjusted score = better. Pinned records (`metadata.pinned == "true"`)
    bypass the decay penalty so curated memories stay top regardless of age.
    Records missing/unparseable `captured_ts` are treated as no-decay so
    legacy/imported memories don't disappear from chat context.
    """
    now_ts = time.time()
    scored: list[tuple[tuple, float]] = []
    for hit in hits:
        try:
            _content, score, meta = hit
        except (TypeError, ValueError):
            continue
        meta = meta or {}
        if meta.get("pinned") == "true":
            adjusted = float(score)
        else:
            captured_raw = meta.get("captured_ts")
            try:
                captured = float(captured_raw) if captured_raw is not None else None
            except (TypeError, ValueError):
                captured = None
            if captured is None:
                adjusted = float(score)
            else:
                age_days = max(0.0, (now_ts - captured) / 86400.0)
                decay = math.exp(-age_days / half_life_days)
                adjusted = float(score) / (decay + 0.01)
        scored.append((hit, adjusted))
    scored.sort(key=lambda x: x[1])
    return [h for h, _ in scored[:k]]

# ── Auth ────────────────────────────────────────────────────────────────────

def _require_user(credentials: Optional[HTTPAuthorizationCredentials]) -> str:
    if not credentials:
        raise HTTPException(status_code=401, detail="Authentication required")
    user_id = get_user_by_api_key(credentials.credentials)
    if not user_id:
        raise HTTPException(status_code=401, detail="Invalid API key")
    touch_api_key_last_used(credentials.credentials)
    touch_user_last_seen(user_id)
    return user_id


# ── Heuristics ──────────────────────────────────────────────────────────────

# Triggers past-chat retrieval. Match on whole-word boundaries to avoid
# false positives like "before" matching "beforehand" — we want explicit
# references to prior conversations, not generic prose.
_PRIOR_CHAT_PATTERNS = re.compile(
    r"\b(earlier|previously|before|last\s+time|last\s+week|last\s+month|"
    r"yesterday|we\s+discussed|we\s+talked|you\s+said|you\s+told|you\s+mentioned|"
    r"remember\s+when|remember\s+what|continue|continuing)\b",
    re.IGNORECASE,
)


def references_prior_chat(query: str, *, is_first_in_session: bool) -> bool:
    """Decide whether to pull past-chat RAG for this query.

    True when:
      - explicit temporal/conversational trigger words match, OR
      - this is the first message in a brand-new session AND the query is
        long enough that the user is likely opening with a continuation
        ("ok now let's pick up where we left off…")
    """
    if _PRIOR_CHAT_PATTERNS.search(query):
        return True
    if is_first_in_session and len(query.split()) >= 8:
        # Be conservative on greenfield sessions: only pull past chats when
        # the user wrote a substantial message (not "hi"). We bias toward
        # quietly including continuity context.
        return True
    return False


# ── Past-chat RAG namespace ─────────────────────────────────────────────────

def _past_chat_namespace(user_id: str) -> str:
    return f"chat_{user_id}"


def _index_past_chat_turn(
    *, user_id: str, session_id: str, user_msg_id: str, assistant_msg_id: str,
    user_text: str, assistant_text: str, session_title: str,
) -> None:
    """Embed a completed Q+A pair into the user's past-chat namespace.
    Errors are logged and swallowed — past-chat indexing is best-effort.
    """
    try:
        record_id = assistant_msg_id  # one indexed turn per assistant reply
        content = f"Q: {user_text}\n\nA: {assistant_text}"
        ingest(records=[{
            "id": record_id,
            # 12000 chars (Sprint 1/3): old 6000 cap silently truncated long
            # answers. FTS5 fallback (chat_messages_fts) covers full content
            # via chat_messages trigger regardless of this cap.
            "content": content[:12000],
            "namespace": _past_chat_namespace(user_id),
            "metadata": {
                "id": record_id,
                "type": "chat_turn",
                "session_id": session_id,
                "session_title": session_title,
                "user_message_id": user_msg_id,
                "assistant_message_id": assistant_msg_id,
                "title": session_title,
                "summary": user_text[:200],
                "namespace": _past_chat_namespace(user_id),
            },
        }])
    except Exception as e:
        logger.warning("past-chat index failed (session=%s): %s", session_id, e)


def _search_past_chats(user_id: str, query: str, k: int = PAST_CHAT_K) -> list:
    """Hybrid past-chat search. Returns (content, score, meta) tuples.

    Strategy:
      1. Vector query over `chat_{user_id}` namespace.
      2. If embedder is unavailable (zero vector probe) OR vector returns no
         hits, fall back to FTS5 keyword search (Sprint 1's chat_messages_fts).
      3. Each tuple's meta carries `source: 'vector' | 'fts'` for citation UI.

    Meta shape stays compatible with the past-chat citation builder:
      assistant_message_id, session_id, session_title, source.
    """
    from shail.memory.embeddings import is_zero_vector

    vector_hits: list = []
    embedder_failed = False
    try:
        store = _get_store()
        emb = emb_q(query)
        if is_zero_vector(emb):
            embedder_failed = True
        else:
            raw = store.query(
                query_embedding=emb,
                namespace=_past_chat_namespace(user_id),
                filters=None,
                k=k,
            )
            for r in raw:
                meta = dict(r.get("metadata") or {})
                meta["source"] = "vector"
                vector_hits.append((r["content"], float(r.get("score", 0.0)), meta))
    except Exception as e:
        logger.warning("past-chat vector search failed: %s", e)
        embedder_failed = True

    if vector_hits and not embedder_failed:
        return vector_hits[:k]

    # FTS fallback — keeps past-chat retrieval working when embedder is down.
    if not chat_store.fts_available():
        return vector_hits[:k]
    try:
        fts_rows = chat_store.search_chat_fts(user_id, query, limit=k)
    except Exception as e:
        logger.warning("past-chat FTS fallback failed: %s", e)
        return vector_hits[:k]

    fts_hits: list = []
    seen = {m.get("assistant_message_id") or m.get("id") for _, _, m in vector_hits}
    for row in fts_rows:
        mid = row["message_id"]
        if mid in seen:
            continue
        # bm25 rank: smaller = better match (negative scores possible);
        # negate so higher score means stronger hit, parallel to vector cos sim.
        score = -float(row.get("rank") or 0.0)
        meta = {
            "id": mid,
            "assistant_message_id": mid,
            "session_id": row["session_id"],
            "session_title": "(keyword match)",
            "source": "fts",
        }
        fts_hits.append((row["content"], score, meta))

    combined = (vector_hits + fts_hits)[:k]
    return combined


# ── Pydantic models ─────────────────────────────────────────────────────────

class ChatMessage(BaseModel):
    role: str
    content: str


class ChatRequest(BaseModel):
    message: str = Field(..., min_length=1)
    session_id: Optional[str] = None
    stream: bool = True


class WebSourceOut(BaseModel):
    title: str
    url: str
    snippet: str = ""


class MemoryCitation(BaseModel):
    id: str
    title: str
    score: float = 0.0


class PastChatCitation(BaseModel):
    message_id: str
    session_id: str
    session_title: str
    snippet: str
    score: float = 0.0


class MCPCitation(BaseModel):
    provider: str
    id: str
    title: str
    snippet: str = ""
    url: Optional[str] = None


class LocalFileCitation(BaseModel):
    id: str
    title: str
    path: str
    snippet: str = ""
    file_type: str = ""
    score: float = 0.0


class ChatResponse(BaseModel):
    answer: str
    session_id: str
    message_id: str
    provider: str
    model: str
    fellback: bool = False
    memories: List[MemoryCitation] = Field(default_factory=list)
    past_chats: List[PastChatCitation] = Field(default_factory=list)
    web_sources: List[WebSourceOut] = Field(default_factory=list)
    mcp_sources: List[MCPCitation] = Field(default_factory=list)
    local_files: List[LocalFileCitation] = Field(default_factory=list)
    used_web: bool = False


class SessionPatch(BaseModel):
    title: Optional[str] = None
    pinned: Optional[bool] = None
    # Phase C — capture + retention controls
    capture_enabled: Optional[bool] = None
    retention_policy: Optional[str] = None  # 'keep_raw' | 'blueprint_only' | 'transcript_deleted'


class BackfillRequest(BaseModel):
    include_blueprint: bool = True
    char_cap: int = 24_000
    # Sprint 2: when True, runs synchronously (legacy; used by tests/small sessions).
    # When False (default in UI), kicks off via BackgroundTasks and returns immediately.
    synchronous: bool = False


class BackfillResponse(BaseModel):
    session_id: str
    turns_seen: int
    turns_indexed: int
    turns_skipped: int
    blueprint_generated: bool
    blueprint_memory_id: Optional[str] = None
    raw_transcript_chars: int
    errors: list[str] = Field(default_factory=list)
    duration_ms: float
    # Sprint 1
    degraded_mode: bool = False
    degraded_reason: Optional[str] = None
    fts_fallback_used: bool = False


class BackfillJobResponse(BaseModel):
    """Sprint 2: immediate response for async backfill job."""
    session_id: str
    job_id: str
    state: str  # 'running' | 'idle'
    accepted: bool


class BackfillStatusResponse(BaseModel):
    """Sprint 2: polling endpoint payload."""
    session_id: str
    state: str
    cursor: int
    total_messages: int
    progress_pct: float
    remaining: int
    job_id: Optional[str] = None
    error: Optional[str] = None
    backfilled_at: Optional[str] = None


# ── Context build ───────────────────────────────────────────────────────────

async def _fetch_mcp_sources(user_id: str, query: str) -> list[MCPCitation]:
    """Hybrid-routed active fetch over the user's connected MCP providers.

    Stage A picks providers via heuristic; Stage B uses LLM fallback when
    ambiguous. Each provider call has a 2s hard timeout; failures are
    logged and dropped so chat never stalls on a flaky integration.
    """
    conns = list_mcp_connections(user_id)
    if not conns:
        return []
    connected = {c["provider"] for c in conns}
    picked = await pick_providers(query, connected=connected, user_id=user_id)
    if not picked:
        return []

    async def _one(provider_name: str) -> list[MCPCitation]:
        prov = get_mcp_provider(provider_name)
        conn = get_mcp_connection(user_id, provider_name)
        if not prov or not conn:
            return []
        # Refresh Google tokens before any live API call — they expire in 1hr.
        try:
            from apps.shail.mcp._oauth import maybe_refresh_google_token
            conn = await maybe_refresh_google_token(conn)
        except Exception as _ref_err:
            logger.debug("token refresh probe failed: %s", _ref_err)
        settings = get_mcp_settings(user_id, provider_name) or {}
        # Provider-specific settings hint (e.g. github needs login from OAuth metadata)
        settings = {**settings, **(conn.get("metadata") or {})}
        try:
            hits = await asyncio.wait_for(
                prov.fetch_relevant(
                    user_id=user_id, query=query, k=3,
                    access_token=conn["access_token"],
                    refresh_token=conn.get("refresh_token"),
                    settings=settings,
                ),
                timeout=2.0,
            )
        except asyncio.TimeoutError:
            logger.warning("mcp fetch timeout: %s", provider_name)
            return []
        except Exception as e:
            logger.warning("mcp fetch error (%s): %s", provider_name, e)
            return []
        out: list[MCPCitation] = []
        for h in hits:
            out.append(MCPCitation(
                provider=provider_name,
                id=h.id,
                title=h.title,
                snippet=h.snippet,
                url=h.url,
            ))
            write_event("MCP_FETCH", f"{provider_name}: {h.title[:60]}",
                        user_id=user_id, ref_id=h.id)
        return out

    results = await asyncio.gather(*[_one(p) for p in picked], return_exceptions=True)
    flat: list[MCPCitation] = []
    for r in results:
        if isinstance(r, list):
            flat.extend(r)
    return flat


async def _build_context(
    user_id: str, query: str, *, is_first_in_session: bool,
    task_id: Optional[str] = None,
) -> tuple[str, list[MemoryCitation], list[PastChatCitation], list[WebSourceOut], list[MCPCitation], list[LocalFileCitation]]:
    """Run all retrieval sources in parallel; combine into a single context
    block plus structured citation lists.

    `task_id` (Sprint 2): if provided, retrieved memories are registered for
    usefulness feedback after the task completes.
    """
    namespace = f"user_{user_id}"

    async def _rag() -> list:
        # Sprint 3 PR3 — flag-gated hybrid retrieval. Default OFF preserves
        # legacy semantic-only path bit-for-bit. Hybrid returns the same
        # `(content, score, metadata)` tuple shape so the rest of
        # `_build_context` is untouched.
        if get_settings().shail_hybrid_retrieval:
            try:
                hits = await _hybrid_search(
                    query, namespace=namespace,
                    k=RAG_K, overfetch_k=RAG_K_OVERFETCH,
                    task_id=task_id,
                )
                return [h for h in hits if (h[2] or {}).get("source") != "local_file"]
            except Exception as e:
                logger.warning("hybrid_search failed; falling back to legacy rag: %s", e)
        try:
            raw = rag_search(query, k=RAG_K_OVERFETCH, namespace=namespace)
            raw = [h for h in raw if (h[2] or {}).get("source") != "local_file"]
            return _apply_time_decay(raw, k=RAG_K)
        except Exception as e:
            logger.warning("rag_search failed in chat: %s", e)
            return []

    async def _past() -> list:
        if not references_prior_chat(query, is_first_in_session=is_first_in_session):
            return []
        return await asyncio.to_thread(_search_past_chats, user_id, query, PAST_CHAT_K)

    async def _mcp_rag() -> list[MCPCitation]:
        """Query the vector-indexed MCP namespaces for semantically relevant
        docs. Complements live fetch_relevant() with content that was indexed
        in the background (READMEs, Drive docs, Notion pages, Gmail threads).
        """
        conns = list_mcp_connections(user_id)
        if not conns:
            return []
        cites: list[MCPCitation] = []
        for c in conns:
            pname = c["provider"]
            ns = f"mcp_{user_id}_{pname}"
            try:
                hits = await asyncio.to_thread(rag_search, query, k=2, namespace=ns)
                for content, score, meta in hits:
                    if float(score or 0.0) < 0.3:
                        continue  # skip low-relevance indexed docs
                    cites.append(MCPCitation(
                        provider=pname,
                        id=meta.get("provider_id") or meta.get("id") or "",
                        title=meta.get("title") or "(untitled)",
                        snippet=(content or "")[:200],
                        url=meta.get("sourceUrl"),
                    ))
            except Exception as _e:
                logger.debug("mcp_rag failed for %s/%s: %s", user_id, pname, _e)
        return cites

    rag_task     = asyncio.create_task(_rag())
    past_task    = asyncio.create_task(_past())
    mcp_task     = asyncio.create_task(_fetch_mcp_sources(user_id, query))
    mcp_rag_task = asyncio.create_task(_mcp_rag())
    local_file_task = None
    _settings_lf = get_settings()
    if _settings_lf.shail_local_files_in_chat:
        async def _local_files() -> list[LocalFileCitation]:
            try:
                from apps.shail.retrieval.local_files import retrieve_local_file_context
                hits = await asyncio.to_thread(
                    retrieve_local_file_context, query,
                    k=_settings_lf.shail_local_files_k,
                    max_snippet_chars=_settings_lf.shail_local_files_snippet_chars,
                    read_cap_bytes=_settings_lf.shail_local_files_read_cap_bytes,
                )
                min_score = _settings_lf.shail_local_files_min_score
                hits = [h for h in hits if h.score >= min_score]
                return [
                    LocalFileCitation(
                        id=h.id, title=h.title, path=h.path,
                        snippet=h.snippet[:_settings_lf.shail_local_files_snippet_chars],
                        file_type=h.file_type, score=h.score,
                    )
                    for h in hits
                ]
            except Exception as exc:
                logger.debug("local file retrieval skipped: %s", exc)
                return []
        local_file_task = asyncio.create_task(_local_files())
    web_task = (
        asyncio.create_task(web_search(query, max_results=WEB_MAX_RESULTS, timeout=WEB_TIMEOUT))
        if needs_web_search(query) else None
    )

    rag_hits     = await rag_task
    past_hits    = await past_task
    mcp_cites    = await mcp_task
    mcp_rag_hits = await mcp_rag_task
    local_files  = await local_file_task if local_file_task else []
    # Merge live fetch + indexed vector results; deduplicate by (provider, id)
    seen_mcp = {(c.provider, c.id) for c in mcp_cites}
    for c in mcp_rag_hits:
        if (c.provider, c.id) not in seen_mcp:
            mcp_cites.append(c)
            seen_mcp.add((c.provider, c.id))
    web_results  = await web_task if web_task else []

    parts: list[str] = []
    citations: list[MemoryCitation] = []
    past_chat_cites: list[PastChatCitation] = []
    web_sources: list[WebSourceOut] = []

    # ── Memories ──
    # Sprint 4 PR3: deterministic context packet behind SHAIL_CONTEXT_PACKET.
    # Coupled with SHAIL_HYBRID_RETRIEVAL: packet sections expect hits with
    # `metadata.surface` set by hybrid_search. If packet is enabled but
    # hybrid is OFF, EXACT_FACTS will be (none) and Gemma will reply
    # "not found in memory" too aggressively — guard against that.
    _settings = get_settings()
    _use_packet = _settings.shail_context_packet and _settings.shail_hybrid_retrieval
    if _use_packet and rag_hits:
        from apps.shail.retrieval.packet import build as _build_packet
        result = _build_packet(rag_hits)
        parts.append(result.text)
        for content, score, meta in rag_hits:
            mid = meta.get("customId") or meta.get("id") or meta.get("memory_id") or ""
            title = meta.get("title", "(untitled)")
            if mid:
                citations.append(MemoryCitation(id=mid, title=title, score=float(score)))
                write_event("RECALL", f"memory used as chat context: {title[:60]}",
                            user_id=user_id, ref_id=mid)
    elif rag_hits:
        # Legacy formatter — bit-for-bit unchanged.
        hit_ids = [
            (m.get("customId") or m.get("id") or m.get("memory_id") or "")
            for _, _, m in rag_hits
        ]
        blueprints = get_blueprints_for_ids([i for i in hit_ids if i])

        rag_lines = ["[AVAILABLE CITATIONS — Memories]"]
        for content, score, meta in rag_hits:
            mid = meta.get("customId") or meta.get("id") or meta.get("memory_id") or ""
            title = meta.get("title", "(untitled)")
            snippet = (content or "").strip().replace("\n", " ")[:300]
            block = f"[memory_id={mid}] {title}\n{snippet}"
            bp = blueprints.get(mid) if mid else None
            if bp:
                hl = format_blueprint_for_context(bp)
                if hl:
                    block += f"\n  blueprint:\n{hl}"
            rag_lines.append(block)
            if mid:
                citations.append(MemoryCitation(id=mid, title=title, score=float(score)))
                write_event("RECALL", f"memory used as chat context: {title[:60]}",
                            user_id=user_id, ref_id=mid)
        parts.append("\n\n".join(rag_lines))

    # ── Past chats ──
    if past_hits:
        chat_lines = ["[AVAILABLE CITATIONS — Past chats from this user]"]
        for content, score, meta in past_hits:
            asst_id = meta.get("assistant_message_id") or meta.get("id") or ""
            sess_id = meta.get("session_id") or ""
            title   = meta.get("session_title") or "(prior chat)"
            snippet = (content or "").strip().replace("\n", " ")[:280]
            chat_lines.append(f"[message_id={asst_id}] (from session: {title})\n{snippet}")
            if asst_id:
                past_chat_cites.append(PastChatCitation(
                    message_id=asst_id,
                    session_id=sess_id,
                    session_title=title,
                    snippet=snippet[:200],
                    score=float(score),
                ))
                write_event("RECALL", f"past chat used as context: {title[:60]}",
                            user_id=user_id, ref_id=asst_id)
        parts.append("\n\n".join(chat_lines))

    # ── MCP connected sources ──
    if mcp_cites:
        mcp_lines = ["[AVAILABLE CITATIONS — Your connected sources]"]
        for c in mcp_cites:
            mcp_lines.append(
                f"[mcp:{c.provider}:{c.id}] {c.title}\n{c.snippet}"
            )
        parts.append("\n\n".join(mcp_lines))

    # ── Local files ──
    # Pointer-only retrieval: the file lives ONLY on the user's disk; nothing
    # was written to the vector store. The model sees the snippet, the
    # extractor used, the score, and the file_type so it can rank these
    # against memories / web / MCP hits.
    if local_files:
        file_lines = [
            "[AVAILABLE CITATIONS — Local files on this device]",
            "(Not in memory. Content read live from disk. Cite with "
            "{{cite:local_file:<id>}}.)",
        ]
        for f in local_files:
            header = f"[local_file_id={f.id} type={f.file_type or 'unknown'} score={f.score:.2f}]"
            file_lines.append(
                f"{header} {f.title}\n"
                f"path: {f.path}\n"
                f"{f.snippet}"
            )
            write_event("RECALL", f"local file used as chat context: {f.title[:60]}",
                        user_id=user_id, ref_id=f.id)
        parts.append("\n\n".join(file_lines))

    # ── Web ──
    if web_results:
        parts.append("[AVAILABLE CITATIONS — Web results]\n" + web_format(web_results))
        web_sources = [WebSourceOut(**r) for r in web_results]

    return "\n\n---\n\n".join(parts), citations, past_chat_cites, web_sources, mcp_cites, local_files


def _sse(event: dict) -> bytes:
    return f"data: {json.dumps(event, ensure_ascii=False)}\n\n".encode("utf-8")


# ── Auto-title generation ───────────────────────────────────────────────────

async def _autotitle(session_id: str, user_id: str, first_user_msg: str, first_assistant_msg: str) -> None:
    """Generate a 4-6 word title for a fresh session. Fire-and-forget."""
    try:
        prompt = (
            f"Generate a 4-6 word title for this conversation. "
            f"Reply with ONLY the title — no quotes, no punctuation at the end.\n\n"
            f"User: {first_user_msg[:300]}\nAssistant: {first_assistant_msg[:300]}"
        )
        title, _ = await call_llm(
            messages=[{"role": "user", "content": prompt}],
            user_id=user_id,
            system_prompt="You title conversations concisely.",
        )
        title = (title or "").strip().strip('"').strip("'")[:80]
        if title:
            chat_store.update_session(session_id, user_id, title=title)
    except Exception as e:
        logger.warning("autotitle failed for %s: %s", session_id, e)


# ── Session endpoints ──────────────────────────────────────────────────────

@chat_router.get("/sessions")
async def list_sessions(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(_bearer),
) -> dict:
    user_id = _require_user(credentials)
    return {"items": chat_store.list_sessions(user_id)}


@chat_router.post("/sessions")
async def create_session(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(_bearer),
) -> dict:
    user_id = _require_user(credentials)
    return chat_store.create_session(user_id)


@chat_router.get("/sessions/{session_id}")
async def get_session(
    session_id: str,
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(_bearer),
) -> dict:
    user_id = _require_user(credentials)
    sess = chat_store.get_session(session_id, user_id)
    if not sess:
        raise HTTPException(status_code=404, detail="Session not found")
    sess["messages"] = chat_store.get_messages(session_id, user_id)
    return sess


@chat_router.patch("/sessions/{session_id}")
async def patch_session(
    session_id: str,
    body: SessionPatch,
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(_bearer),
) -> dict:
    user_id = _require_user(credentials)
    sess = chat_store.update_session(session_id, user_id, title=body.title, pinned=body.pinned)
    if not sess:
        raise HTTPException(status_code=404, detail="Session not found")
    # Phase C: capture + retention controls
    if body.capture_enabled is not None:
        session_backfill.set_session_capture(session_id, user_id, body.capture_enabled)
    if body.retention_policy is not None:
        try:
            session_backfill.set_session_retention(session_id, user_id, body.retention_policy)
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e))
    meta = session_backfill.get_session_meta(session_id, user_id) or sess
    return {
        **sess,
        "capture_enabled": bool(meta.get("capture_enabled", 1)),
        "retention_policy": meta.get("retention_policy", "keep_raw"),
        "blueprint_memory_id": meta.get("blueprint_memory_id"),
        "backfilled_at": meta.get("backfilled_at"),
    }


# ── Phase C: backfill, timeline, blueprint, redact ──────────────────────────

@chat_router.post("/sessions/{session_id}/backfill")
async def backfill_session_endpoint(
    session_id: str,
    background_tasks: BackgroundTasks,
    body: BackfillRequest = BackfillRequest(),
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(_bearer),
):
    """Sprint 2: async backfill job.

    Default (synchronous=False): returns BackfillJobResponse immediately,
    backfill runs in BackgroundTasks. Client polls /backfill/status.
    Returns 409 if already running. Resumes from backfill_cursor on retry.

    Synchronous mode (synchronous=True): blocks until done, returns full
    BackfillResponse. Used by tests and small sessions.
    """
    user_id = _require_user(credentials)
    # Ownership check up front — both paths need it
    session = chat_store.get_session(session_id, user_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    status = session_backfill.get_backfill_status(session_id, user_id)
    if status and status["state"] == "running":
        raise HTTPException(
            status_code=409,
            detail=f"Backfill already running (cursor={status['cursor']}/{status['total_messages']})",
        )

    if body.synchronous:
        summary = await session_backfill.backfill_session(
            session_id, user_id,
            include_blueprint=body.include_blueprint,
            char_cap=body.char_cap,
        )
        if "session_not_found" in summary.errors:
            raise HTTPException(status_code=404, detail="Session not found")
        return BackfillResponse(**summary.to_dict())

    # Async path: stamp running + queue background task
    job_id = f"bf_{uuid.uuid4().hex[:12]}"
    session_backfill._set_backfill_state(
        session_id, state="running", job_id=job_id, error="",
    )

    async def _run() -> None:
        try:
            await session_backfill.backfill_session(
                session_id, user_id,
                include_blueprint=body.include_blueprint,
                char_cap=body.char_cap,
            )
        except Exception as exc:
            logger.exception("background backfill failed for %s", session_id)
            session_backfill._set_backfill_state(
                session_id, state="failed", error=f"{type(exc).__name__}: {exc}",
            )

    background_tasks.add_task(_run)
    return BackfillJobResponse(
        session_id=session_id, job_id=job_id, state="running", accepted=True,
    )


@chat_router.get(
    "/sessions/{session_id}/backfill/status",
    response_model=BackfillStatusResponse,
)
async def backfill_status_endpoint(
    session_id: str,
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(_bearer),
) -> BackfillStatusResponse:
    """Sprint 2: poll backfill progress. Client UI polls this every ~2s."""
    user_id = _require_user(credentials)
    status = session_backfill.get_backfill_status(session_id, user_id)
    if not status:
        raise HTTPException(status_code=404, detail="Session not found")
    return BackfillStatusResponse(**status)


# ── Phase C Sprint 7: bulk backfill + observability ─────────────────────────

@chat_router.post("/backfill/all")
async def backfill_all_endpoint(
    background_tasks: BackgroundTasks,
    include_blueprint: bool = True,
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(_bearer),
) -> dict:
    """Sprint 7: enqueue background backfill for every eligible session.

    Eligible = not currently 'running'. Sessions in 'done' state are re-run
    from cursor=0 (idempotent semantics, matches single-session behavior).
    Returns the job list; client polls per-session status endpoints.
    """
    user_id = _require_user(credentials)
    eligible = session_backfill.list_backfillable_sessions(user_id)
    jobs: list[dict] = []
    for s in eligible:
        sid = s["id"]
        job_id = f"bf_{uuid.uuid4().hex[:12]}"
        session_backfill._set_backfill_state(
            sid, state="running", job_id=job_id, error="",
        )
        jobs.append({"session_id": sid, "job_id": job_id, "title": s["title"]})

        async def _run(sid_: str = sid) -> None:
            try:
                await session_backfill.backfill_session(
                    sid_, user_id, include_blueprint=include_blueprint,
                )
            except Exception as exc:
                logger.exception("bulk backfill failed sid=%s", sid_)
                session_backfill._set_backfill_state(
                    sid_, state="failed", error=f"{type(exc).__name__}: {exc}",
                )

        background_tasks.add_task(_run)

    return {"accepted": True, "jobs_enqueued": len(jobs), "jobs": jobs}


@chat_router.get("/backfill/stats")
async def backfill_stats_endpoint(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(_bearer),
) -> dict:
    """Sprint 7: aggregate backfill state across all of user's sessions."""
    user_id = _require_user(credentials)
    return session_backfill.get_backfill_stats(user_id)


# ── Phase C Sprint 4: external chat imports ─────────────────────────────────

@chat_router.post("/import")
async def import_chats_endpoint(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    source: str = Form(...),
    auto_backfill: bool = Form(True),
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(_bearer),
) -> dict:
    """Sprint 4 + Plan B3: ingest an external chat export.

    `source` ∈ {chatgpt, claude, cursor, gemini, grok, perplexity}.
    The uploaded file is parsed into (user, assistant) pairs, sessions+messages
    are created, then a backfill job is enqueued per session (unless
    `auto_backfill=false`).
    """
    user_id = _require_user(credentials)
    from apps.shail.importers import PARSERS, import_conversation_payload

    if source not in PARSERS:
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported source '{source}'. Supported: {sorted(PARSERS)}",
        )
    raw = await file.read()
    if not raw:
        raise HTTPException(status_code=400, detail="Empty file")

    try:
        conversations = PARSERS[source](raw)
    except Exception as exc:
        raise HTTPException(
            status_code=400,
            detail=f"Failed to parse {source} export: {type(exc).__name__}: {exc}",
        )

    result = import_conversation_payload(
        user_id=user_id, source=source, conversations=conversations,
    )

    if auto_backfill and result.session_ids:
        async def _enqueue() -> None:
            for sid in result.session_ids:
                try:
                    await session_backfill.backfill_session(
                        sid, user_id, include_blueprint=True,
                    )
                except Exception:
                    logger.exception("post-import backfill failed sid=%s", sid)
        background_tasks.add_task(_enqueue)

    return result.to_dict()


# ── Local file/folder ingestion ─────────────────────────────────────────────

class FileIngestRequest(BaseModel):
    """Index local file pointers for retrieval.

    `paths` are absolute filesystem paths. Directories are walked recursively.
    This endpoint updates the local path_index only; it does not embed file
    contents into SHAIL memory.
    """
    paths: List[str] = Field(..., description="Absolute file or directory paths")
    max_files: int = Field(default=500, ge=1, le=5000)


class FileIngestResponse(BaseModel):
    ingested: int
    skipped: int
    files_seen: int
    errors: List[str] = Field(default_factory=list)


@chat_router.post("/files/ingest", response_model=FileIngestResponse)
async def ingest_local_files(
    req: FileIngestRequest,
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(_bearer),
) -> FileIngestResponse:
    """Walk paths and refresh the local path_index.

    Safety:
    - Hidden files and common junk dirs are skipped.
    - Symlinks are NOT followed (avoid loops / escaping intended scope).
    - Hard cap on file count to prevent runaway scans.
    """
    import os as _os
    from apps.shail.settings import get_settings
    from shail.memory import path_index
    user_id = _require_user(credentials)

    files: list[str] = []
    errors: list[str] = []
    files_seen = 0
    settings = get_settings()

    for root in req.paths:
        try:
            if _os.path.isfile(root):
                files_seen += 1
                if path_index.upsert_file(settings.path_index_db, root):
                    files.append(root)
            elif _os.path.isdir(root):
                for dirpath, dirnames, filenames in _os.walk(root, followlinks=False):
                    # Prune hidden + junk dirs in-place
                    dirnames[:] = [d for d in dirnames if not d.startswith(".") and d not in path_index._SKIP_DIRS]
                    path_index.upsert_folder(settings.path_index_db, dirpath, child_count=len(dirnames) + len(filenames))
                    for fn in filenames:
                        if fn.startswith("."):
                            continue
                        files_seen += 1
                        fp = _os.path.join(dirpath, fn)
                        if path_index.upsert_file(settings.path_index_db, fp):
                            files.append(fp)
                        if len(files) >= req.max_files:
                            break
                    if len(files) >= req.max_files:
                        break
            else:
                errors.append(f"not found: {root}")
        except Exception as exc:
            errors.append(f"{root}: {exc}")

    files = files[:req.max_files]

    indexed = len(files)
    write_event("INDEX", f"local file map: {indexed} files indexed",
                user_id=user_id, ref_id=None)
    return FileIngestResponse(
        ingested=indexed,
        skipped=max(0, files_seen - indexed),
        files_seen=files_seen,
        errors=errors,
    )


# ── Blueprint queue observability (Plan B6) ──────────────────────────────────

@chat_router.get("/blueprint-jobs")
async def list_blueprint_jobs(
    state: Optional[str] = Query(None, description="pending|running|done|failed"),
    limit: int = Query(100, ge=1, le=500),
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(_bearer),
) -> dict:
    _require_user(credentials)
    from apps.shail.blueprint_queue import list_jobs
    return {"jobs": list_jobs(state=state, limit=limit)}


@chat_router.post("/sessions/{session_id}/blueprint/retry")
async def retry_session_blueprint(
    session_id: str,
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(_bearer),
) -> dict:
    """Force re-enqueue a blueprint job for this session. Useful when the
    user knows Ollama is now back up and doesn't want to wait for the poll."""
    user_id = _require_user(credentials)
    session = chat_store.get_session(session_id, user_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    from apps.shail.blueprint_queue import enqueue
    from apps.shail.session_backfill import _session_blueprint_memory_id
    job_id = enqueue(
        memory_id=_session_blueprint_memory_id(session_id),
        session_id=session_id,
        user_id=user_id,
        content_type="chat_session",
    )
    return {"ok": True, "job_id": job_id, "session_id": session_id}


class AutoRedactRequest(BaseModel):
    enabled: bool


@chat_router.put("/sessions/{session_id}/auto-redact")
async def set_session_auto_redact_endpoint(
    session_id: str,
    body: AutoRedactRequest,
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(_bearer),
) -> dict:
    """Plan B7: per-session opt-in toggle for auto-deleting raw transcript
    after a high-quality blueprint."""
    user_id = _require_user(credentials)
    from apps.shail.session_backfill import set_session_auto_redact
    ok = set_session_auto_redact(session_id, user_id, body.enabled)
    if not ok:
        raise HTTPException(status_code=404, detail="Session not found")
    return {"ok": True, "session_id": session_id, "auto_redact": body.enabled}


# ── Filesystem watcher endpoints ─────────────────────────────────────────────

class WatchRequest(BaseModel):
    path: str = Field(..., description="Absolute directory path to watch")


class WatchResponse(BaseModel):
    ok: bool
    path: Optional[str] = None
    status: Optional[str] = None
    error: Optional[str] = None


async def _ingest_paths_for_user(user_id: str, paths: List[str]) -> int:
    """Compatibility helper: refresh path_index rows, not memory vectors."""
    from shail.memory import path_index
    settings = get_settings()
    def _refresh() -> int:
        count = 0
        for fp in paths:
            try:
                if path_index.upsert_file(settings.path_index_db, fp):
                    count += 1
            except Exception as exc:
                logger.warning("path index refresh failed for %s: %s", fp, exc)
        return count
    try:
        return await asyncio.to_thread(_refresh)
    except Exception as exc:
        logger.error("path index refresh failed: %s", exc)
        return 0


@chat_router.post("/files/watch", response_model=WatchResponse)
async def start_watch(
    req: WatchRequest,
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(_bearer),
) -> WatchResponse:
    """Start watching a directory recursively. Changes trigger debounced
    re-ingest into the user's namespace."""
    user_id = _require_user(credentials)
    from shail.integrations.local.filesystem.adapter import get_adapter
    res = get_adapter().start_watch(user_id, req.path)
    return WatchResponse(
        ok=bool(res.get("ok")),
        path=res.get("path"),
        status=res.get("status"),
        error=res.get("error"),
    )


@chat_router.delete("/files/watch", response_model=WatchResponse)
async def stop_watch(
    path: str = Query(..., description="Absolute path previously registered"),
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(_bearer),
) -> WatchResponse:
    user_id = _require_user(credentials)
    from shail.integrations.local.filesystem.adapter import get_adapter
    res = get_adapter().stop_watch(user_id, path)
    return WatchResponse(ok=bool(res.get("ok")), path=res.get("path"), status=res.get("status"))


@chat_router.get("/files/watch")
async def list_watches(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(_bearer),
) -> dict:
    user_id = _require_user(credentials)
    from shail.integrations.local.filesystem.adapter import get_adapter
    return {"watches": get_adapter().list_watches(user_id)}


@chat_router.get("/sessions/{session_id}/timeline")
async def get_timeline(
    session_id: str,
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(_bearer),
) -> dict:
    """Return turn-by-turn timeline + session blueprint + retention state."""
    user_id = _require_user(credentials)
    tl = session_backfill.build_timeline(session_id, user_id)
    if tl is None:
        raise HTTPException(status_code=404, detail="Session not found")
    return tl


@chat_router.get("/sessions/{session_id}/blueprint")
async def get_session_blueprint(
    session_id: str,
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(_bearer),
) -> dict:
    """Return only the session-level blueprint (decisions, Q&A, entities…)."""
    user_id = _require_user(credentials)
    meta = session_backfill.get_session_meta(session_id, user_id)
    if not meta:
        raise HTTPException(status_code=404, detail="Session not found")
    from apps.shail.blueprints import get_blueprint as _get_bp
    bp_id = meta.get("blueprint_memory_id") or session_backfill._session_blueprint_memory_id(session_id)
    bp = _get_bp(bp_id)
    if not bp:
        raise HTTPException(status_code=404, detail="Blueprint not yet generated — run backfill first")
    return bp


@chat_router.post("/sessions/{session_id}/redact")
async def redact_session(
    session_id: str,
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(_bearer),
) -> dict:
    """Delete raw transcript. Refused unless a blueprint exists.
    Sets retention_policy to 'transcript_deleted'."""
    user_id = _require_user(credentials)
    result = session_backfill.redact_session_transcript(session_id, user_id)
    if not result.get("ok"):
        reason = result.get("reason", "unknown")
        if reason == "session_not_found":
            raise HTTPException(status_code=404, detail="Session not found")
        if reason == "no_blueprint_stored":
            raise HTTPException(
                status_code=400,
                detail="Cannot redact: no blueprint stored. Run /backfill first.",
            )
        raise HTTPException(status_code=400, detail=reason)
    return result


@chat_router.delete("/sessions/{session_id}")
async def delete_session(
    session_id: str,
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(_bearer),
) -> dict:
    user_id = _require_user(credentials)
    ok = chat_store.delete_session(session_id, user_id)
    if not ok:
        raise HTTPException(status_code=404, detail="Session not found")
    return {"ok": True, "id": session_id}


@chat_router.get("/sessions/{session_id}/health")
async def session_health(
    session_id: str,
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(_bearer),
) -> dict:
    """Sprint 1: capture-pipeline health for one session.

    Reports whether the embedder is reachable, whether FTS5 fallback is
    populated for this session, and how many vector records exist. UI uses
    this to surface degraded-mode banners.
    """
    user_id = _require_user(credentials)
    session = chat_store.get_session(session_id, user_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    # Probe embedder cheaply — single embed_query on a fixed string.
    ollama_up = False
    embedder_error: Optional[str] = None
    try:
        from shail.memory.embeddings import embed_query, is_zero_vector
        probe = embed_query("ping")
        ollama_up = not is_zero_vector(probe)
    except Exception as exc:
        embedder_error = str(exc)

    # FTS rows for this session
    fts_rows = 0
    fts_avail = chat_store.fts_available()
    if fts_avail:
        try:
            import sqlite3 as _sqlite3
            from apps.shail.settings import get_settings
            with _sqlite3.connect(get_settings().sqlite_path) as con:
                row = con.execute(
                    "SELECT COUNT(*) FROM chat_messages_fts WHERE session_id = ?",
                    (session_id,),
                ).fetchone()
                fts_rows = int(row[0]) if row else 0
        except Exception as exc:
            logger.warning("fts row count failed: %s", exc)

    # Vector store records — best-effort count via session_id metadata filter
    vector_rows = 0
    try:
        store = _get_store()
        # ChromaDB get() with where clause; small RAM ceiling
        result = store.collection.get(
            where={"session_id": session_id},
            limit=10_000,
        )
        vector_rows = len(result.get("ids", []))
    except Exception as exc:
        logger.warning("vector row count failed: %s", exc)

    # Crash-gap detection: count assistant messages that have no matching
    # vector record (assistant_message_id in metadata). This catches turns
    # that were written to chat_messages (and FTS via trigger) but whose
    # asyncio.create_task() indexing job was lost to a process crash.
    unindexed_turns = 0
    try:
        import sqlite3 as _sqlite3
        from apps.shail.settings import get_settings as _gs
        with _sqlite3.connect(_gs().sqlite_path) as con:
            total_assistant = con.execute(
                "SELECT COUNT(*) FROM chat_messages WHERE session_id = ? AND role = 'assistant'",
                (session_id,),
            ).fetchone()[0]
        # vector_rows counts records per assistant turn (one record per turn in
        # the standard per-turn indexer path). Treat the gap as unindexed.
        unindexed_turns = max(0, int(total_assistant) - int(vector_rows))
    except Exception as exc:
        logger.debug("unindexed_turns probe failed: %s", exc)

    return {
        "session_id": session_id,
        "ollama_up": ollama_up,
        "embedder_error": embedder_error,
        "fts_available": fts_avail,
        "fts_indexed": fts_rows,
        "vector_indexed": vector_rows,
        "degraded_mode": (not ollama_up) and fts_avail,
        "unindexed_turns": unindexed_turns,
        "needs_backfill": unindexed_turns > 0,
    }


# ── Main chat endpoint ──────────────────────────────────────────────────────

@chat_router.post("")
async def chat(
    req: ChatRequest,
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(_bearer),
):
    user_id = _require_user(credentials)
    cfg = get_user_llm_config(user_id)

    # Resolve / create session
    session: Optional[dict] = None
    if req.session_id:
        session = chat_store.get_session(req.session_id, user_id)
        if not session:
            raise HTTPException(status_code=404, detail="Session not found")
        is_first = chat_store.get_message_count(session["id"]) == 0
    else:
        session = chat_store.create_session(user_id, title=req.message[:60] or "New chat")
        is_first = True

    session_id = session["id"]

    # Persist the user message FIRST so it's not lost if streaming dies
    user_msg = chat_store.append_message(
        session_id, user_id, role="user", content=req.message,
    )

    # Build the unified RAG context — pass session_id as task_id so retrieved
    # memories get registered for post-response usefulness feedback.
    context, citations, past_chats, web_sources, mcp_sources, local_files = await _build_context(
        user_id, req.message, is_first_in_session=is_first,
        task_id=session_id,
    )

    # Reload prior thread for the LLM
    prior = chat_store.get_messages(session_id, user_id)
    history_msgs = [
        {"role": m["role"], "content": m["content"]}
        for m in prior if m["role"] in ("user", "assistant") and m["id"] != user_msg["id"]
    ]
    messages = history_msgs + [{"role": "user", "content": req.message}]

    # ── Non-streaming path ──
    if not req.stream:
        answer, meta = await call_llm(
            messages=messages, user_id=user_id,
            context=context, system_prompt=_system_prompt(),
        )
        # Sprint 4 PR3: post-generation hallucinated-number check.
        # Observability only — never blocks the response.
        if get_settings().shail_context_packet:
            try:
                from apps.shail.retrieval.validator import validate_answer
                validate_answer(answer or "", context or "")
            except Exception:
                pass
        asst_msg = chat_store.append_message(
            session_id, user_id, role="assistant", content=answer,
            citations=_collect_citations(citations, past_chats, web_sources, mcp_sources, local_files),
            provider=meta.get("provider"), model=meta.get("model"),
        )
        # Index into past-chat RAG and auto-title (fire-and-forget)
        _schedule_post_reply(
            user_id=user_id, session_id=session_id,
            user_msg=user_msg, assistant_msg=asst_msg,
            session_title=session["title"], is_first=is_first,
        )
        return ChatResponse(
            answer=answer, session_id=session_id, message_id=asst_msg["id"],
            provider=meta.get("provider", cfg["provider"]),
            model=meta.get("model", cfg["model"]),
            fellback=meta.get("fellback", False),
            memories=citations, past_chats=past_chats,
            web_sources=web_sources, mcp_sources=mcp_sources, local_files=local_files,
            used_web=bool(web_sources),
        )

    # ── Streaming path ──
    async def _stream() -> AsyncIterator[bytes]:
        yield _sse({
            "type": "meta", "session_id": session_id,
            "provider": cfg["provider"], "model": cfg["model"],
            "fellback": cfg.get("fellback", False),
            "is_first": is_first,
            "session_title": session["title"],
        })
        # Per-source status — Block 4 unified-RAG observability for the UI.
        yield _sse({"type": "source_status", "source": "memories",   "count": len(citations)})
        yield _sse({"type": "source_status", "source": "past_chats", "count": len(past_chats)})
        yield _sse({"type": "source_status", "source": "web",        "count": len(web_sources)})
        yield _sse({"type": "source_status", "source": "mcp",        "count": len(mcp_sources)})
        yield _sse({"type": "source_status", "source": "local_files","count": len(local_files)})
        if citations:
            yield _sse({"type": "memories", "items": [c.model_dump() for c in citations]})
        if past_chats:
            yield _sse({"type": "past_chats", "items": [c.model_dump() for c in past_chats]})
        if web_sources:
            yield _sse({"type": "web", "items": [s.model_dump() for s in web_sources]})
        if mcp_sources:
            yield _sse({"type": "mcp", "items": [c.model_dump() for c in mcp_sources]})
        if local_files:
            yield _sse({"type": "local_files", "items": [c.model_dump() for c in local_files]})

        chosen_meta = cfg
        full_answer_parts: list[str] = []
        async for payload, meta in stream_llm(
            messages=messages, user_id=user_id,
            context=context, system_prompt=_system_prompt(),
        ):
            chosen_meta = meta
            chunk = payload.get("text") or ""
            if chunk:
                full_answer_parts.append(chunk)
                yield _sse({"type": "delta", "text": chunk})
            if payload.get("done"):
                break

        full_answer = "".join(full_answer_parts)

        if chosen_meta.get("fellback") and not cfg.get("fellback"):
            yield _sse({
                "type": "meta",
                "provider": chosen_meta["provider"],
                "model": chosen_meta["model"],
                "fellback": True,
                "reason": chosen_meta.get("reason", ""),
            })

        # Persist the assistant reply
        asst_msg = chat_store.append_message(
            session_id, user_id, role="assistant", content=full_answer,
            citations=_collect_citations(citations, past_chats, web_sources, mcp_sources, local_files),
            provider=chosen_meta.get("provider"),
            model=chosen_meta.get("model"),
        )

        _schedule_post_reply(
            user_id=user_id, session_id=session_id,
            user_msg=user_msg, assistant_msg=asst_msg,
            session_title=session["title"], is_first=is_first,
        )

        yield _sse({"type": "done", "message_id": asst_msg["id"]})

    return StreamingResponse(
        _stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


def _collect_citations(
    memories: list[MemoryCitation],
    past_chats: list[PastChatCitation],
    web_sources: list[WebSourceOut],
    mcp_sources: Optional[list[MCPCitation]] = None,
    local_files: Optional[list[LocalFileCitation]] = None,
) -> list[dict]:
    """Flatten the citation lists into a single JSON-serialisable array
    that the chat_messages.citations column stores. Used by the dashboard
    to re-hydrate citation chips when loading old threads.
    """
    out: list[dict] = []
    for m in memories:
        out.append({"type": "memory", "id": m.id, "title": m.title, "score": m.score})
    for c in past_chats:
        out.append({
            "type": "chat", "id": c.message_id,
            "session_id": c.session_id, "title": c.session_title,
            "snippet": c.snippet, "score": c.score,
        })
    for i, w in enumerate(web_sources, start=1):
        out.append({"type": "web", "id": str(i), "title": w.title, "url": w.url, "snippet": w.snippet})
    for c in (mcp_sources or []):
        out.append({
            "type": "mcp", "id": c.id, "provider": c.provider,
            "title": c.title, "snippet": c.snippet, "url": c.url,
        })
    for f in (local_files or []):
        out.append({
            "type": "local_file", "id": f.id, "title": f.title,
            "path": f.path, "snippet": f.snippet, "file_type": f.file_type,
            "score": f.score,
        })
    return out


def _schedule_post_reply(
    *, user_id: str, session_id: str,
    user_msg: dict, assistant_msg: dict,
    session_title: str, is_first: bool,
) -> None:
    """Fire post-reply background tasks: past-chat indexing + autotitle +
    Sprint 2 usefulness feedback for retrieved memories."""
    async def _run():
        # Sprint 2: usefulness feedback. Evaluates which retrieved memories
        # actually appear in the assistant response. Cheap lexical heuristic.
        try:
            from shail.memory.usefulness import evaluate_task
            evaluate_task(
                session_id,
                assistant_msg.get("content", ""),
                success=True,    # chat response generated == success
                retry_count=0,
            )
        except Exception as e:
            logger.debug("usefulness eval failed: %s", e)
        # Phase C: gate continue-capture on per-session capture_enabled flag.
        # If user has paused capture on this session, skip indexing entirely.
        if not session_backfill.is_capture_enabled(session_id):
            logger.info("capture disabled for session %s — skipping continue-capture", session_id)
            return
        try:
            _index_past_chat_turn(
                user_id=user_id, session_id=session_id,
                user_msg_id=user_msg["id"], assistant_msg_id=assistant_msg["id"],
                user_text=user_msg["content"], assistant_text=assistant_msg["content"],
                session_title=session_title,
            )
        except Exception as e:
            from apps.shail import telemetry as _tel
            _tel.incr(_tel.CAPTURE_INDEX_FAIL)
            logger.error(
                "live-capture index FAILED session=%s msg=%s: %s — "
                "turn is in FTS (trigger) but NOT in vector store; "
                "run /sessions/%s/backfill to recover.",
                session_id, assistant_msg.get("id"), e, session_id,
            )
        if is_first:
            try:
                await _autotitle(session_id, user_id, user_msg["content"], assistant_msg["content"])
            except Exception as e:
                logger.warning("autotitle task crashed: %s", e)

    def _on_task_done(task: asyncio.Task) -> None:
        if not task.cancelled() and task.exception() is not None:
            from apps.shail import telemetry as _tel
            _tel.incr(_tel.CAPTURE_INDEX_FAIL)
            logger.error(
                "post-reply task raised unhandled exception session=%s: %s — "
                "run /sessions/%s/backfill to recover missing vectors.",
                session_id, task.exception(), session_id,
            )

    t = asyncio.create_task(_run())
    t.add_done_callback(_on_task_done)
