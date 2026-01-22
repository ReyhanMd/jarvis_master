import pytest

from shail.orchestration.graph import LangGraphExecutor


class DummyAgent:
    name = "dummy"
    tools = []

    def plan(self, text: str):
        return "plan"

    def act(self, text: str):
        return "done", []


def test_langgraph_executor_builds_graph():
    agent = DummyAgent()
    executor = LangGraphExecutor(agent, task_id="test")
    app = executor.build_graph()
    assert app is not None


def test_langgraph_executor_run():
    agent = DummyAgent()
    executor = LangGraphExecutor(agent, task_id="test-run")
    result = executor.run(type("Req", (), {"text": "hello"}))
    assert result.summary == "done"
    assert result.status.value == "completed"
