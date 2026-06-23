#!/usr/bin/env python3
"""
FAIRiAgent — Paper Experiment Comprehensive Analysis
=====================================================
Parses all evaluation run data (batch outputs + eval runs) and computes:
  - Field-ID F1 per sheet per document
  - Value-level F1 (exact + normalized match)
  - Mandatory field coverage
  - Confidence score distributions
  - Source grounding statistics
  - Cross-model comparison tables
"""

import json
import os
import re
import sys
from pathlib import Path
from collections import defaultdict
from datetime import datetime

PROJECT_ROOT = Path(__file__).resolve().parents[2]
EVAL_DIR = PROJECT_ROOT / "evaluation"
RUNS_DIR = EVAL_DIR / "runs"
VALUES_DIR = EVAL_DIR / "datasets" / "annotated" / "values"
OUTPUT_DIR = EVAL_DIR / "paper_experiments_v1"

SHEETS = ["investigation", "study", "observationunit", "sample", "assay"]
SKIP_KEYS = {"_evidence", "_ambiguity", "_ambiguity_rationale", "generated_by", "generated_at"}

# ── Helpers ───────────────────────────────────────────────────────────

def normalize_value(v):
    """Normalize a value for comparison."""
    if v is None:
        return ""
    if isinstance(v, (dict, list)):
        return json.dumps(v, sort_keys=True)
    s = str(v).strip().lower()
    s = re.sub(r"\s+", " ", s)
    s = s.rstrip(".,;:")
    return s

def values_match(v1, v2, numeric_tol=0.01):
    """Check if two values match (exact or numeric tolerance)."""
    n1 = normalize_value(v1)
    n2 = normalize_value(v2)
    if n1 == n2:
        return True
    # Try numeric comparison
    try:
        f1 = float(v1)
        f2 = float(v2)
        return abs(f1 - f2) / max(abs(f2), 1e-9) < numeric_tol
    except (ValueError, TypeError):
        pass
    # Substring match for long values
    if len(n1) > 10 and len(n2) > 10:
        if n1 in n2 or n2 in n1:
            return True
    return False

# ── Load Ground Truth ─────────────────────────────────────────────────

def load_gt_values():
    """Load per-document ground truth values with ISA row structure."""
    docs = {}
    for vf in sorted(VALUES_DIR.glob("ground_truth_*_values.json")):
        with open(vf) as f:
            data = json.load(f)
        doc_id = data["document_id"]
        sheets = data.get("isa_sheets", {})
        doc_data = {"document_id": doc_id, "sheets": {}}
        for sname in SHEETS:
            sdata = sheets.get(sname, {})
            rows = sdata.get("expected_rows", [])
            parsed_rows = []
            for row in rows:
                if isinstance(row, dict):
                    clean = {k: v for k, v in row.items()
                             if k not in SKIP_KEYS and v is not None and v != ""}
                    parsed_rows.append(clean)
            doc_data["sheets"][sname] = {
                "rows": parsed_rows,
                "multi_row": sdata.get("multi_row", len(parsed_rows) > 1),
            }
        docs[doc_id] = doc_data
    return docs

# ── Collect Prediction Data ───────────────────────────────────────────

def collect_batch_outputs():
    """Collect metadata.json from output/*eval_batch*/ directories."""
    outputs = []
    batch_dirs = sorted(PROJECT_ROOT.glob("output/*eval_batch*"))
    for bd in batch_dirs:
        meta_path = bd / "metadata.json"
        if not meta_path.exists():
            continue
        try:
            with open(meta_path) as f:
                pred = json.load(f)
        except (json.JSONDecodeError, IOError):
            continue
        # Extract document name from directory
        dir_name = bd.name
        doc_id = dir_name.replace("_eval_batch_27b_20260504_0643", "").replace("_eval_batch_", "")
        outputs.append({
            "source": "batch_output",
            "doc_id": doc_id,
            "dir_name": dir_name,
            "model_family": "qwen3.6-27b",  # These are from 27b batch
            "config": "qwen3.6-27b",
            "metadata_path": str(meta_path),
            "pred": pred,
        })
    return outputs

