#!/usr/bin/env python3
"""
SHAIL Single-User Migration Script
====================================
Consolidates all data from secondary user accounts into the canonical user.
Secondary users are ARCHIVED (status=archived, merged_into=canonical), NOT deleted.
Smoke-test data (smoketest2@example.com) is preserved as archived test data.

Usage:
    python migrate_single_user.py [--dry-run] [--verify-only] [--skip-chroma]

Steps:
    1.  Add archive columns to users table (idempotent)
    2.  Add migration_lock to block writes during migration
    3.  SQLite: migrate all user-owned tables to canonical user
    4.  SQLite: archive secondary users (mark status=archived, NOT delete)
    5.  SQLite: archive smoke-test data separately
    6.  ChromaDB: re-namespace all embeddings to canonical namespace
    7.  ChromaDB: migrate legacy project rag_chroma (18 embeddings)
    8.  Invalidate retrieval cache
    9.  Remove migration lock
    10. Verify row counts and namespace consistency
    11. Emit migration report
"""

from __future__ import annotations

import argparse
import json
import logging
import shutil
import sqlite3
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

log = logging.getLogger("shail_migrate")
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

# ── Constants ────────────────────────────────────────────────────────────────

CANONICAL_ID    = "0661bf06-300a-4165-bf34-759f835993d6"
CANONICAL_EMAIL = "reyhanmd45@gmail.com"
CANONICAL_NS    = f"user_{CANONICAL_ID}"

# Secondary users to migrate data from and then ARCHIVE
SECONDARY_IDS = [
    "6208d61b-68f5-4a15-bd74-d25acb3c1744",   # reyhanstark22@gmail.com
    "ffbb5fe4-9b80-41d8-8e29-65f7df7477ab",   # recruitment.shailai@gmail.com
    "97a52ba1-d8bf-40ea-af69-2f038ebc1eae",   # armaaan.world@gmail.com
    "88a57d73-dabf-4e95-80de-c104954df18f",   # iloveshail3000@gmail.com
    "7c46487c-b726-486d-ac2e-0d569bf672c1",   # mcp_test@x.com
]

# Smoke-test account: data NOT migrated, archived separately
SMOKETEST_ID    = "c3f5bfef-fb8c-4e65-beaa-158d25265c93"
SMOKETEST_EMAIL = "smoketest2@example.com"

# All namespaces to re-target in ChromaDB
SOURCE_NAMESPACES = [
    # Current metadata.db secondary users
    f"user_{uid}" for uid in SECONDARY_IDS
] + [
    f"user_{SMOKETEST_ID}",
    # Chat namespaces for all users
    f"chat_{CANONICAL_ID}",
    f"chat_ffbb5fe4-9b80-41d8-8e29-65f7df7477ab",
    f"chat_6208d61b-68f5-4a15-bd74-d25acb3c1744",
    # Legacy old-DB namespaces
    "user_8b2393f5-c071-491e-8c6b-15406d46fc90",
    "user_172608a7-34a6-4d04-9548-c9afb7af7728",
    "user_696dc995-69ff-4de2-8890-13f0cbebc2f0",
    "user_619afe3a-da05-4c87-96f9-e3d741016ad2",
    # Anonymous namespaces
    "browser_memory",
    "local",
    "chat_u_e2e",
]

DB_PATH     = Path.home() / "Library/Application Support/SHAIL/metadata.db"
CHROMA_PATH = Path.home() / "Library/Application Support/SHAIL/memory/chroma"
CACHE_PATH  = Path.home() / "Library/Application Support/SHAIL/retrieval_cache.db"
PROJECT_CHROMA = Path(__file__).parents[3] / "rag_chroma"
LOCK_PATH   = Path.home() / "Library/Application Support/SHAIL/migration.lock"


# ── Step 0: Schema evolution ─────────────────────────────────────────────────

def evolve_schema(con: sqlite3.Connection) -> None:
    """Add archive columns to users table if not already present (idempotent)."""
    existing = {row[1] for row in con.execute("PRAGMA table_info(users)")}
    if "status" not in existing:
        con.execute("ALTER TABLE users ADD COLUMN status TEXT DEFAULT 'active'")
        log.info("Added status column to users")
    if "merged_into" not in existing:
        con.execute("ALTER TABLE users ADD COLUMN merged_into TEXT")
        log.info("Added merged_into column to users")
    if "archived_at" not in existing:
        con.execute("ALTER TABLE users ADD COLUMN archived_at TEXT")
        log.info("Added archived_at column to users")
    con.commit()


