from __future__ import annotations

import logging
from typing import Iterable

logger = logging.getLogger(__name__)


def _scoped_where(namespace: str, field: str, value: str) -> dict:
    return {"$and": [{"namespace": namespace}, {field: value}]}


def _ids_for_where(store, where: dict) -> set[str]:
    try:
        result = store.collection.get(where=where, include=[])
        return set(result.get("ids", []) or [])
    except Exception as exc:
        logger.warning("memory delete lookup failed for %s: %s", where, exc)
        return set()


def _metadata_for_id(store, memory_id: str, namespaces: Iterable[str]) -> dict | None:
    for namespace in namespaces:
        try:
            result = store.collection.get(
                ids=[memory_id],
                where={"namespace": namespace},
                include=["metadatas"],
            )
        except Exception as exc:
            logger.warning("memory ownership lookup failed for %s in %s: %s", memory_id, namespace, exc)
            continue
        if result.get("ids"):
            metas = result.get("metadatas") or [{}]
            return metas[0] or {}
    return None


def _logical_id_from_metadata(requested_id: str, metadata: dict | None) -> str:
    if not metadata:
        return requested_id
    return (
        metadata.get("customId")
        or metadata.get("parent_memory_id")
        or metadata.get("id")
        or requested_id
    )


def collect_memory_delete_ids(
    store,
    requested_id: str,
    namespaces: Iterable[str],
) -> tuple[str, set[str]]:
    """Return the logical memory id and every vector row that belongs to it.

    A single captured memory may be represented as one parent row plus many
    chunk rows. Chunk rows are keyed with ids such as `memory#000`, while their
    metadata keeps `customId` / `parent_memory_id` pointing back to the logical
    memory. Deleting only the clicked row leaves the rest visible after refresh.
    """
    namespaces = list(dict.fromkeys(ns for ns in namespaces if ns))
    metadata = _metadata_for_id(store, requested_id, namespaces)
    logical_id = _logical_id_from_metadata(requested_id, metadata)

    ids: set[str] = set()
    for namespace in namespaces:
        try:
            direct_ids = list(dict.fromkeys([requested_id, logical_id]))
            direct = store.collection.get(
                ids=direct_ids,
                where={"namespace": namespace},
                include=[],
            )
            ids.update(direct.get("ids", []) or [])
        except Exception as exc:
            logger.warning("direct memory delete lookup failed in %s: %s", namespace, exc)

        ids.update(_ids_for_where(store, _scoped_where(namespace, "customId", logical_id)))
        ids.update(_ids_for_where(store, _scoped_where(namespace, "parent_memory_id", logical_id)))

    return logical_id, ids


def delete_memory_everywhere(
    store,
    requested_id: str,
    namespaces: Iterable[str],
) -> tuple[str, set[str]]:
    """Delete a logical memory from vector, capture, transcript, and blueprint stores."""
    logical_id, ids = collect_memory_delete_ids(store, requested_id, namespaces)
    if not ids:
        return logical_id, set()

    store.delete_ids(sorted(ids))

    try:
        from apps.shail.capture_store import delete_memory_state

        delete_memory_state(logical_id)
    except Exception as exc:
        logger.warning("capture cascade delete failed for %s: %s", logical_id, exc)

    try:
        from apps.shail.raw_transcripts import delete as delete_raw_transcript

        delete_raw_transcript(logical_id)
    except Exception as exc:
        logger.warning("raw transcript cascade delete failed for %s: %s", logical_id, exc)

    try:
        from apps.shail.blueprints import delete_blueprint

        delete_blueprint(logical_id)
    except Exception as exc:
        logger.warning("blueprint cascade delete failed for %s: %s", logical_id, exc)

    return logical_id, ids
