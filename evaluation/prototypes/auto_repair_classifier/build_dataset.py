#!/usr/bin/env python3
"""Build a field-level decision table from paired Shadow/Tuned eval runs."""

from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from rules import fallback_decision, normalize_field


STATUS_RANK = {"missing": 0, "wrong": 1, "partial": 2, "match": 3}
DEFAULT_ROOT = Path("evaluation/prototypes/auto_repair_classifier")


def load_json(path: Path) -> Dict[str, Any]:
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def first_model_result(results: Dict[str, Any]) -> Dict[str, Any]:
    per_model = results.get("per_model_results") or {}
    if not per_model:
        raise ValueError("evaluation_results.json has no per_model_results")
    return next(iter(per_model.values()))


def first_model_metrics(results: Dict[str, Any]) -> Dict[str, Any]:
    metrics = (results.get("model_comparison") or {}).get("metrics") or {}
    return next(iter(metrics.values())) if metrics else {}


def discover_model_run_root(run_dir: Path) -> Path:
    children = [
        p for p in run_dir.iterdir()
        if p.is_dir() and p.name not in {"results", "outputs"}
    ]
    direct = [p for p in children if any(p.glob("*/run_*/workflow_report.json"))]
    if len(direct) == 1:
        return direct[0]
    if len(children) == 1:
        return children[0]
    raise ValueError(f"Could not uniquely identify model run root under {run_dir}")


