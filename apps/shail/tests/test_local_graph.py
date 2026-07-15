from __future__ import annotations

from pathlib import Path


def _paths(tmp_path: Path) -> tuple[str, str, Path]:
    path_db = str(tmp_path / "path_index.db")
    graph_db = str(tmp_path / "graph.db")
    root = tmp_path / "approved"
    root.mkdir()
    return path_db, graph_db, root


def _build(path_db: str, graph_db: str, root: Path):
    from apps.shail import local_graph
    from shail.memory import path_index

    path_index.scan(path_db, roots=[str(root)])
    return local_graph.build_local_file_graph(
        path_db=path_db,
        graph_db=graph_db,
        env_roots=[str(root)],
        limit=500,
    )


def test_graph_build_creates_project_topic_entity_and_file_nodes(tmp_path):
    path_db, graph_db, root = _paths(tmp_path)
    (root / "Dubai_Pitch_v1.md").write_text("Dubai Client Alpha pricing plan")

    graph = _build(path_db, graph_db, root)

    node_types = {n["type"] for n in graph["nodes"]}
    relations = {e["relation"] for e in graph["relations"]}
    assert {"local_file", "folder", "project", "topic", "entity"}.issubset(node_types)
    assert "belongs_to_project" in relations
    assert "has_topic" in relations
    assert "mentions_entity" in relations
    assert any(e["confidence"] in {"EXTRACTED", "INFERRED"} for e in graph["relations"])


def test_graph_excludes_denied_and_deleted_paths(tmp_path):
    from apps.shail import local_graph
    from shail.memory import path_index

    path_db, graph_db, root = _paths(tmp_path)
    blocked = root / "private"
    blocked.mkdir()
    allowed = root / "allowed.md"
    denied = blocked / "secret.md"
    gone = root / "gone.md"
    allowed.write_text("allowed project file")
    denied.write_text("blocked private file")
    gone.write_text("temporary")

    path_index.add_deny_path(path_db, str(blocked), reason="private")
    path_index.scan(path_db, roots=[str(root)])
    gone.unlink()
    path_index.scan(path_db, roots=[str(root)])

    graph = local_graph.build_local_file_graph(
        path_db=path_db,
        graph_db=graph_db,
        env_roots=[str(root)],
        limit=500,
    )
    paths = {n.get("source_path") for n in graph["nodes"]}

    assert str(allowed) in paths
    assert str(denied) not in paths
    assert str(gone) not in paths


def test_graph_detects_duplicates_and_versions(tmp_path):
    path_db, graph_db, root = _paths(tmp_path)
    (root / "Dubai_Pitch_v1.md").write_text("same duplicate body")
    (root / "Dubai_Pitch_v2.md").write_text("same duplicate body")

    graph = _build(path_db, graph_db, root)
    relations = {e["relation"] for e in graph["relations"]}

    assert "same_content_as" in relations
    assert "version_of" in relations
    assert "newer_than" in relations


def test_graph_search_and_neighbors_return_related_files(tmp_path):
    from apps.shail import local_graph
    from shail.memory import path_index

    path_db, graph_db, root = _paths(tmp_path)
    pitch = root / "Dubai_Pitch_v1.md"
    revenue = root / "Dubai_Revenue_Model.md"
    pitch.write_text("Dubai pricing narrative")
    revenue.write_text("Dubai revenue spreadsheet notes")
    path_index.scan(path_db, roots=[str(root)])
    graph = local_graph.build_local_file_graph(
        path_db=path_db,
        graph_db=graph_db,
        env_roots=[str(root)],
        limit=500,
    )

    search = local_graph.graph_search("Dubai", graph_db=graph_db, limit=20)
    assert any("Dubai" in (n["title"] or "") for n in search["nodes"])

    pitch_row = path_index.get_by_path(path_db, str(pitch))
    related = local_graph.related_local_file_ids(pitch_row["id"], graph_db=graph_db, limit=5)
    related_rows = [path_index.get_by_id(path_db, r["id"]) for r in related]
    assert any(row and row["path"] == str(revenue) for row in related_rows)
