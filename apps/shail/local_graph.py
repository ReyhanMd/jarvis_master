"""Deterministic local-file knowledge graph for SHAIL Graphify.

This is SHAIL-specific Graphify: it builds a graph from approved path_index rows
only. It is derived state, pointer-first, and can be rebuilt at any time.
"""
from __future__ import annotations

import json
import os
import re
import sqlite3
import time
import unicodedata
from pathlib import Path
from typing import Any, Iterable, Optional

from apps.shail.settings import get_settings
from apps.shail import local_semantics
from apps.shail import local_semantic_reasoning
from shail.memory import path_index

CONF_EXTRACTED = "EXTRACTED"
CONF_INFERRED = "INFERRED"

_STOPWORDS = {
    "and", "the", "for", "with", "from", "this", "that", "your", "you",
    "file", "files", "final", "copy", "draft", "new", "old", "data",
    "notes", "note", "doc", "docs", "document", "project", "report",
}

_VERSION_RE = re.compile(
    r"(?i)(?:^|[_\-\s.])(?:v(?:ersion)?\s*\d+|final|draft|copy|\d{4}[-_.]\d{1,2}[-_.]\d{1,2})(?:$|[_\-\s.])"
)
_TOKEN_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{2,}")
_DOMAIN_RE = re.compile(r"\b[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}\b")
_ENTITY_RE = re.compile(r"\b[A-Z][A-Za-z0-9&.-]*(?:\s+[A-Z][A-Za-z0-9&.-]*){0,3}\b")


def _graph_db_path() -> str:
    return getattr(get_settings(), "sqlite_path", "") or get_settings().path_index_db


def _conn(db_path: Optional[str] = None) -> sqlite3.Connection:
    path = Path(db_path or _graph_db_path()).expanduser()
    path.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(str(path))
    con.row_factory = sqlite3.Row
    _ensure_schema(con)
    return con


def _ensure_schema(con: sqlite3.Connection) -> None:
    con.executescript(
        """
        CREATE TABLE IF NOT EXISTS local_graph_nodes (
            id TEXT PRIMARY KEY,
            type TEXT NOT NULL,
            label TEXT NOT NULL,
            uri TEXT,
            source_path TEXT,
            privacy_state TEXT NOT NULL DEFAULT 'allowed',
            metadata_json TEXT NOT NULL DEFAULT '{}',
            updated_at REAL NOT NULL
        );
        CREATE TABLE IF NOT EXISTS local_graph_edges (
            source_id TEXT NOT NULL,
            target_id TEXT NOT NULL,
            relation TEXT NOT NULL,
            weight REAL NOT NULL DEFAULT 1.0,
            confidence TEXT NOT NULL DEFAULT 'INFERRED',
            evidence TEXT,
            source_path TEXT,
            updated_at REAL NOT NULL,
            PRIMARY KEY (source_id, target_id, relation)
        );
        CREATE TABLE IF NOT EXISTS local_graph_build_runs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            started_at REAL NOT NULL,
            completed_at REAL,
            source_count INTEGER NOT NULL DEFAULT 0,
            node_count INTEGER NOT NULL DEFAULT 0,
            edge_count INTEGER NOT NULL DEFAULT 0,
            status TEXT NOT NULL,
            error TEXT
        );
        CREATE INDEX IF NOT EXISTS idx_local_graph_nodes_type ON local_graph_nodes(type);
        CREATE INDEX IF NOT EXISTS idx_local_graph_edges_source ON local_graph_edges(source_id);
        CREATE INDEX IF NOT EXISTS idx_local_graph_edges_target ON local_graph_edges(target_id);
        CREATE INDEX IF NOT EXISTS idx_local_graph_edges_relation ON local_graph_edges(relation);
        """
    )
    con.commit()


def normalize_id(value: str) -> str:
    value = unicodedata.normalize("NFKC", value or "")
    value = re.sub(r"[^\w]+", "_", value, flags=re.UNICODE)
    value = re.sub(r"_+", "_", value)
    return value.strip("_").casefold() or "unknown"


def _node_id(kind: str, value: str) -> str:
    return f"{kind}:{normalize_id(value)}"


def _clean_label(value: str, *, limit: int = 180) -> str:
    value = re.sub(r"[\x00-\x1f\x7f]+", " ", value or "")
    value = re.sub(r"\s+", " ", value).strip()
    return value[:limit] or "Untitled"


