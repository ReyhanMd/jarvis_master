from abc import ABC, abstractmethod
from typing import Any, List, Optional, Tuple
from shail.core.types import Artifact


class AbstractAgent(ABC):
    name: str = "abstract"
    capabilities: List[str] = []

    @abstractmethod
    def plan(self, text: str) -> str:
        ...

    @abstractmethod
    def act(self, text: str) -> Tuple[str, List[Artifact]]:
        ...

    def run(self, text: str) -> Tuple[str, List[Artifact]]:
        _ = self.plan(text)
        return self.act(text)

    # ── Phase 5: Shared context helpers ──────────────────────────────── #

    async def get_shared_context(
        self,
        context_id: str,
        key: str,
        namespace: Optional[str] = None,
    ) -> Optional[Any]:
        """Read a value from the shared cross-agent context store."""
        try:
            from shail.memory.shared_context import get_shared_context as _store
            ns = namespace or self.name
            return await _store().read(context_id, ns, key)
        except Exception:
            return None

    async def set_shared_context(
        self,
        context_id: str,
        key: str,
        value: Any,
        namespace: Optional[str] = None,
    ) -> None:
        """Write a value to the shared cross-agent context store."""
        try:
            from shail.memory.shared_context import get_shared_context as _store
            ns = namespace or self.name
            await _store().write(context_id, ns, key, value)
        except Exception:
            pass


