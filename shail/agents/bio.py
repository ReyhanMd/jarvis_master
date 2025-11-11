from typing import List, Tuple
from shail.core.types import Artifact
from shail.agents.base import AbstractAgent


class BioAgent(AbstractAgent):
    name = "bio"
    capabilities = ["protein_design", "simulation_stub"]

    def plan(self, text: str) -> str:
        return "Analyze bio request and outline steps."

    def act(self, text: str) -> Tuple[str, List[Artifact]]:
        return "BioAgent stub: capability not yet implemented.", []


