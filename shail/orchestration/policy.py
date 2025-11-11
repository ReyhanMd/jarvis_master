from typing import Tuple
from shail.core.types import TaskRequest, RoutingDecision


KEYWORD_MAP = {
    "code": ["code", "build", "website", "app", "api", "next.js", "python", "flask", "react"],
    "bio": ["protein", "crispr", "gene", "drug", "fold", "sequence"],
    "robo": ["cad", "robot", "solidworks", "freecad", "ros", "kinematics"],
    "plasma": ["plasma", "fusion", "openfoam", "simulink", "matlab"],
    "research": ["paper", "literature", "research", "summarize", "data"],
}


def route_request(req: TaskRequest) -> RoutingDecision:
    if req.mode and req.mode != "auto":
        mode = req.mode
        return RoutingDecision(agent=mode, confidence=0.9, rationale=f"User requested mode={mode}")

    text = (req.text or "").lower()
    for agent, kws in KEYWORD_MAP.items():
        if any(kw in text for kw in kws):
            return RoutingDecision(agent=agent, confidence=0.7, rationale=f"Matched keywords for {agent}")

    return RoutingDecision(agent="code", confidence=0.55, rationale="Defaulted to code agent")


