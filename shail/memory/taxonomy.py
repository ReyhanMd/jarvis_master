"""Hierarchical Taxonomy Engine (Phase 7).

Classifies memory entries into structured tags before ingestion.
Tags are hierarchical — child tags expand to include inherited parent tags.

Usage:
    from shail.memory.taxonomy import get_taxonomy
    tags = get_taxonomy().classify_content(content, agent_type="code", mode="code", project="shail")
    # → ["project:shail", "org:reyhan", "domain:agentic", "domain:backend", "memory_type:execution"]
"""
from __future__ import annotations

import json
import logging
import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Set

logger = logging.getLogger(__name__)


class TaxonomyClassifier:
    """Load taxonomy.json and classify content/context into tag lists."""

    def __init__(self, config_path: Optional[str] = None) -> None:
        self._config: Dict[str, Any] = {}
        self._ext_map: Dict[str, str] = {}        # ".py" → "domain:backend"
        self._kw_map: Dict[str, str] = {}         # "langgraph" → "domain:agentic"
        self._agent_map: Dict[str, str] = {}      # "code" → "memory_type:execution"
        self._mode_map: Dict[str, str] = {}       # "code" → "mode:code"
        self._project_map: Dict[str, List[str]] = {}  # "shail" → [...]
        self._inheritance: Dict[str, List[str]] = {}  # "domain:agentic" → ["domain:backend"]
        self._status_map: Dict[str, str] = {}

        # Custom rules: (compiled pattern, tags)
        self._custom_rules: List[tuple] = []

        if config_path:
            self.load_config(config_path)
        else:
            self._load_default()

    # ------------------------------------------------------------------ #
    # Config loading                                                        #
    # ------------------------------------------------------------------ #

    def load_config(self, path: str) -> None:
        """Load taxonomy config from JSON file."""
        p = Path(path).expanduser()
        if not p.exists():
            logger.warning("taxonomy.json not found at %s — using built-in defaults", p)
            self._load_default()
            return
        try:
            self._config = json.loads(p.read_text("utf-8"))
            self._parse_config()
            logger.debug("Taxonomy loaded from %s", p)
        except Exception as exc:
            logger.error("Failed to load taxonomy config: %s — using defaults", exc)
            self._load_default()

    def _load_default(self) -> None:
        """Load from taxonomy.json adjacent to this file."""
        default = Path(__file__).parent / "taxonomy.json"
        if default.exists():
            try:
                self._config = json.loads(default.read_text("utf-8"))
                self._parse_config()
                return
            except Exception as exc:
                logger.debug("Default taxonomy load failed: %s", exc)
        # Hard-coded minimal fallback
        self._config = {}
        self._parse_config()

    def _parse_config(self) -> None:
        domains = self._config.get("domains", {})
        exts = domains.get("extensions", {})
        self._ext_map = {f".{k}": v for k, v in exts.items()}

        kws = domains.get("keywords", {})
        self._kw_map = {k.lower(): v for k, v in kws.items()}

        self._agent_map = {k.lower(): v for k, v in self._config.get("agent_types", {}).items()}
        self._mode_map  = {k.lower(): v for k, v in self._config.get("task_modes", {}).items()}

        raw_proj = self._config.get("projects", {})
        self._project_map = {k.lower(): (v if isinstance(v, list) else [v]) for k, v in raw_proj.items()}

        self._inheritance = {k: (v if isinstance(v, list) else [v])
                             for k, v in self._config.get("inheritance", {}).items()}

        self._status_map = {k.lower(): v for k, v in self._config.get("status_tags", {}).items()}

    # ------------------------------------------------------------------ #
    # Public API                                                            #
    # ------------------------------------------------------------------ #

    def add_rule(self, pattern: str, tags: List[str]) -> None:
        """Add a custom regex pattern → tag list rule."""
        try:
            self._custom_rules.append((re.compile(pattern, re.IGNORECASE), tags))
        except re.error as exc:
            logger.warning("Invalid taxonomy rule pattern %r: %s", pattern, exc)

    def classify(self, result: Any, request: Any) -> List[str]:
        """Classify a TaskResult + TaskRequest into tags.

        Accepts any object with attributes; missing attributes silently skipped.
        Returns deduplicated, inheritance-expanded tag list.
        """
        raw: Set[str] = set()

        # Agent type
        agent_type = getattr(request, "agent_type", None) or getattr(result, "generated_by", None)
        if agent_type:
            raw.update(self._tags_for_agent(str(agent_type)))

        # Task mode
        mode = getattr(request, "mode", None)
        if mode:
            raw.update(self._tags_for_mode(str(mode)))

        # Project/namespace
        ns = getattr(request, "namespace", None) or getattr(request, "project", None)
        if ns:
            raw.update(self._tags_for_project(str(ns)))

        # Content keyword scan
        content = (
            getattr(result, "summary", "")
            or getattr(result, "content", "")
            or getattr(result, "output", "")
            or ""
        )
        if content:
            raw.update(self._tags_for_content(str(content)))

        # File artifacts — infer domain from extension
        artifacts = getattr(result, "artifacts", None) or []
        for artifact in artifacts:
            path_str = str(getattr(artifact, "path", artifact) if not isinstance(artifact, str) else artifact)
            ext = Path(path_str).suffix.lower()
            tag = self._ext_map.get(ext)
            if tag:
                raw.add(tag)

        # Status
        status = getattr(result, "status", None)
        if status:
            st = self._status_map.get(str(status).lower())
            if st:
                raw.add(st)

        # Custom rules against full content
        text_blob = f"{content} {agent_type or ''} {mode or ''} {ns or ''}".lower()
        for pattern, tags in self._custom_rules:
            if pattern.search(text_blob):
                raw.update(tags)

        return self._expand_inheritance(raw)

    def classify_content(
        self,
        content: str,
        *,
        agent_type: Optional[str] = None,
        mode: Optional[str] = None,
        project: Optional[str] = None,
        status: Optional[str] = None,
        artifact_paths: Optional[List[str]] = None,
    ) -> List[str]:
        """Simpler interface when you have raw strings instead of typed objects."""
        raw: Set[str] = set()

        if agent_type:
            raw.update(self._tags_for_agent(agent_type))
        if mode:
            raw.update(self._tags_for_mode(mode))
        if project:
            raw.update(self._tags_for_project(project))
        if content:
            raw.update(self._tags_for_content(content))
        if status:
            st = self._status_map.get(status.lower())
            if st:
                raw.add(st)
        for path_str in (artifact_paths or []):
            ext = Path(path_str).suffix.lower()
            tag = self._ext_map.get(ext)
            if tag:
                raw.add(tag)

        text_blob = f"{content} {agent_type or ''} {mode or ''} {project or ''}".lower()
        for pattern, tags in self._custom_rules:
            if pattern.search(text_blob):
                raw.update(tags)

        return self._expand_inheritance(raw)

    # ------------------------------------------------------------------ #
    # Internal helpers                                                      #
    # ------------------------------------------------------------------ #

    def _tags_for_agent(self, agent_type: str) -> List[str]:
        tag = self._agent_map.get(agent_type.lower())
        return [tag] if tag else []

    def _tags_for_mode(self, mode: str) -> List[str]:
        tag = self._mode_map.get(mode.lower())
        return [tag] if tag else []

    def _tags_for_project(self, project: str) -> List[str]:
        key = project.lower()
        # Exact match first, then substring scan
        if key in self._project_map:
            return list(self._project_map[key])
        for proj_key, tags in self._project_map.items():
            if proj_key in key or key in proj_key:
                return list(tags)
        return []

    def _tags_for_content(self, content: str) -> List[str]:
        lower = content.lower()
        tags: List[str] = []
        for kw, tag in self._kw_map.items():
            if kw in lower:
                tags.append(tag)
        return tags

    def _expand_inheritance(self, raw: Set[str]) -> List[str]:
        """Expand tags via inheritance graph (BFS, cycle-safe)."""
        expanded: Set[str] = set(raw)
        frontier = list(raw)
        while frontier:
            tag = frontier.pop()
            parents = self._inheritance.get(tag, [])
            for p in parents:
                if p not in expanded:
                    expanded.add(p)
                    frontier.append(p)
        # Deterministic, deduplicated output
        return sorted(expanded)


# ── Singleton ─────────────────────────────────────────────────────────── #

_classifier: Optional[TaxonomyClassifier] = None


def get_taxonomy() -> TaxonomyClassifier:
    global _classifier
    if _classifier is None:
        from apps.shail.settings import get_settings
        s = get_settings()
        if s.taxonomy_enabled and s.taxonomy_config_path:
            _classifier = TaxonomyClassifier(s.taxonomy_config_path)
        else:
            _classifier = TaxonomyClassifier()
    return _classifier


def reset_taxonomy() -> None:
    """Force reload (useful after config change in tests)."""
    global _classifier
    _classifier = None
