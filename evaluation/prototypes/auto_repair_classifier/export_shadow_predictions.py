#!/usr/bin/env python3
"""Export classifier/rule predictions in auto-repair trace-compatible JSON."""

from __future__ import annotations

import argparse
import json
import pickle
from pathlib import Path
from typing import Any, Dict, List, Optional

from rules import fallback_decision, normalize_field
from train_decision_model import feature_dict, load_rows


ROOT = Path("evaluation/prototypes/auto_repair_classifier")
DEFAULT_DATASET = ROOT / "artifacts/pro_field_decisions.csv"
DEFAULT_OUTPUT = ROOT / "artifacts/auto_repair_classifier_predictions.json"


def _probability_from_model(model: Any, row: Dict[str, Any]) -> Optional[float]:
    if model is None:
        return None
    try:
        return float(model.predict_proba([feature_dict(row)])[0][1])
    except Exception:
        return None


def _prediction_for_row(
    row: Dict[str, Any],
    *,
    label: str,
    threshold: float,
    model: Any = None,
    model_version: str = "rules_fallback",
) -> Dict[str, Any]:
    probability = _probability_from_model(model, row)
    decision = fallback_decision(row)
    if probability is None:
        positive = bool(
            decision["accept_patch"]
            if label == "safe_accept_label"
            else decision["decision"] == "semantic_repair"
        )
        probability = 1.0 if positive else 0.0
    else:
        positive = probability >= threshold

    return {
        "label": label,
        "decision": "accept_patch" if positive else "keep",
        "probability": round(float(probability), 6),
        "threshold": threshold,
        "score": decision.get("repair_score", 0),
        "model": "sklearn_logistic_calibrated" if model is not None else "rules_fallback",
        "model_version": model_version,
        "reasons": decision.get("repair_reasons", []),
    }


def build_predictions(
    rows: List[Dict[str, Any]],
    *,
    label: str,
    threshold: float,
    model: Any = None,
    model_version: str = "rules_fallback",
    doc_id: Optional[str] = None,
) -> Dict[str, Any]:
    grouped: Dict[str, Dict[str, Dict[str, Any]]] = {}
    for row in rows:
        current_doc = str(row.get("doc_id") or "")
        if doc_id and current_doc != doc_id:
            continue
        field = normalize_field(str(row.get("field") or ""))
        if not current_doc or not field:
            continue
        grouped.setdefault(current_doc, {})[field] = _prediction_for_row(
            row,
            label=label,
            threshold=threshold,
            model=model,
            model_version=model_version,
        )

    if doc_id:
        return grouped.get(doc_id, {})
    return {
        "schema_version": "auto_repair_classifier_predictions.v1",
        "label": label,
        "threshold": threshold,
        "model": "sklearn_logistic_calibrated" if model is not None else "rules_fallback",
        "model_version": model_version,
        "documents": grouped,
    }


def load_model(path: Optional[Path]) -> Any:
    if path is None:
        return None
    with path.open("rb") as handle:
        return pickle.load(handle)


def parse_args(argv: Optional[List[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dataset", type=Path, default=DEFAULT_DATASET)
    parser.add_argument("--model", type=Path)
    parser.add_argument(
        "--label",
        choices=["should_repair_label", "safe_accept_label"],
        default="should_repair_label",
    )
    parser.add_argument("--threshold", type=float, default=0.75)
    parser.add_argument("--model-version", default="rules_fallback")
    parser.add_argument("--doc-id", help="Output only one document as a direct field mapping.")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    return parser.parse_args(argv)


def main(argv: Optional[List[str]] = None) -> int:
    args = parse_args(argv)
    rows = load_rows(args.dataset)
    model = load_model(args.model)
    model_version = (
        args.model_version
        if args.model is None
        else f"{args.model_version}:{args.model.name}"
    )
    payload = build_predictions(
        rows,
        label=args.label,
        threshold=args.threshold,
        model=model,
        model_version=model_version,
        doc_id=args.doc_id,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    print(f"Wrote predictions to {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
