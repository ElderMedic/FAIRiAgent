import csv
import importlib.util
import sys
from pathlib import Path


def _load_exporter():
    path = (
        Path(__file__).resolve().parents[1]
        / "evaluation"
        / "prototypes"
        / "auto_repair_classifier"
        / "export_shadow_predictions.py"
    )
    module_dir = str(path.parent)
    if module_dir not in sys.path:
        sys.path.insert(0, module_dir)
    spec = importlib.util.spec_from_file_location("auto_prediction_export", path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _row(**overrides):
    row = {
        "doc_id": "doc_a",
        "field": "study title",
        "sheet": "study",
        "shadow_status": "missing",
        "tuned_status": "match",
        "shadow_score": "0",
        "tuned_score": "0.9",
        "score_delta": "0.9",
        "shadow_occurrences": "0",
        "tuned_occurrences": "1",
        "lexical_hit_count": "0",
        "semantic_hit_count": "3",
        "hybrid_hit_count": "3",
        "prompt_mode": "semantic_fallback",
        "rerank_status": "ok",
        "semantic_only_hint": "1",
        "completeness_delta": "0.1",
        "extra_fields_delta": "0",
        "row_alignment_f1_delta": "0",
        "sheet_placement_delta": "0",
        "schema_delta": "0",
        "llm_judge_delta": "0.1",
        "global_aggregate_delta": "0.1",
        "fallback_repair_score": "8",
    }
    row.update(overrides)
    return row


def test_build_predictions_groups_by_document_and_normalized_field():
    exporter = _load_exporter()
    payload = exporter.build_predictions(
        [_row()],
        label="should_repair_label",
        threshold=0.75,
    )

    assert payload["schema_version"] == "auto_repair_classifier_predictions.v1"
    prediction = payload["documents"]["doc_a"]["study title"]
    assert prediction["decision"] == "accept_patch"
    assert prediction["model"] == "rules_fallback"
    assert prediction["threshold"] == 0.75


def test_build_predictions_doc_id_returns_direct_state_mapping():
    exporter = _load_exporter()
    payload = exporter.build_predictions(
        [_row(doc_id="doc_a"), _row(doc_id="doc_b", field="assay name")],
        label="should_repair_label",
        threshold=0.75,
        doc_id="doc_b",
    )

    assert set(payload) == {"assay name"}
    assert payload["assay name"]["label"] == "should_repair_label"


def test_export_predictions_main_writes_json(tmp_path):
    exporter = _load_exporter()
    dataset = tmp_path / "decisions.csv"
    rows = [_row()]
    with dataset.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)
    output = tmp_path / "predictions.json"

    assert exporter.main(["--dataset", str(dataset), "--output", str(output)]) == 0
    text = output.read_text(encoding="utf-8")

    assert "auto_repair_classifier_predictions.v1" in text
    assert "study title" in text
