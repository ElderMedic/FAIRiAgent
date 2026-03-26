#!/usr/bin/env python3
"""
Build private presentation-ready summaries from FAIRiAgent evaluation artifacts.

This script intentionally supports mixing current and legacy runs so we can
assemble a narrative for talks before final slide generation.
"""

from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path
from typing import Any, Dict, List


LEGACY_BENCHMARKS = {
    "campaign_id": "legacy_final_benchmark_2026-01-30",
    "kind": "historical_benchmark",
    "source": "evaluation/reports/FINAL_EVALUATION_RESULTS.md",
    "note": (
        "Legacy multi-model benchmark. Workflow versions differ from current "
        "branch, but numbers remain useful for presentation narrative."
    ),
    "models": [
        {
            "model": "qwen_max",
            "provider": "qwen",
            "workflow": "agentic",
            "runs": 20,
            "success_rate": 0.80,
            "mandatory_coverage": 0.81,
            "verified": True,
        },
        {
            "model": "gpt-5.1",
            "provider": "openai",
            "workflow": "baseline",
            "runs": 20,
            "success_rate": 0.0,
            "mandatory_coverage": 0.54,
            "verified": True,
        },
        {
            "model": "claude-haiku-4-5",
            "provider": "anthropic",
            "workflow": "baseline",
            "runs": 10,
            "success_rate": 0.0,
            "mandatory_coverage": 0.49,
            "verified": True,
        },
        {
            "model": "ollama_deepseek-r1-70b",
            "provider": "ollama",
            "workflow": "agentic",
            "runs": 19,
            "success_rate": 0.0,
            "mandatory_coverage": 0.37,
            "verified": True,
        },
    ],
    "document_highlights": [
        {
            "document_id": "earthworm",
            "model": "qwen_max",
            "success_rate": 1.0,
            "mandatory_coverage": 1.0,
        },
        {
            "document_id": "biosensor",
            "model": "qwen_max",
            "success_rate": 0.6,
            "mandatory_coverage": 0.63,
        },
        {
            "document_id": "pomato",
            "model": "ollama_deepseek-r1-70b",
            "success_rate": 0.0,
            "mandatory_coverage": 0.26,
        },
    ],
}

OPTIONAL_CAMPAIGNS = [
    (
        "phase2_qwenmax_traced",
        "evaluation/harness/runs/presentation_phase2_qwenmax_traced_r3",
        "agentic_traced",
    ),
    (
        "phase2_gpt54_traced",
        "evaluation/harness/runs/presentation_phase2_gpt54_traced_r3_fix2",
        "agentic_traced",
    ),
]


def load_json(path: Path) -> Dict[str, Any]:
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def load_phase1_campaign(name: str, run_dir: Path, kind: str) -> Dict[str, Any]:
    results_path = run_dir / "results" / "evaluation_results.json"
    data = load_json(results_path)
    model_comparison_metrics = data.get("model_comparison", {}).get("metrics", {})
    model_name = next(iter(model_comparison_metrics))
    aggregate = model_comparison_metrics[model_name]
    model_results = data.get("per_model_results", {}).get(model_name, {})

    campaign: Dict[str, Any] = {
        "campaign_id": name,
        "kind": kind,
        "source": str(run_dir),
        "model_key": model_name,
        "aggregate": aggregate,
        "documents": [],
    }

    per_doc = model_results.get("completeness", {}).get("per_document", {})
    correctness_per_doc = model_results.get("correctness", {}).get("per_document", {})
    schema_per_doc = model_results.get("schema_validation", {}).get("per_document", {})

    for document_id, doc_metrics in per_doc.items():
        doc_entry: Dict[str, Any] = {
            "document_id": document_id,
            "metrics": doc_metrics.get("overall_metrics", {}),
        }
        correctness_summary = correctness_per_doc.get(document_id, {}).get("summary_metrics", {})
        schema_summary = schema_per_doc.get(document_id, {})
        if correctness_summary:
            doc_entry["metrics"]["correctness_f1"] = correctness_summary.get("f1_score")
        if schema_summary:
            doc_entry["metrics"]["schema_compliance"] = schema_summary.get("schema_compliance_rate")

        run_root = run_dir / "outputs" / model_name / document_id / "run_1"
        if kind == "agentic":
            workflow_path = (
                run_root
                / "workflow_report.json"
            )
            eval_result_path = (
                run_root
                / "eval_result.json"
            )
            if workflow_path.exists():
                workflow = load_json(workflow_path)
                quality_summary = next(
                    (
                        value
                        for value in workflow.values()
                        if isinstance(value, dict)
                        and "packages_used" in value
                        and "total_fields" in value
                    ),
                    {},
                )
                field_analysis = workflow.get("field_analysis", {})
                execution_summary = workflow.get("execution_summary", {})
                doc_entry["workflow"] = {
                    "status": workflow.get("workflow_status"),
                    "overall_confidence": quality_summary.get("overall_confidence"),
                    "metadata_overall_confidence": quality_summary.get("metadata_overall_confidence"),
                    "total_fields": quality_summary.get("total_fields") or field_analysis.get("total_fields"),
                    "confirmed_fields": quality_summary.get("confirmed_fields"),
                    "provisional_fields": quality_summary.get("provisional_fields"),
                    "packages_used": quality_summary.get("packages_used", field_analysis.get("packages_used", [])),
                    "needs_review": quality_summary.get(
                        "needs_review", execution_summary.get("needs_human_review")
                    ),
                }
            if eval_result_path.exists():
                eval_result = load_json(eval_result_path)
                doc_entry["runtime_seconds"] = eval_result.get("runtime_seconds")
                doc_entry["n_fields_extracted"] = eval_result.get("n_fields_extracted")
        else:
            eval_result_path = run_root / "eval_result.json"
            if eval_result_path.exists():
                eval_result = load_json(eval_result_path)
                doc_entry["runtime_seconds"] = eval_result.get("runtime_seconds")
                doc_entry["n_fields_extracted"] = eval_result.get("n_fields_extracted")

        campaign["documents"].append(doc_entry)

    campaign["documents"].sort(key=lambda row: row["document_id"])
    return campaign