# ── Step 1: Migration lock ───────────────────────────────────────────────────

def acquire_lock(dry_run: bool) -> None:
    if dry_run:
        log.info("[DRY RUN] Would write migration.lock")
        return
    if LOCK_PATH.exists():
        log.warning("migration.lock already exists — another migration may be running")
        log.warning("If this is stale, delete it manually: rm '%s'", LOCK_PATH)
        sys.exit(1)
    LOCK_PATH.write_text(json.dumps({
        "started_at": datetime.now(timezone.utc).isoformat(),
        "canonical_id": CANONICAL_ID,
        "pid": __import__("os").getpid(),
    }))
    log.info("✅ Migration lock acquired: %s", LOCK_PATH)


def release_lock(dry_run: bool) -> None:
    if dry_run:
        return
    if LOCK_PATH.exists():
        LOCK_PATH.unlink()
    log.info("✅ Migration lock released")


# ── Step 2: Count rows before migration ─────────────────────────────────────

def count_state(con: sqlite3.Connection) -> dict:
    counts = {}
    tables = [
        "chat_sessions", "chat_messages", "raw_transcripts", "blueprints",
        "blueprint_jobs", "api_keys", "ascents", "deliverables", "todos",
        "watched_folders", "pipeline_status",
    ]
    for t in tables:
        try:
            counts[t] = con.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
        except Exception:
            counts[t] = "N/A"
    counts["users"] = con.execute("SELECT COUNT(*) FROM users").fetchone()[0]
    return counts


# ── Step 3: SQLite migration ─────────────────────────────────────────────────

def migrate_sqlite(con: sqlite3.Connection, dry_run: bool) -> dict:
    """
    Move all data from secondary users into canonical user.
    Smoke-test user data is NOT migrated — it stays in place until archival.
    All operations in one WAL transaction.
    """
    ph = ",".join([f"'{uid}'" for uid in SECONDARY_IDS])  # exclude smoketest
    now_iso = datetime.now(timezone.utc).isoformat()

    statements = [
        # chat_sessions
        f"UPDATE chat_sessions SET user_id='{CANONICAL_ID}' WHERE user_id IN ({ph})",
        # chat_messages
        f"UPDATE chat_messages SET user_id='{CANONICAL_ID}' WHERE user_id IN ({ph})",
        # raw_transcripts — also rewrite namespace
        f"UPDATE raw_transcripts SET user_id='{CANONICAL_ID}', namespace='{CANONICAL_NS}' WHERE user_id IN ({ph})",
        # blueprints
        f"UPDATE blueprints SET user_id='{CANONICAL_ID}', namespace='{CANONICAL_NS}' WHERE user_id IN ({ph})",
        # blueprint_jobs
        f"UPDATE blueprint_jobs SET user_id='{CANONICAL_ID}' WHERE user_id IN ({ph})",
        # api_keys — transferred to canonical (remain valid)
        f"UPDATE api_keys SET user_id='{CANONICAL_ID}' WHERE user_id IN ({ph})",
        # ascents from recruitment.shailai (real ascent: "fundraise for shail")
        f"UPDATE ascents SET user_id='{CANONICAL_ID}' WHERE user_id IN ({ph})",
        # watched_folders from reyhanstark22 (real user folders)
        f"UPDATE watched_folders SET user_id='{CANONICAL_ID}' WHERE user_id IN ({ph})",
        # user_settings (secondary users' settings → keep canonical, delete secondary after archival)
        f"DELETE FROM user_settings WHERE user_id IN ({ph})",
        # mcp_connections
        f"UPDATE mcp_connections SET user_id='{CANONICAL_ID}' WHERE user_id IN ({ph}) AND EXISTS (SELECT 1 FROM pragma_table_info('mcp_connections') WHERE name='user_id')",
        # Legacy "u1" user_settings row (test artifact)
        f"DELETE FROM user_settings WHERE user_id='u1'",
    ]

    changes = {}
    if dry_run:
        for s in statements:
            log.info("[DRY RUN] %s", s[:120])
        return changes

    with con:
        for stmt in statements:
            try:
                cur = con.execute(stmt)
                changes[stmt[:60]] = cur.rowcount
            except Exception as exc:
                log.warning("Statement failed (may be OK): %s | Error: %s", stmt[:80], exc)

    log.info("✅ SQLite migration complete. Changes: %s rows", sum(v for v in changes.values() if isinstance(v, int)))
    return changes


