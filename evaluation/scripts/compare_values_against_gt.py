#!/usr/bin/env python3
"""
Value accuracy evaluation for FAIRiAgent outputs vs ground truth.

Metrics
-------
* Semantic similarity  — sentence-transformers cosine similarity (all-MiniLM-L6-v2).
                         Falls back to token-F1 when the model is unavailable.
                         Threshold: sim >= 0.75 → "match", >= 0.4 → "partial".
* Token F1             — SQuAD-style token overlap. Used as fallback or alongside
                         semantic similarity for numeric / short values.
* Field coverage       — fraction of non-empty GT fields whose *name* appears
                         in the LLM output (regardless of value accuracy).
* Row alignment        — for multi-row sheets, Hungarian-algorithm best-match
                         so row order differences don't penalise the score.

Usage
-----
  python compare_values_against_gt.py <gt_values.json> <run_dir> [--json]

  gt_values.json  — evaluation/datasets/annotated/values/ground_truth_*_values.json
  run_dir         — output/<project_dir>  (must contain metadata.json)
  --json          — also dump JSON results to stdout
"""

from __future__ import annotations

import argparse
import json
import re
import string
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import numpy as np

try:
    from scipy.optimize import linear_sum_assignment
    _SCIPY = True
except ImportError:
    _SCIPY = False

# ── sentence-transformers semantic similarity ─────────────────────────────────

_ST_MODEL = None
_ST_AVAILABLE = False


def _get_st_model():
    global _ST_MODEL, _ST_AVAILABLE
    if _ST_MODEL is not None:
        return _ST_MODEL
    try:
        from sentence_transformers import SentenceTransformer
        _ST_MODEL = SentenceTransformer("all-MiniLM-L6-v2")
        _ST_AVAILABLE = True
    except Exception:
        _ST_AVAILABLE = False
    return _ST_MODEL


def semantic_sim(a: str, b: str) -> float:
    """Cosine similarity in [0,1] using all-MiniLM-L6-v2; fallback 0.0."""
    model = _get_st_model()
    if model is None or not a.strip() or not b.strip():
        return 0.0
    try:
        embs = model.encode([a, b], convert_to_numpy=True, normalize_embeddings=True)
        return float(np.clip(float(embs[0] @ embs[1]), 0.0, 1.0))
    except Exception:
        return 0.0


# ── token-F1 (SQuAD-style) ───────────────────────────────────────────────────

def _normalize(text: str) -> List[str]:
    text = text.lower()
    text = text.translate(str.maketrans("", "", string.punctuation))
    return [t for t in text.split() if t]


_STOPWORDS = frozenset({"the", "a", "an", "is", "are", "was", "were", "be", "been",
                        "and", "or", "of", "in", "to", "for", "with", "on", "at",
                        "by", "from", "as", "not", "no", "n/a", "na", "unknown"})


def token_f1(pred: str, gt: str) -> Tuple[float, float, float]:
    """Token-level precision, recall, F1."""
    p_toks = [t for t in _normalize(pred) if t not in _STOPWORDS]
    g_toks = [t for t in _normalize(gt)   if t not in _STOPWORDS]
    if not g_toks:
        return (1.0, 1.0, 1.0) if not p_toks else (0.0, 1.0, 0.0)
    if not p_toks:
        return (0.0, 0.0, 0.0)
    common = set(p_toks) & set(g_toks)
    if not common:
        return (0.0, 0.0, 0.0)
    prec = len(common) / len(p_toks)
    rec  = len(common) / len(g_toks)
    f1   = 2 * prec * rec / (prec + rec)
    return (prec, rec, f1)


def combined_score(pred: str, gt: str) -> float:
    """
    Best-of semantic similarity and token-F1.

    For short / numeric values (≤ 3 tokens) token-F1 is more reliable.
    For longer values, semantic similarity captures paraphrases.
    """
    _, _, tf1 = token_f1(pred, gt)
    gt_toks = _normalize(gt)
    if not gt_toks:
        return tf1
    # Short values: use token-F1 directly
    if len(gt_toks) <= 3:
        return tf1
    # Long values: take max(semantic, token_f1) so we don't penalise
    # well-phrased paraphrases that happen to share fewer tokens.
    sim = semantic_sim(pred, gt)
    return max(sim, tf1)


