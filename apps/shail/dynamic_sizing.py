"""Dynamic sizing — context-window-aware budgeting for the blueprint pipeline.

Replaces the hard-coded `content_cap = 16_000` and `char_cap = 24_000`
constants with a runtime calculation based on:
  - the model's context window (Ollama `num_ctx`)
  - the extraction prompt overhead (system + instruction + scaffolding)
  - reserved tokens for the JSON response
  - any prior-blueprint payload that must coexist in the prompt

Budgets are returned in CHARACTERS because the rest of the pipeline already
works in characters and we don't want to require a tokenizer dependency.
The char↔token approximation is intentionally conservative.

Tunables in settings:
  blueprint_chars_per_token        - approximation factor (default 3.5)
  blueprint_prompt_overhead_chars  - estimated prompt scaffolding size
  blueprint_response_reserve_pct   - fraction of context reserved for response
  blueprint_safety_margin_pct      - extra headroom (defense in depth)
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from apps.shail.settings import get_settings


@dataclass
class SizingBudget:
    """Computed budget for one blueprint LLM call."""
    context_tokens: int        # model context window in tokens
    chars_per_token: float
    prompt_overhead_chars: int  # system + instruction + JSON scaffolding
    prior_payload_chars: int    # size of prior blueprint when refining
    response_reserve_chars: int
    safety_margin_chars: int
    content_budget_chars: int   # what's actually available for content

    def to_dict(self) -> dict:
        return {
            "context_tokens": self.context_tokens,
            "chars_per_token": self.chars_per_token,
            "prompt_overhead_chars": self.prompt_overhead_chars,
            "prior_payload_chars": self.prior_payload_chars,
            "response_reserve_chars": self.response_reserve_chars,
            "safety_margin_chars": self.safety_margin_chars,
            "content_budget_chars": self.content_budget_chars,
        }


def compute_budget(
    *,
    prior_blueprint_chars: int = 0,
    context_tokens_override: Optional[int] = None,
) -> SizingBudget:
    """Calculate the per-call content budget.

    `prior_blueprint_chars` is the serialized size of the prior blueprint JSON
    when refining. The caller knows this (it has the prior in hand). Pass 0
    for fresh extraction.
    """
    settings = get_settings()
    context_tokens = context_tokens_override or settings.blueprint_context_tokens
    cpt = max(1.0, float(settings.blueprint_chars_per_token))
    total_chars = int(context_tokens * cpt)

    prompt_overhead = int(settings.blueprint_prompt_overhead_chars)
    response_reserve_pct = max(0.05, min(0.6, settings.blueprint_response_reserve_pct))
    safety_pct = max(0.0, min(0.3, settings.blueprint_safety_margin_pct))

    response_reserve = int(total_chars * response_reserve_pct)
    safety_margin = int(total_chars * safety_pct)

    content_budget = (
        total_chars
        - prompt_overhead
        - prior_blueprint_chars
        - response_reserve
        - safety_margin
    )
    # Floor — never go under the absolute minimum so we don't ship empty calls.
    content_budget = max(settings.blueprint_min_content_chars, content_budget)

    return SizingBudget(
        context_tokens=context_tokens,
        chars_per_token=cpt,
        prompt_overhead_chars=prompt_overhead,
        prior_payload_chars=prior_blueprint_chars,
        response_reserve_chars=response_reserve,
        safety_margin_chars=safety_margin,
        content_budget_chars=content_budget,
    )


def compute_window_size(
    *,
    transcript_chars: int,
    prior_blueprint_chars: int = 0,
) -> tuple[int, int]:
    """Choose a window size + overlap for chunked extraction.

    Strategy:
      - One window if the transcript fits the content budget. (window == budget)
      - Otherwise pick window = budget so each window saturates the model.
      - Overlap = settings.blueprint_window_overlap_pct of window size, capped.

    Returns (window_size_chars, overlap_chars).
    """
    settings = get_settings()
    budget = compute_budget(prior_blueprint_chars=prior_blueprint_chars)
    window_size = budget.content_budget_chars
    overlap_pct = max(0.0, min(0.5, settings.blueprint_window_overlap_pct))
    overlap = int(window_size * overlap_pct)
    return window_size, overlap


def expected_window_count(transcript_chars: int, *, prior_blueprint_chars: int = 0) -> int:
    """How many windows it'll take to cover `transcript_chars`."""
    window_size, overlap = compute_window_size(
        transcript_chars=transcript_chars,
        prior_blueprint_chars=prior_blueprint_chars,
    )
    if transcript_chars <= window_size:
        return 1 if transcript_chars > 0 else 0
    step = max(1, window_size - overlap)
    # Ceiling division
    return max(1, (transcript_chars - overlap + step - 1) // step)
