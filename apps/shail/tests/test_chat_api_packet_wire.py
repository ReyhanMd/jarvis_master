"""Sprint 4 PR3: chat_api honors SHAIL_CONTEXT_PACKET + GROUNDING policy."""
from __future__ import annotations

import pytest

import apps.shail.chat_api as chat_api
from apps.shail import settings


def test_system_prompt_legacy_when_packet_off() -> None:
    s = settings.get_settings()
    # Defaults must be OFF.
    assert s.shail_context_packet is False
    assert s.shail_hybrid_retrieval is False
    out = chat_api._system_prompt()
    assert out == chat_api.CHAT_SYSTEM_PROMPT
    assert "STRUCTURED GROUNDING POLICY" not in out


def test_system_prompt_appends_policy_when_both_flags_on(monkeypatch) -> None:
    s = settings.get_settings()
    monkeypatch.setattr(s, "shail_hybrid_retrieval", True)
    monkeypatch.setattr(s, "shail_context_packet", True)
    out = chat_api._system_prompt()
    assert "STRUCTURED GROUNDING POLICY" in out
    assert "EXACT_FACTS" in out
    assert "not found in memory" in out
    # Legacy citation rules still present.
    assert "{{cite:memory:" in out


def test_system_prompt_skips_policy_when_only_packet_on(monkeypatch) -> None:
    """Packet flag without hybrid → no policy (avoids forcing 'not found' replies
    when EXACT_FACTS section will always be empty)."""
    s = settings.get_settings()
    monkeypatch.setattr(s, "shail_context_packet", True)
    monkeypatch.setattr(s, "shail_hybrid_retrieval", False)
    out = chat_api._system_prompt()
    assert "STRUCTURED GROUNDING POLICY" not in out


def test_grounding_policy_references_packet_section_names() -> None:
    """If packet section headers ever change, this test catches the policy drift."""
    text = chat_api.GROUNDING_POLICY_PROMPT
    for section in ("EXACT_FACTS", "STRUCTURED_FACTS", "SUPPORTING_CONTEXT", "CITATIONS"):
        assert section in text


def test_packet_module_importable() -> None:
    from apps.shail.retrieval import packet, validator
    assert callable(packet.build)
    assert callable(validator.validate_answer)
