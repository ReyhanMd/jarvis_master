"""
Hybrid MCP routing — heuristic-first, LLM fallback when ambiguous.

Stage A: keyword scoring per provider returns confidence ∈ [0, 1].
Stage B: if max confidence < 0.5 AND query is long-ish (> 6 words), call
the user's configured LLM with a 300ms cap to pick providers. Result is
unioned with any high-confidence heuristic picks.

The router never returns disconnected providers.
"""

from __future__ import annotations

import asyncio
import logging
import re
from typing import Iterable

from apps.shail.llm import call_llm
from apps.shail.mcp import PROVIDERS

logger = logging.getLogger(__name__)

# ── Stage A: heuristic keyword scorer ──────────────────────────────────────
# Each provider has a list of patterns; matching any contributes to its score.
# Tuned for high precision — false positives waste an MCP fetch budget.

_PATTERNS: dict[str, list[re.Pattern]] = {
    "github": [
        re.compile(r"\b(pr|pull\s+request|issue|commit|branch|repo|repository|merge|code\s+review)\b", re.I),
        re.compile(r"\b(github|main\s+branch|master\s+branch)\b", re.I),
        re.compile(r"\b(bug|fix|patch|cherry[\s-]pick|rebase|squash)\b", re.I),
    ],
    "drive": [
        re.compile(r"\b(doc|document|gdoc|google\s+doc|spreadsheet|sheet|slide|deck|presentation)\b", re.I),
        re.compile(r"\b(drive|google\s+drive|folder|shared\s+with\s+me)\b", re.I),
        re.compile(r"\b(spec|brief|memo|proposal|report|whitepaper)\b", re.I),
    ],
    "notion": [
        re.compile(r"\b(notion|page|wiki|workspace|database|kanban)\b", re.I),
        re.compile(r"\b(roadmap|okr|brainstorm|note|notes)\b", re.I),
    ],
    "gmail": [
        re.compile(r"\b(email|emails|mail|inbox|gmail|message\s+from|reply)\b", re.I),
        re.compile(r"\bfrom\s+[A-Z][a-z]+\b"),  # "from Sarah"
        re.compile(r"\b(thread|conversation\s+with|cc[d]?|forwarded?)\b", re.I),
    ],
}


def heuristic_score(query: str) -> dict[str, float]:
    """Return {provider: confidence in [0,1]} for the heuristic stage."""
    scores: dict[str, float] = {}
    for prov, patterns in _PATTERNS.items():
        hits = sum(1 for p in patterns if p.search(query))
        if hits == 0:
            scores[prov] = 0.0
        elif hits == 1:
            scores[prov] = 0.55  # one keyword: borderline
        else:
            scores[prov] = 0.85  # multiple keywords: confident
    return scores


# ── Stage B: LLM fallback ───────────────────────────────────────────────────

async def llm_route(query: str, candidates: Iterable[str], user_id: str, *, timeout: float = 0.3) -> set[str]:
    """Ask the user's configured LLM which connected providers are relevant.
    Returns a set of provider names. Empty on timeout / parse failure.
    """
    cands = list(candidates)
    if not cands:
        return set()
    labels = ", ".join(f"{n} ({PROVIDERS[n].label})" for n in cands if n in PROVIDERS)
    prompt = (
        f"Available connected sources: {labels}.\n"
        f"User query: {query}\n\n"
        "Reply with comma-separated source names from the list that are likely "
        "to contain the answer. Reply 'none' if no source applies. Output ONLY "
        "the names or 'none' — no other text."
    )
    try:
        answer, _meta = await asyncio.wait_for(
            call_llm(
                messages=[{"role": "user", "content": prompt}],
                user_id=user_id,
                system_prompt="You are a relevance router. Reply tersely.",
            ),
            timeout=timeout,
        )
    except asyncio.TimeoutError:
        return set()
    except Exception as e:
        logger.warning("llm_route failed: %s", e)
        return set()

    text = (answer or "").strip().lower()
    if "none" in text:
        return set()
    picked: set[str] = set()
    for name in cands:
        if name.lower() in text:
            picked.add(name)
    return picked


# ── Combined ────────────────────────────────────────────────────────────────

async def pick_providers(
    query: str, *, connected: set[str], user_id: str,
) -> set[str]:
    """End-to-end routing decision. Only returns providers in `connected`.

    Decision tree:
      - hits with confidence >= 0.8 → always include
      - if highest hit < 0.5 AND query > 6 words → invoke LLM fallback
        (with the connected set as candidates) to disambiguate
      - otherwise: include all hits with confidence >= 0.5 (single-keyword)
    """
    if not connected:
        return set()
    scores = heuristic_score(query)
    high     = {p for p, s in scores.items() if s >= 0.8 and p in connected}
    medium   = {p for p, s in scores.items() if 0.5 <= s < 0.8 and p in connected}
    max_conf = max((scores.get(p, 0.0) for p in connected), default=0.0)

    picked = set(high)
    word_count = len(query.split())

    if max_conf < 0.5 and word_count > 6:
        # Ambiguous — let the LLM pick from the connected set
        picked |= await llm_route(query, connected, user_id)
    else:
        picked |= medium

    return picked
