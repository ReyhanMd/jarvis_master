"""
Worker nodes for LangGraph orchestration.

These nodes delegate to specific LLM workers (Gemini, ChatGPT) based on state.
"""

from typing import Dict, Any, Callable
from shail.llm.gemini_worker import GeminiWorker
from shail.llm.chatgpt_worker import ChatGPTWorker
from shail.llm.kimi_k2 import KimiK2Client


class WorkerNodes:
    def __init__(self):
        self.gemini = GeminiWorker()
        self.chatgpt = ChatGPTWorker()
        self.kimi = KimiK2Client()

    def _select_worker(self, agent: str) -> Callable[[str], str]:
        if agent == "gemini":
            return self.gemini.run
        if agent == "chatgpt":
            return self.chatgpt.run
        return self.kimi.chat

    def __call__(self, state: Dict[str, Any]) -> Dict[str, Any]:
        text = state.get("task_description") or state.get("request") or ""
        agent = state.get("agent", "gemini")
        worker = self._select_worker(agent)

        result = worker(text)
        tool_history = state.get("tool_history", [])
        tool_history.append(
            {
                "worker": agent,
                "response": result,
            }
        )
        state.update(
            {
                "worker_response": result,
                "tool_history": tool_history,
                "status": "executing",
            }
        )
        return state
