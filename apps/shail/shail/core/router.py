from typing import Any
from ..agents.code import CodeAgent
from .types import TaskRequest, TaskResult, Artifact
from ...settings import Settings


class ShailRouter:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        # In future: registry of agents
        self.code_agent = CodeAgent(settings=settings)

    async def route(self, req: TaskRequest) -> TaskResult:
        target = self._decide_agent(req)
        if target == "code":
            summary, artifacts = await self.code_agent.handle(req)
            return TaskResult(status="ok", summary=summary, artifacts=artifacts)
        # Stubs for other agents
        return TaskResult(status="unimplemented", summary="Agent not yet implemented", artifacts=[])

    def _decide_agent(self, req: TaskRequest) -> str:
        if req.mode and req.mode != "default":
            return req.mode
        text = (req.text or "").lower()
        if any(k in text for k in ["code", "project", "build", "app", "website"]):
            return "code"
        return "code"


