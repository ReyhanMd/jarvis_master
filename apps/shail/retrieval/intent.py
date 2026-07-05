"""Query-intent classifier for hybrid retrieval (Sprint 3).

Pure functions. No I/O. No SQLite. No LLM. Regex-first; tiny heuristics.

Output: an `IntentPlan` describing how the orchestrator should query each
surface and how fusion should weight the result. Intent is advisory:
the orchestrator ALWAYS runs both surfaces — intent only steers weights
and selects whether to construct a numeric filter.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from enum import Enum
from typing import Optional

from apps.shail.exact_index import NumericFilter, parse_numeric_filter


class QueryIntent(str, Enum):
    EXACT_VALUE = "exact_value"
    STRUCTURED_FILTER = "structured_filter"
    SEMANTIC = "semantic"


@dataclass(frozen=True)
class IntentPlan:
    intent: QueryIntent
    fts_query: Optional[str]
    numeric_filter: Optional[NumericFilter]
    weights: dict          # {"exact": float, "semantic": float, "recency": float}
    as_of: Optional[str] = None    # historical traversal token, e.g. "2023" or "Q3 2023"
    historical: bool = False        # True when caller wants `is_latest=0` rows


# Per-intent weight presets. Sum to 1.0. Tunable via eval suite.
_WEIGHTS_BY_INTENT: dict[QueryIntent, dict] = {
    QueryIntent.EXACT_VALUE:       {"exact": 0.70, "semantic": 0.20, "recency": 0.10},
    QueryIntent.STRUCTURED_FILTER: {"exact": 0.55, "semantic": 0.30, "recency": 0.15},
    QueryIntent.SEMANTIC:          {"exact": 0.20, "semantic": 0.65, "recency": 0.15},
}


# Cheap signals that the user wants a value, not a discussion.
_NUMERIC_SIGNAL_RE = re.compile(
    r"(?:\$|€|£|%|\b\d+(?:\.\d+)?\b|\b(?:Q[1-4]|FY|H[12])\b)",
    re.IGNORECASE,
)
# Imperative-style "tell me X for Y" patterns — lean exact even without numerics.
# Bare "what" is too generic ("what did we discuss?") so we require a value-shaped
# pairing.
_LOOKUP_VERB_RE = re.compile(
    r"\b(how much|how many|value of|amount of|metric|kpi|exact value)\b",
    re.IGNORECASE,
)

# Sprint 5 PR3: "as of" / historical lookup patterns. The captured token is
# fed to readers so they can traverse the `parent_fact_id` chain back to
# the version that was current at that time.
_AS_OF_RE = re.compile(
    r"\b(?:as\s+of|previously|prior(?:\s+to)?|at\s+the\s+time\s+of|"
    r"before|original(?:ly)?|earlier|last\s+(?:quarter|month|year))\b",
    re.IGNORECASE,
)


def classify(query: str) -> IntentPlan:
    """Determine intent + per-surface weights for a free-text query."""
    q = (query or "").strip()
    if not q:
        return IntentPlan(
            intent=QueryIntent.SEMANTIC,
            fts_query=None,
            numeric_filter=None,
            weights=_WEIGHTS_BY_INTENT[QueryIntent.SEMANTIC],
        )

    nf = parse_numeric_filter(q)
    has_op_value = (
        nf is not None and nf.op is not None and nf.value_num is not None
    )
    has_period_or_unit = nf is not None and (nf.period or nf.unit)

    if has_op_value:
        intent = QueryIntent.EXACT_VALUE
    elif has_period_or_unit:
        intent = QueryIntent.STRUCTURED_FILTER
    elif _NUMERIC_SIGNAL_RE.search(q) or _LOOKUP_VERB_RE.search(q):
        # Looks value-shaped even though parser found nothing concrete.
        intent = QueryIntent.EXACT_VALUE
    else:
        intent = QueryIntent.SEMANTIC

    historical = bool(_AS_OF_RE.search(q))
    as_of = (nf.period if (nf is not None and nf.period and historical) else None)

    return IntentPlan(
        intent=intent,
        fts_query=q,
        numeric_filter=nf,
        weights=_WEIGHTS_BY_INTENT[intent],
        as_of=as_of,
        historical=historical,
    )
