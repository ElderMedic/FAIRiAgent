"""§12.1 EvidenceStore upsert/dedupe by stable evidence_id."""

from pathlib import Path

from fairifier.services.evidence_packets import evidence_packet_dedupe_key
from fairifier.services.evidence_store import EvidenceStore, stable_evidence_id


def test_stable_evidence_id_prefers_span_and_field():
    record = {
        "source_id": "src-1",
        "char_start": 10,
        "char_end": 40,
        "field_candidate": "sample temperature",
        "value": "4 °C",
        "produced_by": "section_map_reduce",
    }
    eid = stable_evidence_id(record)
    assert eid
    assert stable_evidence_id(record) == eid
    # packet_id changes must not change the stable evidence identity.
    other = dict(record)
    other["packet_id"] = "different-packet"
    assert stable_evidence_id(other) == eid


def test_evidence_store_upsert_deduplicates_and_preserves_count(tmp_path: Path):
    store = EvidenceStore(tmp_path)
    first = {
        "source_id": "src-1",
        "char_start": 0,
        "char_end": 20,
        "field_candidate": "title",
        "value": "Cold stress",
        "produced_by": "section_map_reduce",
        "evidence_text": "Cold stress study",
    }
    second = dict(first)
    second["packet_id"] = "p2"
    third = {
        "source_id": "src-1",
        "char_start": 100,
        "char_end": 140,
        "field_candidate": "organism",
        "value": "Pisum sativum",
        "produced_by": "DocumentParser",
        "evidence_text": "organism Pisum sativum",
    }

    added = store.upsert_many([first, second, third])
    assert added == 2
    assert len(store.records()) == 2
    assert all(r.get("evidence_id") for r in store.records())

    # Reloading and upserting the same records must not grow the store.
    store2 = EvidenceStore(tmp_path)
    store2.load_existing()
    assert len(store2.records()) == 2
    added_again = store2.upsert_many([first, third])
    assert added_again == 0
    assert len(store2.records()) == 2


def test_evidence_packet_dedupe_key_aligns_with_evidence_id_inputs():
    packet = {
        "source_id": "s",
        "char_start": 1,
        "char_end": 2,
        "field_candidate": "title",
        "value": "X",
        "produced_by": "DocumentParser",
    }
    assert evidence_packet_dedupe_key(packet)
    assert stable_evidence_id(packet)