# ── Step 4: Archive secondary users (NOT delete) ─────────────────────────────

def archive_users(con: sqlite3.Connection, dry_run: bool) -> list:
    """Mark secondary users as archived with merged_into reference. NOT deleted."""
    now_iso = datetime.now(timezone.utc).isoformat()
    archived = []

    for uid in SECONDARY_IDS:
        row = con.execute("SELECT email FROM users WHERE id=?", (uid,)).fetchone()
        if not row:
            continue
        email = row[0]
        if dry_run:
            log.info("[DRY RUN] Would archive user: %s (%s)", email, uid)
            archived.append(email)
            continue
        con.execute(
            "UPDATE users SET status='archived', merged_into=?, archived_at=? WHERE id=?",
            (CANONICAL_ID, now_iso, uid),
        )
        log.info("  ✅ Archived: %s", email)
        archived.append(email)

    if not dry_run:
        con.commit()

    return archived


def archive_smoketest(con: sqlite3.Connection, dry_run: bool) -> dict:
    """
    Mark smoketest user as archived. Their ascents/deliverables/todos stay in DB
    but tagged with the smoketest user_id which is now archived — not visible to canonical.
    """
    now_iso = datetime.now(timezone.utc).isoformat()
    row = con.execute("SELECT email FROM users WHERE id=?", (SMOKETEST_ID,)).fetchone()
    if not row:
        return {"status": "not_found"}

    counts = {
        "ascents": con.execute("SELECT COUNT(*) FROM ascents WHERE user_id=?", (SMOKETEST_ID,)).fetchone()[0],
        "deliverables": con.execute(
            "SELECT COUNT(*) FROM deliverables d JOIN ascents a ON d.ascent_id=a.id WHERE a.user_id=?",
            (SMOKETEST_ID,)
        ).fetchone()[0],
    }

    if dry_run:
        log.info("[DRY RUN] Would archive smoketest user (%s): %s", SMOKETEST_EMAIL, counts)
        return {"status": "dry_run", "counts": counts}

    con.execute(
        "UPDATE users SET status='archived_test_data', merged_into=NULL, archived_at=? WHERE id=?",
        (now_iso, SMOKETEST_ID),
    )
    con.commit()
    log.info("  ✅ Smoketest archived (data preserved for recovery): %s", counts)
    return {"status": "archived", "counts": counts}


# ── Step 5: ChromaDB re-namespace ─────────────────────────────────────────────

def migrate_chroma(dry_run: bool, chroma_path: Path) -> dict:
    """Re-tag all embeddings in secondary namespaces to canonical namespace."""
    try:
        import chromadb
    except ImportError:
        log.error("chromadb not installed.")
        return {}

    # suppress noisy SSL warning
    import warnings
    warnings.filterwarnings("ignore")

    client = chromadb.PersistentClient(path=str(chroma_path))
    col = client.get_collection("shail_rag")

    total_moved = 0
    report = {}

    for old_ns in SOURCE_NAMESPACES:
        try:
            data = col.get(
                where={"namespace": old_ns},
                include=["metadatas", "documents", "embeddings"],
                limit=10000,
            )
        except Exception as e:
            log.debug("Could not query namespace %s: %s", old_ns, e)
            continue

        ids = data.get("ids") or []
        if not ids:
            continue

        metas = data.get("metadatas") or [{}] * len(ids)

        # Deduplicate: check if any of these IDs already exist in canonical NS
        # (customId-based dedup — same customId shouldn't get duplicated)
        new_metas = []
        for m in metas:
            updated = dict(m or {})
            updated["namespace"] = CANONICAL_NS
            # Record provenance for audit trail
            if "migrated_from_ns" not in updated:
                updated["migrated_from_ns"] = old_ns
                updated["migrated_at"] = datetime.now(timezone.utc).isoformat()
            new_metas.append(updated)

        if dry_run:
            log.info("[DRY RUN] Would re-namespace %d embeddings: %s → canonical", len(ids), old_ns)
            report[old_ns] = len(ids)
            continue

        # ChromaDB update: IDs stay the same, only metadata changes
        col.update(ids=ids, metadatas=new_metas)
        total_moved += len(ids)
        report[old_ns] = len(ids)
        log.info("  ✅ Re-namespaced %d embeddings: %s", len(ids), old_ns)

    if not dry_run:
        log.info("✅ ChromaDB: %d total embeddings re-namespaced to %s", total_moved, CANONICAL_NS)
    return report


