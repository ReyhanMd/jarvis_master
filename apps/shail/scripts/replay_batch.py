"""Selective replay driver.

Iterates capture artifacts matching --kind/--since filters, runs each through
shadow materialization, validates determinism, and (optionally) promotes when
the bundle version matches a feature-flag whitelist.

Usage:
    python -m apps.shail.scripts.replay_batch --kind github_diff_capture --limit 10
    python -m apps.shail.scripts.replay_batch --kind html_table_capture --promote --namespace user_alice
"""

from __future__ import annotations

import argparse
import asyncio
from typing import Optional

from apps.shail import capture_store
from apps.shail.settings import get_settings


PROMOTABLE_KINDS = {
    "normalized_text_capture": "semantic_chunk_promotion_enabled",
    "github_diff_capture": "github_diff_capture_enabled",
    "pdf_document": "pdf_extraction_enabled",
    "pdf_stub": "pdf_extraction_enabled",
    "html_table_capture": "structured_dom_capture_enabled",
    "dashboard_capture": "structured_dom_capture_enabled",
    "chart_capture": "structured_dom_capture_enabled",
}


def _kind_promotable(kind: str) -> bool:
    flag = PROMOTABLE_KINDS.get(kind)
    if not flag:
        return False
    return bool(getattr(get_settings(), flag, False))


async def _run(kind: str, since: Optional[str], limit: Optional[int], namespace: str, promote: bool) -> dict:
    if promote and not _kind_promotable(kind):
        raise SystemExit(
            f"Refusing to promote: feature flag for kind={kind} is OFF. Flip the SHAIL_* env first."
        )
    job_id = capture_store.create_replay_job(
        mode="promote" if promote else "shadow",
        scope_type="artifact_kind",
        scope_ref=kind,
        options={"since": since, "limit": limit},
    )
    job = await capture_store.run_replay_job(job_id, user_id=None, namespace=namespace)
    return job or {"status": "missing", "replay_job_id": job_id}


def main() -> None:
    parser = argparse.ArgumentParser(description="Run a selective replay batch.")
    parser.add_argument("--kind", required=True, help="artifact_kind to replay")
    parser.add_argument("--since", default=None, help="ISO timestamp filter")
    parser.add_argument("--limit", type=int, default=None, help="Max artifacts to replay")
    parser.add_argument("--namespace", default="anonymous", help="Vector store namespace")
    parser.add_argument("--promote", action="store_true", help="Promote after shadow validation")
    args = parser.parse_args()

    job = asyncio.run(_run(args.kind, args.since, args.limit, args.namespace, args.promote))
    print(f"replay_job_id={job.get('replay_job_id')} status={job.get('status')} items={len(job.get('items', []))}")


if __name__ == "__main__":
    main()
