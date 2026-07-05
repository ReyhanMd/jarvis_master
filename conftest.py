"""Repo-root conftest. Pins sys.path so the top-level `shail/` package wins
over the legacy `apps/shail/shail/` subpackage during test imports.
Without this, pytest's rootdir-import mode could resolve `shail.memory`
against the inner package and fail.
"""
from __future__ import annotations

import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent
_root_str = str(_ROOT)
if _root_str in sys.path:
    sys.path.remove(_root_str)
sys.path.insert(0, _root_str)

import shail.memory.rag
