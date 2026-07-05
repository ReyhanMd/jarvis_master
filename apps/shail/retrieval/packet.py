"""Deterministic context packet builder (Sprint 4 PR1).

Replaces the prose memory block in `_build_context` with four named
sections so Gemma can tell exact facts from supporting prose:

    === EXACT_FACTS ===          (capped 800 chars)
    === STRUCTURED_FACTS ===     (capped 1000 chars; reserved for blueprint
                                  table rows / metrics — empty in Sprint 4)
    === SUPPORTING_CONTEXT ===   (capped 1500 chars)
    === CITATIONS ===            (capped 400 chars)

Total cap ≈ 3700 chars. Priority truncation drops SUPPORTING_CONTEXT
first, then STRUCTURED_FACTS — EXACT_FACTS is preserved at all costs.

Returns the rendered packet plus the legacy `MemoryCitation` list so
the existing chat response shape is unchanged.

Pure function. No I/O. No side effects beyond reading the input list.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import List, Optional, Sequence, Tuple


# Section caps (chars). Eval-tunable. Order = priority for truncation.
EXACT_FACTS_CAP        = 800
STRUCTURED_FACTS_CAP   = 1000
SUPPORTING_CONTEXT_CAP = 1500
CITATIONS_CAP          = 400

EXACT_SURFACES = {"fts", "numeric", "exact", "fused"}

# Hit shape from hybrid_search / rag_search: (content, score, metadata).
Hit = Tuple[str, float, dict]


@dataclass(frozen=True)
class PacketResult:
    text: str
    sections: dict           # name -> rendered section body (uncapped, for tests)
    fact_ids: list           # memory_ids that contributed to EXACT_FACTS
    truncated_sections: list # names of sections that hit the cap


def _section_header(name: str) -> str:
    return f"=== {name} ==="


def _trim(text: str, cap: int) -> tuple[str, bool]:
    if len(text) <= cap:
        return text, False
    # Cut at last newline before cap to keep lines whole.
    cut = text.rfind("\n", 0, cap)
    if cut <= 0:
        cut = cap
    return text[:cut].rstrip() + "\n…[truncated]", True


def _render_exact_line(content: str, score: float, meta: dict) -> str:
    """Render one fact-shaped hit. Content already pre-formatted upstream
    (`fusion._format_exact_hit`) so we just append the score + memory_id."""
    mid = meta.get("memory_id") or meta.get("customId") or meta.get("id") or ""
    score_str = f" [score={score:.2f}]" if score is not None else ""
    return f"- {content.strip()}{score_str}"


def _render_supporting_line(content: str, score: float, meta: dict) -> str:
    mid = meta.get("memory_id") or meta.get("customId") or meta.get("id") or ""
    title = meta.get("title", "(untitled)")
    snippet = (content or "").strip().replace("\n", " ")[:300]
    head = f"[memory_id={mid}] {title}" if mid else title
    return f"- {head}\n  {snippet}"


def _render_citation_line(meta: dict, score: float) -> str:
    mid = meta.get("memory_id") or meta.get("customId") or meta.get("id") or ""
    title = meta.get("title", "(untitled)")
    return f"  - {mid}: {title} (score={score:.2f})" if mid else f"  - {title}"


def split_hits(hits: Sequence[Hit]) -> tuple[list, list]:
    """Partition hits into (exact, supporting) by `metadata.surface`.

    Hits without `surface` (legacy semantic) → supporting.
    """
    exact: list = []
    supporting: list = []
    for h in hits:
        _, _, meta = h
        s = (meta or {}).get("surface", "semantic")
        if s in EXACT_SURFACES:
            exact.append(h)
        else:
            supporting.append(h)
    return exact, supporting


def build(
    rag_hits: Sequence[Hit],
    *,
    structured_rows: Optional[Sequence[dict]] = None,
) -> PacketResult:
    """Render the packet from hybrid_search results.

    `structured_rows` is reserved for direct-from-blueprint table/metrics
    injection in a future sprint. Empty by default → STRUCTURED_FACTS
    placeholder shows `(none)`.
    """
    exact_hits, supporting_hits = split_hits(rag_hits or [])

    # ── EXACT_FACTS ──
    if exact_hits:
        exact_body = "\n".join(_render_exact_line(c, s, m) for c, s, m in exact_hits)
    else:
        exact_body = "(none)"

    # ── STRUCTURED_FACTS ──
    if structured_rows:
        struct_lines = []
        for row in structured_rows:
            entity = row.get("entity") or ""
            attribute = row.get("attribute") or ""
            value = row.get("value") or ""
            period = row.get("period") or ""
            mid = row.get("memory_id") or ""
            head = f"{entity} {attribute}".strip() or "(row)"
            tail = f" ({period})" if period else ""
            cite = f" [memory_id={mid}]" if mid else ""
            struct_lines.append(f"- {head}{tail}: {value}{cite}")
        struct_body = "\n".join(struct_lines)
    else:
        struct_body = "(none)"

    # ── SUPPORTING_CONTEXT ──
    if supporting_hits:
        support_body = "\n".join(_render_supporting_line(c, s, m) for c, s, m in supporting_hits)
    else:
        support_body = "(none)"

    # ── CITATIONS ──
    cite_lines = []
    fact_ids: list[str] = []
    for c, s, m in (list(exact_hits) + list(supporting_hits)):
        line = _render_citation_line(m or {}, s)
        cite_lines.append(line)
        mid = (m or {}).get("memory_id") or (m or {}).get("customId") or (m or {}).get("id")
        if mid:
            fact_ids.append(str(mid))
    cite_body = "\n".join(cite_lines) if cite_lines else "(none)"

    # Apply caps.
    truncated: list[str] = []
    exact_body_t, t1 = _trim(exact_body, EXACT_FACTS_CAP)
    struct_body_t, t2 = _trim(struct_body, STRUCTURED_FACTS_CAP)
    support_body_t, t3 = _trim(support_body, SUPPORTING_CONTEXT_CAP)
    cite_body_t, t4 = _trim(cite_body, CITATIONS_CAP)
    if t1: truncated.append("EXACT_FACTS")
    if t2: truncated.append("STRUCTURED_FACTS")
    if t3: truncated.append("SUPPORTING_CONTEXT")
    if t4: truncated.append("CITATIONS")

    text = "\n".join([
        _section_header("EXACT_FACTS"),       exact_body_t,
        _section_header("STRUCTURED_FACTS"),  struct_body_t,
        _section_header("SUPPORTING_CONTEXT"), support_body_t,
        _section_header("CITATIONS"),         cite_body_t,
    ])

    return PacketResult(
        text=text,
        sections={
            "EXACT_FACTS":        exact_body,
            "STRUCTURED_FACTS":   struct_body,
            "SUPPORTING_CONTEXT": support_body,
            "CITATIONS":          cite_body,
        },
        fact_ids=fact_ids,
        truncated_sections=truncated,
    )
