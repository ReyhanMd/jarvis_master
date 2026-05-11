"""Regression tests for Sprint 2 — Memory Reliability.

Covers:
  • Provenance schema + trust scoring
  • Semantic dedup correctness + concurrency
  • Dead-letter queue: record, retry, quarantine, recover
  • Usefulness feedback: registration, eval, reranking
  • RRF fusion ranking + determinism
  • Telemetry bridge
  • Shared context worker-node integration (mocked)
"""
from __future__ import annotations

import os
import sys
import tempfile
import threading
import time
import uuid
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

_ROOT = Path(__file__).parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))


# ─────────────────────────────────────────────────────────────────────── #
# Provenance                                                                 #
# ─────────────────────────────────────────────────────────────────────── #

def test_provenance_trust_score_user_higher_than_legacy():
    from shail.memory.provenance import build_provenance, SOURCE_USER, SOURCE_LEGACY
    user_prov = build_provenance(source_type=SOURCE_USER)
    legacy_prov = build_provenance(source_type=SOURCE_LEGACY)
    assert user_prov.trust_score() > legacy_prov.trust_score()


def test_provenance_failure_lowers_trust():
    from shail.memory.provenance import build_provenance, SOURCE_AGENT, merge_feedback
    p = build_provenance(source_type=SOURCE_AGENT)
    base = p.trust_score()
    for _ in range(5):
        p = merge_feedback(p, usefulness_delta=0.4, failure=True)
    assert p.trust_score() < base
    assert p.failure_count == 5


def test_provenance_useful_feedback_raises_trust():
    from shail.memory.provenance import build_provenance, SOURCE_AGENT, merge_feedback
    p = build_provenance(source_type=SOURCE_AGENT)
    base = p.trust_score()
    for _ in range(10):
        p = merge_feedback(p, usefulness_delta=0.9)
    assert p.trust_score() > base


def test_provenance_attach_extract_roundtrip():
    from shail.memory.provenance import (
        build_provenance, attach_provenance, extract_provenance, SOURCE_USER,
    )
    prov = build_provenance(source_type=SOURCE_USER, task_id="task-xyz", generated_by="alice")
    meta = attach_provenance({"foo": "bar"}, prov)
    assert meta["foo"] == "bar"
    assert meta["trust_score"] > 0.5
    extracted = extract_provenance(meta)
    assert extracted.source_type == SOURCE_USER
    assert extracted.task_id == "task-xyz"
    assert extracted.generated_by == "alice"


def test_provenance_legacy_metadata_fallback():
    from shail.memory.provenance import extract_provenance, SOURCE_LEGACY
    p = extract_provenance({"foo": "bar"})  # no provenance key
    assert p.source_type == SOURCE_LEGACY


# ─────────────────────────────────────────────────────────────────────── #
# Semantic Dedup                                                              #
# ─────────────────────────────────────────────────────────────────────── #

@pytest.fixture
def temp_dedup_db(tmp_path):
    return str(tmp_path / "dedup.db")


def test_semantic_dedup_exact_match(temp_dedup_db):
    from shail.memory.semantic_dedup import SemanticDedup
    d = SemanticDedup(db_path=temp_dedup_db, window_size=10, threshold=0.95)
    emb = [1.0, 0.0, 0.0, 0.0]
    d.record("hello world", "ns1", emb)
    is_dup, sim, _ = d.is_duplicate("hello world", "ns1", emb)
    assert is_dup
    assert sim == 1.0


def test_semantic_dedup_near_duplicate(temp_dedup_db):
    from shail.memory.semantic_dedup import SemanticDedup
    d = SemanticDedup(db_path=temp_dedup_db, window_size=10, threshold=0.95)
    a = [1.0, 0.0, 0.0]
    b = [0.99, 0.01, 0.0]   # cosine ~0.999
    d.record("text a", "ns1", a)
    is_dup, sim, _ = d.is_duplicate("text b — different words", "ns1", b)
    assert is_dup
    assert sim > 0.99


def test_semantic_dedup_not_duplicate_dissimilar(temp_dedup_db):
    from shail.memory.semantic_dedup import SemanticDedup
    d = SemanticDedup(db_path=temp_dedup_db, window_size=10, threshold=0.95)
    a = [1.0, 0.0, 0.0]
    b = [0.0, 1.0, 0.0]  # orthogonal — cosine = 0
    d.record("alpha", "ns1", a)
    is_dup, sim, _ = d.is_duplicate("beta", "ns1", b)
    assert not is_dup
    assert sim < 0.1


