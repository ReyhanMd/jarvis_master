#!/usr/bin/env python3
"""Recover legacy browser/AI captures into the canonical SHAIL store.

Default mode is dry-run. Apply mode creates a backup snapshot before changing
live Chroma/SQLite state.
"""
from __future__ import annotations

import argparse
import json
import shutil
import sqlite3
import sys
import tempfile
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

ROOT = Path(__file__).resolve().parents[3]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from apps.shail.source_normalization import (  # noqa: E402
    is_browser_memory,
    is_local_or_activity_memory,
    normalize_browser_metadata,
)

COLLECTION_NAME = "shail_rag"


@dataclass
class ChromaRecord:
    id: str
    document: str
    metadata: Dict[str, Any]
    embedding: Any = None
    source_store: str = "unknown"

    @property
    def logical_id(self) -> str:
        return (
            self.metadata.get("customId")
            or self.metadata.get("parent_memory_id")
            or self.metadata.get("id")
            or self.id
        )


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def default_app_support() -> Path:
    return Path.home() / "Library" / "Application Support" / "SHAIL"


def default_source_chromas() -> List[Path]:
    app = default_app_support()
    candidates = [
        app / "backups" / "20260611_093034" / "chroma_snapshot",
        ROOT / "rag_chroma",
        ROOT / "apps" / "shail" / "rag_chroma",
    ]
    return [p for p in candidates if (p / "chroma.sqlite3").exists()]


def load_chroma_records(path: Path, source_store: str) -> List[ChromaRecord]:
    if not (path / "chroma.sqlite3").exists():
        return []
    import warnings

    warnings.filterwarnings("ignore")
    import chromadb

    # Chroma's PersistentClient may write lock/sysdb state even for reads.
    # Load through a temporary copy so dry-runs never mutate live/backup stores.
    with tempfile.TemporaryDirectory(prefix="shail_chroma_read_") as tmp:
        read_path = Path(tmp) / "chroma"
        shutil.copytree(path, read_path)
        client = chromadb.PersistentClient(path=str(read_path))
        try:
            collection = client.get_collection(COLLECTION_NAME)
        except Exception:
            return []
        try:
            data = collection.get(include=["documents", "metadatas", "embeddings"], limit=20000)
        except Exception:
            data = collection.get(include=["documents", "metadatas"], limit=20000)
        ids = data.get("ids") or []
        docs = data.get("documents") or [""] * len(ids)
        metas = data.get("metadatas") or [{}] * len(ids)
        embeddings = data.get("embeddings")
        out: List[ChromaRecord] = []
        for idx, rid in enumerate(ids):
            emb = None
            if embeddings is not None:
                try:
                    emb = embeddings[idx]
                except Exception:
                    emb = None
            out.append(ChromaRecord(
                id=rid,
                document=docs[idx] if idx < len(docs) else "",
                metadata=dict(metas[idx] or {}),
                embedding=emb,
                source_store=source_store,
            ))
        return out


def load_raw_rows(sqlite_path: Path) -> List[Dict[str, Any]]:
    if not sqlite_path.exists():
        return []
    with sqlite3.connect(str(sqlite_path)) as con:
        con.row_factory = sqlite3.Row
        try:
            rows = con.execute("SELECT * FROM raw_transcripts").fetchall()
        except sqlite3.Error:
            return []
    out = []
    for row in rows:
        d = dict(row)
        try:
            d["metadata"] = json.loads(d.get("metadata") or "{}")
        except Exception:
            d["metadata"] = {}
        out.append(d)
    return out


def load_blueprint_rows(sqlite_path: Path) -> Dict[str, Dict[str, Any]]:
    if not sqlite_path.exists():
        return {}
    with sqlite3.connect(str(sqlite_path)) as con:
        con.row_factory = sqlite3.Row
        try:
            rows = con.execute("SELECT * FROM blueprints").fetchall()
        except sqlite3.Error:
            return {}
    out = {}
    for row in rows:
        d = dict(row)
        out[d.get("memory_id")] = d
    return out


def load_blueprint_jobs(sqlite_path: Path) -> List[Dict[str, Any]]:
    if not sqlite_path.exists():
        return []
    with sqlite3.connect(str(sqlite_path)) as con:
        con.row_factory = sqlite3.Row
        try:
            rows = con.execute("SELECT * FROM blueprint_jobs").fetchall()
        except sqlite3.Error:
            return []
    return [dict(r) for r in rows]