def collect_eval_runs():
    """Collect eval_result.json + metadata.json from evaluation/runs/."""
    runs = []
    for run_dir in sorted(RUNS_DIR.iterdir()):
        if run_dir.name in ("docinputs", "paper_experiments_v1"):
            continue
        if not run_dir.is_dir():
            continue
        # Walk deep into subdirectories to find eval_result.json
        for eval_file in sorted(run_dir.rglob("eval_result.json")):
            try:
                with open(eval_file) as f:
                    eval_data = json.load(f)
            except (json.JSONDecodeError, IOError):
                continue
            doc_id = eval_data.get("document_id", "")
            if not doc_id:
                continue
            # Find corresponding metadata.json
            meta_path = eval_file.parent / "metadata.json"
            pred = None
            if meta_path.exists():
                try:
                    with open(meta_path) as f:
                        pred = json.load(f)
                except (json.JSONDecodeError, IOError):
                    pass
            # Determine model
            config = eval_data.get("config_name", "")
            model_family = "unknown"
            if "deepseek" in config.lower():
                model_family = "deepseek-v4-pro"
            elif "27b" in config.lower():
                model_family = "qwen3.6-27b"
            elif "35b" in config.lower():
                model_family = "qwen3.6-35b"
            elif "qwen" in config.lower():
                model_family = "qwen3.6-35b"

            runs.append({
                "source": "eval_runs",
                "doc_id": doc_id,
                "model_family": model_family,
                "config": config,
                "run_idx": eval_data.get("run_idx", 1),
                "success": eval_data.get("success", False),
                "n_fields": eval_data.get("n_fields_extracted", 0),
                "duration_s": eval_data.get("runtime_seconds", 0),
                "confidence": eval_data.get("confidence_scores", {}),
                "metadata_path": str(meta_path) if meta_path.exists() else "",
                "eval_result_path": str(eval_file),
                "pred": pred,
            })
    return runs

# ── Compute Metrics for One Prediction ────────────────────────────────

