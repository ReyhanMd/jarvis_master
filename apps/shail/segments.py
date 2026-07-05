"""Content-type segments — preserves rich data types through the capture pipeline.

Before this module the capture pipeline flattened everything into plain text:
tables collapsed to TSV-ish strings, code lost language hints, mermaid
diagrams went through as opaque blobs, images had no representation at all.

A Segment is the smallest typed unit of capture content. A transcript is a
list of segments. Each segment knows its kind, its raw payload, and any
metadata needed to re-render it faithfully (e.g. code language, table headers,
image URI).

Pipeline contract:
    raw input  → parse_segments()      (detect kinds from text/markdown)
                ↘ Segment[]            (canonical typed list, persisted)
                ↗ render_for_llm()     (collapses to markdown for blueprint)
                ↗ render_for_display() (UI rendering)
                ↗ token_estimate()     (dynamic sizing)

Kinds:
    text       - plain paragraphs
    markdown   - inline-formatted markdown (kept verbatim, headings/lists/etc.)
    code       - fenced code block with language
    table      - structured rows (headers + rows)
    mermaid    - mermaid diagram source
    math       - latex/asciimath block
    html       - raw html block
    json       - structured json payload
    image_ref  - reference to an image (uri, alt, dimensions)
    tool_call  - tool invocation captured from AI conversation
    tool_result - tool output captured from AI conversation

No truncation happens inside segments. Sizing decisions are the caller's job.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field, asdict
from typing import Any, Iterable, Optional

SEGMENT_KINDS = (
    "text", "markdown", "code", "table", "mermaid",
    "math", "html", "json", "image_ref", "tool_call", "tool_result",
)


@dataclass
class Segment:
    """One typed chunk of capture content. Round-trips through JSON."""
    kind: str
    content: str
    language: Optional[str] = None
    role: Optional[str] = None  # "user" | "assistant" | "system" | None
    metadata: dict = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.kind not in SEGMENT_KINDS:
            # Tolerate unknown kinds — store as text so we never lose payload.
            self.metadata = {**self.metadata, "original_kind": self.kind}
            self.kind = "text"

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "Segment":
        return cls(
            kind=str(d.get("kind") or "text"),
            content=str(d.get("content") or ""),
            language=d.get("language") or None,
            role=d.get("role") or None,
            metadata=dict(d.get("metadata") or {}),
        )

    def char_len(self) -> int:
        # Cheap proxy for token budgeting before the real tokenizer runs.
        return len(self.content)


# ── Parsing ─────────────────────────────────────────────────────────────────

_FENCE_RE = re.compile(r"^```([\w+\-]*)\s*\n(.*?)\n```\s*$", re.DOTALL | re.MULTILINE)
_TABLE_LINE_RE = re.compile(r"^\s*\|.*\|\s*$")
_TABLE_SEPARATOR_RE = re.compile(r"^\s*\|?\s*:?-{2,}:?\s*(\|\s*:?-{2,}:?\s*)+\|?\s*$")


def parse_segments(raw: str, *, default_kind: str = "text") -> list[Segment]:
    """Parse a markdown-flavored blob into typed segments.

    Detects:
      - fenced code blocks → code (language preserved)
      - mermaid fences → mermaid
      - markdown tables → table (headers + rows)
      - everything else → markdown (preserves inline formatting)

    The output is faithful: concatenating render_for_llm() back gives a
    semantically equivalent markdown blob. No truncation, no loss.
    """
    if not raw:
        return []
    segments: list[Segment] = []
    pos = 0
    text = raw

    fence_pattern = re.compile(r"```([\w+\-]*)\s*\n(.*?)\n```", re.DOTALL)
    for m in fence_pattern.finditer(text):
        if m.start() > pos:
            prelude = text[pos:m.start()].strip("\n")
            if prelude.strip():
                segments.extend(_split_non_code(prelude))
        lang = (m.group(1) or "").strip().lower() or None
        body = m.group(2)
        if lang == "mermaid":
            segments.append(Segment(kind="mermaid", content=body, language="mermaid"))
        else:
            segments.append(Segment(kind="code", content=body, language=lang))
        pos = m.end()
    if pos < len(text):
        tail = text[pos:].strip("\n")
        if tail.strip():
            segments.extend(_split_non_code(tail))
    if not segments:
        segments.append(Segment(kind=default_kind, content=raw))
    return segments


def _split_non_code(blob: str) -> list[Segment]:
    """Split non-code text into table + markdown segments."""
    lines = blob.split("\n")
    out: list[Segment] = []
    buf: list[str] = []
    i = 0
    while i < len(lines):
        line = lines[i]
        # Table detect: header row | separator row | data rows...
        if _TABLE_LINE_RE.match(line) and i + 1 < len(lines) and _TABLE_SEPARATOR_RE.match(lines[i + 1]):
            if buf:
                joined = "\n".join(buf).strip()
                if joined:
                    out.append(Segment(kind="markdown", content=joined))
                buf = []
            # Consume the table
            table_lines = [line, lines[i + 1]]
            j = i + 2
            while j < len(lines) and _TABLE_LINE_RE.match(lines[j]):
                table_lines.append(lines[j])
                j += 1
            table_seg = _parse_markdown_table(table_lines)
            out.append(table_seg)
            i = j
            continue
        buf.append(line)
        i += 1
    if buf:
        joined = "\n".join(buf).strip()
        if joined:
            out.append(Segment(kind="markdown", content=joined))
    return out


def _parse_markdown_table(lines: list[str]) -> Segment:
    """Parse markdown table lines → Segment with structured rows."""
    def split_cells(line: str) -> list[str]:
        # Strip leading/trailing pipes, split on |
        s = line.strip()
        if s.startswith("|"):
            s = s[1:]
        if s.endswith("|"):
            s = s[:-1]
        return [c.strip() for c in s.split("|")]

    headers = split_cells(lines[0])
    rows: list[dict[str, str]] = []
    for raw_row in lines[2:]:
        cells = split_cells(raw_row)
        # Pad/truncate to header width
        if len(cells) < len(headers):
            cells = cells + [""] * (len(headers) - len(cells))
        elif len(cells) > len(headers):
            cells = cells[:len(headers)]
        rows.append({h: c for h, c in zip(headers, cells)})
    raw_blob = "\n".join(lines)
    return Segment(
        kind="table",
        content=raw_blob,  # original markdown preserved
        metadata={"headers": headers, "rows": rows, "row_count": len(rows)},
    )


# ── Rendering ───────────────────────────────────────────────────────────────


def render_for_llm(segments: Iterable[Segment]) -> str:
    """Render segments back to markdown for LLM consumption.

    Lossless for the kinds we model — code keeps its fence + language,
    tables keep markdown pipe form, mermaid keeps its fence.
    """
    parts: list[str] = []
    for seg in segments:
        if seg.role:
            role_prefix = f"[{seg.role.upper()}] "
        else:
            role_prefix = ""
        if seg.kind == "code":
            lang = seg.language or ""
            parts.append(f"{role_prefix}```{lang}\n{seg.content}\n```")
        elif seg.kind == "mermaid":
            parts.append(f"{role_prefix}```mermaid\n{seg.content}\n```")
        elif seg.kind == "table":
            # Prefer the original markdown blob if we have it; rebuild otherwise.
            if seg.content.strip().startswith("|"):
                parts.append(f"{role_prefix}{seg.content}")
            else:
                parts.append(role_prefix + _rebuild_table(seg.metadata))
        elif seg.kind == "math":
            parts.append(f"{role_prefix}$$\n{seg.content}\n$$")
        elif seg.kind == "html":
            parts.append(f"{role_prefix}{seg.content}")
        elif seg.kind == "json":
            parts.append(f"{role_prefix}```json\n{seg.content}\n```")
        elif seg.kind == "image_ref":
            uri = seg.metadata.get("uri") or seg.content
            alt = seg.metadata.get("alt") or ""
            parts.append(f"{role_prefix}![{alt}]({uri})")
        elif seg.kind in ("tool_call", "tool_result"):
            tag = seg.kind.upper()
            parts.append(f"{role_prefix}<{tag}>\n{seg.content}\n</{tag}>")
        else:
            parts.append(f"{role_prefix}{seg.content}")
    return "\n\n".join(parts)


def _rebuild_table(meta: dict) -> str:
    headers = meta.get("headers") or []
    rows = meta.get("rows") or []
    if not headers:
        return ""
    header_line = "| " + " | ".join(headers) + " |"
    sep_line = "| " + " | ".join(["---"] * len(headers)) + " |"
    row_lines = []
    for row in rows:
        row_lines.append("| " + " | ".join(str(row.get(h, "")) for h in headers) + " |")
    return "\n".join([header_line, sep_line, *row_lines])


def render_plain(segments: Iterable[Segment]) -> str:
    """Plain-text projection. Loses fences but keeps content. Used for vector
    embedding where markdown fences are noise.
    """
    parts: list[str] = []
    for seg in segments:
        if seg.role:
            parts.append(f"{seg.role.upper()}: {seg.content}")
        else:
            parts.append(seg.content)
    return "\n\n".join(p for p in parts if p.strip())


# ── Serialization ───────────────────────────────────────────────────────────


def segments_to_json(segments: list[Segment]) -> str:
    return json.dumps([s.to_dict() for s in segments], ensure_ascii=False)


def segments_from_json(blob: Optional[str]) -> list[Segment]:
    if not blob:
        return []
    try:
        data = json.loads(blob)
    except (TypeError, json.JSONDecodeError):
        return []
    if not isinstance(data, list):
        return []
    return [Segment.from_dict(d) for d in data if isinstance(d, dict)]


# ── Sizing helpers ──────────────────────────────────────────────────────────


def total_chars(segments: Iterable[Segment]) -> int:
    return sum(s.char_len() for s in segments)


def slice_segments_by_budget(
    segments: list[Segment],
    char_budget: int,
    *,
    overlap_chars: int = 0,
) -> list[list[Segment]]:
    """Pack segments into windows that each fit `char_budget`.

    A single oversized segment (e.g. one giant code block) is NEVER cut in
    the middle — it's emitted as a window of its own. Caller decides what to
    do with it (down-stream code splits oversized blocks at line boundaries).
    """
    if char_budget <= 0:
        return [segments] if segments else []
    windows: list[list[Segment]] = []
    current: list[Segment] = []
    current_size = 0
    for seg in segments:
        seg_size = seg.char_len()
        if seg_size > char_budget:
            if current:
                windows.append(current)
                current = []
                current_size = 0
            # Oversized: needs sub-slicing — split on line boundaries.
            for sub in _split_oversized_segment(seg, char_budget):
                windows.append([sub])
            continue
        if current_size + seg_size > char_budget and current:
            windows.append(current)
            if overlap_chars > 0:
                # Carry tail segments worth `overlap_chars` into next window.
                tail: list[Segment] = []
                running = 0
                for s in reversed(current):
                    if running + s.char_len() > overlap_chars:
                        break
                    tail.insert(0, s)
                    running += s.char_len()
                current = list(tail)
                current_size = running
            else:
                current = []
                current_size = 0
        current.append(seg)
        current_size += seg_size
    if current:
        windows.append(current)
    return windows


def _split_oversized_segment(seg: Segment, budget: int) -> list[Segment]:
    """Split a single segment that exceeds budget. Preserves kind."""
    if seg.char_len() <= budget:
        return [seg]
    lines = seg.content.split("\n")
    out: list[Segment] = []
    buf: list[str] = []
    running = 0
    for ln in lines:
        ln_size = len(ln) + 1
        if running + ln_size > budget and buf:
            out.append(Segment(
                kind=seg.kind, content="\n".join(buf), language=seg.language,
                role=seg.role, metadata={**seg.metadata, "split": True},
            ))
            buf = []
            running = 0
        buf.append(ln)
        running += ln_size
    if buf:
        out.append(Segment(
            kind=seg.kind, content="\n".join(buf), language=seg.language,
            role=seg.role, metadata={**seg.metadata, "split": True},
        ))
    return out