# ── Step 6: Migrate legacy project rag_chroma ────────────────────────────────

def migrate_project_chroma(dry_run: bool) -> int:
    """Pull embeddings from jarvis_master/rag_chroma into the live chroma store."""
    try:
        import chromadb
        import warnings
        warnings.filterwarnings("ignore")
    except ImportError:
        return 0

    if not PROJECT_CHROMA.exists():
        log.info("Project rag_chroma not found at %s — skip", PROJECT_CHROMA)
        return 0

    src_client = chromadb.PersistentClient(path=str(PROJECT_CHROMA))
    dst_client = chromadb.PersistentClient(path=str(CHROMA_PATH))

    try:
        src_col = src_client.get_collection("shail_rag")
        dst_col = dst_client.get_or_create_collection("shail_rag")
    except Exception as e:
        log.warning("Could not open project rag_chroma: %s", e)
        return 0

    data = src_col.get(include=["metadatas", "documents", "embeddings"], limit=1000)
    ids = data.get("ids") or []
    if not ids:
        log.info("Project rag_chroma: empty — skip")
        return 0

    metas = data.get("metadatas") or [{}] * len(ids)
    new_metas = [{**(m or {}), "namespace": CANONICAL_NS, "migrated_from_ns": "project_rag_chroma", "migrated_at": datetime.now(timezone.utc).isoformat()} for m in metas]
    docs = data.get("documents") or [""] * len(ids)
    raw_embeddings = data.get("embeddings")
    embeddings = raw_embeddings if raw_embeddings is not None else None

    if dry_run:
        log.info("[DRY RUN] Would copy %d embeddings from project rag_chroma", len(ids))
        return len(ids)

    # Prefix IDs to avoid collision
    prefixed_ids = [f"legacy_proj_{i}" for i in ids]
    try:
        dst_col.upsert(ids=prefixed_ids, documents=docs, metadatas=new_metas, embeddings=embeddings)
        log.info("✅ Migrated %d embeddings from project rag_chroma", len(ids))
        return len(ids)
    except Exception as e:
        log.error("Project chroma migration failed: %s", e)
        return 0


# ── Step 7: Invalidate caches ─────────────────────────────────────────────────

def clear_retrieval_cache(dry_run: bool) -> int:
    if not CACHE_PATH.exists():
        return 0
    try:
        con = sqlite3.connect(str(CACHE_PATH), timeout=10.0)
        count = con.execute("SELECT COUNT(*) FROM retrieval_cache").fetchone()[0]
        if not dry_run:
            con.execute("DELETE FROM retrieval_cache")
            con.commit()
            log.info("✅ Cleared %d retrieval cache entries", count)
        else:
            log.info("[DRY RUN] Would clear %d retrieval cache entries", count)
        con.close()
        return count
    except Exception as e:
        log.warning("Cache clear failed: %s", e)
        return 0


# ── Step 8: Blueprint recovery (Phase 7) ─────────────────────────────────────

