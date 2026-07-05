"""Sprint 3 PR1: query intent classifier."""
from __future__ import annotations

import pytest

from apps.shail.retrieval.intent import (
    IntentPlan,
    QueryIntent,
    classify,
)


def test_empty_query_is_semantic() -> None:
    plan = classify("")
    assert plan.intent == QueryIntent.SEMANTIC
    assert plan.fts_query is None
    assert plan.numeric_filter is None


def test_pure_text_is_semantic() -> None:
    plan = classify("summarize what we discussed about onboarding")
    assert plan.intent == QueryIntent.SEMANTIC


def test_explicit_numeric_op_is_exact_value() -> None:
    plan = classify("revenue > $50B")
    assert plan.intent == QueryIntent.EXACT_VALUE
    assert plan.numeric_filter is not None
    assert plan.numeric_filter.op == ">"
    assert plan.numeric_filter.value_num == 50e9


def test_period_only_is_structured_filter() -> None:
    plan = classify("what was the churn in 2023")
    assert plan.intent == QueryIntent.STRUCTURED_FILTER
    assert plan.numeric_filter is not None
    assert plan.numeric_filter.period == "2023"


def test_question_with_dollars_is_exact() -> None:
    plan = classify("how much was revenue $X amount")
    assert plan.intent == QueryIntent.EXACT_VALUE


def test_lookup_verb_routes_to_exact() -> None:
    plan = classify("what is the value of churn")
    assert plan.intent == QueryIntent.EXACT_VALUE


def test_weights_sum_to_one_each_intent() -> None:
    for intent in QueryIntent:
        plan = classify_with_intent(intent)
        total = sum(plan.weights.values())
        assert abs(total - 1.0) < 1e-9, f"weights for {intent} sum to {total}"


def test_exact_intent_weights_favor_exact() -> None:
    plan = classify("revenue > $50B")
    w = plan.weights
    assert w["exact"] > w["semantic"]
    assert w["exact"] > w["recency"]


def test_semantic_intent_weights_favor_semantic() -> None:
    plan = classify("tell me about our onboarding philosophy")
    w = plan.weights
    assert w["semantic"] > w["exact"]


def test_fts_query_preserved() -> None:
    plan = classify("Tesla revenue 2023")
    assert plan.fts_query == "Tesla revenue 2023"


# ── helper for parameterized weight check ──


def classify_with_intent(intent: QueryIntent) -> IntentPlan:
    queries = {
        QueryIntent.EXACT_VALUE: "revenue > $50B",
        QueryIntent.STRUCTURED_FILTER: "churn in 2023",
        QueryIntent.SEMANTIC: "what is product strategy",
    }
    return classify(queries[intent])