def _add_node(nodes: dict[str, dict[str, Any]], node: dict[str, Any]) -> None:
    node["label"] = _clean_label(str(node.get("label") or node.get("id") or "Untitled"))
    node.setdefault("privacy_state", "allowed")
    node.setdefault("metadata", {})
    nodes[node["id"]] = node


def _add_edge(edges: dict[tuple[str, str, str], dict[str, Any]], edge: dict[str, Any]) -> None:
    key = (edge["source_id"], edge["target_id"], edge["relation"])
    existing = edges.get(key)
    if existing and existing.get("confidence") == CONF_EXTRACTED:
        return
    edge.setdefault("weight", 1.0)
    edge.setdefault("confidence", CONF_INFERRED)
    edges[key] = edge


def _row_dict(row: sqlite3.Row | dict[str, Any]) -> dict[str, Any]:
    return dict(row)


def _allowed_rows(path_db: str, *, limit: int) -> list[dict[str, Any]]:
    with path_index._conn(path_db) as con:  # path_index owns schema migrations.
        rows = con.execute(
            """
            SELECT * FROM path_index
            WHERE deleted_at IS NULL
            ORDER BY is_dir DESC, path
            LIMIT ?
            """,
            (limit,),
        ).fetchall()
    out: list[dict[str, Any]] = []
    for row in rows:
        d = _row_dict(row)
        if path_index.is_denied(path_db, d.get("path") or ""):
            continue
        out.append(d)
    return out


def _folder_id(path: str) -> str:
    return _node_id("folder", str(Path(path).expanduser()))


def _project_id(path: str) -> str:
    return _node_id("project", str(Path(path).expanduser()))


def _file_node(row: dict[str, Any]) -> dict[str, Any]:
    path = row.get("path") or ""
    return {
        "id": row.get("id") or _node_id("file", path),
        "type": "local_file",
        "label": row.get("title") or Path(path).name,
        "uri": path,
        "source_path": path,
        "metadata": {
            "file_type": row.get("file_type"),
            "kind": row.get("kind"),
            "size_bytes": row.get("size_bytes"),
            "mtime": row.get("mtime"),
            "content_hash": row.get("content_hash"),
            "pointer_first": True,
        },
    }


def _folder_node(path: str, row: Optional[dict[str, Any]] = None) -> dict[str, Any]:
    return {
        "id": _folder_id(path),
        "type": "folder",
        "label": Path(path).name or path,
        "uri": path,
        "source_path": path,
        "metadata": {"child_count": (row or {}).get("child_count")},
    }


def _active_roots(path_db: str, env_roots: Optional[list[str]] = None) -> list[str]:
    try:
        return path_index.get_active_scan_roots(path_db, env_roots=env_roots or get_settings().scan_roots)
    except Exception:
        return path_index.get_persisted_roots(path_db)


def _best_project_root(path: str, roots: list[str]) -> Optional[str]:
    try:
        candidate = Path(path).expanduser().resolve()
    except Exception:
        return None
    matches = []
    for root in roots:
        try:
            r = Path(root).expanduser().resolve()
            if candidate == r or candidate.is_relative_to(r):
                matches.append(str(r))
        except Exception:
            continue
    if not matches:
        return None
    return max(matches, key=len)


def _terms_from(row: dict[str, Any], *, max_terms: int = 8) -> list[str]:
    text = " ".join(
        str(row.get(k) or "")
        for k in ("title", "file_name", "kind", "file_type", "summary_snippet", "path")
    )
    terms: list[str] = []
    for token in _TOKEN_RE.findall(text):
        low = token.lower().strip("._-")
        if len(low) < 3 or low in _STOPWORDS:
            continue
        if low.isdigit():
            continue
        if low not in terms:
            terms.append(low)
        if len(terms) >= max_terms:
            break
    return terms


def _entities_from(row: dict[str, Any], *, max_entities: int = 8) -> list[str]:
    text = " ".join(str(row.get(k) or "") for k in ("title", "file_name", "summary_snippet"))
    found: list[str] = []
    for pattern in (_DOMAIN_RE, _ENTITY_RE):
        for match in pattern.findall(text):
            value = _clean_label(str(match), limit=80)
            if len(value) < 3 or value.lower() in _STOPWORDS:
                continue
            if value not in found:
                found.append(value)
            if len(found) >= max_entities:
                return found
    return found


