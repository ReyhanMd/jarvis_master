"""
Checkpointing utilities for LangGraph in Shail.

Provides:
- MemorySaver as primary, with optional SQLite backup for persistence.
- Helper to build a checkpointer configured from settings.
"""

from typing import Optional, Any
import os

from apps.shail.settings import get_settings
from shail.orchestration.langgraph_integration import (
    get_memory_saver,
    get_sqlite_saver,
)


class CheckpointerBuilder:
    """
    Builds LangGraph checkpointers:
    - MemorySaver (default)
    - Optional SQLite saver for persistence
    """

    def __init__(self, sqlite_path: Optional[str] = None):
        settings = get_settings()
        self.sqlite_path = sqlite_path or getattr(settings, "sqlite_path", None)
        self.MemorySaver = get_memory_saver()
        try:
            self.SqliteSaver = get_sqlite_saver()
        except ImportError:
            self.SqliteSaver = None

    def _ensure_sqlite_dir(self) -> None:
        if self.sqlite_path:
            os.makedirs(os.path.dirname(self.sqlite_path), exist_ok=True)

    def build(self, persistent: bool = True) -> Any:
        """
        Create a checkpointer. If persistent=True and SQLite saver is available,
        use SQLite; otherwise fall back to MemorySaver.
        """
        if persistent and self.SqliteSaver and self.sqlite_path:
            self._ensure_sqlite_dir()
            return self.SqliteSaver.from_conn_string(self.sqlite_path)
        # Memory-only fallback
        return self.MemorySaver()


def create_checkpointer(persistent: bool = True) -> Any:
    """
    Convenience helper to build a checkpointer using settings.
    """
    builder = CheckpointerBuilder()
    return builder.build(persistent=persistent)
