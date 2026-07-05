"""Sprint 1 PR2: structured-fact prompt + parser coercers."""
from __future__ import annotations

import json

from apps.shail.blueprints import _parse_blueprint, _EXTRACTION_INSTRUCTION


# ── Prompt regression ───────────────────────────────────────────────────────


def test_prompt_includes_structured_keys() -> None:
    """Prompt must request facts/metrics/tables; rules must forbid paraphrase."""
    assert '"facts":' in _EXTRACTION_INSTRUCTION
    assert '"metrics":' in _EXTRACTION_INSTRUCTION
    assert '"tables":' in _EXTRACTION_INSTRUCTION
    assert "DO NOT paraphrase numeric values" in _EXTRACTION_INSTRUCTION
    assert "value_num" in _EXTRACTION_INSTRUCTION


# ── Parser back-compat ──────────────────────────────────────────────────────


def test_legacy_blueprint_still_parses() -> None:
    """Old JSON missing facts/metrics/tables must coerce to empty arrays."""
    raw = json.dumps({
        "summary": "Old session",
        "decisions": [{"statement": "ship now", "reasoning": "deadline", "confidence": "high"}],
        "questions_answered": [],
        "open_questions": [],
        "next_actions": [],
        "key_entities": ["X"],
        "reasoning_chains": [],
        "failed_attempts": [],
        "extensions": {},
    })
    parsed = _parse_blueprint(raw)
    assert parsed is not None
    assert parsed["facts"] == []
    assert parsed["metrics"] == []
    assert parsed["tables"] == []
    assert parsed["decisions"][0]["statement"] == "ship now"


# ── Parser determinism ──────────────────────────────────────────────────────


def test_parser_deterministic_with_facts() -> None:
    raw = json.dumps({
        "summary": "Tesla revenue",
        "facts": [
            {"entity": "Tesla", "attribute": "revenue", "value": "$81B",
             "unit": "USD", "period": "2023", "source_span": "$81.0B in 2023",
             "confidence": 0.95},
        ],
        "metrics": [],
        "tables": [],
    })
    a = _parse_blueprint(raw)
    b = _parse_blueprint(raw)
    assert a == b
    f = a["facts"][0]
    assert f["entity"] == "Tesla"
    assert f["value"] == "$81B"
    assert f["confidence"] == 0.95


# ── Numeric value preservation ──────────────────────────────────────────────


def test_metric_value_num_preserved() -> None:
    raw = json.dumps({
        "summary": "x", "decisions": [], "questions_answered": [],
        "open_questions": [], "next_actions": [], "key_entities": [],
        "reasoning_chains": [], "failed_attempts": [],
        "metrics": [
            {"entity": "Tesla", "metric": "growth", "value": "62%",
             "value_num": 62, "unit": "%", "period": "2023"},
            {"entity": "Tesla", "attribute": "revenue", "value": "$81B",
             "value_num": 81000000000, "unit": "USD", "period": "2023"},
        ],
        "extensions": {},
    })
    parsed = _parse_blueprint(raw)
    metrics = parsed["metrics"]
    assert len(metrics) == 2
    assert metrics[0]["attribute"] == "growth"
    assert metrics[0]["value_num"] == 62.0
    assert metrics[1]["value_num"] == 81000000000.0


def test_invalid_value_num_coerced_to_none() -> None:
    raw = json.dumps({
        "summary": "x",
        "metrics": [{"entity": "X", "metric": "y", "value": "abc", "value_num": "not-a-number"}],
    })
    parsed = _parse_blueprint(raw)
    assert parsed["metrics"][0]["value_num"] is None


# ── Tolerance ───────────────────────────────────────────────────────────────


def test_facts_with_missing_keys_dropped_when_empty() -> None:
    raw = json.dumps({
        "summary": "x",
        "facts": [
            {"entity": "Tesla", "value": "$81B"},   # kept (has entity + value)
            {},                                      # dropped (all empty)
            {"unit": "USD"},                         # dropped (only unit)
        ],
    })
    parsed = _parse_blueprint(raw)
    assert len(parsed["facts"]) == 1
    assert parsed["facts"][0]["entity"] == "Tesla"


def test_confidence_clamped() -> None:
    raw = json.dumps({
        "summary": "x",
        "facts": [
            {"entity": "X", "value": "y", "confidence": 1.5},
            {"entity": "X", "value": "z", "confidence": -0.2},
        ],
    })
    parsed = _parse_blueprint(raw)
    assert parsed["facts"][0]["confidence"] == 1.0
    assert parsed["facts"][1]["confidence"] == 0.0


def test_table_rows_preserved() -> None:
    raw = json.dumps({
        "summary": "x",
        "tables": [
            {"title": "Tesla revenue",
             "rows": [
                 {"Year": "2022", "Revenue": "$50B"},
                 {"Year": "2023", "Revenue": "$81B"},
             ],
             "source_span": "10-K"},
        ],
    })
    parsed = _parse_blueprint(raw)
    t = parsed["tables"][0]
    assert t["title"] == "Tesla revenue"
    assert len(t["rows"]) == 2
    assert t["rows"][0]["Year"] == "2022"


def test_malformed_json_still_returns_none() -> None:
    """Existing safety net: bad JSON → None, caller falls back to prior bp."""
    assert _parse_blueprint("not json at all") is None
    assert _parse_blueprint("") is None
