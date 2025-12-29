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
            semantic_score = 0.0  # Placeholder; swap in embedding similarity when available
            age_seconds = max(1.0, now - seg.end_time)
            recency_score = 1 - min(age_seconds / self.buffer.window, 1)
            confidence = 0.5 * keyword_score + 0.3 * semantic_score + 0.2 * recency_score
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

    def _extract_temporal_references(self, query: str) -> Optional[Tuple[float, float]]:
        """
        Parse simple temporal hints like '2 minutes ago'. Returns absolute epoch range.
        """
        import re

        match = re.search(r"(\d+)\s*minute", query.lower())
        if match:
            minutes = int(match.group(1))
            end_ts = time.time() - (minutes * 60)
            return (end_ts - 60, end_ts + 60)
        return None
