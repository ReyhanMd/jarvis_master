from abc import ABC, abstractmethod
from typing import Tuple, List
from ..core.types import TaskRequest, Artifact
from ...settings import Settings


class AbstractAgent(ABC):
    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    @abstractmethod
    async def handle(self, req: TaskRequest) -> Tuple[str, List[Artifact]]:
        ...


