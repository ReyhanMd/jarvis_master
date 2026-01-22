from typing import Optional

from shail.core.types import AccessibilityEvent
from shail.memory.rag import store_project_context_for_rag
from shail.perception.buffer import GroundingBuffer


class ProjectContextDetector:
    def __init__(self, buffer: GroundingBuffer):
        self.buffer = buffer

    def detect_active_project(self) -> Optional[str]:
        """
        Heuristic project detection based on recent accessibility events.
        Looks for window titles like "ProjectName - App" or "ProjectName — App".
        """
        try:
            events = list(self.buffer._ax_events)[-20:]
        except Exception:
            return None

        for _, event in reversed(events):
            project = self._extract_project_from_event(event)
            if project:
                return project
        return None

    def persist_project_context(self, project_name: str, source: str = "accessibility"):
        store_project_context_for_rag(
            project_name=project_name,
            context_type="intent",
            content={"project": project_name, "source": source},
        )

    def _extract_project_from_event(self, event: AccessibilityEvent) -> Optional[str]:
        window_title = None
        if event.metadata:
            window_title = event.metadata.get("window_title")
        if not window_title:
            return None

        for separator in [" - ", " — ", " | "]:
            if separator in window_title:
                return window_title.split(separator)[0].strip()
        return None
