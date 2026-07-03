"""
Layer 5 - Confidence Calibration diagnostics (optional fast-follow).

Once Layer 2 (``value_accuracy_evaluator.py``) supplies a real per-field
correctness signal, FAIRiAgent's existing (but previously near-meaningless)
confidence-vs-correctness check can be upgraded from a Pearson correlation
against a near-binary "has_value" flag into a proper **calibration**
analysis: Expected Calibration Error (ECE) and Brier score of the model's
self-reported confidence against actual Layer-2 correctness.

Methodology follows the binning approach used in "Beyond Logprobs: A
Multi-Signal Confidence Engine for LLM-Based Document Field Extraction"
(2026), which evaluates the same task family (LLM document field
extraction).

This module has no dependency on the rest of the evaluation pipeline beyond
plain (confidence, is_correct) pairs, so it can be applied to per-field
confidence scores (from ``json_generator.py``) or aggregated
workflow-level confidence (``confidence_aggregator.py``) alike.
"""

from __future__ import annotations

from typing import List, Sequence, Tuple


def expected_calibration_error(
    confidences: Sequence[float],
    correctness: Sequence[float],
    n_bins: int = 10,
) -> float:
    """
    Expected Calibration Error (ECE).

    ECE = sum_b (|B_b| / N) * |acc(B_b) - conf(B_b)|

    Args:
        confidences: predicted confidence in [0, 1] per item.
        correctness: 1.0 if correct (or a continuous correctness score in
            [0, 1], e.g. Layer-2's per-field match score), 0.0 if not.
        n_bins: number of equal-width confidence bins.
    """
    n = len(confidences)
    if n == 0 or n != len(correctness):
        return 0.0

    bin_edges = [i / n_bins for i in range(n_bins + 1)]
    ece = 0.0
    for i in range(n_bins):
        lo, hi = bin_edges[i], bin_edges[i + 1]
        in_bin = [
            (c, y) for c, y in zip(confidences, correctness)
            if (lo <= c < hi) or (i == n_bins - 1 and c == hi)
        ]
        if not in_bin:
            continue
        bin_conf = sum(c for c, _ in in_bin) / len(in_bin)
        bin_acc = sum(y for _, y in in_bin) / len(in_bin)
        ece += (len(in_bin) / n) * abs(bin_acc - bin_conf)
    return ece


def brier_score(
    confidences: Sequence[float], correctness: Sequence[float]
) -> float:
    """
    Brier score: mean squared error between confidence and correctness.

    Lower is better (0 = perfectly calibrated and accurate).
    """
    n = len(confidences)
    if n == 0 or n != len(correctness):
        return 0.0
    return sum((c - y) ** 2 for c, y in zip(confidences, correctness)) / n


def calibration_bins(
    confidences: Sequence[float],
    correctness: Sequence[float],
    n_bins: int = 10,
) -> List[Tuple[float, float, float, int]]:
    """
    Returns per-bin (bin_lower, mean_confidence, mean_accuracy, count) for a
    reliability-diagram-style breakdown.
    """
    n = len(confidences)
    if n == 0 or n != len(correctness):
        return []
    bin_edges = [i / n_bins for i in range(n_bins + 1)]
    rows: List[Tuple[float, float, float, int]] = []
    for i in range(n_bins):
        lo, hi = bin_edges[i], bin_edges[i + 1]
        in_bin = [
            (c, y) for c, y in zip(confidences, correctness)
            if (lo <= c < hi) or (i == n_bins - 1 and c == hi)
        ]
        if not in_bin:
            rows.append((lo, 0.0, 0.0, 0))
            continue
        mean_conf = sum(c for c, _ in in_bin) / len(in_bin)
        mean_acc = sum(y for _, y in in_bin) / len(in_bin)
        rows.append((lo, mean_conf, mean_acc, len(in_bin)))
    return rows


def calibration_report(
    confidences: Sequence[float],
    correctness: Sequence[float],
    n_bins: int = 10,
) -> dict:
    """Convenience wrapper bundling ECE, Brier score, and bin breakdown."""
    ece = expected_calibration_error(confidences, correctness, n_bins)
    brier = brier_score(confidences, correctness)
    bin_rows = calibration_bins(confidences, correctness, n_bins)
    return {
        "n_samples": len(confidences),
        "ece": round(ece, 4),
        "brier_score": round(brier, 4),
        "bins": [
            {
                "bin_lower": lo,
                "mean_confidence": mc,
                "mean_accuracy": ma,
                "count": n,
            }
            for lo, mc, ma, n in bin_rows
        ],
    }
