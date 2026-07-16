#!/usr/bin/env python3
"""Offline §12.1 structural convergence replay against existing run artifacts.

Compares Layer-3 structural metrics for each document under four projections:
  1. baseline_metadata  — metadata.json isa_values as stored (historical eval path)
  2. sidecar_raw        — isa_values_json.json as stored
  3. compiled_metadata  — compile_isa_matrix(metadata isa_values)
  4. compiled_sidecar   — compile_isa_matrix(sidecar)  ← recommended projection

No LLM calls. Writes a JSON report under the run directory.
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from evaluation.evaluators.structural_evaluator import StructuralEvaluator
from fairifier.utils.isa_matrix_compiler import compile_isa_matrix, matrix_id_for
from fairifier.utils.isa_matrix_projection import (
    apply_matrix_to_metadata,
    extract_matrix_from_metadata,
)

DOC_IDS = [
    "earthworm",
    "biosensor",
    "pea_cold_stress",
    "sea_cucumber_gut_metagenome",
    "petase_10_1002_anie_202218390",
    "petase_10_1038_s41586-020-2149-4",
]

METRIC_KEYS = (
    "row_alignment_f1",
    "row_alignment_precision",
    "row_alignment_recall",
    "row_count_ratio",
    "sheet_placement_accuracy",
    "value_accuracy_given_correct_structure",
)


def _load_json(path: Path) -> Any:
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


def _find_run_dir(model_root: Path, doc_id: str) -> Optional[Path]:
    doc_dir = model_root / doc_id
    if not doc_dir.is_dir():
        return None
    run_dirs = sorted(
        [d for d in doc_dir.iterdir() if d.is_dir() and d.name.startswith("run_")]
    )
    return run_dirs[0] if run_dirs else None


def _gt_path_for(doc_id: str) -> Path:
    return (
        PROJECT_ROOT
        / "evaluation"
        / "datasets"
        / "annotated"
        / "values"
        / f"ground_truth_{doc_id}_values.json"
    )


def _row_counts(matrix: Dict[str, Any]) -> Dict[str, int]:
    out: Dict[str, int] = {}
    for sheet, block in (matrix or {}).items():
        if isinstance(block, dict):
            out[sheet] = len([r for r in (block.get("rows") or []) if isinstance(r, dict)])
    return out


def _payload_for(matrix: Dict[str, Any], base_meta: Dict[str, Any]) -> Dict[str, Any]:
    return apply_matrix_to_metadata(base_meta, matrix, matrix_id=matrix_id_for(matrix))


def _evaluate(
    evaluator: StructuralEvaluator,
    payload: Dict[str, Any],
    gt_doc: Dict[str, Any],
) -> Dict[str, Any]:
    result = evaluator.evaluate(payload, gt_doc)
    summary = result.get("summary_metrics") or {}
    return {k: summary.get(k) for k in METRIC_KEYS}


def _mean(values: List[float]) -> float:
    return float(statistics.mean(values)) if values else 0.0


def replay_document(
    run_dir: Path,
    doc_id: str,
    evaluator: StructuralEvaluator,
) -> Dict[str, Any]:
    meta = _load_json(run_dir / "metadata.json")
    sidecar_path = run_dir / "isa_values_json.json"
    sidecar = _load_json(sidecar_path) if sidecar_path.is_file() else {}
    gt_doc = _load_json(_gt_path_for(doc_id))

    meta_matrix = extract_matrix_from_metadata(meta)
    sidecar_matrix = {
        sheet: {
            "columns": list((block or {}).get("columns") or []),
            "rows": list((block or {}).get("rows") or []),
        }
        for sheet, block in (sidecar or {}).items()
        if isinstance(block, dict)
    }

    compiled_meta = compile_isa_matrix(meta_matrix)["matrix"]
    compiled_side = compile_isa_matrix(sidecar_matrix or meta_matrix)["matrix"]

    variants = {
        "baseline_metadata": _payload_for(meta_matrix, meta),
        "sidecar_raw": _payload_for(sidecar_matrix or meta_matrix, meta),
        "compiled_metadata": _payload_for(compiled_meta, meta),
        "compiled_sidecar": _payload_for(compiled_side, meta),
    }

    metrics = {name: _evaluate(evaluator, payload, gt_doc) for name, payload in variants.items()}

    return {
        "document_id": doc_id,
        "run_dir": str(run_dir),
        "row_counts": {
            "baseline_metadata": _row_counts(meta_matrix),
            "sidecar_raw": _row_counts(sidecar_matrix),
            "compiled_metadata": _row_counts(compiled_meta),
            "compiled_sidecar": _row_counts(compiled_side),
        },
        "matrix_ids": {
            "compiled_metadata": matrix_id_for(compiled_meta),
            "compiled_sidecar": matrix_id_for(compiled_side),
        },
        "metrics": metrics,
        "deltas_vs_baseline": {
            name: {
                k: (metrics[name].get(k) or 0) - (metrics["baseline_metadata"].get(k) or 0)
                for k in METRIC_KEYS
            }
            for name in metrics
            if name != "baseline_metadata"
        },
    }


def aggregate(docs: List[Dict[str, Any]]) -> Dict[str, Any]:
    variants = ["baseline_metadata", "sidecar_raw", "compiled_metadata", "compiled_sidecar"]
    agg: Dict[str, Any] = {}
    for variant in variants:
        agg[variant] = {
            k: _mean(
                [
                    float(doc["metrics"][variant].get(k) or 0.0)
                    for doc in docs
                    if variant in doc["metrics"]
                ]
            )
            for k in METRIC_KEYS
        }
    recommended = "compiled_sidecar"
    baseline = "baseline_metadata"
    agg["recommended_delta_vs_baseline"] = {
        k: agg[recommended][k] - agg[baseline][k] for k in METRIC_KEYS
    }
    agg["sidecar_raw_delta_vs_baseline"] = {
        k: agg["sidecar_raw"][k] - agg[baseline][k] for k in METRIC_KEYS
    }
    return agg


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--run-root",
        type=Path,
        default=PROJECT_ROOT
        / "evaluation"
        / "runs"
        / "auto_pro_tuned"
        / "deepseek_v4-pro_v1.4.0_tunnel_auto_tuned",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=None,
        help="Report JSON path (default: <run-root>/../results/structural_convergence_replay.json)",
    )
    args = parser.parse_args()
    run_root = args.run_root.resolve()
    output = args.output or (
        run_root.parent / "results" / "structural_convergence_replay.json"
    )

    evaluator = StructuralEvaluator()
    docs: List[Dict[str, Any]] = []
    missing: List[str] = []
    for doc_id in DOC_IDS:
        run_dir = _find_run_dir(run_root, doc_id)
        if run_dir is None or not (run_dir / "metadata.json").is_file():
            missing.append(doc_id)
            continue
        if not _gt_path_for(doc_id).is_file():
            missing.append(f"{doc_id}:missing_gt")
            continue
        docs.append(replay_document(run_dir, doc_id, evaluator))

    report = {
        "schema_version": "structural_convergence_replay.v1",
        "run_root": str(run_root),
        "n_documents": len(docs),
        "missing": missing,
        "aggregate": aggregate(docs),
        "per_document": docs,
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    agg = report["aggregate"]
    print(f"Wrote {output}")
    print(f"Documents: {len(docs)} (missing={missing})")
    print("--- aggregate structural metrics ---")
    for variant in ["baseline_metadata", "sidecar_raw", "compiled_metadata", "compiled_sidecar"]:
        m = agg[variant]
        print(
            f"{variant:20s}  F1={m['row_alignment_f1']:.4f}  "
            f"ratio={m['row_count_ratio']:.3f}  "
            f"place={m['sheet_placement_accuracy']:.4f}  "
            f"val@struct={m['value_accuracy_given_correct_structure']:.4f}"
        )
    delta = agg["recommended_delta_vs_baseline"]
    print("--- compiled_sidecar − baseline_metadata ---")
    for k, v in delta.items():
        print(f"  {k}: {v:+.4f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
