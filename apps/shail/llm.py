"""
Unified LLM call layer — Ollama + OpenAI + Anthropic.

Routes a chat completion to whichever provider the user has configured
in their `user_settings` row. Handles streaming and non-streaming, and
falls back to local Ollama on provider error so a transient API outage
doesn't break dashboard chat for users who normally use a paid provider.

Public:
    call_llm(messages, *, user_id, context, system_prompt) -> str
    stream_llm(messages, *, user_id, context, system_prompt) -> AsyncIterator[str]
    test_provider(provider, api_key, model) -> tuple[bool, str]
    get_user_llm_config(user_id) -> dict

Provider keys come from `user_settings`. v1 stores them as plaintext —
encryption-at-rest is a v2 concern (flagged with a TODO so we don't
forget). Each provider exposes a different streaming protocol; this
module normalizes them so the caller sees identical str chunks.
"""

# TODO(v2): encrypt api keys at rest. Today they live as plaintext in
# `user_settings.openai_api_key` and `user_settings.anthropic_api_key`.

from __future__ import annotations

import asyncio
import json
import logging
from typing import AsyncIterator, Dict, List, Optional, Tuple

import httpx

from apps.shail.auth_store import get_user_settings
from apps.shail.settings import get_settings

logger = logging.getLogger(__name__)


# ── Defaults ────────────────────────────────────────────────────────────────

PROVIDER_OLLAMA = "ollama"
PROVIDER_OPENAI = "openai"
PROVIDER_ANTHROPIC = "anthropic"

PROVIDERS = (PROVIDER_OLLAMA, PROVIDER_OPENAI, PROVIDER_ANTHROPIC)

DEFAULT_MODELS = {
    PROVIDER_OLLAMA: "gemma3:4b-it-q4_K_M",
    PROVIDER_OPENAI: "gpt-4o-mini",
    PROVIDER_ANTHROPIC: "claude-haiku-4-5-20251001",
}

OPENAI_API = "https://api.openai.com/v1/chat/completions"
ANTHROPIC_API = "https://api.anthropic.com/v1/messages"

# How long we wait for an LLM response before giving up.
NONSTREAM_TIMEOUT = 90.0
STREAM_TIMEOUT = 180.0


# ── Per-user config ─────────────────────────────────────────────────────────

def get_user_llm_config(user_id: Optional[str]) -> dict:
    """Return the active provider, model, and key for a user. Defaults to
    Ollama (no key) when the user has no settings row or is anonymous.
    """
    settings: dict = {}
    if user_id and user_id != "local":
        try:
            settings = get_user_settings(user_id) or {}
        except Exception as e:
            logger.warning("get_user_llm_config: %s", e)
            settings = {}

    provider = (settings.get("active_provider") or PROVIDER_OLLAMA).lower()
    if provider not in PROVIDERS:
        provider = PROVIDER_OLLAMA

    # Pick model: explicit user choice → provider default
    model = settings.get("active_model") or DEFAULT_MODELS.get(provider, "")

    api_key = ""
    if provider == PROVIDER_OPENAI:
        api_key = settings.get("openai_api_key") or ""
    elif provider == PROVIDER_ANTHROPIC:
        api_key = settings.get("anthropic_api_key") or ""

    # If the chosen provider needs a key but the user hasn't set one,
    # silently fall back to ollama so chat still works rather than 401.
    if provider in (PROVIDER_OPENAI, PROVIDER_ANTHROPIC) and not api_key:
        return {
            "provider": PROVIDER_OLLAMA,
            "model": DEFAULT_MODELS[PROVIDER_OLLAMA],
            "api_key": "",
            "fellback": True,
            "reason": f"no API key for {provider}",
        }

    return {"provider": provider, "model": model, "api_key": api_key, "fellback": False}


# ── Message helpers ─────────────────────────────────────────────────────────

def _build_system_content(base_prompt: str, context: str) -> str:
    s = base_prompt or "You are SHAIL, a personal AI assistant."
    if context:
        s += f"\n\nRelevant context from memory and live web results:\n{context}"
    return s


def _ensure_messages(messages: List[Dict[str, str]]) -> List[Dict[str, str]]:
    """Drop any pre-existing system messages — we always set our own."""
    return [m for m in messages if m.get("role") != "system"]


# ── Ollama (local) ──────────────────────────────────────────────────────────

