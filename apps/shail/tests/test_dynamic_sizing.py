"""Tests for context-window-aware blueprint sizing."""
from __future__ import annotations

import os

import pytest

from apps.shail import dynamic_sizing as DS
from apps.shail.settings import Settings


@pytest.fixture(autouse=True)
def reset_settings(monkeypatch):
    """Force a fresh Settings object so env overrides take effect per test."""
    import apps.shail.settings as S
    monkeypatch.setattr(S, "_settings", None)
    yield
    monkeypatch.setattr(S, "_settings", None)


def test_default_budget_is_much_larger_than_legacy_16k():
    """Default config should give content budget well above the legacy 16K cap.

    The old hard-coded value was 16_000 chars. With a 32K context window and
    default chars-per-token of 3.5, the budget should be in tens of thousands.
    """
    b = DS.compute_budget()
    assert b.content_budget_chars > 16_000, (
        f"budget {b.content_budget_chars} should exceed legacy cap"
    )


def test_budget_shrinks_when_prior_blueprint_present(monkeypatch):
    fresh = DS.compute_budget(prior_blueprint_chars=0).content_budget_chars
    refine = DS.compute_budget(prior_blueprint_chars=20_000).content_budget_chars
    assert refine == fresh - 20_000


def test_budget_floors_at_min_content():
    """If a giant prior blueprint would zero out the budget, we still floor it."""
    import apps.shail.settings as S
    s = S.get_settings()
    floor = s.blueprint_min_content_chars
    b = DS.compute_budget(prior_blueprint_chars=10**9)
    assert b.content_budget_chars >= floor


def test_window_size_scales_with_context(monkeypatch):
    # Override the live settings object so the test does not depend on
    # pydantic re-reading os.environ (Field(default=os.getenv(...)) freezes
    # at class definition time).
    import apps.shail.settings as S
    s = S.get_settings()
    monkeypatch.setattr(s, "blueprint_context_tokens", 8192)
    small_b = DS.compute_budget()
    monkeypatch.setattr(s, "blueprint_context_tokens", 131072)
    big_b = DS.compute_budget()
    assert big_b.content_budget_chars > small_b.content_budget_chars


def test_window_count_covers_full_transcript():
    """Sliding-window count × window step >= transcript size."""
    transcript = 500_000
    n = DS.expected_window_count(transcript)
    ws, ov = DS.compute_window_size(transcript_chars=transcript)
    step = ws - ov
    covered = ov + n * step
    assert covered >= transcript


def test_zero_transcript_gives_zero_windows():
    assert DS.expected_window_count(0) == 0