def compute_metrics(pred, gt_doc):
    """Compute per-sheet and overall F1, coverage, value-F1."""
    if pred is None:
        return None

    # Handle two different output formats:
    # Format 1 (batch): isa_values -> sheet -> {columns, rows: [{col: val}]}
    # Format 2 (eval runs): isa_structure -> sheet -> {fields: [{field_name, value}]}
    pred_sheets = pred.get("isa_values", {})
    if not pred_sheets or not isinstance(pred_sheets, dict) or not any(
            isinstance(v, dict) and v.get("rows") for v in pred_sheets.values()):
        # Try isa_structure format
        alt_sheets = pred.get("isa_structure", {})
        if isinstance(alt_sheets, dict):
            pred_sheets = {}
            for sname, sdata in alt_sheets.items():
                if isinstance(sdata, dict):
                    fields = sdata.get("fields", [])
                    if fields and isinstance(fields, list) and isinstance(fields[0], dict):
                        # Convert [{field_name, value}] to {columns, rows: [{col: val}]}
                        row_dict = {}
                        for f in fields:
                            fn = f.get("field_name", f.get("name", ""))
                            fv = f.get("value", "")
                            if fn and fv:
                                row_dict[fn] = fv
                        pred_sheets[sname] = {"columns": list(row_dict.keys()), "rows": [row_dict]}

    stats = pred.get("statistics", {})

    results = {"per_sheet": {}, "overall": {}}

    total_tp_id = 0
    total_fp_id = 0
    total_fn_id = 0
    total_tp_val = 0
    total_fp_val = 0
    total_fn_val = 0

    for sheet in SHEETS:
        ps = pred_sheets.get(sheet, {})
        gs = gt_doc.get("sheets", {}).get(sheet, {})

        # Extract predicted (field_name, value) pairs
        pred_pairs = []  # list of (col, value)
        pred_cols_set = set()
        pred_rows = ps.get("rows", [])
        for row in pred_rows:
            if isinstance(row, dict):
                for col, val in row.items():
                    if col in SKIP_KEYS:
                        continue
                    if val is not None and val != "" and val != "N/A":
                        pred_pairs.append((col, val))
                        pred_cols_set.add(col)

        # Extract GT (field_name, value) pairs
        gt_pairs = []
        gt_cols_set = set()
        gt_rows = gs.get("rows", [])
        for row in gt_rows:
            if isinstance(row, dict):
                for col, val in row.items():
                    if col in SKIP_KEYS:
                        continue
                    if val is not None and val != "" and val != "N/A":
                        gt_pairs.append((col, val))
                        gt_cols_set.add(col)

        # Field-ID level matching
        tp_id = len(pred_cols_set & gt_cols_set)
        fp_id = len(pred_cols_set - gt_cols_set)
        fn_id = len(gt_cols_set - pred_cols_set)

        # Value-level matching (greedy per field_name)
        tp_val = 0
        matched_gt_indices = set()
        for pcol, pval in pred_pairs:
            for gi, (gcol, gval) in enumerate(gt_pairs):
                if pcol == gcol and gi not in matched_gt_indices:
                    if values_match(pval, gval):
                        tp_val += 1
                        matched_gt_indices.add(gi)
                        break
        fp_val = len(pred_pairs) - tp_val
        fn_val = len(gt_pairs) - tp_val

        # Compute rates
        p_id = tp_id / (tp_id + fp_id) if (tp_id + fp_id) > 0 else 0
        r_id = tp_id / (tp_id + fn_id) if (tp_id + fn_id) > 0 else 0
        f1_id = 2 * p_id * r_id / (p_id + r_id) if (p_id + r_id) > 0 else 0

        p_val = tp_val / (tp_val + fp_val) if (tp_val + fp_val) > 0 else 0
        r_val = tp_val / (tp_val + fn_val) if (tp_val + fn_val) > 0 else 0
        f1_val = 2 * p_val * r_val / (p_val + r_val) if (p_val + r_val) > 0 else 0

        results["per_sheet"][sheet] = {
            "f1_field_id": round(f1_id, 4),
            "precision_id": round(p_id, 4),
            "recall_id": round(r_id, 4),
            "f1_value": round(f1_val, 4),
            "precision_val": round(p_val, 4),
            "recall_val": round(r_val, 4),
            "tp_id": tp_id, "fp_id": fp_id, "fn_id": fn_id,
            "tp_val": tp_val, "fp_val": fp_val, "fn_val": fn_val,
            "n_pred_rows": len(pred_rows),
            "n_gt_rows": len(gt_rows),
            "n_pred_values": len(pred_pairs),
            "n_gt_values": len(gt_pairs),
        }

        total_tp_id += tp_id
        total_fp_id += fp_id
        total_fn_id += fn_id
        total_tp_val += tp_val
        total_fp_val += fp_val
        total_fn_val += fn_val

    # Overall metrics (micro-averaged)
    p_id_micro = total_tp_id / (total_tp_id + total_fp_id) if (total_tp_id + total_fp_id) > 0 else 0
    r_id_micro = total_tp_id / (total_tp_id + total_fn_id) if (total_tp_id + total_fn_id) > 0 else 0
    f1_id_micro = 2 * p_id_micro * r_id_micro / (p_id_micro + r_id_micro) if (p_id_micro + r_id_micro) > 0 else 0

    p_val_micro = total_tp_val / (total_tp_val + total_fp_val) if (total_tp_val + total_fp_val) > 0 else 0
    r_val_micro = total_tp_val / (total_tp_val + total_fn_val) if (total_tp_val + total_fn_val) > 0 else 0
    f1_val_micro = 2 * p_val_micro * r_val_micro / (p_val_micro + r_val_micro) if (p_val_micro + r_val_micro) > 0 else 0

    # Source grounding
    grounding = stats.get("source_grounding_summary", {})
    overall_conf = pred.get("overall_confidence")

    results["overall"] = {
        "f1_field_id_micro": round(f1_id_micro, 4),
        "precision_id_micro": round(p_id_micro, 4),
        "recall_id_micro": round(r_id_micro, 4),
        "f1_value_micro": round(f1_val_micro, 4),
        "precision_val_micro": round(p_val_micro, 4),
        "recall_val_micro": round(r_val_micro, 4),
        "total_tp_id": total_tp_id, "total_fp_id": total_fp_id, "total_fn_id": total_fn_id,
        "total_tp_val": total_tp_val, "total_fp_val": total_fp_val, "total_fn_val": total_fn_val,
        "n_total_pred_fields": sum(sum(1 for r in pred_sheets.get(s, {}).get("rows", [])
                                         if isinstance(r, dict)
                                         for k, v in r.items() if k not in SKIP_KEYS and v and v != "N/A")
                                    for s in SHEETS),
        "n_total_pred_rows": sum(len(pred_sheets.get(s, {}).get("rows", [])) for s in SHEETS),
        "n_total_gt_rows": sum(len(gt_doc.get("sheets", {}).get(s, {}).get("rows", [])) for s in SHEETS),
        "overall_confidence": overall_conf,
        "confirmed_fields": stats.get("confirmed_fields", 0),
        "provisional_fields": stats.get("provisional_fields", 0),
        "ungrounded_high_conf": grounding.get("ungrounded_high_confidence_fields", 0),
        "source_grounded": grounding.get("source_grounded_fields", 0),
        "packages_used": pred.get("packages_used", []),
    }

    return results

