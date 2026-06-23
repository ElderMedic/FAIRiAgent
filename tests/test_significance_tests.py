import math

import numpy as np

from evaluation.analysis.analyzers.pass_at_k import PassAtKAnalyzer


def test_friedman_detects_clear_condition_difference():
    from evaluation.analysis.analyzers.significance_tests import friedman

    matrix = np.array(
        [
            [0.20, 0.45, 0.90],
            [0.25, 0.50, 0.88],
            [0.18, 0.47, 0.91],
            [0.22, 0.49, 0.89],
            [0.24, 0.51, 0.92],
            [0.21, 0.46, 0.87],
            [0.23, 0.48, 0.90],
            [0.19, 0.44, 0.86],
            [0.20, 0.45, 0.89],
            [0.26, 0.52, 0.93],
        ]
    )

    result = friedman(matrix)

    assert result.df == 2
    assert result.p_value < 0.05
    assert 0 <= result.effect_size <= 1


def test_wilcoxon_pairwise_bonferroni_emits_all_pairs():
    from evaluation.analysis.analyzers.significance_tests import wilcoxon_pairwise_bonferroni

    matrix = np.array(
        [
            [0.10, 0.20, 0.50, 0.80],
            [0.11, 0.22, 0.52, 0.82],
            [0.12, 0.21, 0.51, 0.81],
            [0.13, 0.23, 0.53, 0.83],
            [0.14, 0.24, 0.54, 0.84],
            [0.15, 0.25, 0.55, 0.85],
        ]
    )

    result = wilcoxon_pairwise_bonferroni(matrix, ["a", "b", "c", "d"])

    assert len(result.comparisons) == 6
    assert math.isclose(result.alpha_corrected, 0.05 / 6)
    assert all("pair" in row for row in result.comparisons)


def test_mcnemar_paired_detects_discordance():
    from evaluation.analysis.analyzers.significance_tests import mcnemar_paired

    a = np.array([1] * 90 + [0] * 10)
    b = np.array([1] * 70 + [0] * 30)

    result = mcnemar_paired(a, b)

    assert result.contingency_table == [[70, 20], [0, 10]]
    assert result.p_value < 0.05


def test_bootstrap_pass_at_k_ci_contains_estimate():
    from evaluation.analysis.analyzers.significance_tests import bootstrap_pass_at_k_ci

    successes = np.array([1] * 8 + [0] * 2)

    result = bootstrap_pass_at_k_ci(successes, k=3, n_boot=200, alpha=0.05, random_seed=7)

    assert 0.0 <= result.ci_lo <= result.estimate <= result.ci_hi <= 1.0
    assert math.isclose(result.estimate, 1.0)


def test_bootstrap_seed_varies_by_document():
    from evaluation.analysis.analyzers.pass_at_k import _bootstrap_seed

    seed_a = _bootstrap_seed(5, doc_key="doc_a", k=1)
    seed_b = _bootstrap_seed(5, doc_key="doc_b", k=1)
    assert seed_a is not None and seed_b is not None
    assert seed_a != seed_b


def test_aggregate_bootstrap_ci_uses_distinct_document_seeds():
    run = {
        "success": True,
        "n_fields_extracted": 12,
        "completeness": {"required_completeness": 0.8},
        "correctness": {"f1_score": 0.6},
        "internal_metrics": {"overall_confidence": 0.7},
    }
    fail = {
        "success": False,
        "n_fields_extracted": 0,
        "completeness": {"required_completeness": 0.0},
        "correctness": {"f1_score": 0.0},
        "internal_metrics": {"overall_confidence": 0.0},
    }
    analyzer = PassAtKAnalyzer(
        runs_dir="evaluation/runs",
        k_values=[1],
        bootstrap=True,
        n_boot=120,
        random_seed=5,
    )
    analyzer.eval_results = {
        "model_a": {
            "doc_a": [run, fail, run],
            "doc_b": [fail, run, run],
        }
    }

    results = analyzer.get_model_pass_at_k("model_a")
    doc_a_ci = results["by_document"]["doc_a"]["pass@1_ci_lo"]
    doc_b_ci = results["by_document"]["doc_b"]["pass@1_ci_lo"]
    assert doc_a_ci != doc_b_ci


def test_pass_at_k_analyzer_adds_bootstrap_ci_columns():
    analyzer = PassAtKAnalyzer(
        runs_dir="evaluation/runs",
        k_values=[1, 3],
        bootstrap=True,
        n_boot=100,
        ci_alpha=0.1,
        random_seed=5,
    )
    analyzer.eval_results = {
        "ollama_qwen3.6": {
            "doc_a": [
                {
                    "success": True,
                    "n_fields_extracted": 12,
                    "completeness": {"required_completeness": 0.8},
                    "correctness": {"f1_score": 0.6},
                    "internal_metrics": {"overall_confidence": 0.7},
                },
                {
                    "success": False,
                    "n_fields_extracted": 0,
                    "completeness": {"required_completeness": 0.0},
                    "correctness": {"f1_score": 0.0},
                    "internal_metrics": {"overall_confidence": 0.0},
                },
                {
                    "success": True,
                    "n_fields_extracted": 15,
                    "completeness": {"required_completeness": 0.9},
                    "correctness": {"f1_score": 0.7},
                    "internal_metrics": {"overall_confidence": 0.8},
                },
            ]
        }
    }

    summary_df = analyzer.get_summary_dataframe()
    doc_df = analyzer.get_document_level_dataframe()

    assert "pass@1_ci_lo" in summary_df.columns
    assert "pass@1_ci_hi" in summary_df.columns
    assert "pass@3_ci_lo" in summary_df.columns
    assert "pass@3_ci_hi" in summary_df.columns
    assert "pass@1_ci_lo" in doc_df.columns
    assert "pass@1_ci_hi" in doc_df.columns
    assert summary_df.loc[0, "pass@1_ci_lo"] <= summary_df.loc[0, "pass@1"] <= summary_df.loc[0, "pass@1_ci_hi"]
