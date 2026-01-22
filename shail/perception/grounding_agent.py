"""
Grounding Agent (The Searcher)

Responsible for localizing specific events in the user's timeline based on high-level goals.
Queries the GroundingBuffer for accessibility evidence and selects timestamp ranges.
"""

import time
from typing import List, Optional, Tuple

from shail.core.types import GroundingResult, NarrativeSegment
from shail.perception.buffer import GroundingBuffer


CONFIDENCE_ACCEPT = 0.6
CONFIDENCE_RETRY = 0.4
CONFIDENCE_ESCALATE = 0.4


class GroundingAgent:
    """
    The Searcher. Finds *when* something happened.
    """

    def __init__(self, buffer: GroundingBuffer):
        self.buffer = buffer

    def find_event(self, query: str, max_glances: int = 3) -> GroundingResult:
        """
        Search for a time segment matching the query using multiple glances if needed.
        """
        print(f"[GroundingAgent] Searching for: '{query}'")

        time_range = self._extract_temporal_references(query)
        best_segment: Optional[NarrativeSegment] = None
        best_confidence = 0.0

        for glance in range(max_glances):
            candidates = self.buffer.query_semantic(query, time_range=time_range)
            if not candidates:
                continue

            ranked = self._score_segments(query, candidates)
            if not ranked:
                continue

            top_seg, top_conf = ranked[0]
            if top_conf > best_confidence:
                best_confidence = top_conf
                best_segment = top_seg

            if top_conf >= CONFIDENCE_ACCEPT:
                break

            # Expand search window slightly for next glance
            if time_range:
                start, end = time_range
                pad = 15
                time_range = (start - pad, end + pad)

        if best_segment is None:
            return GroundingResult(
                segment=None,
                confidence=0.0,
                rationale="No relevant events found in buffer.",
            )

        return GroundingResult(
            segment=best_segment,
            confidence=best_confidence,
            rationale=f"Selected segment at {best_segment.start_time} with confidence {best_confidence:.2f}",
        )

    # ------------------------------
    # Helpers
    # ------------------------------
    def _score_segments(
        self, query: str, segments: List[NarrativeSegment]
    ) -> List[Tuple[NarrativeSegment, float]]:
        scored: List[Tuple[NarrativeSegment, float]] = []
        now = time.time()
        for seg in segments:
            keyword_score = self._keyword_score(query, seg)
            semantic_score = self._semantic_score(query, seg)
            app_context_score = self._app_context_score(query, seg)
            age_seconds = max(1.0, now - seg.end_time)
            recency_score = 1 - min(age_seconds / self.buffer.window, 1)
            confidence = (
                0.4 * keyword_score
                + 0.3 * semantic_score
                + 0.2 * recency_score
                + 0.1 * app_context_score
            )
            scored.append((seg, confidence))
        scored.sort(key=lambda item: item[1], reverse=True)
        return scored

    def _keyword_score(self, query: str, segment: NarrativeSegment) -> float:
        keywords = ["error", "traceback", "exception", "failed", "red"]
        text = f"{segment.story} {' '.join(segment.raw_logs or [])}".lower()
        hits = sum(1 for kw in keywords if kw in text)
        query_hits = sum(1 for token in query.lower().split() if token in text)
        total_terms = max(1, len(keywords) + len(query.split()))
        return min(1.0, (hits + query_hits) / total_terms)

    def _semantic_score(self, query: str, segment: NarrativeSegment) -> float:
        query_tokens = set(query.lower().split())
        seg_text = f"{segment.story} {' '.join(segment.raw_logs or [])}".lower()
        seg_tokens = set(seg_text.split())
        if not query_tokens or not seg_tokens:
            return 0.0
        intersection = query_tokens.intersection(seg_tokens)
        union = query_tokens.union(seg_tokens)
        return min(1.0, len(intersection) / max(1, len(union)))

    def _app_context_score(self, query: str, segment: NarrativeSegment) -> float:
        story = segment.story or ""
        app_name = None
        if story.startswith("[") and "]" in story:
            app_name = story[1 : story.index("]")]
        if not app_name:
            return 0.0
        return 1.0 if app_name.lower() in query.lower() else 0.0

    def _extract_temporal_references(self, query: str) -> Optional[Tuple[float, float]]:
        """
        Parse simple temporal hints like '2 minutes ago'. Returns absolute epoch range.
        """
        import re

        q = query.lower()
        match = re.search(r"(\d+)\s*(second|sec|minute|min|hour|hr)", q)
        if match:
            value = int(match.group(1))
            unit = match.group(2)
            seconds = value
            if unit.startswith("min"):
                seconds = value * 60
            elif unit.startswith("hour") or unit.startswith("hr"):
                seconds = value * 3600
            end_ts = time.time() - seconds
            return (end_ts - 120, end_ts + 120)

        if "last hour" in q:
            end_ts = time.time()
            return (end_ts - 3600, end_ts)

        if "yesterday" in q:
            end_ts = time.time() - 24 * 3600
            return (end_ts - 24 * 3600, end_ts)
        return None