def build_artifact_inventory(project_root: Path) -> List[Dict[str, Any]]:
    candidates = [
        (
            "phase1_baseline_qwenflash",
            "evaluation/harness/runs/presentation_phase1_baseline_qwenflash",
            "current_phase1",
        ),
        (
            "phase1_agentic_qwenflash",
            "evaluation/harness/runs/presentation_phase1_agentic_qwenflash_r2",
            "current_phase1",
        ),
        (
            "legacy_qwen35_eval_all_pubfix",
            "evaluation/runs/qwen35_no_langfuse_eval_all_pubfix",
            "legacy",
        ),
        (
            "legacy_qwen35_earthworm_output",
            "output/qwen35_no_langfuse_earthworm",
            "legacy",
        ),
        (
            "phase2_qwenmax_traced",
            "evaluation/harness/runs/presentation_phase2_qwenmax_traced_r3",
            "current_phase2",
        ),
        (
            "phase2_gpt54_traced",
            "evaluation/harness/runs/presentation_phase2_gpt54_traced_r3_fix2",
            "current_phase2",
        ),
    ]

    inventory: List[Dict[str, Any]] = []
    for artifact_id, rel_path, kind in candidates:
        path = project_root / rel_path
        inventory.append(
            {
                "artifact_id": artifact_id,
                "kind": kind,
                "path": rel_path,
                "exists": path.exists(),
            }
        )
    return inventory


def write_csvs(summary: Dict[str, Any], aggregate_csv: Path, document_csv: Path) -> None:
    aggregate_rows: List[Dict[str, Any]] = []
    document_rows: List[Dict[str, Any]] = []

    for campaign in summary["campaigns"]:
        if campaign["kind"] == "historical_benchmark":
            for model in campaign["models"]:
                aggregate_rows.append(
                    {
                        "campaign_id": campaign["campaign_id"],
                        "kind": campaign["kind"],
                        "model": model["model"],
                        "workflow": model["workflow"],
                        "runs": model["runs"],
                        "aggregate_score": "",
                        "success_rate": model["success_rate"],
                        "mandatory_coverage": model["mandatory_coverage"],
                        "completeness": "",
                        "correctness_f1": "",
                        "schema_compliance": "",
                    }
                )
            for highlight in campaign["document_highlights"]:
                document_rows.append(
                    {
                        "campaign_id": campaign["campaign_id"],
                        "kind": campaign["kind"],
                        "model_key": highlight["model"],
                        "document_id": highlight["document_id"],
                        "runtime_seconds": "",
                        "required_completeness": highlight["mandatory_coverage"],
                        "overall_completeness": "",
                        "correctness_f1": "",
                        "schema_compliance": "",
                        "total_fields": "",
                        "packages_used": "",
                        "needs_review": "",
                    }
                )
            continue

        aggregate = campaign["aggregate"]
        aggregate_rows.append(
            {
                "campaign_id": campaign["campaign_id"],
                "kind": campaign["kind"],
                "model": campaign["model_key"],
                "workflow": campaign["kind"],
                "runs": len(campaign["documents"]),
                "aggregate_score": aggregate.get("aggregate_score"),
                "success_rate": "",
                "mandatory_coverage": campaign.get("mean_required_completeness", ""),
                "completeness": aggregate.get("completeness"),
                "correctness_f1": aggregate.get("correctness_f1"),
                "schema_compliance": aggregate.get("schema_compliance"),
            }
        )

        for doc in campaign["documents"]:
            metrics = doc["metrics"]
            workflow = doc.get("workflow", {})
            document_rows.append(
                {
                    "campaign_id": campaign["campaign_id"],
                    "kind": campaign["kind"],
                    "model_key": campaign["model_key"],
                    "document_id": doc["document_id"],
                    "runtime_seconds": doc.get("runtime_seconds", ""),
                    "required_completeness": metrics.get("required_completeness", ""),
                    "overall_completeness": metrics.get("overall_completeness", ""),
                    "correctness_f1": metrics.get("correctness_f1", ""),
                    "schema_compliance": metrics.get("schema_compliance", ""),
                    "total_fields": workflow.get("total_fields", doc.get("n_fields_extracted", "")),
                    "packages_used": "|".join(workflow.get("packages_used", [])),
                    "needs_review": workflow.get("needs_review", ""),
                }
            )

    aggregate_csv.parent.mkdir(parents=True, exist_ok=True)
    with aggregate_csv.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(aggregate_rows[0].keys()))
        writer.writeheader()
        writer.writerows(aggregate_rows)

    with document_csv.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(document_rows[0].keys()))
        writer.writeheader()
        writer.writerows(document_rows)


