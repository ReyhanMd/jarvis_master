"""
One-shot Chroma dedup for pre-Sprint-1 fragmented captures.

Problem: before canonical session continuity (Sprint 1), the extension
sometimes wrote multiple Chroma records for the same conversation
(different content-hash customIds across turns). After Sprint 1 every turn
upserts to a single conversationId-derived record, so any group of >1
records sharing the same conversationId is fragmentation residue.

Strategy: group by metadata.conversationId. Skip records with empty/missing
conversationId (page_visits + legacy captures — different days are not
duplicates). Within each group, keep the newest by captured_ts and delete
the rest. Cascade-delete blueprints by memory_id.

Idempotent. Dry-run by default. Pass `--apply` to commit.

Usage:
  cd ~/jarvis_master
  source services_env/bin/activate
  python scripts/deduplicate_chroma.py            # preview
  python scripts/deduplicate_chroma.py --apply    # delete
"""

from __future__ import annotations

import os
import sys
from collections import defaultdict
from typing import Optional

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from shail.memory.rag import _get_store


def _parse_ts(raw) -> float:
    try:
        return float(raw) if raw is not None else 0.0
    except (TypeError, ValueError):
        return 0.0


def _scan(store) -> tuple[dict[str, list[tuple[str, dict]]], int]:
    """Return ({conversationId: [(id, meta), ...]}, total_records_scanned)."""
    if not hasattr(store, "collection"):
        return {}, 0
    raw = store.collection.get(include=["metadatas"])
    ids = raw.get("ids") or []
    metas = raw.get("metadatas") or []
    groups: dict[str, list[tuple[str, dict]]] = defaultdict(list)
    for rid, meta in zip(ids, metas):
        m = dict(meta or {})
        conv = (m.get("conversationId") or "").strip()
        if not conv:
            continue
        groups[conv].append((rid, m))
    return groups, len(ids)


def _resolve_dups(
    groups: dict[str, list[tuple[str, dict]]],
) -> tuple[list[tuple[str, str, str]], dict[str, int]]:
    """For each group with >1 records, keep newest-by-captured_ts and mark
    others for deletion. Returns ([(victim_id, kept_id, namespace), ...],
    per-namespace deletion counts).
    """
    victims: list[tuple[str, str, str]] = []
    per_ns_count: dict[str, int] = defaultdict(int)
    for conv, items in groups.items():
        if len(items) <= 1:
            continue
        items_sorted = sorted(items, key=lambda x: _parse_ts(x[1].get("captured_ts")), reverse=True)
        keep_id, keep_meta = items_sorted[0]
        keep_ns = (keep_meta.get("namespace") or "").strip() or "<unknown>"
        for victim_id, victim_meta in items_sorted[1:]:
            ns = (victim_meta.get("namespace") or "").strip() or "<unknown>"
            victims.append((victim_id, keep_id, ns))
            per_ns_count[ns] += 1
    return victims, dict(per_ns_count)


def _print_preview(victims: list[tuple[str, str, str]], total: int, group_count: int) -> None:
    print(f"scanned {total} records; {group_count} conversationId groups; "
          f"{len(victims)} duplicates would be deleted")
    if not victims:
        return
    print()
    print(f"{'VICTIM':<24} {'KEEP':<24} {'NAMESPACE':<24}")
    print("-" * 76)
    for v_id, k_id, ns in victims[:50]:
        print(f"{v_id[:22]:<24} {k_id[:22]:<24} {ns[:22]:<24}")
    if len(victims) > 50:
        print(f"... and {len(victims) - 50} more")


def _apply(store, victims: list[tuple[str, str, str]]) -> None:
    if not victims:
        print("nothing to delete.")
        return
    try:
        from apps.shail.blueprints import delete_blueprint
    except Exception:
        delete_blueprint = None  # cascade is best-effort

    victim_ids = [v for v, _, _ in victims]
    store.collection.delete(ids=victim_ids)
    print(f"deleted {len(victim_ids)} chroma records")

    if delete_blueprint is not None:
        bp_deleted = 0
        for v_id in victim_ids:
            try:
                delete_blueprint(v_id)
                bp_deleted += 1
            except Exception:
                pass
        print(f"cascade: cleared {bp_deleted} blueprint rows (best-effort)")


def main(argv: Optional[list[str]] = None) -> int:
    args = argv if argv is not None else sys.argv[1:]
    apply = "--apply" in args

    store = _get_store()
    groups, total = _scan(store)
    victims, per_ns = _resolve_dups(groups)

    _print_preview(victims, total=total, group_count=len(groups))

    if per_ns:
        print()
        print("per-namespace deletion counts:")
        for ns, n in sorted(per_ns.items()):
            print(f"  {ns:<32} {n}")

    if not apply:
        print()
        print("dry-run. re-run with --apply to delete.")
        return 0

    print()
    _apply(store, victims)
    return 0


if __name__ == "__main__":
    sys.exit(main())
