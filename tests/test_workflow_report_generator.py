from fairifier.utils.report_generator import WorkflowReportGenerator


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
