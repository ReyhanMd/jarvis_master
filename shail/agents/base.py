from abc import ABC, abstractmethod
from typing import List, Tuple
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