def test_semantic_dedup_namespace_isolation(temp_dedup_db):
    from shail.memory.semantic_dedup import SemanticDedup
    d = SemanticDedup(db_path=temp_dedup_db, window_size=10, threshold=0.95)
    emb = [1.0, 0.0]
    d.record("text", "ns_a", emb)
    is_dup, _, _ = d.is_duplicate("text", "ns_b", emb)  # diff namespace
    assert not is_dup


def test_semantic_dedup_window_eviction(temp_dedup_db):
    from shail.memory.semantic_dedup import SemanticDedup
    d = SemanticDedup(db_path=temp_dedup_db, window_size=2, threshold=0.95)
    d.record("a", "ns", [1.0, 0.0])
    d.record("b", "ns", [0.0, 1.0])
    d.record("c", "ns", [0.5, 0.5])
    # "a" should be evicted from in-memory window
    window = d._get_window("ns")
    assert len(window) == 2


def test_semantic_dedup_persistence_across_instances(temp_dedup_db):
    from shail.memory.semantic_dedup import SemanticDedup
    d1 = SemanticDedup(db_path=temp_dedup_db, window_size=10, threshold=0.95)
    d1.record("hello", "ns", [1.0, 0.0])

    d2 = SemanticDedup(db_path=temp_dedup_db, window_size=10, threshold=0.95)
    is_dup, sim, _ = d2.is_duplicate("hello", "ns", [1.0, 0.0])
    assert is_dup


# ─────────────────────────────────────────────────────────────────────── #
# Dead-letter queue                                                           #
# ─────────────────────────────────────────────────────────────────────── #

@pytest.fixture
def temp_dlq_db(tmp_path):
    return str(tmp_path / "dlq.db")


def test_dead_letter_record_and_list(temp_dlq_db):
    from shail.memory.dead_letter import DeadLetterQueue
    dlq = DeadLetterQueue(db_path=temp_dlq_db)
    rid = dlq.record("bad content", {"task_id": "t1"}, "embedding failed", "ns1")
    assert rid > 0
    pending = dlq.list_pending()
    assert len(pending) == 1
    assert pending[0]["content"] == "bad content"
    assert pending[0]["error_msg"] == "embedding failed"
    assert pending[0]["status"] == "pending"


def test_dead_letter_quarantine_after_max_attempts(temp_dlq_db):
    from shail.memory.dead_letter import DeadLetterQueue, MAX_ATTEMPTS, STATUS_QUARANTINED
    dlq = DeadLetterQueue(db_path=temp_dlq_db)
    for _ in range(MAX_ATTEMPTS):
        dlq.record("same content", {}, "fail", "ns")
    quarantined = dlq.list_quarantined()
    assert len(quarantined) == 1
    assert quarantined[0]["status"] == STATUS_QUARANTINED
    assert quarantined[0]["attempt_count"] >= MAX_ATTEMPTS


def test_dead_letter_mark_recovered(temp_dlq_db):
    from shail.memory.dead_letter import DeadLetterQueue, STATUS_RECOVERED
    dlq = DeadLetterQueue(db_path=temp_dlq_db)
    rid = dlq.record("c", {}, "e", "ns")
    dlq.mark_recovered(rid)
    stats = dlq.stats()
    assert stats.get(STATUS_RECOVERED, 0) == 1
    assert len(dlq.list_pending()) == 0


# ─────────────────────────────────────────────────────────────────────── #
# Usefulness                                                                  #
# ─────────────────────────────────────────────────────────────────────── #

@pytest.fixture
def temp_usefulness_db(tmp_path, monkeypatch):
    from shail.memory import usefulness as _u
    _u.reset_for_tests()
    db = str(tmp_path / "u.db")
    # Patch settings to point at temp db
    from apps.shail.settings import Settings
    monkeypatch.setattr(Settings, "usefulness_db", db, raising=False)
    yield db
    _u.reset_for_tests()