def choose_canonical_namespace(raw_rows: List[Dict[str, Any]], live_records: List[ChromaRecord]) -> str:
    counts: Counter[str] = Counter()
    for row in raw_rows:
        ns = row.get("namespace")
        if ns:
            counts[ns] += 5
    for rec in live_records:
        ns = rec.metadata.get("namespace")
        if ns:
            counts[ns] += 1
    for ns, _count in counts.most_common():
        if str(ns).startswith("user_"):
            return ns
    return "browser_memory"


def dedupe_key(meta: Dict[str, Any], document: str) -> Tuple[str, str, str]:
    normalized = normalize_browser_metadata(meta, document)
    return (
        str(normalized.get("sourceApp") or "").lower(),
        str(normalized.get("sourceUrl") or "").strip().lower(),
        str(normalized.get("title") or "").strip().lower(),
    )


def _embedding_dim(embedding: Any) -> Optional[int]:
    if embedding is None:
        return None
    try:
        return len(embedding)
    except Exception:
        return None


def is_test_record(record_id: str, meta: Dict[str, Any]) -> bool:
    title = str(meta.get("title") or "").strip().lower()
    rid = str(record_id or "").strip().lower()
    custom = str(meta.get("customId") or meta.get("id") or "").strip().lower()
    return rid.startswith("auth-test") or custom.startswith("auth-test") or title == "auth test"


def classify_live_records(records: List[ChromaRecord]) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    counts: Counter[str] = Counter()
    for rec in records:
        old_source = rec.metadata.get("sourceApp") or rec.metadata.get("source") or ""
        normalized = normalize_browser_metadata(rec.metadata, rec.document)
        if is_test_record(rec.id, normalized):
            counts["test_record"] += 1
            rows.append({
                "classification": "test_record",
                "id": rec.id,
                "logical_id": rec.logical_id,
                "title": normalized.get("title") or "",
                "old_sourceApp": rec.metadata.get("sourceApp") or rec.metadata.get("source") or "",
                "sourceApp": normalized.get("sourceApp"),
                "sourceUrl": normalized.get("sourceUrl") or "",
                "namespace": rec.metadata.get("namespace"),
                "store": rec.source_store,
            })
            continue
        is_local = is_local_or_activity_memory(rec.metadata)
        browser = is_browser_memory(rec.metadata, rec.document)
        label = "live_visible" if browser else "local_file" if is_local else "non_browser"
        if browser and normalized.get("sourceApp") != rec.metadata.get("sourceApp"):
            label = "source_mislabel"
        counts[label] += 1
        rows.append({
            "classification": label,
            "id": rec.id,
            "logical_id": rec.logical_id,
            "title": normalized.get("title") or rec.metadata.get("title") or "",
            "old_sourceApp": old_source,
            "sourceApp": normalized.get("sourceApp"),
            "sourceUrl": normalized.get("sourceUrl") or "",
            "namespace": rec.metadata.get("namespace"),
            "store": rec.source_store,
        })
    return rows, dict(counts)