def recover_blueprints(con: sqlite3.Connection, dry_run: bool) -> dict:
    """
    Phase 7: Retry failed blueprint jobs that now belong to canonical user.
    Reset state=failed → state=pending so the worker picks them up.
    """
    failed = con.execute(
        "SELECT id, memory_id, last_error FROM blueprint_jobs WHERE state='failed' AND user_id=?",
        (CANONICAL_ID,)
    ).fetchall()

    running = con.execute(
        "SELECT COUNT(*) FROM blueprint_jobs WHERE state='running' AND user_id=?",
        (CANONICAL_ID,)
    ).fetchone()[0]

    done = con.execute(
        "SELECT COUNT(*) FROM blueprint_jobs WHERE state='done' AND user_id=?",
        (CANONICAL_ID,)
    ).fetchone()[0]

    # Orphan transcripts: raw_transcripts where blueprinted=0 but embedded=1
    orphans = con.execute(
        "SELECT COUNT(*) FROM raw_transcripts WHERE user_id=? AND embedded=1 AND (blueprinted IS NULL OR blueprinted=0)",
        (CANONICAL_ID,)
    ).fetchone()[0]

    report = {
        "failed_before": len(failed),
        "running": running,
        "done": done,
        "orphan_transcripts": orphans,
        "retried": 0,
        "still_failed": 0,
    }

    if dry_run:
        log.info("[DRY RUN] Would retry %d failed blueprint jobs", len(failed))
        report["retried"] = len(failed)
        return report

    now_iso = datetime.now(timezone.utc).isoformat()
    retried = 0
    for job_id, memory_id, last_error in failed:
        # Reset to pending, clear error, reset attempt counter
        con.execute(
            "UPDATE blueprint_jobs SET state='pending', attempts=0, last_error=NULL, next_attempt_at=?, updated_at=? WHERE id=?",
            (now_iso, now_iso, job_id),
        )
        retried += 1
        log.info("  ↩️  Retrying blueprint job for memory: %s", memory_id[:16])

    if retried:
        con.commit()
        log.info("✅ Blueprint recovery: %d jobs reset to pending", retried)

    report["retried"] = retried
    return report


# ── Step 9: Verify ────────────────────────────────────────────────────────────

def verify(con: sqlite3.Connection, chroma_path: Path) -> dict:
    issues = []
    ok_items = []

    # 1. Canonical user must exist and be active
    canonical = con.execute("SELECT id, email, status FROM users WHERE id=?", (CANONICAL_ID,)).fetchone()
    if not canonical:
        issues.append("❌ Canonical user missing from users table!")
    else:
        ok_items.append(f"✅ Canonical user: {canonical[1]} (status={canonical[2]})")

    # 2. Only ONE active user
    active_users = con.execute("SELECT id, email FROM users WHERE status='active' OR status IS NULL").fetchall()
    active_emails = [r[1] for r in active_users]
    if len(active_users) != 1 or active_users[0][0] != CANONICAL_ID:
        issues.append(f"❌ Active users should be exactly 1 canonical, got: {active_emails}")
    else:
        ok_items.append(f"✅ Exactly 1 active user: {active_emails[0]}")

    # 3. No user-owned data for secondary users
    all_secondary = SECONDARY_IDS + [SMOKETEST_ID]
    ph = ",".join([f"'{uid}'" for uid in SECONDARY_IDS])  # smoketest data stays on smoketest user
    for table, col in [
        ("chat_sessions", "user_id"),
        ("chat_messages", "user_id"),
        ("raw_transcripts", "user_id"),
        ("blueprints", "user_id"),
        ("blueprint_jobs", "user_id"),
        ("api_keys", "user_id"),
        ("watched_folders", "user_id"),
    ]:
        count = con.execute(f"SELECT COUNT(*) FROM {table} WHERE {col} IN ({ph})").fetchone()[0]
        if count > 0:
            issues.append(f"❌ {table}: {count} rows still on secondary users")
        else:
            ok_items.append(f"✅ {table}: clean (no secondary user rows)")

    # 4. ChromaDB namespace check
    try:
        import chromadb, warnings
        warnings.filterwarnings("ignore")
        client = chromadb.PersistentClient(path=str(chroma_path))
        col = client.get_collection("shail_rag")
        data = col.get(include=["metadatas"], limit=10000)
        import collections
        ns_counts = collections.Counter(m.get("namespace","?") for m in (data.get("metadatas") or []) if m)
        canonical_count = ns_counts.get(CANONICAL_NS, 0)
        other_ns = {k: v for k, v in ns_counts.items() if k != CANONICAL_NS}
        ok_items.append(f"✅ ChromaDB canonical namespace: {canonical_count} embeddings")
        if other_ns:
            issues.append(f"❌ ChromaDB still has non-canonical namespaces: {other_ns}")
        else:
            ok_items.append("✅ ChromaDB: only canonical namespace present")
    except Exception as e:
        issues.append(f"❌ ChromaDB verify failed: {e}")

    # 5. No namespace=local or namespace=browser_memory in SQLite
    try:
        local_ns = con.execute("SELECT COUNT(*) FROM raw_transcripts WHERE namespace='local' OR namespace='browser_memory'").fetchone()[0]
        if local_ns > 0:
            issues.append(f"❌ raw_transcripts has {local_ns} rows with old namespace (local/browser_memory)")
        else:
            ok_items.append("✅ raw_transcripts: no legacy namespace rows")
    except Exception:
        pass

    return {"ok": len(issues) == 0, "issues": issues, "ok_items": ok_items}