def _version_key(row: dict[str, Any]) -> str:
    path = Path(row.get("path") or "")
    stem = _VERSION_RE.sub("_", path.stem)
    stem = re.sub(r"[_\-\s.]+", "_", stem).strip("_").lower() or path.stem.lower()
    return f"{path.parent}:{stem}:{path.suffix.lower()}"


def _version_rank(row: dict[str, Any]) -> tuple[int, float]:
    name = str(row.get("file_name") or row.get("title") or "")
    nums = [int(x) for x in re.findall(r"(?i)(?:v|version)[_\-\s.]*(\d+)", name)]
    version = max(nums) if nums else 0
    return version, float(row.get("mtime") or 0.0)


def build_local_file_graph(
    *,
    path_db: Optional[str] = None,
    graph_db: Optional[str] = None,
    limit: int = 1000,
    env_roots: Optional[list[str]] = None,
) -> dict[str, Any]:
    path_db = path_db or get_settings().path_index_db
    started = time.time()
    rows = _allowed_rows(path_db, limit=limit)
    roots = _active_roots(path_db, env_roots=env_roots)
    nodes: dict[str, dict[str, Any]] = {}
    edges: dict[tuple[str, str, str], dict[str, Any]] = {}

    files = [r for r in rows if not r.get("is_dir")]
    folders = [r for r in rows if r.get("is_dir")]

    for row in folders:
        _add_node(nodes, _folder_node(row.get("path") or "", row))

    for root in roots:
        _add_node(nodes, {
            "id": _project_id(root),
            "type": "project",
            "label": Path(root).name or root,
            "uri": root,
            "source_path": root,
            "metadata": {"root_path": root},
        })

    by_parent: dict[str, list[dict[str, Any]]] = {}
    by_hash: dict[str, list[dict[str, Any]]] = {}
    by_version: dict[str, list[dict[str, Any]]] = {}

    for row in files:
        path = row.get("path") or ""
        file_node = _file_node(row)
        _add_node(nodes, file_node)

        parent = str(Path(path).parent)
        _add_node(nodes, _folder_node(parent))
        _add_edge(edges, {
            "source_id": _folder_id(parent),
            "target_id": file_node["id"],
            "relation": "contains",
            "confidence": CONF_EXTRACTED,
            "weight": 1.0,
            "evidence": "parent_path",
            "source_path": path,
        })
        by_parent.setdefault(parent, []).append(row)

        project_root = _best_project_root(path, roots)
        if project_root:
            _add_node(nodes, {
                "id": _project_id(project_root),
                "type": "project",
                "label": Path(project_root).name or project_root,
                "uri": project_root,
                "source_path": project_root,
                "metadata": {"root_path": project_root},
            })
            _add_edge(edges, {
                "source_id": _project_id(project_root),
                "target_id": file_node["id"],
                "relation": "belongs_to_project",
                "confidence": CONF_EXTRACTED,
                "weight": 0.95,
                "evidence": project_root,
                "source_path": path,
            })

        for term in _terms_from(row):
            tid = _node_id("topic", term)
            _add_node(nodes, {"id": tid, "type": "topic", "label": term, "metadata": {}})
            _add_edge(edges, {
                "source_id": file_node["id"],
                "target_id": tid,
                "relation": "has_topic",
                "confidence": CONF_INFERRED,
                "weight": 0.65,
                "evidence": term,
                "source_path": path,
            })

        for entity in _entities_from(row):
            eid = _node_id("entity", entity)
            _add_node(nodes, {"id": eid, "type": "entity", "label": entity, "metadata": {}})
            _add_edge(edges, {
                "source_id": file_node["id"],
                "target_id": eid,
                "relation": "mentions_entity",
                "confidence": CONF_INFERRED,
                "weight": 0.7,
                "evidence": entity,
                "source_path": path,
            })

        content_hash = row.get("content_hash")
        if content_hash:
            by_hash.setdefault(str(content_hash), []).append(row)
            hid = _node_id("content_hash", str(content_hash))
            _add_node(nodes, {
                "id": hid,
                "type": "content_hash",
                "label": str(content_hash)[:18],
                "metadata": {"content_hash": content_hash},
            })
            _add_edge(edges, {
                "source_id": file_node["id"],
                "target_id": hid,
                "relation": "has_content_hash",
                "confidence": CONF_EXTRACTED,
                "weight": 1.0,
                "evidence": str(content_hash),
                "source_path": path,
            })

        by_version.setdefault(_version_key(row), []).append(row)

    for parent, group in by_parent.items():
        if len(group) < 2:
            continue
        group = sorted(group, key=lambda r: str(r.get("path") or ""))
        for prev, cur in zip(group, group[1:]):
            _add_edge(edges, {
                "source_id": prev.get("id"),
                "target_id": cur.get("id"),
                "relation": "nearby_in_folder",
                "confidence": CONF_INFERRED,
                "weight": 0.35,
                "evidence": parent,
                "source_path": cur.get("path"),
            })

    for content_hash, group in by_hash.items():
        if len(group) < 2:
            continue
        for i, left in enumerate(group):
            for right in group[i + 1:]:
                _add_edge(edges, {
                    "source_id": left.get("id"),
                    "target_id": right.get("id"),
                    "relation": "same_content_as",
                    "confidence": CONF_EXTRACTED,
                    "weight": 1.0,
                    "evidence": content_hash,
                    "source_path": left.get("path"),
                })

    for key, group in by_version.items():
        if len(group) < 2:
            continue
        vid = _node_id("file_version_group", key)
        _add_node(nodes, {
            "id": vid,
            "type": "file_version_group",
            "label": Path(key.split(":")[0]).name + " versions",
            "metadata": {"version_key": key},
        })
        ordered = sorted(group, key=_version_rank)
        for row in ordered:
            _add_edge(edges, {
                "source_id": row.get("id"),
                "target_id": vid,
                "relation": "version_of",
                "confidence": CONF_INFERRED,
                "weight": 0.75,
                "evidence": Path(row.get("path") or "").name,
                "source_path": row.get("path"),
            })
        for older, newer in zip(ordered, ordered[1:]):
            _add_edge(edges, {
                "source_id": newer.get("id"),
                "target_id": older.get("id"),
                "relation": "newer_than",
                "confidence": CONF_INFERRED,
                "weight": 0.8,
                "evidence": "filename version or modified time",
                "source_path": newer.get("path"),
            })

    _add_semantic_graph(nodes, edges, {r.get("id") for r in files if r.get("id")})
    _add_reasoning_graph(nodes, edges, {r.get("id") for r in files if r.get("id")})

    node_list = list(nodes.values())
    edge_list = list(edges.values())
    _persist_graph(node_list, edge_list, graph_db=graph_db, started=started, source_count=len(rows))
    return {"nodes": node_list, "relations": edge_list, "source_count": len(rows)}