def build_reconciliation(
    *,
    live_records: List[ChromaRecord],
    raw_rows: List[Dict[str, Any]],
    source_records: List[ChromaRecord],
    blueprint_jobs: List[Dict[str, Any]],
    blueprint_rows: Dict[str, Dict[str, Any]],
    canonical_namespace: Optional[str] = None,
) -> Dict[str, Any]:
    canonical_namespace = canonical_namespace or choose_canonical_namespace(raw_rows, live_records)
    live_ids = {r.id for r in live_records}
    live_logical_ids = {r.logical_id for r in live_records}
    raw_ids = {r.get("memory_id") for r in raw_rows}
    blueprint_ids = set(blueprint_rows.keys())
    live_keys = {dedupe_key(r.metadata, r.document) for r in live_records if is_browser_memory(r.metadata, r.document)}
    live_dim = next((_embedding_dim(r.embedding) for r in live_records if _embedding_dim(r.embedding)), None)

    live_audit, live_counts = classify_live_records(live_records)
    raw_only: List[Dict[str, Any]] = []
    source_mislabels: List[Dict[str, Any]] = [r for r in live_audit if r["classification"] == "source_mislabel"]
    imports: List[Dict[str, Any]] = []
    vector_repairs: List[Dict[str, Any]] = []
    skipped: List[Dict[str, Any]] = []
    seen_import_keys = set(live_keys)

    for row in raw_rows:
        mid = row.get("memory_id")
        meta = row.get("metadata") or {}
        if is_test_record(mid, meta):
            continue
        if mid not in live_logical_ids and mid not in live_ids and is_browser_memory(meta, row.get("content") or ""):
            normalized = normalize_browser_metadata(meta, row.get("content") or "")
            raw_only.append({
                "classification": "raw_only",
                "id": mid,
                "title": normalized.get("title") or "",
                "sourceApp": normalized.get("sourceApp"),
                "sourceUrl": normalized.get("sourceUrl") or "",
                "embedded": bool(row.get("embedded")),
                "blueprinted": bool(row.get("blueprinted")),
                "namespace": row.get("namespace"),
            })
            if normalized.get("sourceApp") != meta.get("sourceApp"):
                source_mislabels.append({
                    "classification": "source_mislabel",
                    "id": mid,
                    "logical_id": mid,
                    "title": normalized.get("title") or "",
                    "old_sourceApp": meta.get("sourceApp"),
                    "sourceApp": normalized.get("sourceApp"),
                    "sourceUrl": normalized.get("sourceUrl") or "",
                    "namespace": row.get("namespace"),
                    "store": "raw_transcripts",
                })

    for rec in source_records:
        normalized = normalize_browser_metadata(rec.metadata, rec.document)
        if is_test_record(rec.id, normalized):
            skipped.append({
                "classification": "test_record",
                "id": rec.id,
                "logical_id": rec.logical_id,
                "title": normalized.get("title") or "",
                "sourceApp": normalized.get("sourceApp"),
                "sourceUrl": normalized.get("sourceUrl") or "",
                "namespace": rec.metadata.get("namespace"),
                "store": rec.source_store,
            })
            continue
        key = dedupe_key(normalized, rec.document)
        browser = is_browser_memory(normalized, rec.document)
        if not browser:
            skipped.append({
                "classification": "local_file" if is_local_or_activity_memory(rec.metadata) else "non_browser",
                "id": rec.id,
                "title": normalized.get("title") or "",
                "sourceApp": normalized.get("sourceApp"),
                "sourceUrl": normalized.get("sourceUrl") or "",
                "namespace": rec.metadata.get("namespace"),
                "store": rec.source_store,
            })
            continue
        if rec.id in live_ids or rec.logical_id in live_logical_ids or key in seen_import_keys:
            skipped.append({
                "classification": "duplicate",
                "id": rec.id,
                "logical_id": rec.logical_id,
                "title": normalized.get("title") or "",
                "sourceApp": normalized.get("sourceApp"),
                "sourceUrl": normalized.get("sourceUrl") or "",
                "namespace": rec.metadata.get("namespace"),
                "store": rec.source_store,
            })
            continue
        if rec.logical_id in raw_ids:
            rec_dim = _embedding_dim(rec.embedding)
            payload = {
                "id": rec.id,
                "logical_id": rec.logical_id,
                "title": normalized.get("title") or "",
                "sourceApp": normalized.get("sourceApp"),
                "sourceUrl": normalized.get("sourceUrl") or "",
                "namespace": rec.metadata.get("namespace"),
                "target_namespace": canonical_namespace,
                "store": rec.source_store,
            }
            if live_dim is not None and rec_dim is not None and rec_dim != live_dim:
                skipped.append({
                    "classification": "vector_dimension_mismatch_raw_visible",
                    "embedding_dim": rec_dim,
                    "live_embedding_dim": live_dim,
                    **payload,
                })
            else:
                vector_repairs.append({
                    "classification": "raw_import_needs_vector",
                    **payload,
                })
            seen_import_keys.add(key)
            continue
        seen_import_keys.add(key)
        imports.append({
            "classification": "backup_only" if "backup" in rec.source_store else "legacy_namespace",
            "id": rec.id,
            "logical_id": rec.logical_id,
            "title": normalized.get("title") or "",
            "sourceApp": normalized.get("sourceApp"),
            "sourceUrl": normalized.get("sourceUrl") or "",
            "namespace": rec.metadata.get("namespace"),
            "target_namespace": canonical_namespace,
            "store": rec.source_store,
        })

    incomplete_jobs: List[Dict[str, Any]] = []
    unrecoverable_jobs: List[Dict[str, Any]] = []
    stale_cutoff = datetime.now(timezone.utc) - timedelta(minutes=30)
    for job in blueprint_jobs:
        mid = job.get("memory_id")
        has_raw = mid in raw_ids
        has_vector = mid in live_ids or mid in live_logical_ids
        has_blueprint = mid in blueprint_ids
        state = job.get("state")
        stale_running = False
        if state == "running":
            try:
                updated = datetime.fromisoformat(str(job.get("updated_at")).replace("Z", "+00:00"))
                stale_running = updated < stale_cutoff
            except Exception:
                stale_running = True
        if state == "done" and not has_blueprint:
            incomplete_jobs.append({"classification": "done_without_blueprint", **job})
        elif stale_running:
            incomplete_jobs.append({"classification": "stale_running", **job})
        elif not has_raw and not has_vector and not has_blueprint:
            unrecoverable_jobs.append({"classification": "unrecoverable_job_only", **job})

    counts = Counter()
    counts.update(live_counts)
    counts["raw_only"] = len(raw_only)
    counts["source_mislabel"] = len(source_mislabels)
    counts["import_candidates"] = len(imports)
    counts["vector_repair_candidates"] = len(vector_repairs)
    counts["skipped_source_records"] = len(skipped)
    counts["incomplete_blueprint_jobs"] = len(incomplete_jobs)
    counts["unrecoverable_job_only"] = len(unrecoverable_jobs)
    return {
        "generated_at": _now(),
        "canonical_namespace": canonical_namespace,
        "counts": dict(counts),
        "live": live_audit,
        "raw_only": raw_only,
        "source_mislabels": source_mislabels,
        "import_candidates": imports,
        "vector_repair_candidates": vector_repairs,
        "skipped": skipped,
        "incomplete_blueprint_jobs": incomplete_jobs,
        "unrecoverable_job_only": unrecoverable_jobs,
    }


