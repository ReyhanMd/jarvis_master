"""Sprint 4 PR1: hallucinated-number validator."""
from __future__ import annotations

from apps.shail import telemetry
from apps.shail.retrieval import validator


# ── extract_numbers ────────────────────────────────────────────────────────


def test_extract_simple_numbers() -> None:
    nums = validator.extract_numbers("revenue was $81B and growth 62%")
    assert 81e9 in nums
    assert 62.0 in nums


def test_extract_skips_years() -> None:
    nums = validator.extract_numbers("In 2023 the count was 1,200")
    # 2023 should be skipped (year), 1200 retained.
    assert 2023.0 not in nums
    assert 1200.0 in nums


def test_extract_handles_decimals_percent() -> None:
    nums = validator.extract_numbers("churn = 4.2%")
    assert 4.2 in nums


def test_extract_skips_hex_ids() -> None:
    nums = validator.extract_numbers("memory_id=abc123def456 reported 50")
    assert any(abs(n - 50.0) < 1e-9 for n in nums)
    # Hex token must not show up as a separate number.
    assert all(n != 123 and n != 456 for n in nums)


def test_extract_strips_citation_tokens() -> None:
    text = "{{cite:memory:abc-123}} value is 81B"
    nums = validator.extract_numbers(text)
    assert 81e9 in nums


def test_empty_text_returns_empty() -> None:
    assert validator.extract_numbers("") == []
    assert validator.extract_numbers(None) == []  # type: ignore[arg-type]


# ── find_hallucinated_numbers ──────────────────────────────────────────────


def test_no_hallucination_when_numbers_match() -> None:
    grounded = "EXACT_FACTS: Tesla revenue (2023): $81B"
    answer = "Tesla earned $81B in 2023."
    out = validator.find_hallucinated_numbers(answer, grounded)
    assert out == []


def test_hallucinated_when_value_absent() -> None:
    grounded = "EXACT_FACTS: Tesla revenue (2023): $81B"
    answer = "Tesla earned $99B in 2023."
    out = validator.find_hallucinated_numbers(answer, grounded)
    assert 99e9 in out


def test_no_grounded_numbers_means_all_answers_hallucinated() -> None:
    out = validator.find_hallucinated_numbers("Revenue was $50B.", "(none)")
    assert 50e9 in out


def test_approx_tolerance() -> None:
    """81B vs 81.0B (same value) must not trigger."""
    grounded = "$81B"
    answer = "answer says 81000000000"
    out = validator.find_hallucinated_numbers(answer, grounded)
    assert out == []


def test_extra_grounded_sources_considered() -> None:
    grounded = "(none)"
    answer = "Revenue was $50B."
    out = validator.find_hallucinated_numbers(
        answer, grounded, extra_grounded=["earlier note: $50B confirmed"]
    )
    assert out == []


# ── validate_answer (with telemetry) ───────────────────────────────────────


def test_validate_increments_counter_on_hallucination() -> None:
    telemetry.reset()
    validator.validate_answer("Revenue was $99B.",
                              "EXACT_FACTS: Tesla revenue (2023): $81B")
    counters = telemetry.snapshot()["counters"]
    assert counters.get(telemetry.GEMMA_HALLUCINATED_NUMBER, 0) == 1.0


def test_validate_no_increment_when_clean() -> None:
    telemetry.reset()
    validator.validate_answer("Revenue was $81B.",
                              "EXACT_FACTS: Tesla revenue (2023): $81B")
    counters = telemetry.snapshot()["counters"]
    assert counters.get(telemetry.GEMMA_HALLUCINATED_NUMBER, 0) == 0


def test_validator_never_raises(monkeypatch) -> None:
    """Validator must NEVER block a chat response — exceptions swallowed."""
    def boom(*a, **kw):
        raise RuntimeError("synthetic")
    monkeypatch.setattr(validator, "find_hallucinated_numbers", boom)
    out = validator.validate_answer("anything", "anything")
    assert out == []