def aggregate_value_fields(doc_value: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
    fields: Dict[str, Dict[str, Any]] = {}
    for sheet_name, sheet in (doc_value.get("per_sheet") or {}).items():
        for row in sheet.get("row_details") or []:
            for item in row.get("fields") or []:
                field = normalize_field(item.get("field") or "")
                if not field:
                    continue
                status = str(item.get("status") or "missing").lower()
                score = float(item.get("score") or 0.0)
                current = fields.get(field)
                if current is None:
                    fields[field] = {
                        "field": field,
                        "sheet": sheet_name,
                        "status": status,
                        "score": score,
                        "occurrences": 1,
                    }
                    continue
                current["occurrences"] += 1
                if (score, STATUS_RANK.get(status, 0)) > (
                    current["score"],
                    STATUS_RANK.get(current["status"], 0),
                ):
                    current.update({"sheet": sheet_name, "status": status, "score": score})
    return fields


def doc_metrics(model: Dict[str, Any], doc_id: str) -> Dict[str, float]:
    completeness = (
        ((model.get("completeness") or {}).get("per_document") or {})
        .get(doc_id, {})
        .get("overall_metrics", {})
    )
    structural = (
        ((model.get("structural") or {}).get("per_document") or {})
        .get(doc_id, {})
        .get("summary_metrics", {})
    )
    schema = (
        ((model.get("schema_validation") or {}).get("per_document") or {})
        .get(doc_id, {})
    )
    llm = (((model.get("llm_judge") or {}).get("per_document") or {}).get(doc_id, {}))
    return {
        "completeness": float(completeness.get("overall_completeness") or 0.0),
        "extra_fields": float(completeness.get("extra_fields") or 0.0),
        "row_alignment_f1": float(structural.get("row_alignment_f1") or 0.0),
        "sheet_placement_accuracy": float(structural.get("sheet_placement_accuracy") or 0.0),
        "schema_compliance": float(schema.get("schema_compliance_rate") or 0.0),
        "llm_judge_score": float(llm.get("overall_score") or llm.get("score") or 0.0),
    }


def workflow_report_for(model_root: Path, doc_id: str) -> Optional[Path]:
    direct = model_root / doc_id / "run_1" / "workflow_report.json"
    if direct.exists():
        return direct
    matches = sorted(model_root.glob(f"**/{doc_id}/run_*/workflow_report.json"))
    return matches[0] if matches else None


def retrieval_stats(model_root: Path, doc_id: str) -> Dict[str, Dict[str, Any]]:
    path = workflow_report_for(model_root, doc_id)
    if path is None:
        return {}
    stats = (load_json(path).get("retrieval_metrics") or {}).get("field_retrieval_stats") or []
    return {normalize_field(item.get("field") or ""): item for item in stats}


def make_labels(row: Dict[str, Any]) -> Tuple[int, int, int]:
    shadow_rank = STATUS_RANK.get(row["shadow_status"], 0)
    tuned_rank = STATUS_RANK.get(row["tuned_status"], 0)
    shadow_bad = shadow_rank <= 1 or row["shadow_score"] < 0.5
    tuned_improved = row["score_delta"] >= 0.2 or tuned_rank > shadow_rank
    should_repair = int(shadow_bad and tuned_improved and row["semantic_hit_count"] > 0)
    decision = fallback_decision(row)
    safe_accept = int(should_repair and decision["guard_ok"])
    risky_tuned = int(row["extra_fields_delta"] > 25 or row["row_alignment_f1_delta"] < -0.05)
    return should_repair, safe_accept, risky_tuned


def build_rows(phase4_results: Path, shadow_results: Path, phase4_root: Path, shadow_root: Path) -> List[Dict[str, Any]]:
    phase4_json = load_json(phase4_results)
    shadow_json = load_json(shadow_results)
    phase4 = first_model_result(phase4_json)
    shadow = first_model_result(shadow_json)
    phase4_metrics = first_model_metrics(phase4_json)
    shadow_metrics = first_model_metrics(shadow_json)
    phase4_docs = ((phase4.get("value_accuracy") or {}).get("per_document") or {})
    shadow_docs = ((shadow.get("value_accuracy") or {}).get("per_document") or {})

    rows: List[Dict[str, Any]] = []
    for doc_id in sorted(set(phase4_docs) & set(shadow_docs)):
        phase4_fields = aggregate_value_fields(phase4_docs[doc_id])
        shadow_fields = aggregate_value_fields(shadow_docs[doc_id])
        phase4_doc = doc_metrics(phase4, doc_id)
        shadow_doc = doc_metrics(shadow, doc_id)
        phase4_retrieval = retrieval_stats(phase4_root, doc_id)
        shadow_retrieval = retrieval_stats(shadow_root, doc_id)

        for field in sorted(set(phase4_fields) | set(shadow_fields)):
            tuned = phase4_fields.get(field, {"field": field, "sheet": "", "status": "missing", "score": 0.0, "occurrences": 0})
            shd = shadow_fields.get(field, {"field": field, "sheet": tuned.get("sheet", ""), "status": "missing", "score": 0.0, "occurrences": 0})
            rt = phase4_retrieval.get(field) or shadow_retrieval.get(field) or {}
            row: Dict[str, Any] = {
                "doc_id": doc_id,
                "field": field,
                "sheet": tuned.get("sheet") or shd.get("sheet") or "",
                "shadow_status": shd["status"],
                "tuned_status": tuned["status"],
                "shadow_score": round(float(shd["score"]), 4),
                "tuned_score": round(float(tuned["score"]), 4),
                "score_delta": round(float(tuned["score"]) - float(shd["score"]), 4),
                "shadow_occurrences": int(shd.get("occurrences") or 0),
                "tuned_occurrences": int(tuned.get("occurrences") or 0),
                "lexical_hit_count": int(rt.get("lexical_hit_count") or 0),
                "semantic_hit_count": int(rt.get("semantic_hit_count") or 0),
                "hybrid_hit_count": int(rt.get("hybrid_hit_count") or 0),
                "prompt_mode": rt.get("prompt_mode") or "",
                "rerank_status": rt.get("rerank_status") or "",
                "semantic_only_hint": int((rt.get("lexical_hit_count") or 0) == 0 and (rt.get("semantic_hit_count") or 0) > 0),
                "completeness_delta": round(phase4_doc["completeness"] - shadow_doc["completeness"], 4),
                "extra_fields_delta": round(phase4_doc["extra_fields"] - shadow_doc["extra_fields"], 4),
                "row_alignment_f1_delta": round(phase4_doc["row_alignment_f1"] - shadow_doc["row_alignment_f1"], 4),
                "sheet_placement_delta": round(phase4_doc["sheet_placement_accuracy"] - shadow_doc["sheet_placement_accuracy"], 4),
                "schema_delta": round(phase4_doc["schema_compliance"] - shadow_doc["schema_compliance"], 4),
                "llm_judge_delta": round(phase4_doc["llm_judge_score"] - shadow_doc["llm_judge_score"], 4),
                "global_aggregate_delta": round(float(phase4_metrics.get("aggregate_score") or 0.0) - float(shadow_metrics.get("aggregate_score") or 0.0), 4),
            }
            should_repair, safe_accept, risky_tuned = make_labels(row)
            decision = fallback_decision(row)
            row.update({
                "should_repair_label": should_repair,
                "safe_accept_label": safe_accept,
                "risky_tuned_label": risky_tuned,
                "fallback_decision": decision["decision"],
                "fallback_accept_patch": int(decision["accept_patch"]),
                "fallback_repair_score": decision["repair_score"],
                "fallback_reasons": ";".join(decision["repair_reasons"]),
                "fallback_guard_failures": ";".join(decision["guard_failures"]),
            })
            rows.append(row)
    return rows


def write_csv(rows: List[Dict[str, Any]], output: Path) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    if not rows:
        raise ValueError("No rows to write")
    with output.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--phase4-results", type=Path, default=Path("evaluation/runs/phase4_pro_tuned/results/evaluation_results.json"))
    parser.add_argument("--shadow-results", type=Path, default=Path("evaluation/runs/shadow_pro_tuned/results/evaluation_results.json"))
    parser.add_argument("--phase4-run-root", type=Path)
    parser.add_argument("--shadow-run-root", type=Path)
    parser.add_argument("--output", type=Path, default=DEFAULT_ROOT / "artifacts/pro_field_decisions.csv")
    args = parser.parse_args()

    phase4_root = args.phase4_run_root or discover_model_run_root(args.phase4_results.parents[1])
    shadow_root = args.shadow_run_root or discover_model_run_root(args.shadow_results.parents[1])
    rows = build_rows(args.phase4_results, args.shadow_results, phase4_root, shadow_root)
    write_csv(rows, args.output)
    print(f"Wrote {len(rows)} field rows to {args.output}")
    print(f"should_repair positives: {sum(int(row['should_repair_label']) for row in rows)}")
    print(f"safe_accept positives: {sum(int(row['safe_accept_label']) for row in rows)}")


if __name__ == "__main__":
    main()
