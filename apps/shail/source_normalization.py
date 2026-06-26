"""Source normalization for browser/AI memory surfaces.

Old captures used a mix of labels such as ``web``, ``Claude``, and
``browser_chatgpt``. The browser dashboard, sidepanel, graph, export, and
recovery tooling need one shared answer for two questions:

* what product did this capture really come from?
* should it appear in browser-memory surfaces at all?
"""
from __future__ import annotations

from typing import Any, Dict, Mapping, Optional
from urllib.parse import urlparse


SUPPORTED_AI_SOURCES = {"chatgpt", "claude", "gemini", "perplexity", "grok"}
BROWSER_MEMORY_SOURCES = SUPPORTED_AI_SOURCES | {"web"}
LOCAL_OR_ACTIVITY_SOURCES = {
    "local_file",
    "macos_fs",
    "clipboard",
    "screen",
    "screenshot",
    "app_activity",
    "activity",
}


def _clean(value: Any) -> str:
    return str(value or "").strip()


def _lower(value: Any) -> str:
    return _clean(value).lower()


def source_host(source_url: str) -> str:
    try:
        host = urlparse(source_url or "").netloc.lower()
    except Exception:
        return ""
    if host.startswith("www."):
        host = host[4:]
    return host


def infer_source_app(
    source_app: Any = "",
    *,
    source_url: str = "",
    title: str = "",
    metadata: Optional[Mapping[str, Any]] = None,
) -> str:
    """Return the canonical browser-memory source label.

    URL is intentionally stronger than stored sourceApp because legacy Claude
    browser captures were saved as ``sourceApp=web`` while their URLs clearly
    point at claude.ai.
    """
    meta = metadata or {}
    source_app_raw = _lower(source_app or meta.get("sourceApp") or meta.get("source") or "")
    source_raw = _lower(meta.get("source") or "")
    url = source_url or _clean(meta.get("sourceUrl") or meta.get("url") or "")
    host = source_host(url)
    title_l = _lower(title or meta.get("title") or "")

    if host in {"chatgpt.com", "chat.openai.com"} or host.endswith(".chatgpt.com"):
        return "chatgpt"
    if host == "claude.ai" or host.endswith(".claude.ai"):
        return "claude"
    if host in {"gemini.google.com", "bard.google.com"} or host.endswith(".gemini.google.com"):
        return "gemini"
    if host == "perplexity.ai" or host.endswith(".perplexity.ai"):
        return "perplexity"
    if host in {"grok.com", "x.ai"} or host.endswith(".grok.com"):
        return "grok"

    joined = f"{source_app_raw} {source_raw} {title_l}"
    if "chatgpt" in joined or "openai" in joined:
        return "chatgpt"
    if "claude" in joined:
        return "claude"
    if "gemini" in joined or "bard" in joined:
        return "gemini"
    if "perplexity" in joined:
        return "perplexity"
    if "grok" in joined:
        return "grok"

    if source_app_raw in LOCAL_OR_ACTIVITY_SOURCES or source_raw in LOCAL_OR_ACTIVITY_SOURCES:
        return source_app_raw or source_raw
    if source_raw == "local_file":
        return "local_file"
    return "web"


def normalize_browser_metadata(meta: Optional[Mapping[str, Any]], document: str = "") -> Dict[str, Any]:
    """Return a normalized metadata copy without mutating the caller's dict."""
    out: Dict[str, Any] = dict(meta or {})
    source_app = infer_source_app(
        out.get("sourceApp"),
        source_url=_clean(out.get("sourceUrl") or out.get("url") or ""),
        title=_clean(out.get("title") or ""),
        metadata=out,
    )
    out["sourceApp"] = source_app
    if source_app in BROWSER_MEMORY_SOURCES:
        out["source"] = f"browser_{source_app}"
    elif source_app == "local_file":
        out["source"] = "local_file"
    return out


def is_local_or_activity_memory(meta: Optional[Mapping[str, Any]]) -> bool:
    meta = meta or {}
    source_app = _lower(meta.get("sourceApp"))
    source = _lower(meta.get("source"))
    if source_app in LOCAL_OR_ACTIVITY_SOURCES or source in LOCAL_OR_ACTIVITY_SOURCES:
        return True
    if source == "local_file":
        return True
    record_id = _lower(meta.get("id") or meta.get("customId"))
    return record_id.startswith("file:")


def is_browser_memory(meta: Optional[Mapping[str, Any]], document: str = "") -> bool:
    """Whether a record belongs in browser/AI memory cards.

    This deliberately excludes local-file chunks and obvious OS/app activity
    while keeping raw browser captures visible even before embedding finishes.
    """
    meta = meta or {}
    if is_local_or_activity_memory(meta):
        return False
    normalized = normalize_browser_metadata(meta, document)
    source_app = normalized.get("sourceApp", "web")
    event_type = _lower(normalized.get("eventType"))
    url = _clean(normalized.get("sourceUrl") or normalized.get("url") or "")
    source = _lower(normalized.get("source"))

    if source_app in SUPPORTED_AI_SOURCES:
        return True
    if source_app == "web":
        return bool(url.startswith(("http://", "https://"))) or event_type in {
            "page_visit",
            "manual_save",
            "bulk_history",
            "audio_clip",
        }
    if source.startswith("browser_"):
        return True
    return False