def _semantic_node_type_for_fact(fact: dict[str, Any]) -> tuple[str, str]:
    attr = (fact.get("attribute") or "").lower()
    unit = fact.get("unit")
    if attr == "decision":
        return "decision", "has_decision"
    if attr == "section":
        return "document_section", "appears_in_section"
    if attr == "date":
        return "date", "has_date"
    if unit == "%":
        return "percent_value", "has_metric"
    if unit in {"USD", "INR", "AED", "EUR", "GBP"}:
        return "money_value", "has_metric"
    if unit or fact.get("value_num") is not None:
        return "metric", "has_metric"
    return "fact", "states_fact"


def _add_semantic_graph(
    nodes: dict[str, dict[str, Any]],
    edges: dict[tuple[str, str, str], dict[str, Any]],
    active_file_ids: set[str],
) -> None:
    try:
        semantic = local_semantics.search("", limit=1000)
    except Exception:
        return

    for entity in semantic.get("entities") or []:
        fid = entity.get("file_id")
        if fid not in active_file_ids:
            continue
        etype = entity.get("entity_type") or "entity"
        node_type = "organization" if etype == "organization" else "person" if etype == "person" else "entity"
        nid = _node_id(node_type, entity.get("label") or "")
        _add_node(nodes, {
            "id": nid,
            "type": node_type,
            "label": entity.get("label") or "Untitled",
            "uri": entity.get("path"),
            "source_path": entity.get("path"),
            "metadata": {
                "source_span": entity.get("source_span"),
                "confidence": entity.get("confidence"),
            },
        })
        _add_edge(edges, {
            "source_id": fid,
            "target_id": nid,
            "relation": "mentions_organization" if node_type == "organization" else "mentions_person",
            "confidence": entity.get("confidence") or CONF_INFERRED,
            "weight": 0.78,
            "evidence": entity.get("source_span") or entity.get("label"),
            "source_path": entity.get("path"),
        })

    for fact in semantic.get("facts") or []:
        fid = fact.get("file_id")
        if fid not in active_file_ids:
            continue
        node_type, relation = _semantic_node_type_for_fact(fact)
        label = " ".join(str(fact.get(k) or "") for k in ("entity", "attribute", "value")).strip()
        nid = _node_id(node_type, label or fact.get("id") or "")
        _add_node(nodes, {
            "id": nid,
            "type": node_type,
            "label": label or fact.get("value") or "Fact",
            "uri": fact.get("path"),
            "source_path": fact.get("path"),
            "metadata": {
                "semantic_id": fact.get("id"),
                "entity": fact.get("entity"),
                "attribute": fact.get("attribute"),
                "value": fact.get("value"),
                "value_num": fact.get("value_num"),
                "unit": fact.get("unit"),
                "period": fact.get("period"),
                "source_span": fact.get("source_span"),
                "confidence": fact.get("confidence"),
            },
        })
        _add_edge(edges, {
            "source_id": fid,
            "target_id": nid,
            "relation": relation,
            "confidence": fact.get("confidence") or CONF_EXTRACTED,
            "weight": 0.86 if relation in {"states_fact", "has_metric", "has_decision"} else 0.72,
            "evidence": fact.get("source_span") or fact.get("value"),
            "source_path": fact.get("path"),
        })

    for task in semantic.get("tasks") or []:
        fid = task.get("file_id")
        if fid not in active_file_ids:
            continue
        nid = _node_id("task", task.get("text") or task.get("id") or "")
        _add_node(nodes, {
            "id": nid,
            "type": "task",
            "label": task.get("text") or "Task",
            "uri": task.get("path"),
            "source_path": task.get("path"),
            "metadata": {
                "semantic_id": task.get("id"),
                "status": task.get("status"),
                "due_date": task.get("due_date"),
                "source_span": task.get("source_span"),
                "confidence": task.get("confidence"),
            },
        })
        _add_edge(edges, {
            "source_id": fid,
            "target_id": nid,
            "relation": "has_task",
            "confidence": task.get("confidence") or CONF_EXTRACTED,
            "weight": 0.82,
            "evidence": task.get("source_span") or task.get("text"),
            "source_path": task.get("path"),
        })


