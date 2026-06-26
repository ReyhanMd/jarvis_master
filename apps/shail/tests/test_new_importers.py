"""Plan B3 + B4 — Gemini/Grok/Perplexity importers + ChatGPT current_node fix."""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, "/Users/reyhan/shail workspace /shail_master/jarvis_master")


# ── Gemini importer ─────────────────────────────────────────────────────────

class TestGeminiImporter:
    def test_native_format_parses(self):
        from apps.shail.importers import gemini
        payload = json.dumps({
            "conversations": [
                {
                    "id": "g1",
                    "name": "Sample Gemini chat",
                    "createTime": "2026-05-22T10:00:00Z",
                    "messages": [
                        {"role": "user", "text": "what is rust?"},
                        {"role": "model", "text": "Rust is a systems language."},
                        {"role": "user", "text": "ownership?"},
                        {"role": "model", "text": "It's a memory-safety model."},
                    ],
                }
            ]
        })
        out = gemini.parse(payload)
        assert len(out) == 1
        conv = out[0]
        assert conv["title"] == "Sample Gemini chat"
        assert conv["source_id"] == "g1"
        assert len(conv["pairs"]) == 2
        assert "rust" in conv["pairs"][0][0].lower()
        assert "memory-safety" in conv["pairs"][1][1]

    def test_takeout_my_activity_format(self):
        from apps.shail.importers import gemini
        payload = json.dumps([
            {"title": "Said \"hello gemini\"", "header": "Gemini",
             "time": "2026-05-22T10:00:00Z"},
            {"title": "Hi there, how can I help?", "header": "Gemini Apps",
             "time": "2026-05-22T10:00:05Z"},
        ])
        out = gemini.parse(payload)
        assert len(out) == 1
        assert out[0]["pairs"][0][0] == "hello gemini"

    def test_empty_returns_empty(self):
        from apps.shail.importers import gemini
        assert gemini.parse("[]") == []
        assert gemini.parse('{"conversations": []}') == []


# ── Grok importer ───────────────────────────────────────────────────────────

class TestGrokImporter:
    def test_json_format(self):
        from apps.shail.importers import grok
        payload = json.dumps({
            "conversations": [
                {"id": "x1", "title": "Grok chat",
                 "messages": [
                     {"role": "user", "text": "explain transformers"},
                     {"role": "assistant", "text": "Self-attention layers..."},
                 ]}
            ]
        })
        out = grok.parse(payload)
        assert len(out) == 1
        assert out[0]["pairs"][0][0] == "explain transformers"

    def test_html_save_page(self):
        """Grok DOM has 'You' / 'Grok' prefix lines for turn markers."""
        from apps.shail.importers import grok
        html = """
        <html><body>
          <main>
            <div>You: what is dark matter?</div>
            <div>Grok: It's matter that doesn't interact with light.</div>
            <div>You: how much exists?</div>
            <div>Grok: About 85% of all matter.</div>
          </main>
        </body></html>
        """
        out = grok.parse(html)
        assert len(out) == 1
        # 2 turn pairs expected
        assert len(out[0]["pairs"]) >= 1
        joined_users = " ".join(p[0] for p in out[0]["pairs"])
        assert "dark matter" in joined_users.lower()

    def test_unstructured_html_keeps_as_context(self):
        """No You/Grok markers → single context turn rather than dropping."""
        from apps.shail.importers import grok
        html = "<html><body><p>just some plain text without markers</p></body></html>"
        out = grok.parse(html)
        assert len(out) == 1
        # Pair stored with empty user and the full text as assistant context
        assert out[0]["pairs"][0][1].strip() != ""


# ── Perplexity importer ─────────────────────────────────────────────────────

class TestPerplexityImporter:
    def test_single_thread(self):
        from apps.shail.importers import perplexity
        payload = json.dumps({
            "thread_id": "t1",
            "title": "Quantum computing",
            "turns": [
                {"query": "what is qubit?",
                 "answer": "A two-level quantum system.",
                 "sources": [{"url": "https://wiki/qubit", "title": "Qubit (wiki)"}]},
            ]
        })
        out = perplexity.parse(payload)
        assert len(out) == 1
        conv = out[0]
        assert conv["title"] == "Quantum computing"
        assert conv["source_id"] == "t1"
        assert len(conv["pairs"]) == 1
        # Source URL must be inlined into assistant text
        assert "wiki/qubit" in conv["pairs"][0][1]

    def test_bulk_export(self):
        from apps.shail.importers import perplexity
        payload = json.dumps({
            "threads": [
                {"thread_id": "t1", "title": "A",
                 "turns": [{"query": "q1", "answer": "a1"}]},
                {"thread_id": "t2", "title": "B",
                 "turns": [{"query": "q2", "answer": "a2"}]},
            ]
        })
        out = perplexity.parse(payload)
        assert len(out) == 2
        assert {c["title"] for c in out} == {"A", "B"}