def write_reports(report: Dict[str, Any], report_dir: Path) -> Tuple[Path, Path]:
    report_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    json_path = report_dir / f"legacy_capture_reconciliation_{stamp}.json"
    md_path = report_dir / f"legacy_capture_reconciliation_{stamp}.md"
    json_path.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")

    lines = [
        "# Legacy Capture Reconciliation",
        "",
        f"- Generated: `{report['generated_at']}`",
        f"- Canonical namespace: `{report['canonical_namespace']}`",
        "",
        "## Counts",
        "",
    ]
    for key, value in sorted((report.get("counts") or {}).items()):
        lines.append(f"- `{key}`: {value}")
    lines.extend(["", "## Import Candidates", ""])
    for item in report.get("import_candidates", [])[:100]:
        lines.append(f"- `{item['id']}` | {item.get('sourceApp')} | {item.get('title') or '(untitled)'} | {item.get('store')}")
    lines.extend(["", "## Vector Repair Candidates", ""])
    for item in report.get("vector_repair_candidates", [])[:100]:
        lines.append(f"- `{item['id']}` | raw `{item.get('logical_id')}` | {item.get('sourceApp')} | {item.get('title') or '(untitled)'} | {item.get('store')}")
    lines.extend(["", "## Source Mislabels", ""])
    for item in report.get("source_mislabels", [])[:100]:
        lines.append(f"- `{item['id']}` | {item.get('old_sourceApp')} -> {item.get('sourceApp')} | {item.get('title')}")
    lines.extend(["", "## Raw-Only Visible Captures", ""])
    for item in report.get("raw_only", [])[:100]:
        lines.append(f"- `{item['id']}` | {item.get('sourceApp')} | embedded={item.get('embedded')} | blueprinted={item.get('blueprinted')} | {item.get('title')}")
    lines.extend(["", "## Blueprint Repair", ""])
    for item in report.get("incomplete_blueprint_jobs", [])[:100]:
        lines.append(f"- `{item.get('memory_id')}` | {item.get('classification')} | state={item.get('state')} | job={item.get('id')}")
    lines.extend(["", "## Unrecoverable Job-Only Rows", ""])
    for item in report.get("unrecoverable_job_only", [])[:100]:
        lines.append(f"- `{item.get('memory_id')}` | state={item.get('state')} | job={item.get('id')}")
    md_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return json_path, md_path