def main() -> int:
    parser = argparse.ArgumentParser(description="Aggregate presentation metrics.")
    parser.add_argument(
        "--project-root",
        type=Path,
        default=Path(__file__).parents[2],
        help="Repository root",
    )
    parser.add_argument(
        "--output-json",
        type=Path,
        required=True,
        help="Where to write the summary JSON",
    )
    parser.add_argument(
        "--aggregate-csv",
        type=Path,
        required=True,
        help="Where to write aggregate metrics CSV",
    )
    parser.add_argument(
        "--document-csv",
        type=Path,
        required=True,
        help="Where to write document metrics CSV",
    )
    args = parser.parse_args()

    project_root = args.project_root.resolve()
    baseline_dir = project_root / "evaluation/harness/runs/presentation_phase1_baseline_qwenflash"
    agentic_dir = project_root / "evaluation/harness/runs/presentation_phase1_agentic_qwenflash_r2"

    baseline = load_phase1_campaign("phase1_baseline_qwenflash", baseline_dir, "baseline")
    agentic = load_phase1_campaign("phase1_agentic_qwenflash", agentic_dir, "agentic")

    baseline["mean_runtime_seconds"] = round(
        sum(doc.get("runtime_seconds", 0.0) or 0.0 for doc in baseline["documents"])
        / max(len(baseline["documents"]), 1),
        2,
    )
    agentic["mean_runtime_seconds"] = round(
        sum(doc.get("runtime_seconds", 0.0) or 0.0 for doc in agentic["documents"])
        / max(len(agentic["documents"]), 1),
        2,
    )
    agentic["mean_required_completeness"] = round(
        sum(doc["metrics"].get("required_completeness", 0.0) for doc in agentic["documents"])
        / max(len(agentic["documents"]), 1),
        3,
    )

    campaigns: List[Dict[str, Any]] = [
        LEGACY_BENCHMARKS,
        baseline,
        agentic,
    ]
    for campaign_id, rel_path, kind in OPTIONAL_CAMPAIGNS:
        campaign_dir = project_root / rel_path
        results_path = campaign_dir / "results" / "evaluation_results.json"
        if results_path.exists():
            campaigns.append(load_phase1_campaign(campaign_id, campaign_dir, kind))

    summary = {
        "generated_at": __import__("datetime").datetime.now().isoformat(),
        "campaigns": campaigns,
        "presentation_focus": {
            "best_success_case": "earthworm",
            "second_success_case": "biosensor",
            "hardest_case": "pomato",
            "note": "Pomato is the most complex dataset and should remain in the story as the boundary-case workload.",
        },
        "artifact_inventory": build_artifact_inventory(project_root),
        "headline_comparison": {
            "baseline_vs_agentic_phase1": {
                "aggregate_score_delta": round(
                    agentic["aggregate"]["aggregate_score"] - baseline["aggregate"]["aggregate_score"],
                    3,
                ),
                "completeness_delta": round(
                    agentic["aggregate"]["completeness"] - baseline["aggregate"]["completeness"],
                    3,
                ),
                "correctness_f1_delta": round(
                    agentic["aggregate"]["correctness_f1"] - baseline["aggregate"]["correctness_f1"],
                    3,
                ),
                "schema_compliance_delta": round(
                    agentic["aggregate"]["schema_compliance"] - baseline["aggregate"]["schema_compliance"],
                    3,
                ),
                "runtime_ratio": round(
                    agentic["mean_runtime_seconds"] / max(baseline["mean_runtime_seconds"], 1e-9),
                    2,
                ),
            }
        },
    }

    args.output_json.parent.mkdir(parents=True, exist_ok=True)
    with args.output_json.open("w", encoding="utf-8") as handle:
        json.dump(summary, handle, indent=2, ensure_ascii=False)

    write_csvs(summary, args.aggregate_csv, args.document_csv)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