def test_usefulness_record_and_retrieve(temp_usefulness_db):
    from shail.memory.usefulness import UsefulnessStore
    s = UsefulnessStore(db_path=temp_usefulness_db)
    s.record("mem-1", score=0.8)
    s.record("mem-1", score=0.6)
    mean, count = s.get("mem-1")
    assert count == 2
    assert 0.69 < mean < 0.71  # (0.8 + 0.6) / 2


def test_usefulness_unknown_memory_returns_neutral(temp_usefulness_db):
    from shail.memory.usefulness import UsefulnessStore
    s = UsefulnessStore(db_path=temp_usefulness_db)
    mean, count = s.get("never-seen")
    assert mean == 0.5
    assert count == 0


def test_usefulness_failure_increments_failure_count(temp_usefulness_db):
    from shail.memory.usefulness import UsefulnessStore
    s = UsefulnessStore(db_path=temp_usefulness_db)
    s.record("mem-x", score=0.2, failure=True)
    s.record("mem-x", score=0.3, failure=True)
    # Pull raw row
    import sqlite3
    with sqlite3.connect(temp_usefulness_db) as c:
        row = c.execute("SELECT failure_count FROM memory_usefulness WHERE memory_id='mem-x'").fetchone()
    assert row[0] == 2


def test_usefulness_record_retrieval_and_evaluate(temp_usefulness_db):
    from shail.memory.usefulness import record_retrieval, evaluate_task, get_usefulness
    hits = [
        ("Python uses dynamic typing", 0.9, {"memory_id": "mem-A"}),
        ("Functional programming basics", 0.7, {"memory_id": "mem-B"}),
    ]
    task_id = "task-test-1"
    record_retrieval(task_id, hits)
    # Summary contains tokens overlapping mem-A but not mem-B
    n = evaluate_task(task_id, "Python uses dynamic typing for variables", success=True)
    assert n == 2
    mean_a, _ = get_usefulness("mem-A")
    mean_b, _ = get_usefulness("mem-B")
    # mem-A has stronger lexical overlap → higher score
    assert mean_a > mean_b


def test_usefulness_apply_boost_reranks(temp_usefulness_db, monkeypatch):
    from shail.memory import usefulness as _u
    from shail.memory.usefulness import UsefulnessStore, apply_usefulness_boost
    # Force the singleton to point at our temp DB
    test_store = UsefulnessStore(db_path=temp_usefulness_db)
    monkeypatch.setattr(_u, "_store", test_store)
    # mem-low retrieved 10 times with score 0.1 → low usefulness
    # mem-high retrieved 10 times with score 0.9 → high usefulness
    for _ in range(10):
        test_store.record("mem-low", score=0.1)
        test_store.record("mem-high", score=0.9)

    hits = [
        ("A", 0.5, {"memory_id": "mem-low"}),
        ("B", 0.5, {"memory_id": "mem-high"}),
    ]
    reranked = apply_usefulness_boost(hits, boost_weight=0.5)
    # mem-high should be first after reranking
    assert reranked[0][2]["memory_id"] == "mem-high"


# ─────────────────────────────────────────────────────────────────────── #
# RRF Fusion                                                                  #
# ─────────────────────────────────────────────────────────────────────── #

class _FakeExactHit:
    """Minimal ExactHit stand-in so the test doesn't need to import the real one."""
    def __init__(self, memory_id, fact_id, score, surface="exact"):
        self.memory_id = memory_id
        self.fact_id = fact_id
        self.score = score
        self.surface = surface
        self.entity = "Entity"
        self.attribute = "attr"
        self.value = "value"
        self.value_num = None
        self.unit = None
        self.period = None
        self.source_span = None


def test_rrf_fusion_deterministic_ranking():
    pytest.importorskip("apps.shail.exact_index")
    from apps.shail.retrieval.fusion import fuse
    exact = [_FakeExactHit("mem-1", "fact-1", 0.9)]
    semantic = [
        ("text-1", 0.95, {"memory_id": "mem-1"}),
        ("text-2", 0.10, {"memory_id": "mem-2"}),
    ]
    weights = {"exact": 0.5, "semantic": 0.5}

    out1 = fuse(exact, semantic, weights=weights, k=10, mode="rrf")
    out2 = fuse(exact, semantic, weights=weights, k=10, mode="rrf")
    # Same input → identical ranking
    assert [h.memory_id for h in out1] == [h.memory_id for h in out2]