def snapshot_live_store(app_support: Path) -> Path:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    backup_dir = app_support / "backups" / f"reconcile_{stamp}"
    backup_dir.mkdir(parents=True, exist_ok=False)
    sqlite_path = app_support / "metadata.db"
    chroma_path = app_support / "memory" / "chroma"
    if sqlite_path.exists():
        shutil.copy2(sqlite_path, backup_dir / "metadata.db")
    if chroma_path.exists():
        shutil.copytree(chroma_path, backup_dir / "chroma")
    return backup_dir


def _open_collection(path: Path):
    import warnings

    warnings.filterwarnings("ignore")
    import chromadb

    client = chromadb.PersistentClient(path=str(path))
    return client.get_or_create_collection(COLLECTION_NAME)


def apply_reconciliation(
    *,
    live_chroma: Path,
    sqlite_path: Path,
    app_support: Path,
    live_records: List[ChromaRecord],
    source_records: List[ChromaRecord],
    report: Dict[str, Any],
) -> Dict[str, Any]:
    backup_dir = snapshot_live_store(app_support)
    collection = _open_collection(live_chroma)
    canonical_namespace = report["canonical_namespace"]
    user_id = canonical_namespace.removeprefix("user_") if canonical_namespace.startswith("user_") else "local"

    live_by_id = {r.id: r for r in live_records}
    source_by_id = {r.id: r for r in source_records}
    applied = Counter()
    now = _now()

    mislabel_ids = {m["id"] for m in report.get("source_mislabels", []) if m.get("store") != "raw_transcripts"}
    for mid in mislabel_ids:
        rec = live_by_id.get(mid)
        if not rec:
            continue
        meta = normalize_browser_metadata(rec.metadata, rec.document)
        meta["source_normalized_at"] = now
        collection.update(ids=[rec.id], metadatas=[meta])
        applied["normalized_vector_sources"] += 1

    with sqlite3.connect(str(sqlite_path)) as con:
        con.row_factory = sqlite3.Row
        for row in con.execute("SELECT memory_id, metadata, content FROM raw_transcripts").fetchall():
            try:
                meta = json.loads(row["metadata"] or "{}")
            except Exception:
                meta = {}
            normalized = normalize_browser_metadata(meta, row["content"] or "")
            if normalized != meta:
                normalized["source_normalized_at"] = now
                con.execute(
                    "UPDATE raw_transcripts SET metadata = ? WHERE memory_id = ?",
                    (json.dumps(normalized), row["memory_id"]),
                )
                applied["normalized_raw_sources"] += 1
        con.commit()

    candidate_items = list(report.get("import_candidates", [])) + list(report.get("vector_repair_candidates", []))
    import_ids = [i["id"] for i in candidate_items]
    if import_ids:
        from apps.shail import raw_transcripts as _rt
        from apps.shail.blueprint_queue import enqueue as enqueue_blueprint

        live_dim = next((_embedding_dim(r.embedding) for r in live_records if _embedding_dim(r.embedding)), None)
        ids: List[str] = []
        docs: List[str] = []
        metas: List[Dict[str, Any]] = []
        embeddings: List[Any] = []
        for mid in import_ids:
            rec = source_by_id.get(mid)
            if not rec:
                continue
            meta = normalize_browser_metadata(rec.metadata, rec.document)
            meta["namespace"] = canonical_namespace
            meta["legacy_recovered_at"] = now
            meta["legacy_recovered_from"] = rec.source_store
            meta.setdefault("customId", rec.logical_id)
            meta.setdefault("id", rec.id)
            emb_dim = _embedding_dim(rec.embedding)
            if rec.embedding is None or (live_dim is not None and emb_dim != live_dim):
                applied["skipped_vector_dimension_mismatch"] += 1
            else:
                ids.append(rec.id)
                docs.append(rec.document or "")
                metas.append(meta)
                if hasattr(rec.embedding, "tolist"):
                    embeddings.append(rec.embedding.tolist())
                else:
                    embeddings.append(rec.embedding)
            _rt.save(
                memory_id=rec.logical_id,
                user_id=user_id,
                namespace=canonical_namespace,
                content_type=meta.get("eventType", "page_visit"),
                content=rec.document or "",
                metadata=meta,
                capture_mode=meta.get("capture_mode", "bulk"),
            )
            try:
                enqueue_blueprint(
                    memory_id=rec.logical_id,
                    session_id=None,
                    user_id=user_id,
                    content_type=meta.get("eventType", "page_visit"),
                    priority=-1,
                )
                applied["blueprint_jobs_enqueued"] += 1
            except Exception:
                pass
        if ids:
            collection.upsert(ids=ids, documents=docs, metadatas=metas, embeddings=embeddings)
            applied["imported_vector_records"] += len(ids)
        applied["created_or_updated_raw_transcripts"] += len(import_ids)

    raw_repair_ids = [r["id"] for r in report.get("raw_only", []) if not r.get("blueprinted")]
    if raw_repair_ids:
        from apps.shail.blueprint_queue import enqueue as enqueue_blueprint
        from apps.shail import raw_transcripts as _rt
        for mid in raw_repair_ids:
            raw = _rt.get(mid)
            if not raw:
                continue
            enqueue_blueprint(
                memory_id=mid,
                session_id=None,
                user_id=raw.get("user_id") or user_id,
                content_type=raw.get("content_type") or "page_visit",
                priority=-1,
            )
            applied["raw_only_blueprint_jobs_enqueued"] += 1

    with sqlite3.connect(str(sqlite_path)) as con:
        for item in report.get("incomplete_blueprint_jobs", []):
            job_id = item.get("id")
            if not job_id:
                continue
            if item.get("classification") == "done_without_blueprint":
                con.execute(
                    """UPDATE blueprint_jobs
                       SET state = 'failed',
                           last_error = ?,
                           updated_at = ?
                       WHERE id = ?""",
                    ("reconciled: job claimed done but no blueprint row exists", now, job_id),
                )
                applied["done_without_blueprint_marked_failed"] += 1
            else:
                con.execute(
                    """UPDATE blueprint_jobs
                       SET state = 'pending',
                           last_error = ?,
                           next_attempt_at = ?,
                           updated_at = ?
                       WHERE id = ?""",
                    (f"reconciled: {item.get('classification')}", now, now, job_id),
                )
                applied["blueprint_jobs_requeued"] += 1
        for item in report.get("unrecoverable_job_only", []):
            job_id = item.get("id")
            if not job_id:
                continue
            con.execute(
                """UPDATE blueprint_jobs
                   SET state = 'failed',
                       last_error = ?,
                       updated_at = ?
                   WHERE id = ?""",
                ("reconciled: unrecoverable job-only row; no raw transcript, vector record, or blueprint row", now, job_id),
            )
            applied["unrecoverable_jobs_marked_failed"] += 1
        con.commit()

    return {"backup_dir": str(backup_dir), "applied": dict(applied)}


