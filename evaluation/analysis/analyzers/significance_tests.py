from __future__ import annotations

from dataclasses import asdict, dataclass
from itertools import combinations
from math import comb
from typing import Any

import numpy as np
from scipy.stats import chi2, friedmanchisquare, rankdata, wilcoxon


@dataclass
class FriedmanResult:
    statistic: float
    p_value: float
    df: int
    effect_size: float


@dataclass
class WilcoxonResult:
    comparisons: list[dict[str, Any]]
    alpha: float
    alpha_corrected: float
    n_comparisons: int


@dataclass
class McNemarResult:
    statistic: float
    p_value: float
    contingency_table: list[list[int]]


@dataclass
class BootstrapCIResult:
    estimate: float
    ci_lo: float
    ci_hi: float
    n_boot: int
    alpha: float


def friedman(metric_matrix: np.ndarray) -> FriedmanResult:
    matrix = np.asarray(metric_matrix, dtype=float)
    if matrix.ndim != 2 or matrix.shape[1] < 2:
        raise ValueError("metric_matrix must have shape (n_documents, n_conditions>=2)")

    statistic, p_value = friedmanchisquare(*[matrix[:, i] for i in range(matrix.shape[1])])
    ranks = np.apply_along_axis(rankdata, 1, matrix)
    mean_ranks = ranks.mean(axis=0)
    n_docs, n_conditions = matrix.shape
    effect_size = float(
        (12 * n_docs / (n_conditions**2 * (n_conditions + 1)))
        * np.sum((mean_ranks - (n_conditions + 1) / 2) ** 2)
        / (n_docs * (n_conditions - 1))
    )
    return FriedmanResult(
        statistic=float(statistic),
        p_value=float(p_value),
        df=n_conditions - 1,
        effect_size=max(0.0, min(1.0, effect_size)),
    )


def wilcoxon_pairwise_bonferroni(
    metric_matrix: np.ndarray,
    condition_names: list[str],
    alpha: float = 0.05,
) -> WilcoxonResult:
    matrix = np.asarray(metric_matrix, dtype=float)
    if matrix.ndim != 2 or matrix.shape[1] != len(condition_names):
        raise ValueError("condition_names must match metric_matrix columns")

    pairs = list(combinations(range(matrix.shape[1]), 2))
    alpha_corrected = alpha / len(pairs) if pairs else alpha
    comparisons_out: list[dict[str, Any]] = []

    for i, j in pairs:
        stat, p_raw = wilcoxon(matrix[:, i], matrix[:, j], zero_method="zsplit")
        p_corrected = min(1.0, float(p_raw) * len(pairs))
        comparisons_out.append(
            {
                "pair": (condition_names[i], condition_names[j]),
                "statistic": float(stat),
                "p_raw": float(p_raw),
                "p_corrected": p_corrected,
                "significant": p_corrected < alpha,
            }
        )

    return WilcoxonResult(
        comparisons=comparisons_out,
        alpha=alpha,
        alpha_corrected=alpha_corrected,
        n_comparisons=len(pairs),
    )


def mcnemar_paired(
    binary_results_a: np.ndarray,
    binary_results_b: np.ndarray,
) -> McNemarResult:
    a = np.asarray(binary_results_a).astype(int)
    b = np.asarray(binary_results_b).astype(int)
    if a.shape != b.shape:
        raise ValueError("Paired results must have the same shape")

    both_success = int(np.sum((a == 1) & (b == 1)))
    a_only = int(np.sum((a == 1) & (b == 0)))
    b_only = int(np.sum((a == 0) & (b == 1)))
    both_fail = int(np.sum((a == 0) & (b == 0)))
    table = [[both_success, a_only], [b_only, both_fail]]

    try:
        from statsmodels.stats.contingency_tables import mcnemar as sm_mcnemar

        result = sm_mcnemar(table, exact=False, correction=True)
        statistic = float(result.statistic)
        p_value = float(result.pvalue)
    except Exception:
        b_total = a_only + b_only
        if b_total == 0:
            statistic = 0.0
            p_value = 1.0
        else:
            statistic = ((abs(a_only - b_only) - 1) ** 2) / b_total
            p_value = float(chi2.sf(statistic, df=1))

    return McNemarResult(statistic=statistic, p_value=p_value, contingency_table=table)


def pass_at_k_estimate(successes: np.ndarray, k: int) -> float:
    arr = np.asarray(successes).astype(int)
    n = int(arr.size)
    c = int(arr.sum())
    if n == 0 or c == 0:
        return 0.0
    if c >= n:
        return 1.0
    k_eff = min(int(k), n)
    if n - c < k_eff:
        return 1.0
    return float(1 - comb(n - c, k_eff) / comb(n, k_eff))


def bootstrap_pass_at_k_ci(
    successes: np.ndarray,
    k: int,
    n_boot: int = 1000,
    alpha: float = 0.05,
    random_seed: int | None = 0,
) -> BootstrapCIResult:
    arr = np.asarray(successes).astype(int)
    if arr.ndim != 1:
        raise ValueError("successes must be a 1D array")
    if arr.size == 0:
        return BootstrapCIResult(estimate=0.0, ci_lo=0.0, ci_hi=0.0, n_boot=n_boot, alpha=alpha)

    estimate = pass_at_k_estimate(arr, k)
    rng = np.random.default_rng(random_seed)
    samples = np.empty(n_boot, dtype=float)
    for idx in range(n_boot):
        boot = rng.choice(arr, size=arr.size, replace=True)
        samples[idx] = pass_at_k_estimate(boot, k)

    ci_lo = float(np.quantile(samples, alpha / 2))
    ci_hi = float(np.quantile(samples, 1 - alpha / 2))
    return BootstrapCIResult(
        estimate=float(estimate),
        ci_lo=ci_lo,
        ci_hi=ci_hi,
        n_boot=n_boot,
        alpha=alpha,
    )


def result_to_dict(result: Any) -> dict[str, Any]:
    if hasattr(result, "__dataclass_fields__"):
        return asdict(result)
    raise TypeError(f"Unsupported result type: {type(result)!r}")
