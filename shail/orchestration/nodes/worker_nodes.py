"""
Worker nodes for LangGraph orchestration.

These nodes delegate to specific LLM workers (Gemini, ChatGPT) based on state.

Sprint 2: workers now read shared context from prior agents in the same
task (if any) and write their own response back for downstream nodes.
"""

import asyncio
import logging
from typing import Dict, Any, Callable, Optional
from shail.llm.gemini_worker import GeminiWorker
from shail.llm.chatgpt_worker import ChatGPTWorker
from shail.llm.kimi_k2 import KimiK2Client

logger = logging.getLogger(__name__)

# Soft cap on bytes any agent can write to shared context per key — prevents
# uncontrolled context flooding.
SHARED_CTX_VALUE_MAX_BYTES = 16 * 1024


def _truncate_for_context(text: str, max_bytes: int = SHARED_CTX_VALUE_MAX_BYTES) -> str:
    if not text:
        return ""
    if len(text.encode("utf-8")) <= max_bytes:
        return text
    return text[:max_bytes] + "\n…[truncated]"


def _emit(name: str, **labels) -> None:
    try:
        from apps.shail import telemetry
        telemetry.incr(name, **labels)
    except Exception:
        pass


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
        context_id = state.get("shared_context_id")

        # ── Sprint 2: read shared context from prior agents in this task ──
        prior_notes = self._read_prior_notes(context_id)
        prompt = text if not prior_notes else f"{text}\n\n[Prior agent notes]\n{prior_notes}"

        worker = self._select_worker(agent)
        result = worker(prompt)

        # ── Sprint 2: persist response into shared context ──
        self._write_response(context_id, agent, result)

        # ── Sprint 2: lineage append ──
        lineage = state.get("execution_lineage") or []
        lineage.append({"agent": agent, "wrote_key": "response"})

        tool_history = state.get("tool_history", [])
        tool_history.append({
            "worker": agent,
            "response": result,
        })
        state.update({
            "worker_response": result,
            "tool_history": tool_history,
            "execution_lineage": lineage,
            "status": "executing",
        })
        return state

    # ------------------------------------------------------------------ #

    def _read_prior_notes(self, context_id: Optional[str]) -> str:
        """Aggregate prior agent responses from shared context, if any."""
        if not context_id:
            return ""
        try:
            from shail.memory.shared_context import get_shared_context
            store = get_shared_context()
            if not store._enabled:
                return ""
            # Read responses written by other agents on this task
            agents_seen = ["gemini", "chatgpt", "kimi", "code", "research", "bio", "robo", "plasma"]
            notes = []
            for ns in agents_seen:
                val = self._run_sync(store.read(context_id, ns, "response"))
                if val:
                    _emit("memory.shared_context_read", namespace=ns, backend="sc")
                    notes.append(f"[{ns}]: {_truncate_for_context(str(val))}")
            return "\n".join(notes)
        except Exception as exc:
            logger.debug("WorkerNodes: shared-context read failed: %s", exc)
            return ""

    def _write_response(self, context_id: Optional[str], agent: str, result: str) -> None:
        if not context_id or not result:
            return
        try:
            from shail.memory.shared_context import get_shared_context
            store = get_shared_context()
            if not store._enabled:
                return
            truncated = _truncate_for_context(result)
            self._run_sync(store.write(context_id, agent, "response", truncated))
            _emit("memory.shared_context_write", namespace=agent, backend="sc")
        except Exception as exc:
            logger.debug("WorkerNodes: shared-context write failed: %s", exc)

    @staticmethod
    def _run_sync(coro) -> Any:
        """Bridge async store calls from sync LangGraph node context.

        Worker_node.__call__ is sync; SharedContextStore is async. If we are
        running in a thread without a loop, asyncio.run is safe. If we are
        inside the uvicorn loop, run the coroutine in a worker thread.
        """
        try:
            asyncio.get_running_loop()
        except RuntimeError:
            return asyncio.run(coro)
        # Inside running loop — offload to thread
        import threading
        box: Dict[str, Any] = {}
        def _runner():
            try:
                box["value"] = asyncio.run(coro)
            except BaseException as exc:
                box["error"] = exc
        t = threading.Thread(target=_runner, daemon=True)
        t.start()
        t.join(timeout=2.0)
        if "error" in box:
            return None
        return box.get("value")
