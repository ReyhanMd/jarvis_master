"""
Vision Observation Agent (The Observer)

Responsible for inspecting specific frames to extract detailed information.
Implements "Chain-of-Anomaly-Thoughts" (CoAT) to prioritize bug/error detection.
"""

import json
from typing import Dict, List, Optional

from shail.core.types import NarrativeSegment, VisionObservation


class VisionObservationAgent:
    """
    The Observer. Sees *what* happened, with a bias towards anomalies and token efficiency.
    """

    def __init__(self, connector=None, vlm_client=None, token_budget: int = 4000):
        """
        connector: optional PerceptionServiceConnector for frame requests
        vlm_client: optional VLM client (e.g., Gemini 1.5 Pro Vision)
        """
        self.connector = connector
        self.vlm = vlm_client
        self.token_budget = token_budget

    def observe(self, segment: NarrativeSegment, focus_prompt: str) -> VisionObservation:
        """
        Inspect the visual frames of the given segment.
        Currently performs a lightweight anomaly-focused analysis and stubs VLM calls.
        """
        print(
            f"[VisionObservationAgent] Inspecting {segment.start_time}-{segment.end_time} focus='{focus_prompt}'"
        )

        frames = self._request_frames(segment)
        vlm_result = self._analyze_with_vlm(frames, focus_prompt, segment)
        anomalies = self._detect_anomalies(vlm_result)

        text_lines = vlm_result.get("text_lines", [])
        observation_text = "\n".join(text_lines) if text_lines else vlm_result.get("raw_text", "")

        return VisionObservation(
            text=observation_text or segment.story,
            detected_anomalies=anomalies,
            is_anomaly=len(anomalies) > 0,
        )

    # ------------------------------
    # Internal helpers
    # ------------------------------
    def _request_frames(self, segment: NarrativeSegment) -> List[Dict]:
        """
        Request frames for the segment time window.
        If no connector is available, returns an empty list (fallback to narrative).
        """
        if not self.connector:
            return []

        start_ts = segment.start_time
        end_ts = segment.end_time
        try:
            # Connector expected to return FrameResponse-compatible object/dict
            response = self.connector.request_frames_sync(start_ts=start_ts, end_ts=end_ts, max_frames=5)
            return response.get("frames", []) if isinstance(response, dict) else []
        except Exception as e:
            print(f"[VisionObservationAgent] Frame request failed: {e}")
            return []

    def _analyze_with_vlm(
        self, frames: List[Dict], focus_prompt: str, segment: NarrativeSegment
    ) -> Dict:
        """
        Stubbed VLM analysis. In production, send frames + prompt to Gemini Vision and parse JSON.
        """
        if not frames or not self.vlm:
            # Fallback heuristic based on segment narrative
            return {
                "text_lines": [segment.story],
                "errors": ["error" in segment.story.lower()] if segment.story else [],
                "raw_text": segment.story,
            }

        # Example placeholder call; replace with actual VLM integration
        try:
            payload = {"frames": frames, "focus": focus_prompt}
            vlm_response = self.vlm.invoke(json.dumps(payload))
            text = getattr(vlm_response, "content", str(vlm_response))
            return {"raw_text": text, "text_lines": text.splitlines()}
        except Exception as e:
            print(f"[VisionObservationAgent] VLM call failed: {e}")
            return {"raw_text": segment.story, "text_lines": [segment.story]}

    def _detect_anomalies(self, vlm_result: Dict) -> List[str]:
        text = " ".join(vlm_result.get("text_lines", [])) if vlm_result else ""
        anomalies = []
        for marker in ["error", "traceback", "exception", "failed", "warning"]:
            if marker in text.lower():
                anomalies.append(marker)
        return anomalies
