#!/usr/bin/env python3
"""Train/evaluate a lightweight field-level auto-repair decision model."""

from __future__ import annotations

import argparse
import csv
import json
import pickle
from pathlib import Path
from typing import Any, Dict, List

from rules import fallback_decision


ROOT = Path("evaluation/prototypes/auto_repair_classifier")

NUMERIC_FEATURES = [
    "shadow_score",
    "tuned_score",
    "score_delta",
    "shadow_occurrences",
    "tuned_occurrences",
    "lexical_hit_count",
    "semantic_hit_count",
    "hybrid_hit_count",
    "semantic_only_hint",
    "completeness_delta",
    "extra_fields_delta",
    "row_alignment_f1_delta",
    "sheet_placement_delta",
    "schema_delta",
    "llm_judge_delta",
    "global_aggregate_delta",
    "fallback_repair_score",
]

CATEGORICAL_FEATURES = [
    "sheet",
    "shadow_status",
    "tuned_status",
    "prompt_mode",
    "rerank_status",
    "fallback_decision",
]


def as_float(value: Any) -> float:
    try:
        if value in (None, ""):
            return 0.0
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def load_rows(path: Path) -> List[Dict[str, Any]]:
    with path.open("r", encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def feature_dict(row: Dict[str, Any]) -> Dict[str, Any]:
    features: Dict[str, Any] = {}
    for name in NUMERIC_FEATURES:
        features[name] = as_float(row.get(name))
    for name in CATEGORICAL_FEATURES:
        features[name] = str(row.get(name) or "")
    return features


def metrics(y_true: List[int], y_pred: List[int]) -> Dict[str, float]:
    tp = sum(1 for t, p in zip(y_true, y_pred) if t == 1 and p == 1)
    fp = sum(1 for t, p in zip(y_true, y_pred) if t == 0 and p == 1)
    fn = sum(1 for t, p in zip(y_true, y_pred) if t == 1 and p == 0)
    tn = sum(1 for t, p in zip(y_true, y_pred) if t == 0 and p == 0)
    precision = tp / (tp + fp) if tp + fp else 0.0
    recall = tp / (tp + fn) if tp + fn else 0.0
    f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
    accuracy = (tp + tn) / max(1, len(y_true))
    return {
        "accuracy": accuracy,
        "precision": precision,
        "recall": recall,
        "f1": f1,
        "tp": tp,
        "fp": fp,
        "fn": fn,
        "tn": tn,
    }


def evaluate_rules(rows: List[Dict[str, Any]], label: str) -> Dict[str, Any]:
    y_true = [int(float(row[label])) for row in rows]
    y_pred: List[int] = []
    for row in rows:
        decision = fallback_decision(row)
        if label == "safe_accept_label":
            y_pred.append(int(decision["accept_patch"]))
        else:
            y_pred.append(int(decision["decision"] == "semantic_repair"))
    return {"mode": "rules", "metrics": metrics(y_true, y_pred)}


def train_sklearn(rows: List[Dict[str, Any]], label: str, threshold: float) -> Dict[str, Any]:
    from sklearn.calibration import CalibratedClassifierCV
    from sklearn.feature_extraction import DictVectorizer
    from sklearn.linear_model import LogisticRegression
    from sklearn.model_selection import LeaveOneGroupOut
    from sklearn.pipeline import Pipeline

    x = [feature_dict(row) for row in rows]
    y = [int(float(row[label])) for row in rows]
    groups = [row["doc_id"] for row in rows]
    if len(set(y)) < 2:
        raise ValueError(f"Label {label} has only one class")

    def new_model() -> Pipeline:
        return Pipeline(
            [
                ("vectorizer", DictVectorizer(sparse=True)),
                (
                    "classifier",
                    CalibratedClassifierCV(
                        LogisticRegression(max_iter=1000, class_weight="balanced"),
                        cv=3,
                        method="sigmoid",
                    ),
                ),
            ]
        )

    y_true: List[int] = []
    y_pred: List[int] = []
    folds: List[Dict[str, Any]] = []
    for fold, (train_idx, test_idx) in enumerate(LeaveOneGroupOut().split(x, y, groups), start=1):
        y_train = [y[i] for i in train_idx]
        if len(set(y_train)) < 2:
            folds.append({"fold": fold, "doc_id": groups[test_idx[0]], "skipped": "single_class_train"})
            continue
        model = new_model()
        model.fit([x[i] for i in train_idx], y_train)
        probs = model.predict_proba([x[i] for i in test_idx])[:, 1]
        pred = [int(prob >= threshold) for prob in probs]
        true = [y[i] for i in test_idx]
        y_true.extend(true)
        y_pred.extend(pred)
        folds.append(
            {
                "fold": fold,
                "doc_id": groups[test_idx[0]],
                "n": len(test_idx),
                "positive_rate": sum(true) / max(1, len(true)),
                "metrics": metrics(true, pred),
            }
        )

    final_model = new_model()
    final_model.fit(x, y)
    return {
        "mode": "sklearn_logistic_calibrated",
        "model": final_model,
        "cv_metrics": metrics(y_true, y_pred) if y_true else {},
        "folds": folds,
        "n_rows": len(rows),
        "n_docs": len(set(groups)),
        "positive_rate": sum(y) / max(1, len(y)),
        "threshold": threshold,
    }


def write_report(report: Dict[str, Any], output: Path) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    serializable = {k: v for k, v in report.items() if k != "model"}
    with output.open("w", encoding="utf-8") as handle:
        json.dump(serializable, handle, indent=2, sort_keys=True)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dataset", type=Path, default=ROOT / "artifacts/pro_field_decisions.csv")
    parser.add_argument("--label", choices=["should_repair_label", "safe_accept_label"], default="safe_accept_label")
    parser.add_argument("--threshold", type=float, default=0.75)
    parser.add_argument("--report", type=Path, default=ROOT / "artifacts/model_report.json")
    parser.add_argument("--model-out", type=Path, default=ROOT / "artifacts/decision_model.pkl")
    args = parser.parse_args()

    rows = load_rows(args.dataset)
    rule_report = evaluate_rules(rows, args.label)
    try:
        report = train_sklearn(rows, args.label, args.threshold)
        report["rules_baseline"] = rule_report
        args.model_out.parent.mkdir(parents=True, exist_ok=True)
        with args.model_out.open("wb") as handle:
            pickle.dump(report["model"], handle)
        report["model_path"] = str(args.model_out)
    except Exception as exc:
        report = {
            "mode": "rules_only",
            "reason": str(exc),
            "rules_baseline": rule_report,
            "n_rows": len(rows),
        }
    report["label"] = args.label
    write_report(report, args.report)
    print(f"Wrote report to {args.report}")
    print(json.dumps({k: v for k, v in report.items() if k in {"mode", "cv_metrics", "rules_baseline", "reason"}}, indent=2))


if __name__ == "__main__":
    main()