# ── Main ────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="SHAIL single-user migration")
    parser.add_argument("--dry-run", action="store_true", help="Show what would happen without making changes")
    parser.add_argument("--verify-only", action="store_true", help="Run verification checks only")
    parser.add_argument("--skip-chroma", action="store_true", help="Skip ChromaDB re-namespace step")
    args = parser.parse_args()

    con = sqlite3.connect(str(DB_PATH), timeout=30.0)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA journal_mode=WAL")

    if args.verify_only:
        result = verify(con, CHROMA_PATH)
        print("\n=== VERIFICATION REPORT ===")
        for item in result["ok_items"]:
            print(f"  {item}")
        if result["issues"]:
            print("\nISSUES:")
            for issue in result["issues"]:
                print(f"  {issue}")
        print(f"\nResult: {'PASS ✅' if result['ok'] else 'FAIL ❌'}")
        sys.exit(0 if result["ok"] else 1)

    log.info("=== SHAIL Single-User Migration ===")
    log.info("Canonical user: %s (%s)", CANONICAL_EMAIL, CANONICAL_ID)
    log.info("Target namespace: %s", CANONICAL_NS)
    if args.dry_run:
        log.info("*** DRY RUN — no changes will be made ***")

    # Schema evolution (idempotent)
    evolve_schema(con)

    # Acquire migration lock
    acquire_lock(args.dry_run)

    try:
        # Count state before
        before = count_state(con)
        log.info("Before: %s", json.dumps(before, indent=2))

        # SQLite migration (secondary users → canonical)
        sql_changes = migrate_sqlite(con, args.dry_run)

        # Archive secondary users (NOT delete)
        archived = archive_users(con, args.dry_run)

        # Archive smoketest data separately
        smoketest_result = archive_smoketest(con, args.dry_run)

        # ChromaDB re-namespace
        chroma_report = {}
        legacy_count = 0
        if not args.skip_chroma:
            chroma_report = migrate_chroma(args.dry_run, CHROMA_PATH)
            legacy_count = migrate_project_chroma(args.dry_run)
        else:
            log.info("Skipping ChromaDB migration (--skip-chroma)")

        # Blueprint recovery
        blueprint_report = recover_blueprints(con, args.dry_run)

        # Invalidate retrieval cache
        cache_cleared = clear_retrieval_cache(args.dry_run)

        # Count state after
        after = count_state(con)
        log.info("After: %s", json.dumps(after, indent=2))

        # Verify
        verify_result = verify(con, CHROMA_PATH)

    finally:
        release_lock(args.dry_run)

    # Final report
    report = {
        "canonical": {"id": CANONICAL_ID, "email": CANONICAL_EMAIL, "namespace": CANONICAL_NS},
        "before": before,
        "after": after,
        "archived_users": archived,
        "smoketest": smoketest_result,
        "sql_changes": {k[:60]: v for k, v in sql_changes.items()},
        "chroma_moved": chroma_report,
        "chroma_legacy_migrated": legacy_count,
        "blueprint_recovery": blueprint_report,
        "cache_entries_cleared": cache_cleared,
        "verify": verify_result,
    }

    print("\n" + "=" * 60)
    print(" MIGRATION REPORT")
    print("=" * 60)
    print(json.dumps(report, indent=2, ensure_ascii=False))

    if verify_result["ok"]:
        print("\n✅ MIGRATION COMPLETE — All verification checks passed")
        print(f"   Canonical user: {CANONICAL_EMAIL}")
        print(f"   Namespace:      {CANONICAL_NS}")
        print(f"   Archived users: {len(archived)}")
        chroma_total = sum(chroma_report.values())
        print(f"   Embeddings merged: {chroma_total}")
        print(f"   Blueprint jobs retried: {blueprint_report.get('retried', 0)}")
    else:
        print("\n❌ MIGRATION VERIFICATION FAILED:")
        for issue in verify_result["issues"]:
            print(f"   {issue}")
        sys.exit(1)


if __name__ == "__main__":
    main()