# ── GT loader ─────────────────────────────────────────────────────────────────

def load_gt_sheets(gt_path: Path) -> Dict[str, List[Dict[str, str]]]:
    """Return {sheet_name: [row_dict, ...]} skipping _evidence and empty values."""
    with open(gt_path, encoding="utf-8") as f:
        gt = json.load(f)
    out: Dict[str, List[Dict[str, str]]] = {}
    for sheet_name, sheet_data in gt.get("isa_sheets", {}).items():
        rows = sheet_data.get("expected_rows", [])
        cleaned: List[Dict[str, str]] = []
        for row in rows:
            clean = {
                k: str(v).strip()
                for k, v in row.items()
                if k != "_evidence" and str(v).strip()
            }
            if clean:
                cleaned.append(clean)
        if cleaned:
            out[sheet_name] = cleaned
    return out


# ── metadata.json extractor ────────────────────────────────────────────────────

def _normalise_field_name(name: str) -> str:
    return re.sub(r"[\s_\-]+", " ", name.lower().strip())


def load_run_sheets(run_dir: Path) -> Dict[str, List[Dict[str, str]]]:
    """
    Return {sheet_name: [row_dict, ...]} from metadata.json.

    Supports three output structures:
    1. isa_values / isa_structure with {columns, rows} matrix (ISAValueMapper output)
    2. isa_structure.{sheet}.fields flat list (legacy)
    3. metadata_fields list
    """
    meta_path = run_dir / "metadata.json"
    if not meta_path.exists():
        raise FileNotFoundError(f"metadata.json not found in {run_dir}")
    with open(meta_path, encoding="utf-8") as f:
        meta = json.load(f)

    out: Dict[str, List[Dict[str, str]]] = {}

    # Prefer dedicated isa_values_json.json; fall back to isa_structure.fields
    isa_values_path = run_dir / "isa_values_json.json"
    if isa_values_path.exists():
        try:
            with open(isa_values_path, encoding="utf-8") as f:
                isa_values = json.load(f)
        except (json.JSONDecodeError, OSError):
            isa_values = {}
    else:
        isa_values = meta.get("isa_values") or meta.get("isa_structure", {})
    if isinstance(isa_values, dict):
        for sheet_name, sheet_data in isa_values.items():
            if sheet_name in ("description", "statistics"):
                continue
            if isinstance(sheet_data, dict) and "columns" in sheet_data and "rows" in sheet_data:
                cols = sheet_data["columns"]
                rows = sheet_data["rows"]
                if isinstance(cols, list) and isinstance(rows, list):
                    built: List[Dict[str, str]] = []
                    for row in rows:
                        if isinstance(row, list):
                            row_dict = {
                                _normalise_field_name(cols[i]): str(row[i]).strip()
                                for i in range(min(len(cols), len(row)))
                                if row[i] is not None and str(row[i]).strip()
                            }
                        elif isinstance(row, dict):
                            row_dict = {
                                _normalise_field_name(k): str(v).strip()
                                for k, v in row.items()
                                if v is not None and str(v).strip()
                            }
                        else:
                            continue
                        if row_dict:
                            built.append(row_dict)
                    if built:
                        out[sheet_name] = built
                    continue
            if isinstance(sheet_data, dict) and "fields" in sheet_data:
                row_dict: Dict[str, str] = {}
                for field in sheet_data["fields"]:
                    if isinstance(field, dict):
                        name  = _normalise_field_name(field.get("field_name", ""))
                        value = str(field.get("value", "")).strip()
                        if name and value:
                            row_dict[name] = value
                if row_dict:
                    out[sheet_name] = [row_dict]

    if not out:
        fields = meta.get("metadata_fields", [])
        if fields:
            by_sheet: Dict[str, Dict[str, str]] = {}
            for field in fields:
                sheet = field.get("isa_sheet", "unknown")
                name  = _normalise_field_name(field.get("field_name", ""))
                value = str(field.get("value", "")).strip()
                if name and value:
                    by_sheet.setdefault(sheet, {})[name] = value
            for sheet, row_dict in by_sheet.items():
                out[sheet] = [row_dict]

    return out