# ── Main ──────────────────────────────────────────────────────────────

def main():
    print("=" * 80)
    print("FAIRiAgent — Comprehensive Paper Experiment Analysis")
    print(f"Started: {datetime.now().isoformat()}")
    print("=" * 80)

    gt_docs = load_gt_values()
    print(f"\nLoaded ground truth: {len(gt_docs)} documents")
    for doc_id, d in sorted(gt_docs.items()):
        n_rows = sum(len(d["sheets"][s]["rows"]) for s in SHEETS)
        n_vals = sum(sum(len([(k,v) for k,v in r.items() if k not in SKIP_KEYS and v])
                         for r in d["sheets"][s]["rows"])
                     for s in SHEETS)
        print(f"  {doc_id}: {n_rows} rows, {n_vals} values across {len(d['sheets'])} sheets")

    # Collect predictions
    batch_outputs = collect_batch_outputs()
    eval_runs = collect_eval_runs()
    print(f"\nCollected: {len(batch_outputs)} batch outputs, {len(eval_runs)} individual eval runs")

    # Compute metrics for all
    all_results = []

    # Batch outputs
    for bo in batch_outputs:
        doc_id = bo["doc_id"]
        if doc_id not in gt_docs:
            print(f"  Warning: {doc_id} not in ground truth, skipping")
            continue
        metrics = compute_metrics(bo["pred"], gt_docs[doc_id])
        if metrics:
            all_results.append({
                "source": "batch_output",
                "document": doc_id,
                "model_family": bo["model_family"],
                "config": bo["config"],
                "run_idx": 1,
                "overall": metrics["overall"],
                "per_sheet": metrics["per_sheet"],
            })

    # Eval runs
    for er in eval_runs:
        doc_id = er["doc_id"]
        if doc_id not in gt_docs:
            continue
        metrics = compute_metrics(er["pred"], gt_docs[doc_id])
        if metrics:
            all_results.append({
                "source": "eval_runs",
                "document": doc_id,
                "model_family": er["model_family"],
                "config": er["config"],
                "run_idx": er["run_idx"],
                "success": er["success"],
                "duration_s": er["duration_s"],
                "n_fields": er["n_fields"],
                "confidence": er["confidence"],
                "overall": metrics["overall"],
                "per_sheet": metrics["per_sheet"],
            })

    print(f"\nComputed metrics for {len(all_results)} predictions")

    # Group by model + document
    by_key = defaultdict(list)
    for r in all_results:
        key = (r["model_family"], r["document"])
        by_key[key].append(r)

    # Print results
    print("\n" + "=" * 80)
    print("PER-DOCUMENT RESULTS (by model family)")
    print("=" * 80)

    summary_rows = []
    for (model, doc), entries in sorted(by_key.items()):
        n = len(entries)
        f1_ids = [e["overall"]["f1_field_id_micro"] for e in entries]
        f1_vals = [e["overall"]["f1_value_micro"] for e in entries]
        confs = [e["overall"]["overall_confidence"] for e in entries if e["overall"]["overall_confidence"]]
        ungrounded = [e["overall"]["ungrounded_high_conf"] for e in entries]

        mean_f1_id = sum(f1_ids) / len(f1_ids)
        mean_f1_val = sum(f1_vals) / len(f1_vals)
        mean_conf = sum(confs) / len(confs) if confs else None

        row = {
            "model": model,
            "document": doc,
            "n_runs": n,
            "mean_f1_field_id": round(mean_f1_id, 4),
            "mean_f1_value": round(mean_f1_val, 4),
            "best_f1_value": round(max(f1_vals), 4),
            "mean_confidence": round(mean_conf, 4) if mean_conf else None,
            "mean_ungrounded": round(sum(ungrounded) / len(ungrounded), 1) if ungrounded else None,
            "total_fields": entries[0]["overall"]["n_total_pred_fields"],
            "total_rows_pred": entries[0]["overall"]["n_total_pred_rows"],
            "total_rows_gt": entries[0]["overall"]["n_total_gt_rows"],
            "confirmed": entries[0]["overall"]["confirmed_fields"],
            "provisional": entries[0]["overall"]["provisional_fields"],
        }
        summary_rows.append(row)

        print(f"\n{model} | {doc} ({n} runs):")
        print(f"  Field-ID F1: {mean_f1_id:.3f}")
        print(f"  Value F1:    {mean_f1_val:.3f} (best: {max(f1_vals):.3f})")
        print(f"  Confidence:  {mean_conf:.3f}" if mean_conf else "  Confidence: N/A")
        print(f"  Ungrounded high-conf fields: {row['mean_ungrounded']}")
        print(f"  Rows: {row['total_rows_pred']} pred vs {row['total_rows_gt']} GT")
        print(f"  Status: {row['confirmed']} confirmed / {row['provisional']} provisional")

    # Model-level summary
    print("\n" + "=" * 80)
    print("MODEL-LEVEL SUMMARY")
    print("=" * 80)

    by_model = defaultdict(list)
    for r in summary_rows:
        by_model[r["model"]].append(r)

    for model, rows in sorted(by_model.items()):
        f1_ids = [r["mean_f1_field_id"] for r in rows]
        f1_vals = [r["mean_f1_value"] for r in rows]
        confs = [r["mean_confidence"] for r in rows if r["mean_confidence"]]

        print(f"\n{model} ({len(rows)} documents):")
        print(f"  Field-ID F1: mean={sum(f1_ids)/len(f1_ids):.3f}, min={min(f1_ids):.3f}, max={max(f1_ids):.3f}")
        print(f"  Value F1:    mean={sum(f1_vals)/len(f1_vals):.3f}, min={min(f1_vals):.3f}, max={max(f1_vals):.3f}")
        if confs:
            print(f"  Confidence:  mean={sum(confs)/len(confs):.3f}")
        print(f"  Row accuracy: pred/GT ratio per doc = "
              f"{sum(r['total_rows_pred'] for r in rows)}/{sum(r['total_rows_gt'] for r in rows)}")

    # Per-sheet summary (aggregate across all documents for batch outputs)
    print("\n" + "=" * 80)
    print("PER-SHEET AGGREGATE (batch output, all 10 docs)")
    print("=" * 80)

    sheet_agg = defaultdict(lambda: {"f1_ids": [], "f1_vals": [], "p_ids": [], "r_ids": []})
    for r in all_results:
        if r["source"] == "batch_output":
            for sheet, sm in r["per_sheet"].items():
                sheet_agg[sheet]["f1_ids"].append(sm["f1_field_id"])
                sheet_agg[sheet]["f1_vals"].append(sm["f1_value"])
                sheet_agg[sheet]["p_ids"].append(sm["precision_id"])
                sheet_agg[sheet]["r_ids"].append(sm["recall_id"])

    for sheet in SHEETS:
        agg = sheet_agg[sheet]
        if agg["f1_ids"]:
            print(f"  {sheet}: Field-ID F1={sum(agg['f1_ids'])/len(agg['f1_ids']):.3f}, "
                  f"Value F1={sum(agg['f1_vals'])/len(agg['f1_vals']):.3f}, "
                  f"P={sum(agg['p_ids'])/len(agg['p_ids']):.3f}, "
                  f"R={sum(agg['r_ids'])/len(agg['r_ids']):.3f} "
                  f"(n={len(agg['f1_ids'])})")

    # Export all results
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    for sub in ["analysis", "tables", "figures"]:
        (OUTPUT_DIR / sub).mkdir(exist_ok=True)

    # Export full JSON
    export = {
        "generated_at": datetime.now().isoformat(),
        "n_documents": len(gt_docs),
        "n_predictions": len(all_results),
        "summary": summary_rows,
        "per_sheet_aggregate": {s: {k: sum(v)/len(v) if v else 0
                                    for k, v in agg.items()}
                                for s, agg in sheet_agg.items()},
        "all_results": all_results,
    }
    with open(OUTPUT_DIR / "analysis" / "metrics_summary.json", "w") as f:
        json.dump(export, f, indent=2, default=str)

    # Export per-document CSV
    csv_path = OUTPUT_DIR / "analysis" / "per_document_metrics.csv"
    if summary_rows:
        keys = ["model", "document", "n_runs", "mean_f1_field_id", "mean_f1_value",
                "best_f1_value", "mean_confidence", "mean_ungrounded",
                "total_fields", "total_rows_pred", "total_rows_gt",
                "confirmed", "provisional"]
        with open(csv_path, "w") as f:
            f.write(",".join(keys) + "\n")
            for row in summary_rows:
                f.write(",".join(str(row.get(k, "")) for k in keys) + "\n")

    # Export per-sheet CSV
    sheet_csv = OUTPUT_DIR / "analysis" / "per_sheet_metrics.csv"
    with open(sheet_csv, "w") as f:
        f.write("document,sheet,f1_field_id,f1_value,precision_id,recall_id,n_pred_rows,n_gt_rows\n")
        for r in all_results:
            if r["source"] == "batch_output":
                for sheet in SHEETS:
                    sm = r["per_sheet"][sheet]
                    f.write(f"{r['document']},{sheet},{sm['f1_field_id']},{sm['f1_value']},"
                            f"{sm['precision_id']},{sm['recall_id']},"
                            f"{sm['n_pred_rows']},{sm['n_gt_rows']}\n")

    print(f"\nExported:")
    print(f"  {OUTPUT_DIR / 'analysis' / 'metrics_summary.json'}")
    print(f"  {csv_path}")
    print(f"  {sheet_csv}")
    print(f"\nDone: {datetime.now().isoformat()}")
    return export

if __name__ == "__main__":
    main()
