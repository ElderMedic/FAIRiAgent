#!/usr/bin/env python3
"""Build a local inventory of FAIRiAgent runs.

Writes two tables:

* ``evaluation/reports/run_catalog/evaluation_runs.csv``
* ``evaluation/reports/run_catalog/output_runs.csv``

The tables are generated. Re-run this script to refresh them; do not edit the
CSV files by hand. They stay on this machine (see ``.gitignore``) because they
list local campaign paths and unpublished scores.

A run is any directory that directly holds a workflow report, an
``eval_result.json``, or a metadata JSON / FAIR-DS workbook (including the
``deliverables/`` layout). Evaluation campaigns, harness runs, paper-experiment
runs, ablations, and archived batches go in the evaluation table. Everything
discovered under ``output/`` goes in the output table.

``runtime_config.json`` is not opened. Those files store API keys. Provider
and model columns come from the run path, ``eval_result.json``, and any
``run_index.json``.

``result_status``:

* ``complete`` — metadata JSON exists and the workflow or eval record succeeded
* ``deliverable_only`` — metadata JSON exists, with no workflow or eval success/failure record
* ``failed`` — workflow or eval record failed, and no metadata JSON was written
* ``failed_with_metadata`` — a failure record still has metadata JSON
* ``partial`` — some artifacts exist, but the run is not a successful deliverable
"""

from __future__ import annotations

import argparse
import csv
import json
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

CATALOG_VERSION = "1"
DEFAULT_OUTPUT_DIR = Path("evaluation/reports/run_catalog")

EVAL_ROOTS = (
    "evaluation/runs",
    "evaluation/harness/runs",
    "evaluation/paper_experiments_v1",
    "evaluation/ablation_quick_run",
    "evaluation/baselines",
    "evaluation/archive",
)
OUTPUT_ROOTS = ("output",)

SKIP_DIR_NAMES = {
    "__pycache__",
    ".git",
    ".matplotlib",
    ".mineru_cache",
    "checkpoints",
    "node_modules",
    "site-packages",
}
MARKER_NAMES = {
    "workflow_report.json",
    "eval_result.json",
    "metadata.json",
    "metadata_json.json",
    "metadata_fairds.xlsx",
    "isa_values.json",
    "isa_values_json.json",
}
TAIL_SKIP = {"outputs", "output", "results", "run"}
RUN_DIR_RE = re.compile(r"^run_(\d+)$")
SECRET_ASSIGNMENT_RE = re.compile(
    r"(?i)(api[_-]?key|token|secret|authorization)\s*[:=]\s*\S+"
)
SECRET_TOKEN_RE = re.compile(r"sk-[A-Za-z0-9_\-]{8,}")