def main(argv: Optional[List[str]] = None) -> int:
    app_support = default_app_support()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true", help="Apply changes after writing the audit report.")
    parser.add_argument("--live-chroma", type=Path, default=app_support / "memory" / "chroma")
    parser.add_argument("--sqlite", type=Path, default=app_support / "metadata.db")
    parser.add_argument("--source-chroma", type=Path, action="append", default=None)
    parser.add_argument("--canonical-namespace", default=None)
    parser.add_argument("--report-dir", type=Path, default=ROOT / "recovery_reports")
    args = parser.parse_args(argv)

    source_paths = args.source_chroma if args.source_chroma is not None else default_source_chromas()
    live_records = load_chroma_records(args.live_chroma, "live")
    raw_rows = load_raw_rows(args.sqlite)
    source_records: List[ChromaRecord] = []
    for path in source_paths:
        source_records.extend(load_chroma_records(path, f"source:{path}"))
    report = build_reconciliation(
        live_records=live_records,
        raw_rows=raw_rows,
        source_records=source_records,
        blueprint_jobs=load_blueprint_jobs(args.sqlite),
        blueprint_rows=load_blueprint_rows(args.sqlite),
        canonical_namespace=args.canonical_namespace,
    )
    json_path, md_path = write_reports(report, args.report_dir)
    print(f"wrote {json_path}")
    print(f"wrote {md_path}")
    print(json.dumps(report.get("counts", {}), indent=2, sort_keys=True))

    if args.apply:
        applied = apply_reconciliation(
            live_chroma=args.live_chroma,
            sqlite_path=args.sqlite,
            app_support=args.sqlite.parent,
            live_records=live_records,
            source_records=source_records,
            report=report,
        )
        print(json.dumps(applied, indent=2, sort_keys=True))
    else:
        print("dry-run only; rerun with --apply to mutate live data after reviewing the report")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
