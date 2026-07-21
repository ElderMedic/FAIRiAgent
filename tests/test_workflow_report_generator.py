from fairifier.utils.report_generator import WorkflowReportGenerator
from fairifier.config import FAIRifierConfig, apply_env_overrides


def test_retrieval_metrics_summarize_auto_prompting_modes():
    generator = WorkflowReportGenerator()
    state = {
        "semantic_index": {
            "status": "available",
            "available": True,
            "indexed_chunk_count": 12,
        },
        "retrieval_telemetry": {
            "field_a": {
                "lexical_hit_count": 2,
                "semantic_hit_count": 0,
                "hybrid_hit_count": 2,
                "retrieval_mode": "auto",
                "prompt_mode": "auto_lexical",
                "auto_repair_score": 0,
                "auto_repair_reasons": ["lexical_evidence_present"],
            },
            "field_b": {
                "lexical_hit_count": 0,
                "semantic_hit_count": 3,
                "hybrid_hit_count": 3,
                "retrieval_mode": "auto",
                "prompt_mode": "auto_semantic_fallback",
                "auto_repair_score": 3,
                "auto_repair_reasons": ["semantic_only_gap", "missing_value"],
            },
        },
        "source_chunks": [{}, {}],
        "source_sections": [{}],
        "evidence_store": {"record_count": 5},
    }

    metrics = generator.generate_report(state)["retrieval_metrics"]

    assert metrics["retrieval_mode_counts"] == {"auto": 2}
    assert metrics["prompt_mode_counts"] == {
        "auto_lexical": 1,
        "auto_semantic_fallback": 1,
    }
    assert metrics["auto_repair_score_summary"] == {
        "count": 2,
        "min": 0.0,
        "max": 3.0,
        "avg": 1.5,
    }
    assert metrics["auto_repair_reason_counts"] == {
        "lexical_evidence_present": 1,
        "semantic_only_gap": 1,
        "missing_value": 1,
    }


def test_text_report_exposes_auto_repair_trace_mode_and_patch_status():
    generator = WorkflowReportGenerator()
    report = {
        "generated_at": "2026-07-14T12:00:00",
        "workflow_status": "completed",
        "execution_summary": {},
        "quality_metrics": {},
        "retrieval_metrics": {
            "semantic_index_status": "available",
            "fields_with_retrieval_telemetry": 2,
            "retrieval_mode_counts": {"auto": 2},
            "prompt_mode_counts": {
                "auto_lexical": 1,
                "auto_semantic_fallback": 1,
            },
            "auto_repair_score_summary": {
                "count": 2,
                "avg": 1.5,
                "max": 3.0,
            },
            "auto_repair_reason_counts": {
                "semantic_only_gap": 1,
                "missing_value": 1,
            },
        },
        "auto_repair_trace": {
            "mode": "deterministic_exact_patch",
            "summary": {
                "apply_patches": True,
                "candidate_count": 2,
                "skipped_gap_count": 1,
                "accepted_patch_count": 1,
                "rejected_patch_count": 0,
                "classifier_shadow_prediction_count": 2,
                "metadata_mutated": True,
            },
        },
        "field_analysis": {"error": "not needed"},
        "duplicate_check": {"duplicates_found": False},
        "retry_analysis": {},
        "timeline": [],
    }

    text = generator.generate_text_report(report)

    assert "RETRIEVAL AND AUTO PROMPTING" in text
    assert "Retrieval modes:                 auto=2" in text
    assert "Prompt modes:                    auto_lexical=1, auto_semantic_fallback=1" in text
    assert "Mode:                            deterministic_exact_patch" in text
    assert "Apply patches:                   True" in text
    assert "Classifier shadow predictions:   2" in text


