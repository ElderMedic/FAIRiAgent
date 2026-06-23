from evaluation.scripts.evaluate_agent_quality import (
    calculate_summary_stats,
    compute_metrics,
    compute_pass_at_k,
    compute_win_rates,
    target_normalize_profile,
)


def test_calculate_summary_stats_pools_all_baseline_runs():
    metrics = {
        "full_pipeline": [
            {
                "mandatory_coverage": 1.0,
                "structure_score": 0.8,
                "evidence_rate": 0.2,
                "multi_row_depth": 10,
            }
        ],
        "baseline_b1": [
            {
                "mandatory_coverage": 0.0,
                "structure_score": 0.5,
                "evidence_rate": 0.0,
                "multi_row_depth": 2,
            }
        ],
        "baseline_b2": [
            {
                "mandatory_coverage": 1.0,
                "structure_score": 0.7,
                "evidence_rate": 0.0,
                "multi_row_depth": 4,
            },
            {
                "mandatory_coverage": 0.5,
                "structure_score": 0.6,
                "evidence_rate": 0.0,
                "multi_row_depth": 6,
            },
        ],
    }

    summary = calculate_summary_stats(metrics)

    assert summary["baseline"]["n"] == 3
    assert summary["baseline"]["mandatory_coverage"]["mean"] == 0.5
    assert summary["baseline"]["multi_row_depth"]["mean"] == 4.0


def test_compute_win_rates_counts_ties_separately_from_wins():
    agentic = [
        {"document_id": "doc-a", "mandatory_coverage": 1.0, "structure_score": 0.9},
        {"document_id": "doc-b", "mandatory_coverage": 0.8, "structure_score": 0.7},
    ]
    baselines = [
        {"document_id": "doc-a", "mandatory_coverage": 1.0, "structure_score": 0.6},
        {"document_id": "doc-b", "mandatory_coverage": 0.9, "structure_score": 0.8},
    ]

    rates = compute_win_rates(
        agentic,
        baselines,
        ["mandatory_coverage", "structure_score"],
    )

    assert rates["mandatory_coverage"]["wins"] == 0
    assert rates["mandatory_coverage"]["ties"] == 1
    assert rates["mandatory_coverage"]["total"] == 2
    assert rates["mandatory_coverage"]["rate"] == 0.0
    assert rates["structure_score"]["wins"] == 1
    assert rates["structure_score"]["rate"] == 0.5


def test_compute_metrics_reports_evidence_rate_not_binary_flag():
    metadata = {
        "errors": [],
        "packages_used": ["default"],
        "isa_values": {
            "sample": {
                "columns": ["sample identifier", "organism", "location"],
                "rows": [{"sample identifier": "s1"}],
            }
        },
        "_field_definitions": [{}, {}, {}, {}],
        "evidence_packets_summary": {"count": 1},
    }

    metrics = compute_metrics(metadata)

    assert metrics["evidence_rate"] == 0.25
    assert metrics["fields_with_evidence"] == 1
    assert metrics["total_fields"] == 4


def test_compute_pass_at_k_can_require_evidence_for_strict_success():
    runs = [
        {
            "mandatory_coverage": 1.0,
            "structure_score": 1.0,
            "evidence_rate": 0.25,
        },
        {
            "mandatory_coverage": 1.0,
            "structure_score": 1.0,
            "evidence_rate": 0.05,
        },
    ]

    moderate = compute_pass_at_k(
        runs,
        {"min_mandatory_coverage": 0.60, "min_structure_score": 0.60},
        k_max=1,
    )
    strict = compute_pass_at_k(
        runs,
        {
            "min_mandatory_coverage": 0.85,
            "min_structure_score": 0.85,
            "min_evidence_rate": 0.20,
        },
        k_max=1,
    )

    assert moderate[0] == 1.0
    assert strict[0] == 0.5


def test_target_normalize_profile_uses_interpretable_caps():
    runs = [
        {
            "mandatory_coverage": 0.5,
            "structure_score": 0.8,
            "evidence_rate": 0.1,
            "multi_row_depth": 10,
        },
        {
            "mandatory_coverage": 1.0,
            "structure_score": 1.0,
            "evidence_rate": 0.3,
            "multi_row_depth": 40,
        },
    ]

    profile = target_normalize_profile(runs)

    assert profile["mandatory_coverage"] == 0.75
    assert profile["structure_score"] == 0.9
    assert profile["evidence_rate"] == 1.0
    assert profile["multi_row_depth"] == 1.0
