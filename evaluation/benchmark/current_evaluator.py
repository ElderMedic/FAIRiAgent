"""Deterministic per-run bridge from the current evaluators to benchmark v2.

Unlike ``evaluation/scripts/evaluate_outputs.py``, this bridge is intentionally
single-run and single-document.  It never chooses a best repetition and does
not call an LLM judge.  The caller supplies the exact run specification and
the FAIR-DS/ISA validation checks for that run.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, Mapping, Optional

from fairifier.output_paths import resolve_metadata_output_read_path

from evaluation.evaluators import (
    CorrectnessEvaluator,
    NovelFieldEvaluator,
    SchemaValidator,
    StructuralEvaluator,
    ValueAccuracyEvaluator,
)

from .evaluator_adapter import adapt_evaluator_record


def evaluate_current_run(
    run_spec: Mapping[str, Any],
    run_dir: Path,
    ground_truth_doc: Mapping[str, Any],
    *,
    validation: Mapping[str, Any],
    ground_truth_values_doc: Optional[Mapping[str, Any]] = None,
    source_text: Optional[str] = None,
    status: str = "success",
) -> Dict[str, Any]:
    """Evaluate one existing output directory and return a v2 result envelope.

    ``validation`` is required even though the schema evaluator runs here: the
    benchmark's ``isa_round_trip_valid`` gate must come from an explicit
    round-trip check, not from the presence of a JSON file or a best-run
    heuristic.
    """

    metadata_path = resolve_metadata_output_read_path(run_dir)
    artifact = {
        "exists": metadata_path is not None,
        "parseable": False,
        "path": str(metadata_path) if metadata_path is not None else str(run_dir),
    }
    if metadata_path is None:
        return adapt_evaluator_record(
            run_spec,
            {},
            artifact=artifact,
            validation=validation,
            status="failed" if status == "success" else status,
            provenance={"run_dir": str(run_dir)},
        )

    try:
        output = json.loads(metadata_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return adapt_evaluator_record(
            run_spec,
            {},
            artifact=artifact,
            validation=validation,
            status="failed" if status == "success" else status,
            provenance={"run_dir": str(run_dir)},
        )
    if not isinstance(output, dict):
        return adapt_evaluator_record(
            run_spec,
            {},
            artifact=artifact,
            validation=validation,
            status="failed" if status == "success" else status,
            provenance={"run_dir": str(run_dir)},
        )
    artifact["parseable"] = True

    correctness = CorrectnessEvaluator().evaluate(output, dict(ground_truth_doc))
    schema = SchemaValidator().validate(output)
    evaluator_record: Dict[str, Any] = {
        "correctness": correctness,
        "schema_validation": schema,
    }

    if ground_truth_values_doc is not None:
        value_evaluator = ValueAccuracyEvaluator()
        evaluator_record["value_accuracy"] = value_evaluator.evaluate(
            output, dict(ground_truth_values_doc)
        )
        evaluator_record["structural"] = StructuralEvaluator(
            value_evaluator=value_evaluator
        ).evaluate(output, dict(ground_truth_values_doc))

    # Layer 4 remains a diagnostic.  It is retained in provenance for audit
    # but is deliberately excluded from the benchmark axes and hard gates.
    field_names = {
        field.get("field_name")
        for field in ground_truth_doc.get("ground_truth_fields", [])
        if isinstance(field, Mapping) and field.get("field_name")
    }
    novel = NovelFieldEvaluator().evaluate(
        output,
        field_names,
        source_text=source_text,
        true_positives=correctness["summary_metrics"].get("true_positives", 0),
    )

    return adapt_evaluator_record(
        run_spec,
        evaluator_record,
        artifact=artifact,
        validation=validation,
        status=status,
        provenance={
            "run_dir": str(run_dir),
            "layer4_diagnostics": novel.get("summary_metrics", {}),
        },
    )