def test_performance_report_aggregates_phase_tokens_cost_and_gates(monkeypatch):
    from fairifier.utils import report_generator as report_module

    cfg = FAIRifierConfig()
    cfg.telemetry_llm_input_cost_per_million_usd = 0.5
    cfg.telemetry_llm_output_cost_per_million_usd = 2.0
    cfg.telemetry_compute_cost_per_hour_usd = 1.0
    cfg.performance_gate_max_total_seconds = 120
    cfg.performance_gate_max_phase_seconds = 60
    cfg.performance_gate_max_total_tokens = 500
    cfg.performance_gate_max_estimated_cost_usd = 1.0
    monkeypatch.setattr(report_module, "config", cfg)

    state = {
        "processing_start": "2026-07-21T10:00:00+00:00",
        "processing_end": "2026-07-21T10:01:40+00:00",
        "execution_history": [
            {
                "agent_name": "DocumentParser",
                "start_time": "2026-07-21T10:00:00+00:00",
                "end_time": "2026-07-21T10:00:20+00:00",
                "success": True,
            },
            {
                "agent_name": "KnowledgeRetriever",
                "start_time": "2026-07-21T10:00:20+00:00",
                "end_time": "2026-07-21T10:00:50+00:00",
                "success": True,
            },
        ],
    }
    responses = [
        {
            "operation": "extract_document_info",
            "usage_metadata": {
                "input_tokens": 100,
                "output_tokens": 20,
                "total_tokens": 120,
            },
            "latency_seconds": 4.0,
        },
        {
            "operation": "knowledge_retriever_field_selection",
            "response_metadata": {
                "token_usage": {
                    "prompt_tokens": 50,
                    "completion_tokens": 10,
                    "total_tokens": 60,
                }
            },
            "latency_seconds": 6.0,
        },
    ]

    performance = WorkflowReportGenerator().generate_report(
        state,
        llm_responses=responses,
    )["performance"]

    assert performance["workflow"]["wall_time_seconds"] == 100.0
    assert performance["llm_usage"] == {
        "calls": 2,
        "calls_with_token_usage": 2,
        "usage_coverage_ratio": 1.0,
        "input_tokens": 150,
        "output_tokens": 30,
        "total_tokens": 180,
        "latency_seconds": 10.0,
        "latency_mean_seconds": 5.0,
        "latency_p95_seconds": 6.0,
    }
    assert performance["phases"]["document_parsing"]["input_tokens"] == 100
    assert performance["phases"]["document_parsing"]["estimated_llm_cost"] == 0.00009
    assert performance["phases"]["knowledge_retrieval"]["input_tokens"] == 50
    assert performance["cost"]["estimated_llm_cost"] == 0.000135
    assert performance["cost"]["estimated_compute_cost"] == 0.027778
    assert performance["cost"]["estimated_total_cost"] == 0.027913
    assert performance["gates"]["overall_status"] == "pass"
    assert performance["gates"]["violations"] == []
    assert performance["gates"]["phase_violations"] == []
    assert {
        check["name"]: check["status"]
        for check in performance["gates"]["per_phase"]["document_parsing"]
    } == {
        "latency": "pass",
        "tokens": "pass",
        "estimated_cost": "pass",
    }


