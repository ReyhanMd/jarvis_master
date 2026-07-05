"""Sprint 0 PR1 smoke: every retrieval-evolution flag exists and defaults OFF."""
from __future__ import annotations

import pytest

from apps.shail.settings import Settings


_FLAGS = (
    "shail_exact_index_write",
    "shail_hybrid_retrieval",
    "shail_context_packet",
    "shail_capture_chunking",
    "shail_blueprint_versioning",
    "shail_rerank",
    "shail_retrieval_debug",
)


@pytest.mark.parametrize("flag", _FLAGS)
def test_flag_defined(flag: str) -> None:
    s = Settings()
    assert hasattr(s, flag), f"Missing flag {flag}"


@pytest.mark.parametrize("flag", _FLAGS)
def test_flag_default_off(flag: str) -> None:
    s = Settings()
    assert getattr(s, flag) is False, f"Flag {flag} default must be False"
