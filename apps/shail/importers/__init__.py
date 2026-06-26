"""External chat-source importers (Phase C Sprint 4 + Plan Part B3).

Each importer parses a provider-specific export format into a normalized list
of (user_msg, assistant_msg) pairs, then funnels through `common.import_pairs`
to create a chat_session + messages and enqueue a backfill job.

Supported providers:
    chatgpt     — ChatGPT conversations.json export (current-branch resolved)
    claude      — Claude.ai conversation export JSON
    cursor      — Cursor chat history log JSON
    gemini      — Google Gemini native JSON or Takeout My Activity.json
    grok        — Grok JSON or saved HTML page
    perplexity  — Perplexity thread JSON (single or bulk)
"""

from apps.shail.importers.common import ImportResult, import_conversation_payload
from apps.shail.importers import chatgpt, claude, cursor, gemini, grok, perplexity

PARSERS = {
    "chatgpt":    chatgpt.parse,
    "claude":     claude.parse,
    "cursor":     cursor.parse,
    "gemini":     gemini.parse,
    "grok":       grok.parse,
    "perplexity": perplexity.parse,
}

__all__ = ["PARSERS", "ImportResult", "import_conversation_payload"]