def _add_reasoning_graph(
    nodes: dict[str, dict[str, Any]],
    edges: dict[tuple[str, str, str], dict[str, Any]],
    active_file_ids: set[str],
) -> None:
    try:
        reasoning = local_semantic_reasoning.search("", limit=1000)
    except Exception:
        return
    for group in reasoning.get("items") or []:
        claims = [group.get("preferred_claim"), *(group.get("competing_claims") or [])]
        claims = [c for c in claims if c and c.get("file_id") in active_file_ids]
        if not claims:
            continue
        gid = f"fact_group:{normalize_id(group.get('group_id') or group.get('label') or '')}"
        _add_node(nodes, {
            "id": gid,
            "type": "fact_group",
            "label": group.get("label") or "Resolved fact",
            "metadata": {
                "group_id": group.get("group_id"),
                "status": group.get("status"),
                "confidence": group.get("confidence"),
                "reason": group.get("reason"),
                "warnings": group.get("warnings") or [],
            },
        })
        preferred = group.get("preferred_claim") or {}
        preferred_id = preferred.get("claim_id")
        if preferred.get("file_id") in active_file_ids:
            _add_edge(edges, {
                "source_id": preferred.get("file_id"),
                "target_id": gid,
                "relation": "supports_answer",
                "confidence": CONF_EXTRACTED if group.get("confidence") in {"high", "medium"} else CONF_INFERRED,
                "weight": 0.9 if group.get("confidence") == "high" else 0.74,
                "evidence": group.get("reason") or preferred.get("source_span"),
                "source_path": preferred.get("path"),
            })
        for claim in claims:
            fid = claim.get("file_id")
            if fid not in active_file_ids or claim.get("claim_id") == preferred_id:
                continue
            relation = "same_claim_as" if claim.get("value_norm") == preferred.get("value_norm") else "contradicts"
            _add_edge(edges, {
                "source_id": fid,
                "target_id": gid,
                "relation": relation,
                "confidence": claim.get("confidence") or CONF_INFERRED,
                "weight": 0.7 if relation == "same_claim_as" else 0.82,
                "evidence": claim.get("source_span") or claim.get("value"),
                "source_path": claim.get("path"),
            })
            if relation == "contradicts" and preferred.get("file_id") in active_file_ids:
                _add_edge(edges, {
                    "source_id": preferred.get("file_id"),
                    "target_id": fid,
                    "relation": "supersedes",
                    "confidence": CONF_INFERRED,
                    "weight": 0.62,
                    "evidence": group.get("reason"),
                    "source_path": preferred.get("path"),
                })