async def _ollama_call(
    model: str, messages: List[dict], system: str, *, stream: bool
) -> str | AsyncIterator[dict]:
    s = get_settings()
    payload = {
        "model": model or s.ollama_chat_model,
        "messages": [{"role": "system", "content": system}] + messages,
        "stream": stream,
        "keep_alive": s.ollama_keep_alive,
        "options": {
            "num_ctx":    s.ollama_num_ctx,
            "num_thread": s.ollama_num_thread,
            "num_gpu":    99,
        },
    }
    if not stream:
        async with httpx.AsyncClient(timeout=NONSTREAM_TIMEOUT) as client:
            resp = await client.post(f"{s.ollama_base_url}/api/chat", json=payload)
            resp.raise_for_status()
            return resp.json()["message"]["content"]

    async def gen() -> AsyncIterator[dict]:
        async with httpx.AsyncClient(timeout=STREAM_TIMEOUT) as client:
            async with client.stream(
                "POST", f"{s.ollama_base_url}/api/chat", json=payload
            ) as resp:
                resp.raise_for_status()
                async for line in resp.aiter_lines():
                    if not line:
                        continue
                    try:
                        data = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    chunk = (data.get("message") or {}).get("content") or ""
                    done = bool(data.get("done"))
                    if chunk or done:
                        yield {"text": chunk, "done": done}
    return gen()


# ── OpenAI ──────────────────────────────────────────────────────────────────

async def _openai_call(
    model: str, messages: List[dict], system: str, api_key: str, *, stream: bool
) -> str | AsyncIterator[dict]:
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    payload = {
        "model": model or DEFAULT_MODELS[PROVIDER_OPENAI],
        "messages": [{"role": "system", "content": system}] + messages,
        "stream": stream,
    }

    if not stream:
        async with httpx.AsyncClient(timeout=NONSTREAM_TIMEOUT) as client:
            resp = await client.post(OPENAI_API, json=payload, headers=headers)
            resp.raise_for_status()
            data = resp.json()
            return data["choices"][0]["message"]["content"]

    async def gen() -> AsyncIterator[dict]:
        async with httpx.AsyncClient(timeout=STREAM_TIMEOUT) as client:
            async with client.stream(
                "POST", OPENAI_API, json=payload, headers=headers
            ) as resp:
                resp.raise_for_status()
                async for line in resp.aiter_lines():
                    if not line or not line.startswith("data:"):
                        continue
                    payload_str = line[5:].strip()
                    if payload_str == "[DONE]":
                        yield {"text": "", "done": True}
                        return
                    try:
                        evt = json.loads(payload_str)
                    except json.JSONDecodeError:
                        continue
                    delta = (evt.get("choices") or [{}])[0].get("delta") or {}
                    chunk = delta.get("content") or ""
                    finish_reason = (evt.get("choices") or [{}])[0].get("finish_reason")
                    done = finish_reason is not None
                    if chunk or done:
                        yield {"text": chunk, "done": done}
    return gen()


# ── Anthropic ───────────────────────────────────────────────────────────────

async def _anthropic_call(
    model: str, messages: List[dict], system: str, api_key: str, *, stream: bool
) -> str | AsyncIterator[dict]:
    """Anthropic Messages API: system prompt is a top-level field, not
    a message. SSE chunks come as `event: content_block_delta` with
    `delta.text` carrying the next token.
    """
    headers = {
        "x-api-key": api_key,
        "anthropic-version": "2023-06-01",
        "Content-Type": "application/json",
    }
    payload = {
        "model": model or DEFAULT_MODELS[PROVIDER_ANTHROPIC],
        "system": system,
        "messages": messages,
        "max_tokens": 2048,
        "stream": stream,
    }

    if not stream:
        async with httpx.AsyncClient(timeout=NONSTREAM_TIMEOUT) as client:
            resp = await client.post(ANTHROPIC_API, json=payload, headers=headers)
            resp.raise_for_status()
            data = resp.json()
            blocks = data.get("content") or []
            return "".join(b.get("text", "") for b in blocks if b.get("type") == "text")

    async def gen() -> AsyncIterator[dict]:
        async with httpx.AsyncClient(timeout=STREAM_TIMEOUT) as client:
            async with client.stream(
                "POST", ANTHROPIC_API, json=payload, headers=headers
            ) as resp:
                resp.raise_for_status()
                async for line in resp.aiter_lines():
                    if not line or not line.startswith("data:"):
                        continue
                    payload_str = line[5:].strip()
                    if not payload_str:
                        continue
                    try:
                        evt = json.loads(payload_str)
                    except json.JSONDecodeError:
                        continue
                    if evt.get("type") == "content_block_delta":
                        chunk = (evt.get("delta") or {}).get("text") or ""
                        yield {"text": chunk, "done": False}
                    elif evt.get("type") == "message_stop":
                        yield {"text": "", "done": True}
    return gen()


# ── Public API ──────────────────────────────────────────────────────────────

