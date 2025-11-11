from typing import List, Tuple
from shail.core.types import Artifact
from shail.agents.base import AbstractAgent


class RoboAgent(AbstractAgent):
    name = "robo"
    capabilities = ["cad_stub", "simulation_stub"]

    def plan(self, text: str) -> str:
        return "Analyze robotics/CAD request and outline steps."

    def act(self, text: str) -> Tuple[str, List[Artifact]]:
        return "RoboAgent stub: capability not yet implemented.", []


