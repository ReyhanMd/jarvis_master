from typing import List, Tuple
from shail.core.types import Artifact
from shail.agents.base import AbstractAgent


class ResearchAgent(AbstractAgent):
    name = "research"
    capabilities = ["web_search", "summarization"]

    def plan(self, text: str) -> str:
        return "Search web or summarize content as requested."

    def act(self, text: str) -> Tuple[str, List[Artifact]]:
        return "ResearchAgent stub: capability not yet implemented.", []


