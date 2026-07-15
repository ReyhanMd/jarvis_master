from __future__ import annotations


def test_ollama_payload_normalization_stores_atoms_not_full_text():
    from apps.shail import local_semantics_jobs

    row = {"id": "file-1", "path": "/tmp/approved.txt", "content_hash": "sha256:abc"}
    payload = {
        "entities": [{"label": "Reyhan", "entity_type": "person", "source_span": "Reyhan approved", "confidence": "EXTRACTED"}],
        "facts": [{"entity": "Project", "attribute": "budget", "value": "$10M", "value_num": "10000000", "unit": "USD", "source_span": "budget $10M"}],
        "tasks": [{"text": "Send invoice", "status": "open", "source_span": "Send invoice"}],
    }

    out = local_semantics_jobs._normalize_payload(payload, row=row, chunk_index=2, model="test-model")

    assert out["entities"][0]["metadata"]["extractor"] == "ollama"
    assert out["facts"][0]["value_num"] == 10000000.0
    assert out["tasks"][0]["metadata"]["chunk_index"] == 2
    assert "full text" not in str(out).lower()


def test_ollama_chunking_respects_overlap_and_budget():
    from apps.shail import local_semantics_jobs

    text = "abcdefghijklmnopqrstuvwxyz"
    chunks = local_semantics_jobs._chunk_text(text, max_chars=10, overlap=2)

    assert chunks[0] == "abcdefghij"
    assert chunks[1].startswith("ij")
    assert "".join(chunk[:1] for chunk in chunks)


def test_invalid_confidence_falls_back_to_inferred():
    from apps.shail import local_semantics_jobs

    row = {"id": "file-1", "path": "/tmp/approved.txt", "content_hash": "sha256:abc"}
    payload = {"facts": [{"entity": "Doc", "attribute": "decision", "value": "approved", "confidence": "VERY SURE"}]}

    out = local_semantics_jobs._normalize_payload(payload, row=row, chunk_index=0, model="test-model")

    assert out["facts"][0]["confidence"] == "INFERRED"