COLUMNS: Tuple[str, ...] = (
    "catalog",
    "source_root",
    "campaign",
    "run_dir",
    "run_label",
    "condition_id",
    "model_id",
    "llm_provider",
    "llm_model",
    "llm_enable_thinking",
    "document_id",
    "document_name",
    "repetition",
    "project_id",
    "result_status",
    "workflow_status",
    "eval_success",
    "eval_error",
    "needs_human_review",
    "processing_start",
    "processing_end",
    "wall_time_seconds",
    "eval_runtime_seconds",
    "runtime_config_timestamp",
    "dir_mtime_utc",
    "metadata_mtime_utc",
    "has_metadata_json",
    "has_fairds_xlsx",
    "has_isa_values",
    "has_workflow_report",
    "has_eval_result",
    "has_runtime_config",
    "has_llm_responses",
    "metadata_bytes",
    "xlsx_bytes",
    "total_fields",
    "confirmed_fields",
    "provisional_fields",
    "n_fields_extracted",
    "overall_confidence",
    "critic_confidence",
    "structural_confidence",
    "validation_confidence",
    "metadata_overall_confidence",
    "ungrounded_high_confidence_fields",
    "source_grounded_fields",
    "table_backed_fields",
    "packages_used_count",
    "total_retries",
    "failed_steps",
    "total_steps",
    "llm_calls",
    "total_tokens",
    "input_tokens",
    "output_tokens",
    "usage_coverage_ratio",
    "fairifier_version",
    "workflow_version",
    "eval_completeness",
    "eval_required_completeness",
    "eval_value_mean",
    "eval_sheet_placement",
    "eval_row_f1",
    "eval_schema_compliance",
    "eval_llm_judge",
    "eval_precision_excl_discoveries",
    "model_aggregate_score",
    "score_source",
    "score_scope",
    "score_shared_across_runs",
    "axis_information_coverage",
    "axis_value_accuracy",
    "axis_structural_fidelity",
    "axis_interoperability",
    "fairds_valid",
    "isa_round_trip_valid",
    "index_status",
    "index_validation_status",
    "index_source",
    "expectation_passed",
    "expectation_review_required",
    "expectation_error_count",
    "disable_critic",
    "disable_api_grounding",
    "disable_hard_gate",
    "disable_cross_layer_rollback",
)


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--repo-root",
        type=Path,
        default=None,
        help="Repository root. Defaults to two levels above this script.",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=DEFAULT_OUTPUT_DIR,
        help="Directory for the two CSV tables and catalog_summary.json.",
    )
    parser.add_argument(
        "--describe-only",
        action="store_true",
        help="Read run directories from stdin and write one JSON object per line.",
    )
    parser.add_argument("--catalog", choices=("evaluation", "output"), default="evaluation")
    args = parser.parse_args(argv)
    repo_root = (args.repo_root or Path(__file__).resolve().parents[2]).resolve()
    if args.describe_only:
        return describe_only(repo_root, args.catalog)
    output_dir = args.output_dir
    if not output_dir.is_absolute():
        output_dir = repo_root / output_dir

    generated_at = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    evaluation_rows = collect_catalog(repo_root, EVAL_ROOTS, "evaluation")
    output_rows = collect_catalog(repo_root, OUTPUT_ROOTS, "output")
    rows = evaluation_rows + output_rows
    attach_campaign_scores(repo_root, rows)
    attach_run_indexes(repo_root, rows)
    mark_shared_scores(rows)
    for row in rows:
        row["catalog_generated_at"] = generated_at

    columns = COLUMNS + ("catalog_generated_at",)
    output_dir.mkdir(parents=True, exist_ok=True)
    evaluation_path = output_dir / "evaluation_runs.csv"
    output_path = output_dir / "output_runs.csv"
    summary_path = output_dir / "catalog_summary.json"
    write_csv(evaluation_path, evaluation_rows, columns)
    write_csv(output_path, output_rows, columns)
    summary = build_summary(
        generated_at,
        evaluation_rows,
        output_rows,
        evaluation_path,
        output_path,
        repo_root,
    )
    summary_path.write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    print(
        f"evaluation runs: {len(evaluation_rows)} -> {evaluation_path.relative_to(repo_root)}"
    )
    print(f"output runs: {len(output_rows)} -> {output_path.relative_to(repo_root)}")
    print(
        "complete: "
        f"evaluation {summary['evaluation']['by_status'].get('complete', 0)}, "
        f"output {summary['output']['by_status'].get('complete', 0)}"
    )
    return 0


def describe_only(repo_root: Path, catalog: str) -> int:
    for line in sys.stdin:
        raw = line.strip()
        if not raw:
            continue
        run_dir = Path(raw)
        if not run_dir.is_absolute():
            run_dir = repo_root / run_dir
        sys.stdout.write(json.dumps(describe_run(repo_root, run_dir, catalog), ensure_ascii=False) + "\n")
    return 0


def collect_catalog(repo_root: Path, roots: Sequence[str], catalog: str) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    for relative_root in roots:
        root = repo_root / relative_root
        if not root.is_dir():
            continue
        run_dirs = discover_run_dirs(root)
        print(f"{catalog}: {relative_root} -> {len(run_dirs)} runs", file=sys.stderr, flush=True)
        described = 0
        for chunk in chunks(run_dirs, 25):
            rows.extend(describe_chunk(repo_root, chunk, catalog))
            described += len(chunk)
            print(f"{catalog}: described {described}/{len(run_dirs)}", file=sys.stderr, flush=True)
    rows.sort(key=sort_key)
    return rows


def chunks(items: Sequence[Path], size: int) -> Iterable[Sequence[Path]]:
    for start in range(0, len(items), size):
        yield items[start : start + size]


