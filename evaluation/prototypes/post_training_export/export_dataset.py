#!/usr/bin/env python3
"""Offline exporter: evaluation run dirs → post-training-ready JSONL.

Independent of the FAIRiAgent runtime. Reads existing artifacts only:
  - evaluation_results.json (value_accuracy gt/pred)
  - per-run metadata.json, llm_responses.json, processing_log.jsonl, runtime_config.json

Writes under evaluation/prototypes/post_training_export/artifacts/:
  - error_profile.jsonl
  - dpo_field_pairs.jsonl
  - sft_from_llm.jsonl          (only rows with full prompts)
  - trajectory_index.jsonl
  - export_manifest.json

Example:
  mamba run -n FAIRiAgent python evaluation/prototypes/post_training_export/export_dataset.py \\
    --eval-results evaluation/runs/shadow_pro_tuned/results/evaluation_results.json \\
    --run-root evaluation/runs/shadow_pro_tuned
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

ROOT = Path(__file__).resolve().parents[3]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(Path(__file__).resolve().parent))

from contracts import (  # noqa: E402
    classify_error_type,
    field_dpo_prompt,
    heuristic_swap_candidates,
)

DEFAULT_OUT = Path("evaluation/prototypes/post_training_export/artifacts")


def load_json(path: Path) -> Any:
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def write_jsonl(path: Path, rows: Iterable[Dict[str, Any]]) -> int:
    path.parent.mkdir(parents=True, exist_ok=True)
    n = 0
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")
            n += 1
    return n


def event_id(*parts: str) -> str:
    raw = "|".join(parts)
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()[:16]


def first_model_bucket(results: Dict[str, Any]) -> Tuple[str, Dict[str, Any]]:
    per_model = results.get("per_model_results") or {}
    if not per_model:
        raise ValueError("evaluation_results.json has no per_model_results")
    name, bucket = next(iter(per_model.items()))
    return name, bucket


def discover_doc_run_dirs(run_root: Path, model_config: str, doc_id: str) -> List[Path]:
    """Find run_* dirs for a document under a model config tree."""
    candidates: List[Path] = []
    model_dir = run_root / model_config
    if not model_dir.is_dir():
        # tolerate single nested model folder
        children = [p for p in run_root.iterdir() if p.is_dir() and p.name not in {"results", "outputs"}]
        for child in children:
            if (child / doc_id).is_dir():
                model_dir = child
                break
    doc_dir = model_dir / doc_id
    if not doc_dir.is_dir():
        return []
    for run_dir in sorted(doc_dir.glob("run_*")):
        if (run_dir / "metadata.json").exists() or (run_dir / "llm_responses.json").exists():
            candidates.append(run_dir)
    return candidates


def llm_prompt_quality(llm_path: Path) -> Tuple[int, int, List[str]]:
    """Return (n_calls, n_with_prompt, operations)."""
    if not llm_path.exists():
        return 0, 0, []
    data = load_json(llm_path)
    if not isinstance(data, list):
        return 0, 0, []
    ops = []
    with_prompt = 0
    for item in data:
        if not isinstance(item, dict):
            continue
        ops.append(str(item.get("operation") or ""))
        prompt = item.get("prompt")
        if prompt:
            with_prompt += 1
    return len(data), with_prompt, ops


def messages_from_prompt_field(prompt: Any) -> List[Dict[str, str]]:
    """Normalize llm_responses.prompt into chat messages."""
    if isinstance(prompt, str):
        return [{"role": "user", "content": prompt}]
    if isinstance(prompt, list):
        messages = []
        for msg in prompt:
            if not isinstance(msg, dict):
                continue
            role = str(msg.get("role") or msg.get("type") or "user")
            content = msg.get("content")
            if content is None:
                continue
            if not isinstance(content, str):
                content = json.dumps(content, ensure_ascii=False)
            # LangChain sometimes uses 'human'/'ai'/'system'
            role_map = {"human": "user", "ai": "assistant", "system": "system", "user": "user", "assistant": "assistant"}
            messages.append({"role": role_map.get(role.lower(), role), "content": content})
        return messages
    return []


def iter_value_mismatches(
    model_config: str,
    value_accuracy: Dict[str, Any],
) -> Iterable[Dict[str, Any]]:
    per_doc = value_accuracy.get("per_document") or {}
    for doc_id, doc_val in per_doc.items():
        for sheet_name, sheet in (doc_val.get("per_sheet") or {}).items():
            for row_idx, row in enumerate(sheet.get("row_details") or []):
                for item in row.get("fields") or []:
                    status = str(item.get("status") or "").lower()
                    if status not in {"wrong", "partial", "missing"}:
                        continue
                    field = str(item.get("field") or "")
                    gt = str(item.get("gt_snippet") or "")
                    pred = str(item.get("pred_snippet") or "")
                    yield {
                        "doc_id": doc_id,
                        "model_config": model_config,
                        "isa_sheet": sheet_name,
                        "row_idx": row_idx,
                        "field_name": field,
                        "status": status,
                        "score": float(item.get("score") or 0.0),
                        "match_type": item.get("match_type"),
                        "gt_snippet": gt,
                        "pred_snippet": pred,
                    }


def build_exports(
    eval_results: Dict[str, Any],
    run_root: Path,
    include_match_for_sft: bool = False,
) -> Dict[str, List[Dict[str, Any]]]:
    model_config, model_bucket = first_model_bucket(eval_results)
    value_accuracy = model_bucket.get("value_accuracy") or {}
    novel = model_bucket.get("novel_fields") or {}

    error_rows: List[Dict[str, Any]] = []
    dpo_rows: List[Dict[str, Any]] = []
    sft_rows: List[Dict[str, Any]] = []
    traj_rows: List[Dict[str, Any]] = []

    # --- field mismatches → error profile + DPO ---
    for mm in iter_value_mismatches(model_config, value_accuracy):
        err_type = classify_error_type(
            mm["status"], mm["field_name"], mm["gt_snippet"], mm["pred_snippet"]
        )
        swaps = heuristic_swap_candidates(mm["gt_snippet"], mm["pred_snippet"])
        eid = event_id(
            model_config,
            mm["doc_id"],
            mm["isa_sheet"],
            mm["field_name"],
            mm["status"],
            mm["gt_snippet"],
            mm["pred_snippet"],
        )
        run_dirs = discover_doc_run_dirs(run_root, model_config, mm["doc_id"])
        run_dir = str(run_dirs[0]) if run_dirs else ""
        error_rows.append(
            {
                "event_id": eid,
                "doc_id": mm["doc_id"],
                "model_config": model_config,
                "run_dir": run_dir,
                "isa_sheet": mm["isa_sheet"],
                "field_name": mm["field_name"],
                "status": mm["status"],
                "score": mm["score"],
                "match_type": mm.get("match_type"),
                "gt_snippet": mm["gt_snippet"],
                "pred_snippet": mm["pred_snippet"],
                "error_type": err_type,
                "swap_from": swaps["swap_from"],
                "swap_to": swaps["swap_to"],
                "steer_polarity": "corrective",
                "provenance": "field_pair_only",
            }
        )
        # DPO-lite: same synthetic prompt, chosen=GT, rejected=pred (when wrong/partial with both)
        if mm["status"] in {"wrong", "partial"} and mm["gt_snippet"] and mm["pred_snippet"]:
            dpo_rows.append(
                {
                    "id": f"dpo_{eid}",
                    "doc_id": mm["doc_id"],
                    "model_config": model_config,
                    "field_name": mm["field_name"],
                    "isa_sheet": mm["isa_sheet"],
                    "prompt": field_dpo_prompt(mm["field_name"], mm["isa_sheet"]),
                    "chosen": mm["gt_snippet"],
                    "rejected": mm["pred_snippet"],
                    "provenance": "field_pair_only",
                    "source_run_dir": run_dir,
                    "training_ready": False,  # needs richer prompt/context before real DPO
                    "note": "Synthetic field prompt; use as seed pairs, enrich with document span for training.",
                }
            )

    # --- novel unsupported_fabrication → error profile ---
    for doc_id, doc_novel in (novel.get("per_document") or {}).items():
        classified = doc_novel.get("classified_fields") or doc_novel.get("fields") or []
        if isinstance(classified, dict):
            # tolerate bucketed structure
            buckets = classified
            classified = []
            for bucket, items in buckets.items():
                for it in items or []:
                    if isinstance(it, dict):
                        it = dict(it)
                        it.setdefault("bucket", bucket)
                        classified.append(it)
        for item in classified:
            if not isinstance(item, dict):
                continue
            bucket = str(item.get("bucket") or item.get("label") or item.get("category") or "")
            if "fabrication" not in bucket.lower() and item.get("category") != "unsupported_fabrication":
                continue
            field = str(item.get("field_name") or item.get("field") or item.get("name") or "")
            pred = str(item.get("value") or item.get("pred_snippet") or "")
            eid = event_id(model_config, doc_id, "novel", field, pred)
            run_dirs = discover_doc_run_dirs(run_root, model_config, doc_id)
            error_rows.append(
                {
                    "event_id": eid,
                    "doc_id": doc_id,
                    "model_config": model_config,
                    "run_dir": str(run_dirs[0]) if run_dirs else "",
                    "isa_sheet": item.get("isa_sheet") or "unknown",
                    "field_name": field,
                    "status": "extra",
                    "score": float(item.get("score") or 0.0),
                    "gt_snippet": "",
                    "pred_snippet": pred,
                    "error_type": "unsupported_fabrication",
                    "swap_from": None,
                    "swap_to": None,
                    "steer_polarity": "corrective",
                    "provenance": "field_pair_only",
                }
            )

    # --- trajectory index + optional SFT from llm_responses with full prompts ---
    per_doc_ids = set((value_accuracy.get("per_document") or {}).keys())
    # also scan run_root for docs even if missing from value_accuracy
    model_dir = run_root / model_config
    if not model_dir.is_dir():
        children = [p for p in run_root.iterdir() if p.is_dir() and p.name not in {"results", "outputs"}]
        model_dir = children[0] if len(children) == 1 else model_dir
    if model_dir.is_dir():
        for doc_dir in sorted(model_dir.iterdir()):
            if doc_dir.is_dir() and not doc_dir.name.startswith("."):
                per_doc_ids.add(doc_dir.name)

    for doc_id in sorted(per_doc_ids):
        run_dirs = discover_doc_run_dirs(run_root, model_config, doc_id)
        doc_val = (value_accuracy.get("per_document") or {}).get(doc_id) or {}
        summary = doc_val.get("summary_metrics") or {}
        for run_dir in run_dirs:
            llm_path = run_dir / "llm_responses.json"
            n_calls, n_prompt, ops = llm_prompt_quality(llm_path)
            artifacts = {
                "metadata.json": (run_dir / "metadata.json").exists(),
                "llm_responses.json": llm_path.exists(),
                "processing_log.jsonl": (run_dir / "processing_log.jsonl").exists(),
                "runtime_config.json": (run_dir / "runtime_config.json").exists(),
                "workflow_report.json": (run_dir / "workflow_report.json").exists(),
                "eval_result.json": (run_dir / "eval_result.json").exists(),
            }
            success = None
            if (run_dir / "eval_result.json").exists():
                er = load_json(run_dir / "eval_result.json")
                if isinstance(er, dict) and "success" in er:
                    success = bool(er.get("success"))
            traj_rows.append(
                {
                    "doc_id": doc_id,
                    "model_config": model_config,
                    "run_dir": str(run_dir),
                    "success": success,
                    "n_llm_calls": n_calls,
                    "n_with_full_prompt": n_prompt,
                    "has_full_prompts": n_prompt > 0,
                    "operations": sorted({o for o in ops if o}),
                    "artifacts": artifacts,
                    "value_summary": {
                        "mean_score": summary.get("mean_score"),
                        "value_match_rate": summary.get("value_match_rate"),
                        "wrong_count": summary.get("wrong_count"),
                        "missing_count": summary.get("missing_count"),
                        "partial_count": summary.get("partial_count"),
                    },
                    "training_ready_sft": n_prompt > 0,
                    "training_ready_dpo_field": True,
                    "gap": (
                        None
                        if n_prompt > 0
                        else "llm_responses.json lacks serialized prompt; re-run with current llm_helper logging for SFT/DPO trajectory pairs"
                    ),
                }
            )
            if n_prompt == 0 or not llm_path.exists():
                continue
            for idx, item in enumerate(load_json(llm_path)):
                if not isinstance(item, dict) or not item.get("prompt"):
                    continue
                messages = messages_from_prompt_field(item["prompt"])
                response = item.get("response")
                if not messages or not response:
                    continue
                # Keep assistant target as recorded response (teacher trajectory).
                # For corrective SFT, prefer GT-augmented exports above.
                chat = list(messages)
                if chat and chat[-1].get("role") == "assistant":
                    chat[-1] = {"role": "assistant", "content": str(response)}
                else:
                    chat.append({"role": "assistant", "content": str(response)})
                sft_rows.append(
                    {
                        "id": event_id(str(run_dir), str(idx), str(item.get("operation"))),
                        "doc_id": doc_id,
                        "model_config": model_config,
                        "operation": item.get("operation"),
                        "messages": chat,
                        "provenance": "full_prompt",
                        "source_run_dir": str(run_dir),
                        "training_ready": True,
                        "label": "teacher_trajectory",
                    }
                )

    del include_match_for_sft  # reserved for future GT-rewritten SFT
    return {
        "error_profile": error_rows,
        "dpo_field_pairs": dpo_rows,
        "sft_from_llm": sft_rows,
        "trajectory_index": traj_rows,
    }


def build_manifest(exports: Dict[str, List[Dict[str, Any]]], eval_path: Path, run_root: Path) -> Dict[str, Any]:
    traj = exports["trajectory_index"]
    n_traj = len(traj)
    n_full = sum(1 for t in traj if t.get("has_full_prompts"))
    return {
        "eval_results": str(eval_path),
        "run_root": str(run_root),
        "counts": {k: len(v) for k, v in exports.items()},
        "prompt_coverage": {
            "trajectories": n_traj,
            "with_full_prompts": n_full,
            "fraction": (n_full / n_traj) if n_traj else 0.0,
        },
        "training_readiness": {
            "error_profile_for_steer_lab": True,
            "dpo_field_pairs_seed": True,
            "dpo_field_pairs_production": False,
            "sft_teacher_trajectories": n_full > 0,
            "blocker": (
                None
                if n_full > 0
                else "Existing llm_responses.json files omit full prompts (prompt_length only). "
                "Current fairifier.utils.llm_helper already logs prompt; new runs will unlock SFT/DPO trajectory export."
            ),
        },
        "recommended_next_steps": [
            "Use error_profile.jsonl for J-lens swap/steer case selection (swap_from/swap_to).",
            "Enrich dpo_field_pairs with document evidence spans before preference training.",
            "Re-run a small local-model eval so llm_responses includes full prompts for FireAct-style SFT.",
        ],
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--eval-results",
        type=Path,
        required=True,
        help="Path to evaluation_results.json",
    )
    parser.add_argument(
        "--run-root",
        type=Path,
        required=True,
        help="Root directory containing <model>/<doc_id>/run_* artifacts",
    )
    parser.add_argument(
        "--out-dir",
        type=Path,
        default=DEFAULT_OUT,
        help="Output directory for JSONL + manifest",
    )
    args = parser.parse_args()

    eval_results = load_json(args.eval_results)
    exports = build_exports(eval_results, args.run_root)
    out = args.out_dir
    out.mkdir(parents=True, exist_ok=True)

    counts = {}
    for name, rows in exports.items():
        counts[name] = write_jsonl(out / f"{name}.jsonl", rows)

    manifest = build_manifest(exports, args.eval_results, args.run_root)
    manifest_path = out / "export_manifest.json"
    with manifest_path.open("w", encoding="utf-8") as handle:
        json.dump(manifest, handle, indent=2, ensure_ascii=False)

    print(json.dumps({"wrote": counts, "manifest": str(manifest_path), **manifest["training_readiness"]}, indent=2))


if __name__ == "__main__":
    main()