# ── row alignment ──────────────────────────────────────────────────────────────

def _row_similarity(gt_row: Dict[str, str], pred_row: Dict[str, str]) -> float:
    if not gt_row:
        return 0.0
    total = 0.0
    for field, gt_val in gt_row.items():
        pred_val = pred_row.get(field) or pred_row.get(_normalise_field_name(field), "")
        total += combined_score(pred_val, gt_val)
    return total / len(gt_row)


def align_rows(
    gt_rows: List[Dict[str, str]],
    pred_rows: List[Dict[str, str]],
) -> List[Tuple[Dict[str, str], Optional[Dict[str, str]]]]:
    """Hungarian-algorithm alignment of GT rows to prediction rows."""
    if not pred_rows:
        return [(r, None) for r in gt_rows]
    if len(gt_rows) == 1:
        return [(gt_rows[0], pred_rows[0])]
    n, m = len(gt_rows), len(pred_rows)
    cost = np.zeros((n, m))
    for i, gr in enumerate(gt_rows):
        for j, pr in enumerate(pred_rows):
            cost[i, j] = -_row_similarity(gr, pr)
    if _SCIPY:
        row_ind, col_ind = linear_sum_assignment(cost)
        matched: Dict[int, int] = dict(zip(row_ind.tolist(), col_ind.tolist()))
    else:
        matched = {}
        used: set = set()
        for i in range(n):
            best_j, best_s = -1, -1.0
            for j in range(m):
                if j not in used and -cost[i, j] > best_s:
                    best_j, best_s = j, -cost[i, j]
            if best_j >= 0:
                matched[i] = best_j
                used.add(best_j)
    return [
        (gt_rows[i], pred_rows[matched[i]] if i in matched else None)
        for i in range(n)
    ]


# ── per-sheet evaluation ───────────────────────────────────────────────────────

MATCH_THRESHOLD   = 0.75  # semantic/token score >= 0.75 → "match"
PARTIAL_THRESHOLD = 0.40  # >= 0.40 → "partial"

FieldResult = Dict[str, Any]


def evaluate_sheet(
    sheet_name: str,
    gt_rows: List[Dict[str, str]],
    pred_rows: List[Dict[str, str]],
) -> Dict[str, Any]:
    """Evaluate one sheet. Returns per-row details and aggregate metrics."""
    pairs = align_rows(gt_rows, pred_rows)

    total_fields = 0
    match_count  = 0
    partial_count = 0
    miss_count   = 0
    missing_name_count = 0
    score_sum    = 0.0

    row_details: List[Dict[str, Any]] = []

    for gt_row, pred_row in pairs:
        fields: List[FieldResult] = []
        for field, gt_val in gt_row.items():
            if not gt_val:
                continue
            pred_val = ""
            if pred_row:
                pred_val = (
                    pred_row.get(field)
                    or pred_row.get(_normalise_field_name(field))
                    or ""
                )
            field_present = bool(pred_val)
            score = combined_score(pred_val, gt_val) if pred_val else 0.0

            total_fields += 1
            score_sum    += score

            if score >= MATCH_THRESHOLD:
                status = "match"
                match_count += 1
            elif score >= PARTIAL_THRESHOLD:
                status = "partial"
                partial_count += 1
            elif field_present:
                status = "wrong"
                miss_count += 1
            else:
                status = "missing"
                miss_count += 1
                missing_name_count += 1

            fields.append({
                "field":        field,
                "status":       status,
                "score":        round(score, 3),
                "gt_snippet":   gt_val[:60],
                "pred_snippet": pred_val[:60] if pred_val else "(not found)",
            })
        row_details.append({"fields": fields})

    mean_score = score_sum / total_fields if total_fields else 0.0
    coverage   = (total_fields - missing_name_count) / total_fields if total_fields else 0.0

    return {
        "sheet":              sheet_name,
        "gt_rows":            len(gt_rows),
        "pred_rows":          len(pred_rows),
        "total_fields":       total_fields,
        "match_count":        match_count,
        "partial_count":      partial_count,
        "miss_count":         miss_count,
        "missing_name_count": missing_name_count,
        "mean_score":         round(mean_score, 4),
        "field_coverage":     round(coverage, 4),
        "row_details":        row_details,
    }


