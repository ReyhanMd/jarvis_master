"""Hallucinated-number detector (Sprint 4 PR1).

Post-generation observability. Parses numeric values out of the LLM's
answer and cross-checks them against the values present in the
`EXACT_FACTS` + `STRUCTURED_FACTS` packet sections. Mismatches increment
`telemetry.GEMMA_HALLUCINATED_NUMBER`.

Strict design constraints:
- NEVER raises. NEVER blocks generation. Pure observability.
- Numbers shorter than 2 digits ("1 thing", "two") are ignored — too
  noisy.
- Years (1900..2099) are ignored — they are routinely paraphrased.
- Citation-format numbers (memory_id fragments, inline ids) are ignored
  via regex stripping.
"""
from __future__ import annotations

import re
from typing import Iterable, List

from apps.shail import telemetry


# Match numbers with optional decimals, commas, K/M/B/T multipliers,
# percent and currency markers. Same shape as exact_index._NUM_RE but
# tighter — we are reading model output, not user query.
_NUM_RE = re.compile(
    r"""
    (?P<currency>[\$€£])?
    (?P<num>\d{1,3}(?:[,\d]{1,12})?(?:\.\d+)?)
    (?P<mult>[KkMmBbTt])?
    (?P<percent>%)?
    """,
    re.VERBOSE,
)
# Strip our own citation tokens before scanning so memory ids don't
# get parsed as numbers.
_CITE_TOKEN_RE = re.compile(
    r"\{\{cite:[^}]+\}\}|memory_id=\S+|score=\S+",
    re.IGNORECASE,
)
# Hex-ish identifiers (likely fact_id / memory_id leaks) — ignore.
_HEX_RE = re.compile(r"\b[0-9a-f]{8,}\b", re.IGNORECASE)


_MULT = {"k": 1e3, "m": 1e6, "b": 1e9, "t": 1e12}


def _to_num(match: "re.Match[str]") -> float | None:
    raw = match.group("num").replace(",", "")
    try:
        n = float(raw)
    except ValueError:
        return None
    mult = match.group("mult")
    if mult:
        n *= _MULT[mult.lower()]
    return n


def extract_numbers(text: str) -> List[float]:
    """Return numeric values mentioned in `text`. Years skipped."""
    if not text:
        return []
    cleaned = _CITE_TOKEN_RE.sub(" ", text)
    cleaned = _HEX_RE.sub(" ", cleaned)
    out: list[float] = []
    for m in _NUM_RE.finditer(cleaned):
        if not m.group("num"):
            continue
        n = _to_num(m)
        if n is None:
            continue
        # Skip years (no multiplier, no percent, integer in 1900..2099).
        is_year = (
            n.is_integer() and 1900 <= n <= 2099
            and not m.group("mult") and not m.group("percent")
            and not m.group("currency")
        )
        if is_year:
            continue
        out.append(n)
    return out


def _approx(a: float, b: float, *, rel: float = 1e-3, abs_tol: float = 1e-6) -> bool:
    """Equality tolerant to small float wobble or "$81B" vs "$81.0B" rounding."""
    if a == b:
        return True
    diff = abs(a - b)
    return diff <= abs_tol or diff <= rel * max(abs(a), abs(b))


def find_hallucinated_numbers(
    answer: str,
    grounded_text: str,
    *,
    extra_grounded: Iterable[str] = (),
) -> List[float]:
    """Return numbers that appear in `answer` but not in any grounded text."""
    if not answer:
        return []
    answer_nums = extract_numbers(answer)
    if not answer_nums:
        return []
    grounded_nums: list[float] = []
    grounded_nums.extend(extract_numbers(grounded_text))
    for blob in extra_grounded:
        grounded_nums.extend(extract_numbers(blob or ""))
    if not grounded_nums:
        return list(answer_nums)
    return [n for n in answer_nums if not any(_approx(n, g) for g in grounded_nums)]


def validate_answer(
    answer: str,
    grounded_text: str,
    *,
    extra_grounded: Iterable[str] = (),
) -> List[float]:
    """Run hallucination check, increment telemetry, return offenders.

    Best-effort observability. Never raises. Returns the offending list
    so callers may log per-request.
    """
    try:
        offenders = find_hallucinated_numbers(
            answer, grounded_text, extra_grounded=extra_grounded,
        )
    except Exception:
        # Strict policy: validator must NEVER break a chat response.
        return []
    if offenders:
        telemetry.incr(
            telemetry.GEMMA_HALLUCINATED_NUMBER, value=float(len(offenders)),
        )
    return offenders