def test_rrf_fusion_scale_independent():
    """Multiplying all semantic scores by 1000 must NOT change RRF ranking."""
    from apps.shail.retrieval.fusion import fuse
    semantic_1 = [
        ("A", 0.8, {"memory_id": "a"}),
        ("B", 0.5, {"memory_id": "b"}),
        ("C", 0.1, {"memory_id": "c"}),
    ]
    semantic_2 = [
        ("A", 800.0, {"memory_id": "a"}),
        ("B", 500.0, {"memory_id": "b"}),
        ("C", 100.0, {"memory_id": "c"}),
    ]
    weights = {"exact": 0.5, "semantic": 0.5}
    out1 = [h.memory_id for h in fuse([], semantic_1, weights=weights, k=10, mode="rrf")]
    out2 = [h.memory_id for h in fuse([], semantic_2, weights=weights, k=10, mode="rrf")]
    assert out1 == out2


def test_rrf_fusion_fused_items_outrank_singletons():
    """Item appearing in TWO surfaces should outrank singletons."""
    from apps.shail.retrieval.fusion import fuse
    exact = [_FakeExactHit("mem-shared", "fact-1", 0.5)]
    semantic = [
        ("text-shared", 0.5, {"memory_id": "mem-shared"}),
        ("text-other",  0.99, {"memory_id": "mem-other"}),
    ]
    weights = {"exact": 0.5, "semantic": 0.5}
    out = fuse(exact, semantic, weights=weights, k=10, mode="rrf")
    # mem-shared appears in both surfaces; gets contributions from both
    ranks = {h.memory_id: i for i, h in enumerate(out)}
    assert ranks["mem-shared"] < ranks["mem-other"]


def test_weighted_mode_still_works():
    from apps.shail.retrieval.fusion import fuse
    semantic = [("A", 0.9, {"memory_id": "a"}), ("B", 0.1, {"memory_id": "b"})]
    out = fuse([], semantic, weights={"exact": 0.5, "semantic": 0.5}, k=10, mode="weighted")
    assert out[0].memory_id == "a"


# ─────────────────────────────────────────────────────────────────────── #
# Telemetry bridge                                                            #
# ─────────────────────────────────────────────────────────────────────── #

def test_telemetry_incr_still_works_after_bridge_install():
    from apps.shail import telemetry
    telemetry.reset()
    telemetry.incr("test.counter", value=3.0, label="x")
    snap = telemetry.snapshot()
    key = next(k for k in snap["counters"] if k.startswith("test.counter"))
    assert snap["counters"][key] == 3.0


def test_bridge_install_idempotent():
    from shail.observability.bridge import install_bridge
    install_bridge()
    install_bridge()  # second call must not raise


# ─────────────────────────────────────────────────────────────────────── #
# Concurrent stress                                                           #
# ─────────────────────────────────────────────────────────────────────── #

def test_dedup_concurrent_records(tmp_path):
    from shail.memory.semantic_dedup import SemanticDedup
    d = SemanticDedup(db_path=str(tmp_path / "d.db"), window_size=100, threshold=0.95)

    errors = []
    def _worker(i):
        try:
            for j in range(20):
                d.record(f"content-{i}-{j}", "ns", [float(i), float(j), 0.0])
        except BaseException as exc:
            errors.append(exc)

    threads = [threading.Thread(target=_worker, args=(i,)) for i in range(4)]
    for t in threads: t.start()
    for t in threads: t.join()
    assert not errors


def test_dead_letter_concurrent_records(tmp_path):
    from shail.memory.dead_letter import DeadLetterQueue
    dlq = DeadLetterQueue(db_path=str(tmp_path / "dlq.db"))

    errors = []
    def _worker(i):
        try:
            for j in range(10):
                dlq.record(f"content-{i}-{j}", {}, "fail", "ns")
        except BaseException as exc:
            errors.append(exc)

    threads = [threading.Thread(target=_worker, args=(i,)) for i in range(4)]
    for t in threads: t.start()
    for t in threads: t.join()
    assert not errors
    pending = dlq.list_pending(limit=100)
    quar    = dlq.list_quarantined(limit=100)
    assert len(pending) + len(quar) > 0