# ── report ────────────────────────────────────────────────────────────────────

def print_report(results: List[Dict[str, Any]], use_semantic: bool) -> None:
    w = "=" * 72

    total_fields  = sum(r["total_fields"]  for r in results)
    total_match   = sum(r["match_count"]   for r in results)
    total_partial = sum(r["partial_count"] for r in results)
    total_miss    = sum(r["miss_count"]    for r in results)
    overall_score = (
        sum(r["mean_score"] * r["total_fields"] for r in results) / total_fields
        if total_fields else 0.0
    )
    overall_cov = (
        sum(r["field_coverage"] * r["total_fields"] for r in results) / total_fields
        if total_fields else 0.0
    )

    metric_name = "semantic+token" if use_semantic else "token-F1"
    print(w)
    print(f"  Value Quality ({metric_name})  ·  {Path(sys.argv[2]).name}")
    print(w)

    for r in results:
        frac = f"{r['match_count'] + r['partial_count']}/{r['total_fields']}"
        print(
            f"\n[{r['sheet']}]  GT={r['gt_rows']}r pred={r['pred_rows']}r "
            f"→ {frac}  score={r['mean_score']:.2f}  cov={r['field_coverage']:.0%}"
        )
        for row in r["row_details"]:
            for f in row["fields"]:
                if f["status"] != "match":
                    icon = {"partial": "~", "wrong": "✗", "missing": "✗"}.get(f["status"], "?")
                    print(
                        f"  {icon} '{f['field']}': "
                        f"gt='{f['gt_snippet']}' "
                        f"pred='{f['pred_snippet']}'  score={f['score']}"
                    )

    print()
    print("=" * 40)
    print(f"  OVERALL  {total_match}/{total_fields} match  "
          f"({total_partial} partial  {total_miss} miss)")
    print(f"  Mean score     : {overall_score:.3f}  ({metric_name})")
    print(f"  Field coverage : {overall_cov:.1%}  "
          f"(field name present regardless of value)")
    if use_semantic:
        print("  Model: all-MiniLM-L6-v2  thresholds: match≥0.75  partial≥0.40")
    else:
        print("  [note] sentence-transformers unavailable — token-F1 only")
    if not _SCIPY:
        print("  [note] scipy not available — greedy row alignment used")
    print("=" * 40)


# ── main ──────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("gt_path",  help="Ground truth values JSON")
    parser.add_argument("run_dir",  help="Run output directory (contains metadata.json)")
    parser.add_argument("--json",   action="store_true", help="Dump JSON results to stdout")
    parser.add_argument("--no-semantic", action="store_true",
                        help="Disable sentence-transformers, use token-F1 only")
    args = parser.parse_args()

    if args.no_semantic:
        global _ST_AVAILABLE
        _ST_AVAILABLE = False

    gt_path  = Path(args.gt_path)
    run_dir  = Path(args.run_dir)

    # Warm up model before scoring (prints nothing if unavailable)
    use_semantic = not args.no_semantic and _get_st_model() is not None

    gt_sheets   = load_gt_sheets(gt_path)
    pred_sheets = load_run_sheets(run_dir)

    results: List[Dict[str, Any]] = []
    for sheet_name, gt_rows in gt_sheets.items():
        pred_rows = pred_sheets.get(sheet_name, [])
        results.append(evaluate_sheet(sheet_name, gt_rows, pred_rows))

    print_report(results, use_semantic)

    if args.json:
        import json as _json
        _json.dump(results, sys.stdout, indent=2, ensure_ascii=False)


if __name__ == "__main__":
    main()
