"""Tests for content-type segment preservation."""
from __future__ import annotations

from apps.shail import segments as S


def test_parse_plain_text():
    segs = S.parse_segments("hello world")
    assert len(segs) == 1
    assert segs[0].kind == "markdown"
    assert "hello world" in segs[0].content


def test_parse_code_block_preserves_language():
    raw = "intro\n\n```python\ndef foo():\n    return 1\n```\n\nouter"
    segs = S.parse_segments(raw)
    kinds = [s.kind for s in segs]
    assert "code" in kinds
    code = next(s for s in segs if s.kind == "code")
    assert code.language == "python"
    assert "def foo()" in code.content


def test_parse_mermaid_block_distinct_from_code():
    raw = "```mermaid\ngraph TD; A-->B;\n```"
    segs = S.parse_segments(raw)
    assert len(segs) == 1
    assert segs[0].kind == "mermaid"
    assert segs[0].language == "mermaid"
    assert "A-->B" in segs[0].content


def test_parse_markdown_table_extracts_rows():
    raw = (
        "| Name | Score |\n"
        "| --- | --- |\n"
        "| Alice | 95 |\n"
        "| Bob | 80 |\n"
    )
    segs = S.parse_segments(raw)
    table = next(s for s in segs if s.kind == "table")
    assert table.metadata["headers"] == ["Name", "Score"]
    assert table.metadata["rows"] == [
        {"Name": "Alice", "Score": "95"},
        {"Name": "Bob", "Score": "80"},
    ]
    assert table.metadata["row_count"] == 2


def test_render_for_llm_round_trip_preserves_kinds():
    raw = (
        "intro\n\n"
        "```python\nx = 1\n```\n\n"
        "| a | b |\n| --- | --- |\n| 1 | 2 |\n\n"
        "```mermaid\nflowchart LR\n```\n"
    )
    segs = S.parse_segments(raw)
    rendered = S.render_for_llm(segs)
    assert "```python" in rendered
    assert "x = 1" in rendered
    assert "```mermaid" in rendered
    assert "flowchart LR" in rendered
    # Table should round-trip in pipe form
    assert "| a | b |" in rendered or "a | b" in rendered


def test_segments_to_from_json_round_trip():
    raw = "hello\n\n```js\nlet x;\n```"
    segs = S.parse_segments(raw)
    blob = S.segments_to_json(segs)
    restored = S.segments_from_json(blob)
    assert len(restored) == len(segs)
    assert restored[-1].kind == "code"
    assert restored[-1].language == "js"


def test_slice_by_budget_does_not_split_small_segments():
    segs = [S.Segment(kind="text", content="a" * 100) for _ in range(5)]
    windows = S.slice_segments_by_budget(segs, char_budget=250)
    # 250 budget → 2 segments per window (200 each), then carry overlap.
    assert len(windows) >= 2
    # No segment should be lost.
    total = sum(len(w) for w in windows)
    assert total >= len(segs)  # may be more with overlap


def test_slice_by_budget_splits_oversized_segments_at_line_boundaries():
    big = "line\n" * 1000  # 5000 chars
    seg = S.Segment(kind="text", content=big)
    windows = S.slice_segments_by_budget([seg], char_budget=600)
    assert len(windows) > 1
    # Each window holds exactly one (sub-)segment from the oversized split.
    for w in windows:
        assert len(w) == 1
        assert w[0].kind == "text"


def test_role_attached_segments():
    seg = S.Segment(kind="markdown", content="hi", role="user")
    out = S.render_for_llm([seg])
    assert "[USER]" in out