async def call_llm(
    messages: List[Dict[str, str]],
    *,
    user_id: Optional[str] = None,
    context: str = "",
    system_prompt: str = "",
) -> Tuple[str, dict]:
    """Non-streaming call. Returns (answer, meta) where meta includes the
    provider/model that actually answered (after any fallback).
    """
    cfg = get_user_llm_config(user_id)
    sys_content = _build_system_content(system_prompt, context)
    msgs = _ensure_messages(messages)

    try:
        text = await _dispatch(cfg, msgs, sys_content, stream=False)
        return text, cfg
    except Exception as e:
        if cfg["provider"] == PROVIDER_OLLAMA:
            return f"Local model error: {e}", {**cfg, "error": str(e)}
        # Fall back to ollama for paid providers on any error.
        logger.warning("LLM provider %s failed (%s) — falling back to Ollama", cfg["provider"], e)
        fb_cfg = {"provider": PROVIDER_OLLAMA, "model": DEFAULT_MODELS[PROVIDER_OLLAMA],
                  "api_key": "", "fellback": True, "reason": f"{cfg['provider']} error: {e}"}
        try:
            text = await _dispatch(fb_cfg, msgs, sys_content, stream=False)
            return text, fb_cfg
        except Exception as e2:
            return (
                f"Both {cfg['provider']} and local Ollama failed. "
                f"Original: {e}. Fallback: {e2}",
                {**fb_cfg, "error": str(e2)},
            )


async def stream_llm(
    messages: List[Dict[str, str]],
    *,
    user_id: Optional[str] = None,
    context: str = "",
    system_prompt: str = "",
) -> AsyncIterator[Tuple[dict, dict]]:
    """Streaming call. Yields (payload_dict, meta) tuples. The first yielded meta
    indicates which provider is actually answering (post-fallback). The
    payload_dict is standardized to: {"text": "...", "done": bool}.
    """
    cfg = get_user_llm_config(user_id)
    sys_content = _build_system_content(system_prompt, context)
    msgs = _ensure_messages(messages)

    try:
        gen = await _dispatch(cfg, msgs, sys_content, stream=True)
        has_done = False
        async for payload in gen:
            if payload.get("done"):
                has_done = True
            yield payload, cfg
        if not has_done:
            yield {"text": "", "done": True}, cfg
        return
    except Exception as e:
        if cfg["provider"] == PROVIDER_OLLAMA:
            yield {"text": f"\n[Local model error: {e}]", "done": True}, {**cfg, "error": str(e)}
            return
        logger.warning("LLM stream %s failed (%s) — falling back to Ollama", cfg["provider"], e)
        fb_cfg = {"provider": PROVIDER_OLLAMA, "model": DEFAULT_MODELS[PROVIDER_OLLAMA],
                  "api_key": "", "fellback": True, "reason": f"{cfg['provider']} error: {e}"}
        try:
            gen = await _dispatch(fb_cfg, msgs, sys_content, stream=True)
            has_done = False
            async for payload in gen:
                if payload.get("done"):
                    has_done = True
                yield payload, fb_cfg
            if not has_done:
                yield {"text": "", "done": True}, fb_cfg
        except Exception as e2:
            yield {"text": f"\n[Both providers failed: {e2}]", "done": True}, {**fb_cfg, "error": str(e2)}


async def _dispatch(cfg: dict, msgs: list, system: str, *, stream: bool):
    if cfg["provider"] == PROVIDER_OLLAMA:
        return await _ollama_call(cfg["model"], msgs, system, stream=stream)
    if cfg["provider"] == PROVIDER_OPENAI:
        return await _openai_call(cfg["model"], msgs, system, cfg["api_key"], stream=stream)
    if cfg["provider"] == PROVIDER_ANTHROPIC:
        return await _anthropic_call(cfg["model"], msgs, system, cfg["api_key"], stream=stream)
    raise ValueError(f"unknown provider: {cfg['provider']}")


# ── Settings page "Test" button ─────────────────────────────────────────────

async def test_provider(provider: str, api_key: str, model: str = "") -> Tuple[bool, str]:
    """Send a single trivial message and return (ok, info). Used by the
    Settings page Test button to validate an API key without saving it.
    """
    cfg = {
        "provider": provider,
        "model": model or DEFAULT_MODELS.get(provider, ""),
        "api_key": api_key or "",
    }
    try:
        msgs = [{"role": "user", "content": "Say 'ok' and nothing else."}]
        if provider == PROVIDER_OLLAMA:
            text = await _ollama_call(cfg["model"], msgs, "Reply with one word.", stream=False)
        elif provider == PROVIDER_OPENAI:
            text = await _openai_call(cfg["model"], msgs, "Reply with one word.", api_key, stream=False)
        elif provider == PROVIDER_ANTHROPIC:
            text = await _anthropic_call(cfg["model"], msgs, "Reply with one word.", api_key, stream=False)
        else:
            return False, f"unknown provider: {provider}"
        return True, (text or "").strip()[:80] or "(empty response)"
    except httpx.HTTPStatusError as e:
        return False, f"{e.response.status_code} {e.response.reason_phrase}"
    except Exception as e:
        return False, str(e)
