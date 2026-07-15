"""Compatibility helpers for optional LangChain agent APIs.

LangChain 1.x removed the legacy ReAct helpers from ``langchain.agents``. The
backend should still start even when that optional agent API is unavailable.
"""
from __future__ import annotations

from typing import Any


class FallbackAgentExecutor:
    """Minimal executor used when legacy LangChain ReAct APIs are absent."""

    def __init__(self, llm: Any, *, agent_name: str):
        self.llm = llm
        self.agent_name = agent_name

    def invoke(self, payload: dict[str, Any]) -> dict[str, str]:
        text = str(payload.get("input") or "")
        try:
            response = self.llm.invoke(text)
            content = getattr(response, "content", response)
            return {"output": str(content)}
        except Exception as exc:
            return {
                "output": (
                    f"{self.agent_name} is available, but its legacy LangChain "
                    f"tool executor could not run: {exc}"
                )
            }


def make_react_executor(
    *,
    llm: Any,
    tools: list[Any],
    prompt: Any,
    agent_name: str,
    max_iterations: int,
) -> tuple[Any, Any]:
    try:
        from langchain.agents import AgentExecutor, create_react_agent  # type: ignore

        agent = create_react_agent(llm, tools, prompt)
        executor = AgentExecutor(
            agent=agent,
            tools=tools,
            verbose=True,
            max_iterations=max_iterations,
            handle_parsing_errors=True,
        )
        return agent, executor
    except Exception:
        executor = FallbackAgentExecutor(llm, agent_name=agent_name)
        return None, executor