def test_performance_gate_fails_and_never_changes_workflow_status(monkeypatch):
    from fairifier.utils import report_generator as report_module

    cfg = FAIRifierConfig()
    cfg.telemetry_llm_input_cost_per_million_usd = 1.0
    cfg.telemetry_llm_output_cost_per_million_usd = 1.0
    cfg.performance_gate_max_total_seconds = 10
    cfg.performance_gate_max_phase_seconds = 5
    cfg.performance_gate_max_total_tokens = 10
    cfg.performance_gate_max_phase_tokens = 10
    cfg.performance_gate_max_estimated_cost_usd = 10
    cfg.performance_gate_max_phase_cost_usd = 10
    monkeypatch.setattr(report_module, "config", cfg)
    state = {
        "status": "completed",
        "processing_start": "2026-07-21T10:00:00+00:00",
        "processing_end": "2026-07-21T10:00:20+00:00",
        "execution_history": [
            {
                "agent_name": "JSONGenerator",
                "start_time": "2026-07-21T10:00:00+00:00",
                "end_time": "2026-07-21T10:00:12+00:00",
                "success": True,
            }
        ],
    }
    response = {
        "operation": "generate_complete_metadata",
        "usage_metadata": {
            "input_tokens": 10,
            "output_tokens": 5,
            "total_tokens": 15,
        },
        "latency_seconds": 2,
    }

    report = WorkflowReportGenerator().generate_report(
        state,
        llm_responses=[response],
    )

    assert report["workflow_status"] == "completed"
    assert report["performance"]["gates"]["overall_status"] == "fail"
    assert report["performance"]["gates"]["violations"] == [
        "workflow_latency",
        "phase_latency",
        "total_tokens",
        "phase_tokens",
    ]
    assert report["performance"]["gates"]["phase_violations"] == [
        "metadata_generation.latency",
        "metadata_generation.tokens",
    ]


def test_performance_cost_gate_reports_incomplete_usage(monkeypatch):
    from fairifier.utils import report_generator as report_module

    cfg = FAIRifierConfig()
    cfg.telemetry_llm_input_cost_per_million_usd = 0.5
    cfg.telemetry_llm_output_cost_per_million_usd = 2.0
    monkeypatch.setattr(report_module, "config", cfg)
    report = WorkflowReportGenerator().generate_report(
        {},
        llm_responses=[{"operation": "critic", "latency_seconds": 1.0}],
    )

    performance = report["performance"]
    assert performance["llm_usage"]["usage_coverage_ratio"] == 0.0
    assert performance["cost"]["estimate_status"] == "insufficient_data"
    checks = {item["name"]: item for item in performance["gates"]["checks"]}
    assert checks["total_tokens"]["status"] == "insufficient_data"
    assert checks["estimated_cost"]["status"] == "insufficient_data"


def test_performance_settings_read_environment(monkeypatch):
    monkeypatch.setenv("FAIRIFIER_LLM_INPUT_COST_PER_MILLION_USD", "0.4")
    monkeypatch.setenv("FAIRIFIER_LLM_OUTPUT_COST_PER_MILLION_USD", "1.2")
    monkeypatch.setenv("FAIRIFIER_COMPUTE_COST_PER_HOUR_USD", "0.3")
    monkeypatch.setenv("FAIRIFIER_PERFORMANCE_MAX_TOTAL_SECONDS", "900")
    monkeypatch.setenv("FAIRIFIER_PERFORMANCE_MAX_PHASE_SECONDS", "400")
    monkeypatch.setenv("FAIRIFIER_PERFORMANCE_MAX_TOTAL_TOKENS", "12345")
    monkeypatch.setenv("FAIRIFIER_PERFORMANCE_MAX_PHASE_TOKENS", "6789")
    monkeypatch.setenv("FAIRIFIER_PERFORMANCE_MAX_ESTIMATED_COST_USD", "2.5")
    monkeypatch.setenv("FAIRIFIER_PERFORMANCE_MAX_PHASE_COST_USD", "1.5")
    cfg = FAIRifierConfig()

    apply_env_overrides(cfg)

    assert cfg.telemetry_llm_input_cost_per_million_usd == 0.4
    assert cfg.telemetry_llm_output_cost_per_million_usd == 1.2
    assert cfg.telemetry_compute_cost_per_hour_usd == 0.3
    assert cfg.performance_gate_max_total_seconds == 900
    assert cfg.performance_gate_max_phase_seconds == 400
    assert cfg.performance_gate_max_total_tokens == 12345
    assert cfg.performance_gate_max_phase_tokens == 6789
    assert cfg.performance_gate_max_estimated_cost_usd == 2.5
    assert cfg.performance_gate_max_phase_cost_usd == 1.5