def describe_chunk(repo_root: Path, run_dirs: Sequence[Path], catalog: str) -> List[Dict[str, Any]]:
    try:
        return describe_chunk_once(repo_root, run_dirs, catalog)
    except subprocess.TimeoutExpired:
        if len(run_dirs) == 1:
            print(f"skipped unreadable run: {run_dirs[0]}", file=sys.stderr, flush=True)
            return [unreadable_row(repo_root, run_dirs[0], catalog)]
        middle = max(1, len(run_dirs) // 2)
        return describe_chunk(repo_root, run_dirs[:middle], catalog) + describe_chunk(
            repo_root, run_dirs[middle:], catalog
        )


def describe_chunk_once(repo_root: Path, run_dirs: Sequence[Path], catalog: str) -> List[Dict[str, Any]]:
    completed = subprocess.run(
        [
            sys.executable,
            str(Path(__file__).resolve()),
            "--describe-only",
            "--catalog",
            catalog,
            "--repo-root",
            str(repo_root),
        ],
        input="\n".join(path.as_posix() for path in run_dirs) + "\n",
        capture_output=True,
        text=True,
        timeout=45,
        check=False,
    )
    rows = []
    for line in completed.stdout.splitlines():
        if line.strip():
            rows.append(json.loads(line))
    if len(rows) != len(run_dirs):
        raise subprocess.TimeoutExpired("build_run_catalog.py", 45)
    return rows


def unreadable_row(repo_root: Path, run_dir: Path, catalog: str) -> Dict[str, Any]:
    relative = run_dir.relative_to(repo_root).as_posix()
    source_root, campaign, tail = split_source(Path(relative))
    run_label, repetition, identity_parts = split_tail(tail)
    condition_id, model_id, document_id = identity_from_parts(identity_parts)
    row = {column: "" for column in COLUMNS}
    row.update(
        {
            "catalog": catalog,
            "source_root": source_root,
            "campaign": campaign,
            "run_dir": relative,
            "run_label": run_label,
            "condition_id": condition_id,
            "model_id": model_id,
            "document_id": document_id,
            "repetition": repetition,
            "result_status": "unreadable",
        }
    )
    return row


def discover_run_dirs(root: Path) -> List[Path]:
    found = set()
    for path in find_files(root, tuple(sorted(MARKER_NAMES))):
        if path.parent.name == "deliverables":
            found.add(path.parent.parent)
        else:
            found.add(path.parent)
    return sorted(found)


def describe_run(repo_root: Path, run_dir: Path, catalog: str) -> Dict[str, Any]:
    relative = run_dir.relative_to(repo_root).as_posix()
    source_root, campaign, tail = split_source(Path(relative))
    run_label, repetition, identity_parts = split_tail(tail)
    condition_id, model_id, document_id = identity_from_parts(identity_parts)

    metadata_path = first_existing(
        run_dir / "metadata.json",
        run_dir / "metadata_json.json",
        run_dir / "deliverables" / "metadata.json",
        run_dir / "deliverables" / "metadata_json.json",
    )
    xlsx_path = first_existing(
        run_dir / "metadata_fairds.xlsx",
        run_dir / "deliverables" / "metadata_fairds.xlsx",
    )
    isa_path = first_existing(
        run_dir / "isa_values.json",
        run_dir / "isa_values_json.json",
        run_dir / "deliverables" / "isa_values.json",
        run_dir / "deliverables" / "isa_values_json.json",
    )
    workflow_path = run_dir / "workflow_report.json"
    eval_path = run_dir / "eval_result.json"
    runtime_path = first_existing(
        run_dir / "runtime_config.json",
        run_dir / "reports" / "runtime_config.json",
    )
    llm_path = first_existing(
        run_dir / "llm_responses.json",
        run_dir / "logs" / "llm_responses.json",
    )
    expectation_path = run_dir / "reports" / "expected_outcome_evaluation.json"

    workflow = load_json(workflow_path) if workflow_path.is_file() else None
    eval_result = load_json(eval_path) if eval_path.is_file() else None
    expectation = load_json(expectation_path) if expectation_path.is_file() else None

    row: Dict[str, Any] = {column: "" for column in COLUMNS}
    row.update(
        {
            "catalog": catalog,
            "source_root": source_root,
            "campaign": campaign,
            "run_dir": relative,
            "run_label": run_label,
            "condition_id": condition_id,
            "model_id": model_id,
            "document_id": document_id,
            "repetition": repetition,
            "dir_mtime_utc": iso_mtime(run_dir),
            "has_metadata_json": bool(metadata_path),
            "has_fairds_xlsx": bool(xlsx_path),
            "has_isa_values": bool(isa_path),
            "has_workflow_report": workflow_path.is_file(),
            "has_eval_result": eval_path.is_file(),
            "has_runtime_config": runtime_path is not None,
            "has_llm_responses": llm_path is not None,
            "metadata_bytes": file_size(metadata_path),
            "xlsx_bytes": file_size(xlsx_path),
            "metadata_mtime_utc": iso_mtime(metadata_path) if metadata_path else "",
        }
    )
    apply_workflow(row, workflow)
    apply_eval_result(row, eval_result)
    apply_expectation(row, expectation)
    row["result_status"] = classify_status(row)
    return row


def split_source(relative: Path) -> Tuple[str, str, Tuple[str, ...]]:
    parts = relative.parts
    if parts[0] == "output":
        campaign = parts[1] if len(parts) > 1 else ""
        return "output", campaign, parts[2:]
    if parts[0] != "evaluation":
        return parts[0], parts[1] if len(parts) > 1 else "", parts[2:]
    if len(parts) >= 3 and parts[1] == "harness" and parts[2] == "runs":
        campaign = parts[3] if len(parts) > 3 else ""
        return "evaluation/harness/runs", campaign, parts[4:]
    if parts[1] == "runs":
        campaign = parts[2] if len(parts) > 2 else ""
        return "evaluation/runs", campaign, parts[3:]
    if parts[1] == "paper_experiments_v1":
        rest = parts[2:]
        if rest and rest[0] == "runs":
            rest = rest[1:]
        campaign = rest[0] if rest else "paper_experiments_v1"
        return "evaluation/paper_experiments_v1", campaign, rest[1:]
    if parts[1] in {"ablation_quick_run", "baselines", "archive"}:
        campaign = parts[2] if len(parts) > 2 else parts[1]
        return f"evaluation/{parts[1]}", campaign, parts[3:]
    campaign = parts[2] if len(parts) > 2 else parts[1]
    return f"evaluation/{parts[1]}", campaign, parts[3:]


def split_tail(tail: Tuple[str, ...]) -> Tuple[str, str, Tuple[str, ...]]:
    parts = [part for part in tail if part not in TAIL_SKIP]
    run_label = ""
    repetition = ""
    if parts and RUN_DIR_RE.match(parts[-1]):
        run_label = parts[-1]
        repetition = RUN_DIR_RE.match(parts[-1]).group(1)  # type: ignore[union-attr]
        parts = parts[:-1]
    return run_label, repetition, tuple(parts)


def identity_from_parts(parts: Tuple[str, ...]) -> Tuple[str, str, str]:
    if len(parts) >= 3:
        return parts[0], parts[1], parts[-1]
    if len(parts) == 2:
        return "", parts[0], parts[1]
    if len(parts) == 1:
        return "", "", parts[0]
    return "", "", ""


def apply_workflow(row: Dict[str, Any], workflow: Any) -> None:
    if not isinstance(workflow, dict):
        return
    row["workflow_status"] = scalar(workflow.get("workflow_status"))
    summary = workflow.get("execution_summary")
    if isinstance(summary, dict):
        row["processing_start"] = scalar(summary.get("processing_start"))
        row["processing_end"] = scalar(summary.get("processing_end"))
        row["needs_human_review"] = scalar(summary.get("needs_human_review"))
        row["total_retries"] = scalar(summary.get("total_retries"))
        row["failed_steps"] = scalar(summary.get("failed_steps"))
        row["total_steps"] = scalar(summary.get("total_steps"))
        if row["project_id"] == "":
            row["project_id"] = scalar(summary.get("project_id"))
    quality = workflow.get("quality_metrics")
    if isinstance(quality, dict):
        row["overall_confidence"] = scalar(quality.get("overall_confidence"))
        row["critic_confidence"] = scalar(quality.get("critic_confidence"))
        row["structural_confidence"] = scalar(quality.get("structural_confidence"))
        row["validation_confidence"] = scalar(quality.get("validation_confidence"))
        row["metadata_overall_confidence"] = scalar(quality.get("metadata_overall_confidence"))
        row["total_fields"] = scalar(quality.get("total_fields"))
        row["confirmed_fields"] = scalar(quality.get("confirmed_fields"))
        row["provisional_fields"] = scalar(quality.get("provisional_fields"))
        packages = quality.get("packages_used")
        if isinstance(packages, list):
            row["packages_used_count"] = len(packages)
        grounding = quality.get("source_grounding")
        if isinstance(grounding, dict):
            row["ungrounded_high_confidence_fields"] = scalar(
                grounding.get("ungrounded_high_confidence_fields")
            )
            row["source_grounded_fields"] = scalar(grounding.get("source_grounded_fields"))
            row["table_backed_fields"] = scalar(grounding.get("table_backed_fields"))
        if row["needs_human_review"] == "" and "needs_review" in quality:
            row["needs_human_review"] = scalar(quality.get("needs_review"))
    performance = workflow.get("performance")
    if isinstance(performance, dict):
        wall = performance.get("workflow")
        if isinstance(wall, dict):
            row["wall_time_seconds"] = scalar(wall.get("wall_time_seconds"))
        usage = performance.get("llm_usage")
        if isinstance(usage, dict):
            row["llm_calls"] = scalar(usage.get("calls"))
            row["total_tokens"] = scalar(usage.get("total_tokens"))
            row["input_tokens"] = scalar(usage.get("input_tokens"))
            row["output_tokens"] = scalar(usage.get("output_tokens"))
            row["usage_coverage_ratio"] = scalar(usage.get("usage_coverage_ratio"))


def apply_eval_result(row: Dict[str, Any], payload: Any) -> None:
    if not isinstance(payload, dict):
        return
    if payload.get("document_id"):
        row["document_id"] = scalar(payload.get("document_id"))
    if payload.get("config_name") and row["model_id"] == "":
        row["model_id"] = scalar(payload.get("config_name"))
    elif payload.get("config_name") and row["model_id"] != scalar(payload.get("config_name")):
        if row["condition_id"] == "":
            row["condition_id"] = row["model_id"]
        row["model_id"] = scalar(payload.get("config_name"))
    if payload.get("run_idx") not in (None, "") and row["repetition"] == "":
        row["repetition"] = scalar(payload.get("run_idx"))
    if payload.get("project_id"):
        row["project_id"] = scalar(payload.get("project_id"))
    row["eval_success"] = scalar(payload.get("success"))
    row["eval_error"] = clean_text(payload.get("error"))
    row["eval_runtime_seconds"] = scalar(payload.get("runtime_seconds"))
    row["n_fields_extracted"] = scalar(payload.get("n_fields_extracted"))
    if row["processing_start"] == "":
        row["processing_start"] = scalar(payload.get("start_time"))
    if row["processing_end"] == "":
        row["processing_end"] = scalar(payload.get("end_time"))
    if row["wall_time_seconds"] == "":
        row["wall_time_seconds"] = scalar(payload.get("runtime_seconds"))
    confidence = payload.get("confidence_scores")
    if isinstance(confidence, dict):
        aggregate = confidence.get("_aggregate")
        if isinstance(aggregate, dict):
            if row["overall_confidence"] == "":
                row["overall_confidence"] = scalar(aggregate.get("overall"))
            if row["critic_confidence"] == "":
                row["critic_confidence"] = scalar(aggregate.get("critic"))
            if row["structural_confidence"] == "":
                row["structural_confidence"] = scalar(aggregate.get("structural"))
            if row["validation_confidence"] == "":
                row["validation_confidence"] = scalar(aggregate.get("validation"))


def apply_expectation(row: Dict[str, Any], payload: Any) -> None:
    if not isinstance(payload, dict):
        return
    row["expectation_passed"] = scalar(payload.get("passed"))
    row["expectation_review_required"] = scalar(payload.get("review_required"))
    row["expectation_error_count"] = scalar(payload.get("expectation_error_count"))


def classify_status(row: Mapping[str, Any]) -> str:
    workflow_status = str(row.get("workflow_status") or "").lower()
    eval_success = str(row.get("eval_success") or "").lower()
    has_metadata = _is_true(row.get("has_metadata_json"))
    has_workflow = _is_true(row.get("has_workflow_report"))
    has_eval = _is_true(row.get("has_eval_result"))
    failed = workflow_status in {"failed", "error", "cancelled", "canceled"} or eval_success == "false"
    succeeded = workflow_status in {"completed", "success", "succeeded"} or eval_success == "true"
    if failed and has_metadata:
        return "failed_with_metadata"
    if failed:
        return "failed"
    if succeeded and has_metadata:
        return "complete"
    if has_metadata and workflow_status == "" and eval_success == "":
        return "deliverable_only"
    if has_metadata or has_workflow or has_eval:
        return "partial"
    return "incomplete"


def _is_true(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    return str(value).lower() == "true"


def attach_campaign_scores(repo_root: Path, rows: List[Dict[str, Any]]) -> None:
    index: List[Tuple[Path, str, str, Dict[str, Any]]] = []
    for path in find_named(repo_root, "evaluation_results.json"):
        payload = load_json(path)
        if not isinstance(payload, dict) or "per_model_results" not in payload:
            continue
        base = path.parent.parent if path.parent.name == "results" else path.parent
        per_model = payload.get("per_model_results")
        if not isinstance(per_model, dict):
            continue
        for model_key, model_blob in per_model.items():
            if not isinstance(model_blob, dict):
                continue
            documents = document_ids_in_model(model_blob)
            for document_id in documents:
                index.append((base, str(model_key), document_id, score_record(path, repo_root, model_blob, document_id)))
    for row in rows:
        run_dir = repo_root / row["run_dir"]
        matches = []
        for base, model_key, document_id, scores in index:
            if base != run_dir and base not in run_dir.parents:
                continue
            if not identity_matches(run_dir, base, row, model_key, document_id):
                continue
            matches.append((len(base.parts), scores))
        if not matches:
            continue
        best = max(matches, key=lambda item: item[0])[1]
        for key, value in best.items():
            if value != "" and row.get(key, "") == "":
                row[key] = value


def attach_run_indexes(repo_root: Path, rows: List[Dict[str, Any]]) -> None:
    by_run: Dict[Path, Tuple[Tuple[int, int], Dict[str, Any]]] = {}
    for path in find_named(repo_root, "run_index.json"):
        payload = load_json(path)
        if not isinstance(payload, dict):
            continue
        results = payload.get("results")
        if not isinstance(results, list):
            continue
        for item in results:
            if not isinstance(item, dict):
                continue
            artifact = item.get("artifact")
            artifact_path = ""
            if isinstance(artifact, dict):
                artifact_path = str(artifact.get("path") or "")
            elif isinstance(artifact, str):
                artifact_path = artifact
            if not artifact_path:
                continue
            artifact_file = Path(artifact_path)
            if not artifact_file.is_absolute():
                artifact_file = repo_root / artifact_file
            run_dir = artifact_file.parent.parent if artifact_file.parent.name == "deliverables" else artifact_file.parent
            record = index_record(item, path, repo_root)
            rank = index_rank(record)
            previous = by_run.get(run_dir.resolve())
            if previous is None or rank > previous[0]:
                by_run[run_dir.resolve()] = (rank, record)
    for row in rows:
        found = by_run.get((repo_root / row["run_dir"]).resolve())
        if found is None:
            continue
        record = found[1]
        for key in ("condition_id", "model_id", "document_id", "repetition"):
            if record.get(key):
                row[key] = record[key]
        for key, value in record.items():
            if key in {"condition_id", "model_id", "document_id", "repetition"}:
                continue
            if value != "":
                row[key] = value


def mark_shared_scores(rows: Iterable[Dict[str, Any]]) -> None:
    grouped: Dict[Tuple[str, str, str], int] = {}
    prepared = []
    for row in rows:
        key = (str(row.get("score_source") or ""), str(row.get("model_id") or ""), str(row.get("document_id") or ""))
        prepared.append((row, key))
        if key[0]:
            grouped[key] = grouped.get(key, 0) + 1
    for row, key in prepared:
        if key[0]:
            row["score_shared_across_runs"] = grouped[key] > 1


def document_ids_in_model(model_blob: Mapping[str, Any]) -> List[str]:
    found = set()
    for layer in model_blob.values():
        if isinstance(layer, dict) and isinstance(layer.get("per_document"), dict):
            found.update(str(key) for key in layer["per_document"].keys())
    return sorted(found)


def score_record(path: Path, repo_root: Path, model_blob: Mapping[str, Any], document_id: str) -> Dict[str, Any]:
    completeness = document_layer(model_blob, "completeness", document_id)
    schema = document_layer(model_blob, "schema_validation", document_id)
    value = document_layer(model_blob, "value_accuracy", document_id)
    structural = document_layer(model_blob, "structural", document_id)
    judge = document_layer(model_blob, "llm_judge", document_id)
    novel = document_layer(model_blob, "novel_fields", document_id)
    return {
        "eval_completeness": first_number(
            nested(completeness, "summary", "overall_completeness"),
            nested(completeness, "overall_metrics", "overall_completeness"),
        ),
        "eval_required_completeness": first_number(
            nested(completeness, "summary", "required_completeness"),
            nested(completeness, "overall_metrics", "required_completeness"),
        ),
        "eval_value_mean": nested(value, "summary_metrics", "value_mean_score"),
        "eval_sheet_placement": nested(structural, "summary_metrics", "sheet_placement_accuracy"),
        "eval_row_f1": nested(structural, "summary_metrics", "row_alignment_f1"),
        "eval_schema_compliance": scalar(schema.get("schema_compliance_rate")) if isinstance(schema, dict) else "",
        "eval_llm_judge": scalar(judge.get("overall_score")) if isinstance(judge, dict) else "",
        "eval_precision_excl_discoveries": nested(novel, "summary_metrics", "precision_excl_discoveries"),
        "model_aggregate_score": scalar(model_blob.get("aggregate_score")),
        "score_source": path.relative_to(repo_root).as_posix(),
        "score_scope": "campaign_document",
    }


def index_record(item: Mapping[str, Any], path: Path, repo_root: Path) -> Dict[str, Any]:
    axes = item.get("axes") if isinstance(item.get("axes"), dict) else {}
    validation = item.get("validation") if isinstance(item.get("validation"), dict) else {}
    record = {
        "condition_id": scalar(item.get("condition_id")),
        "model_id": scalar(item.get("model_id")),
        "document_id": scalar(item.get("instance_id") or item.get("document_id")),
        "repetition": scalar(item.get("repetition")),
        "axis_information_coverage": scalar(axes.get("information_coverage")),
        "axis_value_accuracy": scalar(axes.get("value_accuracy")),
        "axis_structural_fidelity": scalar(axes.get("structural_fidelity")),
        "axis_interoperability": scalar(axes.get("interoperability")),
        "fairds_valid": scalar(validation.get("fairds_valid")),
        "isa_round_trip_valid": scalar(validation.get("isa_round_trip_valid")),
        "index_status": scalar(item.get("status")),
        "index_validation_status": scalar(validation.get("validation_status")),
        "index_source": path.relative_to(repo_root).as_posix(),
    }
    return record


def index_rank(record: Mapping[str, Any]) -> Tuple[int, int]:
    axes = [
        record.get("axis_information_coverage"),
        record.get("axis_value_accuracy"),
        record.get("axis_structural_fidelity"),
        record.get("axis_interoperability"),
    ]
    nonzero = any(value not in ("", None, 0, 0.0) for value in axes)
    validated = record.get("index_validation_status") not in ("", None, "not_run")
    return (int(bool(nonzero or validated)), int(bool(validated)))


def identity_matches(run_dir: Path, base: Path, row: Mapping[str, Any], model_key: str, document_id: str) -> bool:
    try:
        relative_parts = run_dir.relative_to(base).parts
    except ValueError:
        return False
    document_ok = document_id == row.get("document_id") or document_id in relative_parts
    model_ok = model_key in relative_parts or model_key in {row.get("model_id"), row.get("llm_model")}
    return document_ok and model_ok


def document_layer(model_blob: Mapping[str, Any], name: str, document_id: str) -> Any:
    layer = model_blob.get(name)
    if not isinstance(layer, dict):
        return {}
    per_document = layer.get("per_document")
    if not isinstance(per_document, dict):
        return {}
    value = per_document.get(document_id)
    return value if isinstance(value, dict) else {}


def find_named(repo_root: Path, filename: str) -> Iterable[Path]:
    for relative in EVAL_ROOTS + OUTPUT_ROOTS:
        root = repo_root / relative
        if root.is_dir():
            yield from find_files(root, (filename,))


def find_files(root: Path, names: Sequence[str]) -> List[Path]:
    """List marker files with ``find``.

    A Python ``os.walk`` over these trees stalls on this machine; ``find``
    returns the same paths quickly.
    """
    prune = []
    for index, name in enumerate(sorted(SKIP_DIR_NAMES)):
        if index:
            prune.append("-o")
        prune.extend(["-name", name])
    names_expr = []
    for index, name in enumerate(names):
        if index:
            names_expr.append("-o")
        names_expr.extend(["-name", name])
    completed = subprocess.run(
        [
            "find",
            str(root),
            "(",
            *prune,
            ")",
            "-prune",
            "-o",
            "-type",
            "f",
            "(",
            *names_expr,
            ")",
            "-print0",
        ],
        capture_output=True,
        check=False,
    )
    return [Path(part.decode()) for part in completed.stdout.split(b"\0") if part]


def nested(payload: Any, *keys: str) -> Any:
    current = payload
    for key in keys:
        if not isinstance(current, dict) or key not in current:
            return ""
        current = current[key]
    return scalar(current)


def first_number(*values: Any) -> Any:
    for value in values:
        if value != "":
            return value
    return ""


def scalar(value: Any) -> Any:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        if isinstance(value, float):
            return round(value, 6)
        return value
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    return ""


def clean_text(value: Any) -> str:
    if not value:
        return ""
    text = " ".join(str(value).split())
    text = SECRET_ASSIGNMENT_RE.sub(r"\1=[redacted]", text)
    text = SECRET_TOKEN_RE.sub("sk-[redacted]", text)
    return text[:300]


def load_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return None


def first_existing(*paths: Path) -> Optional[Path]:
    for path in paths:
        if path.is_file():
            return path
    return None


def file_size(path: Optional[Path]) -> Any:
    if path is None:
        return ""
    try:
        return path.stat().st_size
    except OSError:
        return ""


def iso_mtime(path: Optional[Path]) -> str:
    if path is None:
        return ""
    try:
        stamp = path.stat().st_mtime
    except OSError:
        return ""
    return datetime.fromtimestamp(stamp, timezone.utc).replace(microsecond=0).isoformat()


def sort_key(row: Mapping[str, Any]) -> Tuple[str, str, str, str, int, str]:
    repetition = str(row.get("repetition") or "")
    try:
        repetition_number = int(repetition)
    except ValueError:
        repetition_number = 10**9
    return (
        str(row.get("campaign") or ""),
        str(row.get("document_id") or ""),
        str(row.get("model_id") or ""),
        str(row.get("condition_id") or ""),
        repetition_number,
        str(row.get("run_dir") or ""),
    )


def write_csv(path: Path, rows: Sequence[Mapping[str, Any]], columns: Sequence[str]) -> None:
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(columns), extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow({column: format_cell(row.get(column, "")) for column in columns})


def format_cell(value: Any) -> Any:
    if isinstance(value, bool):
        return "true" if value else "false"
    return value


def build_summary(
    generated_at: str,
    evaluation_rows: Sequence[Mapping[str, Any]],
    output_rows: Sequence[Mapping[str, Any]],
    evaluation_path: Path,
    output_path: Path,
    repo_root: Path,
) -> Dict[str, Any]:
    return {
        "catalog_version": CATALOG_VERSION,
        "generated_at": generated_at,
        "evaluation_table": evaluation_path.relative_to(repo_root).as_posix(),
        "output_table": output_path.relative_to(repo_root).as_posix(),
        "refresh_command": "python evaluation/scripts/build_run_catalog.py",
        "evaluation": summarize_rows(evaluation_rows),
        "output": summarize_rows(output_rows),
    }


def summarize_rows(rows: Sequence[Mapping[str, Any]]) -> Dict[str, Any]:
    by_status: Dict[str, int] = {}
    by_campaign: Dict[str, int] = {}
    for row in rows:
        status = str(row.get("result_status") or "unknown")
        campaign = str(row.get("campaign") or "(none)")
        by_status[status] = by_status.get(status, 0) + 1
        by_campaign[campaign] = by_campaign.get(campaign, 0) + 1
    return {
        "runs": len(rows),
        "by_status": dict(sorted(by_status.items())),
        "campaigns": len(by_campaign),
    }


if __name__ == "__main__":
    sys.exit(main())