# ── ChatGPT branch resolution (B4) ──────────────────────────────────────────

class TestChatGPTBranchResolution:
    def _branched_mapping(self):
        """Build a ChatGPT export with a regenerated branch.

        root → u1 → a1 → u2 → a2(original)
                                  → a2_regen(alternate)
        Current node points to a2_regen — we expect only the regenerated
        branch in the linear path (a1 → u2 → a2_regen), NOT a2.
        """
        return {
            "title": "Branched conv",
            "id": "conv1",
            "current_node": "a2_regen",
            "mapping": {
                "root": {"message": None, "parent": None, "children": ["u1"]},
                "u1": {
                    "message": {"id": "u1", "author": {"role": "user"},
                                "content": {"parts": ["first user msg"]}, "create_time": 1.0},
                    "parent": "root", "children": ["a1"],
                },
                "a1": {
                    "message": {"id": "a1", "author": {"role": "assistant"},
                                "content": {"parts": ["first reply"]}, "create_time": 2.0},
                    "parent": "u1", "children": ["u2"],
                },
                "u2": {
                    "message": {"id": "u2", "author": {"role": "user"},
                                "content": {"parts": ["second user msg"]}, "create_time": 3.0},
                    "parent": "a1", "children": ["a2_original", "a2_regen"],
                },
                "a2_original": {
                    "message": {"id": "a2_original", "author": {"role": "assistant"},
                                "content": {"parts": ["original reply (should be excluded)"]},
                                "create_time": 4.0},
                    "parent": "u2", "children": [],
                },
                "a2_regen": {
                    "message": {"id": "a2_regen", "author": {"role": "assistant"},
                                "content": {"parts": ["regenerated reply (should be included)"]},
                                "create_time": 5.0},
                    "parent": "u2", "children": [],
                },
            },
        }

    def test_current_node_excludes_alternate_branch(self):
        from apps.shail.importers import chatgpt
        payload = json.dumps([self._branched_mapping()])
        out = chatgpt.parse(payload)
        assert len(out) == 1
        # Collect all assistant texts that landed in pairs
        assistant_texts = " ".join(p[1] for p in out[0]["pairs"])
        assert "regenerated reply" in assistant_texts
        assert "original reply" not in assistant_texts, (
            "BFS leaked the regenerated alternate branch into the linear transcript"
        )

    def test_missing_current_node_falls_back_to_bfs(self):
        """Legacy exports without current_node should still parse via BFS."""
        from apps.shail.importers import chatgpt
        mapping = self._branched_mapping()
        del mapping["current_node"]
        out = chatgpt.parse(json.dumps([mapping]))
        # Both branches will be present in the BFS fallback — that's the
        # documented behavior when we don't have a current_node pointer.
        assert len(out) == 1
        joined = " ".join(p[1] for p in out[0]["pairs"])
        # At least one of them should be present
        assert "reply" in joined

    def test_simple_linear_conversation(self):
        """Non-branched ChatGPT export still works correctly."""
        from apps.shail.importers import chatgpt
        mapping = {
            "title": "Simple",
            "id": "c1",
            "current_node": "a1",
            "mapping": {
                "root": {"message": None, "parent": None, "children": ["u1"]},
                "u1": {"message": {"id": "u1", "author": {"role": "user"},
                                    "content": {"parts": ["hi"]}, "create_time": 1.0},
                       "parent": "root", "children": ["a1"]},
                "a1": {"message": {"id": "a1", "author": {"role": "assistant"},
                                    "content": {"parts": ["hello"]}, "create_time": 2.0},
                       "parent": "u1", "children": []},
            },
        }
        out = chatgpt.parse(json.dumps([mapping]))
        assert len(out) == 1
        assert out[0]["pairs"] == [("hi", "hello")]


# ── PARSERS registry ────────────────────────────────────────────────────────

class TestImporterRegistry:
    def test_new_parsers_registered(self):
        from apps.shail.importers import PARSERS
        for k in ("chatgpt", "claude", "cursor", "gemini", "grok", "perplexity"):
            assert k in PARSERS, f"importer not registered: {k}"
            assert callable(PARSERS[k])