def _persist_graph(
    nodes: list[dict[str, Any]],
    edges: list[dict[str, Any]],
    *,
    graph_db: Optional[str],
    started: float,
    source_count: int,
) -> None:
    now = time.time()
    with _conn(graph_db) as con:
        run = con.execute(
            "INSERT INTO local_graph_build_runs (started_at, status, source_count) VALUES (?, 'running', ?)",
            (started, source_count),
        )
        run_id = run.lastrowid
        con.execute("DELETE FROM local_graph_nodes")
        con.execute("DELETE FROM local_graph_edges")
        node_tuples = [
            (
                node["id"], node["type"], node["label"], node.get("uri"),
                node.get("source_path"), node.get("privacy_state", "allowed"),
                json.dumps(node.get("metadata") or {}), now
            )
            for node in nodes
        ]
        con.executemany(
            """INSERT INTO local_graph_nodes
               (id, type, label, uri, source_path, privacy_state, metadata_json, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            node_tuples
        )

        edge_tuples = [
            (
                edge["source_id"], edge["target_id"], edge["relation"],
                float(edge.get("weight", 1.0)), edge.get("confidence", CONF_INFERRED),
                edge.get("evidence"), edge.get("source_path"), now
            )
            for edge in edges
        ]
        con.executemany(
            """INSERT INTO local_graph_edges
               (source_id, target_id, relation, weight, confidence, evidence, source_path, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            edge_tuples
        )
        con.execute(
            """UPDATE local_graph_build_runs
               SET completed_at = ?, status = 'complete', node_count = ?, edge_count = ?
               WHERE id = ?""",
            (now, len(nodes), len(edges), run_id),
        )
        con.commit()


def load_graph(*, graph_db: Optional[str] = None, limit: int = 1000) -> dict[str, Any]:
    with _conn(graph_db) as con:
        node_rows = con.execute(
            "SELECT * FROM local_graph_nodes ORDER BY type, label LIMIT ?",
            (limit,),
        ).fetchall()
        edge_rows = con.execute(
            "SELECT * FROM local_graph_edges ORDER BY relation, source_id LIMIT ?",
            (limit * 3,),
        ).fetchall()
    return {
        "nodes": [_node_from_row(r) for r in node_rows],
        "relations": [_edge_from_row(r) for r in edge_rows],
    }


def _node_from_row(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "id": row["id"],
        "type": row["type"],
        "title": row["label"],
        "label": row["label"],
        "uri": row["uri"],
        "path": row["source_path"],
        "privacy_state": row["privacy_state"],
        "metadata": json.loads(row["metadata_json"] or "{}"),
    }


def _edge_from_row(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "source_id": row["source_id"],
        "target_id": row["target_id"],
        "relation": row["relation"],
        "weight": row["weight"],
        "confidence": row["confidence"],
        "evidence": row["evidence"],
        "source_path": row["source_path"],
    }


def graph_neighbors(node_id: str, *, graph_db: Optional[str] = None, limit: int = 50) -> dict[str, Any]:
    with _conn(graph_db) as con:
        edges = con.execute(
            """SELECT * FROM local_graph_edges
               WHERE source_id = ? OR target_id = ?
               ORDER BY weight DESC LIMIT ?""",
            (node_id, node_id, limit),
        ).fetchall()
        ids = {node_id}
        for edge in edges:
            ids.add(edge["source_id"])
            ids.add(edge["target_id"])
        if not ids:
            return {"nodes": [], "relations": []}
        placeholders = ",".join("?" * len(ids))
        nodes = con.execute(
            f"SELECT * FROM local_graph_nodes WHERE id IN ({placeholders})",
            tuple(ids),
        ).fetchall()
    return {
        "nodes": [_node_from_row(r) for r in nodes],
        "relations": [_edge_from_row(r) for r in edges],
    }


def graph_search(query: str, *, graph_db: Optional[str] = None, limit: int = 25) -> dict[str, Any]:
    terms = [t.lower() for t in _TOKEN_RE.findall(query or "") if len(t) > 1]
    if not terms:
        return load_graph(graph_db=graph_db, limit=limit)
    with _conn(graph_db) as con:
        clauses = " OR ".join(["LOWER(label) LIKE ? OR LOWER(uri) LIKE ? OR LOWER(metadata_json) LIKE ?"] * len(terms))
        params: list[str | int] = []
        for term in terms:
            like = f"%{term}%"
            params.extend([like, like, like])
        params.append(limit)
        nodes = con.execute(
            f"SELECT * FROM local_graph_nodes WHERE {clauses} ORDER BY type, label LIMIT ?",
            params,
        ).fetchall()
    node_ids = [r["id"] for r in nodes]
    related_edges: list[dict[str, Any]] = []
    related_nodes = [_node_from_row(r) for r in nodes]
    seen_nodes = {n["id"] for n in related_nodes}
    for nid in node_ids[:10]:
        neighborhood = graph_neighbors(nid, graph_db=graph_db, limit=10)
        related_edges.extend(neighborhood["relations"])
        for node in neighborhood["nodes"]:
            if node["id"] not in seen_nodes:
                seen_nodes.add(node["id"])
                related_nodes.append(node)
    return {"nodes": related_nodes[:limit * 2], "relations": related_edges}


def related_local_file_ids(document_id: str, *, graph_db: Optional[str] = None, limit: int = 5) -> list[dict[str, Any]]:
    preferred = {
        "belongs_to_project", "has_topic", "same_content_as", "version_of",
        "newer_than", "nearby_in_folder",
    }
    with _conn(graph_db) as con:
        node_rows = con.execute("SELECT id, type FROM local_graph_nodes").fetchall()
        node_types = {row["id"]: row["type"] for row in node_rows}
        edge_rows = con.execute(
            "SELECT * FROM local_graph_edges WHERE source_id = ? OR target_id = ?",
            (document_id, document_id),
        ).fetchall()
        first_hop = [_edge_from_row(r) for r in edge_rows if r["relation"] in preferred]

        candidates: list[dict[str, Any]] = []
        intermediates: list[tuple[str, dict[str, Any]]] = []
        for edge in sorted(first_hop, key=lambda e: float(e.get("weight") or 0), reverse=True):
            other = edge["target_id"] if edge["source_id"] == document_id else edge["source_id"]
            if other == document_id:
                continue
            if node_types.get(other) == "local_file":
                candidates.append({"id": other, "graph_reason": edge["relation"], "evidence": edge.get("evidence")})
            else:
                intermediates.append((other, edge))

        for intermediate, parent_edge in intermediates:
            if len(candidates) >= limit:
                break
            rows = con.execute(
                """SELECT * FROM local_graph_edges
                   WHERE (source_id = ? OR target_id = ?)
                   ORDER BY weight DESC LIMIT 20""",
                (intermediate, intermediate),
            ).fetchall()
            for row in rows:
                edge = _edge_from_row(row)
                other = edge["target_id"] if edge["source_id"] == intermediate else edge["source_id"]
                if other == document_id or node_types.get(other) != "local_file":
                    continue
                candidates.append({
                    "id": other,
                    "graph_reason": parent_edge["relation"],
                    "evidence": parent_edge.get("evidence") or edge.get("evidence"),
                })
                if len(candidates) >= limit:
                    break

    seen: set[str] = set()
    out: list[dict[str, Any]] = []
    for row in candidates:
        if row["id"] in seen:
            continue
        seen.add(row["id"])
        out.append(row)
        if len(out) >= limit:
            break
    return out
