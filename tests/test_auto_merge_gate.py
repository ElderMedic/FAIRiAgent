import importlib.util
import json
import sys
from pathlib import Path


def _load_merge_gate():
    path = (
        Path(__file__).resolve().parents[1]
        / "evaluation"
        / "prototypes"
        / "auto_repair_classifier"
        / "merge_gate.py"
    )
    spec = importlib.util.spec_from_file_location("auto_merge_gate", path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _eval_result(model_name, metrics, doc_scores):
    per_document = {}
    structural = {}
    schema = {}
    values = {}
    for doc_id, scores in doc_scores.items():
        per_document[doc_id] = {
            "overall_metrics": {
                "overall_completeness": scores["completeness"],
                "required_completeness": 1.0,
                "extra_fields": scores.get("extra_fields", 0),
            }
        }
        structural[doc_id] = {
            "summary_metrics": {
                "row_alignment_f1": scores["row_alignment_f1"],
                "sheet_placement_accuracy": scores["sheet_placement_accuracy"],
            }
        }
        schema[doc_id] = {"schema_compliance_rate": scores["schema_compliance"]}
        values[doc_id] = {"summary": {"value_match_rate": scores["value_match_rate"]}}
    return {
        "per_model_results": {
            model_name: {
                "completeness": {"per_document": per_document},
                "structural": {"per_document": structural},
                "schema_validation": {"per_document": schema},
                "value_accuracy": {"per_document": values},
            }
        },
        "model_comparison": {"metrics": {model_name: metrics}},
    }


def _doc_scores(count, **overrides):
    base = {
        "completeness": 0.72,
        "row_alignment_f1": 0.52,
        "sheet_placement_accuracy": 0.99,
        "schema_compliance": 0.89,
        "value_match_rate": 0.16,
    }
    base.update(overrides)
    return {f"doc_{idx}": dict(base) for idx in range(count)}


def _metrics(**overrides):
    base = {
        "schema_compliance": 0.89,
        "row_alignment_f1": 0.52,
        "sheet_placement_accuracy": 0.99,
        "precision_excl_discoveries": 0.98,
        "completeness": 0.72,
        "value_match_rate": 0.16,
        "llm_judge_score": 0.73,
        "aggregate_score": 0.62,
    }
    base.update(overrides)
    return base


def test_merge_gate_reports_missing_auto_results():
    gate = _load_merge_gate()
    shadow = _eval_result("shadow", _metrics(), _doc_scores(6))
    tuned = _eval_result("tuned", _metrics(value_match_rate=0.17), _doc_scores(6))

    report = gate.build_gate_report(
        auto_results=None,
        shadow_results=shadow,
        tuned_results=tuned,
    )

    assert report["passed"] is False
    assert report["status"] == "missing_auto_results"
    assert report["checks"][0]["name"] == "auto_results_present"


def test_merge_gate_passes_when_auto_preserves_shadow_strengths():
    gate = _load_merge_gate()
    shadow = _eval_result("shadow", _metrics(), _doc_scores(6))
    tuned = _eval_result("tuned", _metrics(value_match_rate=0.17), _doc_scores(6))
    auto = _eval_result(
        "auto",
        _metrics(completeness=0.73, value_match_rate=0.165, llm_judge_score=0.75),
        _doc_scores(6, completeness=0.73, value_match_rate=0.165),
    )
    report = gate.build_gate_report(
        auto_results=auto,
        shadow_results=shadow,
        tuned_results=tuned,
        thresholds=gate.GateThresholds(min_common_documents=6),
    )

    assert report["passed"] is False
    assert report["status"] == "fail"
    assert report["artifact_validation"]["reason"] == "auto_run_dir_not_provided"


def _write_auto_artifacts(
    run_root,
    doc_ids,
    *,
    include_trace=True,
    include_excel=True,
    include_runtime_config=True,
    effective_retrieval_mode="auto",
    auto_repair_enabled=True,
    auto_repair_apply_patches=True,
    include_classifier_shadow_config=True,
    include_summary=True,
    include_isa_value=True,
    include_document_source=True,
    trace_mode="deterministic_exact_patch",
    trace_apply_patches=True,
):
    model_root = run_root / "auto_model"
    for doc_id in doc_ids:
        run_dir = model_root / doc_id / "run_1"
        run_dir.mkdir(parents=True)
        (run_dir / "metadata.json").write_text(
            json.dumps(
                {
                    "fairifier_version": "Vtest",
                    "generated_at": "2026-07-14T00:00:00",
                    **(
                        {"document_source": f"{doc_id}.pdf"}
                        if include_document_source
                        else {}
                    ),
                    "isa_structure": {
                        "study": {
                            "fields": [
                                {"field_name": "study title", "value": "Example"}
                            ],
                            "columns": ["study title"],
                            "rows": [{"study title": "Example"}],
                        }
                    },
                    "isa_values": {
                        "study": {
                            "columns": ["study title"],
                            "rows": [{"study title": "Example"}],
                        }
                    },
                    **(
                        {
                            "auto_repair_summary": {
                                "accepted_patch_count": 1,
                                "trace_artifact": "auto_repair_trace.json",
                                "accepted_fields": [
                                    {
                                        "field": "study title",
                                        "isa_sheet": "study",
                                        "field_action": "appended",
                                        "post_patch_validation": "passed",
                                    }
                                ],
                            }
                        }
                        if include_summary
                        else {}
                    ),
                }
            ),
            encoding="utf-8",
        )
        (run_dir / "workflow_report.json").write_text("{}", encoding="utf-8")
        if include_runtime_config:
            (run_dir / "runtime_config.json").write_text(
                json.dumps(
                    {
                        "runtime_info": {"workflow_version": "langgraph"},
                        "config": {
                            "retrieval_mode": effective_retrieval_mode,
                            "effective_retrieval_mode": effective_retrieval_mode,
                            "auto_repair_enabled": auto_repair_enabled,
                            "auto_repair_apply_patches": auto_repair_apply_patches,
                            "auto_repair_min_candidate_confidence": 0.55,
                            **(
                                {"auto_repair_classifier_shadow_enabled": True}
                                if include_classifier_shadow_config
                                else {}
                            ),
                        },
                    }
                ),
                encoding="utf-8",
            )
        (run_dir / "isa_values_json.json").write_text(
            json.dumps(
                {
                    "study": {
                        "columns": ["study title"],
                        "rows": [
                            {"study title": "Example"}
                            if include_isa_value
                            else {}
                        ],
                    }
                }
            ),
            encoding="utf-8",
        )
        if include_trace:
            (run_dir / "auto_repair_trace.json").write_text(
                json.dumps(
                    {
                        "mode": trace_mode,
                        "summary": {
                            "accepted_patch_count": 1,
                            "metadata_mutated": True,
                            "apply_patches": trace_apply_patches,
                        },
                        "accepted_patches": [
                            {
                                "field": "study title",
                                "isa_sheet": "study",
                                "field_action": "appended",
                                "post_patch_validation": "passed",
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )
        if include_excel:
            from fairifier.services.fairds_excel_export import (
                try_export_fairds_metadata_excel,
            )

            try_export_fairds_metadata_excel(run_dir, fair_ds_api_url="")


def test_merge_gate_passes_with_complete_auto_artifacts(tmp_path):
    gate = _load_merge_gate()
    shadow = _eval_result("shadow", _metrics(), _doc_scores(6))
    tuned = _eval_result("tuned", _metrics(value_match_rate=0.17), _doc_scores(6))
    auto = _eval_result(
        "auto",
        _metrics(completeness=0.73, value_match_rate=0.165, llm_judge_score=0.75),
        _doc_scores(6, completeness=0.73, value_match_rate=0.165),
    )
    _write_auto_artifacts(tmp_path, [f"doc_{idx}" for idx in range(6)])

    report = gate.build_gate_report(
        auto_results=auto,
        shadow_results=shadow,
        tuned_results=tuned,
        auto_run_dir=tmp_path,
    )

    assert report["passed"] is True
    assert report["status"] == "pass"
    assert report["common_documents"] == [f"doc_{idx}" for idx in range(6)]
    assert report["artifact_validation"]["summary"]["accepted_patch_count"] == 6
    assert report["artifact_validation"]["summary"]["trace_mode_counts"] == {
        "deterministic_exact_patch": 6
    }
    assert (
        report["artifact_validation"]["summary"][
            "non_production_trace_document_count"
        ]
        == 0
    )


def test_merge_gate_fails_when_auto_trace_artifact_missing(tmp_path):
    gate = _load_merge_gate()
    shadow = _eval_result("shadow", _metrics(), _doc_scores(6))
    tuned = _eval_result("tuned", _metrics(value_match_rate=0.17), _doc_scores(6))
    auto = _eval_result(
        "auto",
        _metrics(completeness=0.73, value_match_rate=0.165, llm_judge_score=0.75),
        _doc_scores(6, completeness=0.73, value_match_rate=0.165),
    )
    _write_auto_artifacts(
        tmp_path,
        [f"doc_{idx}" for idx in range(6)],
        include_trace=False,
    )

    report = gate.build_gate_report(
        auto_results=auto,
        shadow_results=shadow,
        tuned_results=tuned,
        auto_run_dir=tmp_path,
    )

    assert report["passed"] is False
    failed_checks = {
        check["name"] for check in report["checks"]
        if check["severity"] == "fail" and not check["passed"]
    }
    assert "auto_artifacts_complete" in failed_checks
    assert report["artifact_validation"]["summary"]["failed_document_count"] == 6


def test_merge_gate_fails_when_auto_trace_is_error_fallback(tmp_path):
    gate = _load_merge_gate()
    shadow = _eval_result("shadow", _metrics(), _doc_scores(6))
    tuned = _eval_result("tuned", _metrics(value_match_rate=0.17), _doc_scores(6))
    auto = _eval_result(
        "auto",
        _metrics(completeness=0.73, value_match_rate=0.165, llm_judge_score=0.75),
        _doc_scores(6, completeness=0.73, value_match_rate=0.165),
    )
    _write_auto_artifacts(
        tmp_path,
        [f"doc_{idx}" for idx in range(6)],
        trace_mode="error_fallback",
    )

    report = gate.build_gate_report(
        auto_results=auto,
        shadow_results=shadow,
        tuned_results=tuned,
        auto_run_dir=tmp_path,
    )

    assert report["passed"] is False
    first_doc = report["artifact_validation"]["documents"][0]
    assert "auto_repair_trace_unexpected_mode:error_fallback" in first_doc["errors"]
    summary = report["artifact_validation"]["summary"]
    assert summary["trace_mode_counts"] == {"error_fallback": 6}
    assert summary["non_production_trace_document_count"] == 6


def test_merge_gate_fails_when_auto_trace_is_trace_only(tmp_path):
    gate = _load_merge_gate()
    shadow = _eval_result("shadow", _metrics(), _doc_scores(6))
    tuned = _eval_result("tuned", _metrics(value_match_rate=0.17), _doc_scores(6))
    auto = _eval_result(
        "auto",
        _metrics(completeness=0.73, value_match_rate=0.165, llm_judge_score=0.75),
        _doc_scores(6, completeness=0.73, value_match_rate=0.165),
    )
    _write_auto_artifacts(
        tmp_path,
        [f"doc_{idx}" for idx in range(6)],
        trace_apply_patches=False,
    )

    report = gate.build_gate_report(
        auto_results=auto,
        shadow_results=shadow,
        tuned_results=tuned,
        auto_run_dir=tmp_path,
    )

    assert report["passed"] is False
    first_doc = report["artifact_validation"]["documents"][0]
    assert "auto_repair_trace_not_applying_patches" in first_doc["errors"]
    summary = report["artifact_validation"]["summary"]
    assert summary["trace_only_document_count"] == 6
    assert summary["non_production_trace_document_count"] == 6


def test_merge_gate_fails_when_fairds_excel_missing(tmp_path):
    gate = _load_merge_gate()
    shadow = _eval_result("shadow", _metrics(), _doc_scores(6))
    tuned = _eval_result("tuned", _metrics(value_match_rate=0.17), _doc_scores(6))
    auto = _eval_result(
        "auto",
        _metrics(completeness=0.73, value_match_rate=0.165, llm_judge_score=0.75),
        _doc_scores(6, completeness=0.73, value_match_rate=0.165),
    )
    _write_auto_artifacts(
        tmp_path,
        [f"doc_{idx}" for idx in range(6)],
        include_excel=False,
    )

    report = gate.build_gate_report(
        auto_results=auto,
        shadow_results=shadow,
        tuned_results=tuned,
        auto_run_dir=tmp_path,
    )

    assert report["passed"] is False
    first_doc = report["artifact_validation"]["documents"][0]
    assert "metadata_fairds_xlsx_missing" in first_doc["errors"]


def test_merge_gate_fails_when_runtime_config_missing(tmp_path):
    gate = _load_merge_gate()
    shadow = _eval_result("shadow", _metrics(), _doc_scores(6))
    tuned = _eval_result("tuned", _metrics(value_match_rate=0.17), _doc_scores(6))
    auto = _eval_result(
        "auto",
        _metrics(completeness=0.73, value_match_rate=0.165, llm_judge_score=0.75),
        _doc_scores(6, completeness=0.73, value_match_rate=0.165),
    )
    _write_auto_artifacts(
        tmp_path,
        [f"doc_{idx}" for idx in range(6)],
        include_runtime_config=False,
    )

    report = gate.build_gate_report(
        auto_results=auto,
        shadow_results=shadow,
        tuned_results=tuned,
        auto_run_dir=tmp_path,
    )

    assert report["passed"] is False
    first_doc = report["artifact_validation"]["documents"][0]
    assert "runtime_config_missing" in first_doc["errors"]


def test_merge_gate_fails_when_runtime_config_does_not_prove_auto(tmp_path):
    gate = _load_merge_gate()
    shadow = _eval_result("shadow", _metrics(), _doc_scores(6))
    tuned = _eval_result("tuned", _metrics(value_match_rate=0.17), _doc_scores(6))
    auto = _eval_result(
        "auto",
        _metrics(completeness=0.73, value_match_rate=0.165, llm_judge_score=0.75),
        _doc_scores(6, completeness=0.73, value_match_rate=0.165),
    )
    _write_auto_artifacts(
        tmp_path,
        [f"doc_{idx}" for idx in range(6)],
        effective_retrieval_mode="tuned",
        auto_repair_apply_patches=False,
        trace_apply_patches=False,
    )

    report = gate.build_gate_report(
        auto_results=auto,
        shadow_results=shadow,
        tuned_results=tuned,
        auto_run_dir=tmp_path,
    )

    assert report["passed"] is False
    first_doc = report["artifact_validation"]["documents"][0]
    assert "runtime_config_effective_mode_not_auto:tuned" in first_doc["errors"]
    assert "runtime_config_auto_repair_not_applying_patches" in first_doc["errors"]


def test_merge_gate_fails_when_runtime_config_missing_classifier_shadow_setting(tmp_path):
    gate = _load_merge_gate()
    shadow = _eval_result("shadow", _metrics(), _doc_scores(6))
    tuned = _eval_result("tuned", _metrics(value_match_rate=0.17), _doc_scores(6))
    auto = _eval_result(
        "auto",
        _metrics(completeness=0.73, value_match_rate=0.165, llm_judge_score=0.75),
        _doc_scores(6, completeness=0.73, value_match_rate=0.165),
    )
    _write_auto_artifacts(
        tmp_path,
        [f"doc_{idx}" for idx in range(6)],
        include_classifier_shadow_config=False,
    )

    report = gate.build_gate_report(
        auto_results=auto,
        shadow_results=shadow,
        tuned_results=tuned,
        auto_run_dir=tmp_path,
    )

    assert report["passed"] is False
    first_doc = report["artifact_validation"]["documents"][0]
    assert "runtime_config_classifier_shadow_setting_missing" in first_doc["errors"]


def test_merge_gate_markdown_lists_failed_artifact_errors(tmp_path):
    gate = _load_merge_gate()
    shadow = _eval_result("shadow", _metrics(), _doc_scores(6))
    tuned = _eval_result("tuned", _metrics(value_match_rate=0.17), _doc_scores(6))
    auto = _eval_result(
        "auto",
        _metrics(completeness=0.73, value_match_rate=0.165, llm_judge_score=0.75),
        _doc_scores(6, completeness=0.73, value_match_rate=0.165),
    )
    _write_auto_artifacts(
        tmp_path,
        [f"doc_{idx}" for idx in range(6)],
        effective_retrieval_mode="tuned",
        auto_repair_apply_patches=False,
        trace_apply_patches=False,
    )

    report = gate.build_gate_report(
        auto_results=auto,
        shadow_results=shadow,
        tuned_results=tuned,
        auto_run_dir=tmp_path,
    )
    markdown = gate.render_markdown(report)

    assert "### Failed Artifact Documents" in markdown
    assert "`doc_0`" in markdown
    assert "runtime_config_effective_mode_not_auto:tuned" in markdown
    assert "runtime_config_auto_repair_not_applying_patches" in markdown
    assert "auto_repair_trace_not_applying_patches" in markdown
    assert "non-production trace documents: 6" in markdown
    assert "trace modes: deterministic_exact_patch=6" in markdown


def test_merge_gate_fails_when_metadata_repair_summary_missing(tmp_path):
    gate = _load_merge_gate()
    shadow = _eval_result("shadow", _metrics(), _doc_scores(6))
    tuned = _eval_result("tuned", _metrics(value_match_rate=0.17), _doc_scores(6))
    auto = _eval_result(
        "auto",
        _metrics(completeness=0.73, value_match_rate=0.165, llm_judge_score=0.75),
        _doc_scores(6, completeness=0.73, value_match_rate=0.165),
    )
    _write_auto_artifacts(
        tmp_path,
        [f"doc_{idx}" for idx in range(6)],
        include_summary=False,
    )

    report = gate.build_gate_report(
        auto_results=auto,
        shadow_results=shadow,
        tuned_results=tuned,
        auto_run_dir=tmp_path,
    )

    assert report["passed"] is False
    first_doc = report["artifact_validation"]["documents"][0]
    assert "metadata_json_missing_auto_repair_summary" in first_doc["errors"]


def test_merge_gate_fails_when_accepted_patch_not_materialized_in_isa_values(tmp_path):
    gate = _load_merge_gate()
    shadow = _eval_result("shadow", _metrics(), _doc_scores(6))
    tuned = _eval_result("tuned", _metrics(value_match_rate=0.17), _doc_scores(6))
    auto = _eval_result(
        "auto",
        _metrics(completeness=0.73, value_match_rate=0.165, llm_judge_score=0.75),
        _doc_scores(6, completeness=0.73, value_match_rate=0.165),
    )
    _write_auto_artifacts(
        tmp_path,
        [f"doc_{idx}" for idx in range(6)],
        include_isa_value=False,
    )

    report = gate.build_gate_report(
        auto_results=auto,
        shadow_results=shadow,
        tuned_results=tuned,
        auto_run_dir=tmp_path,
    )

    assert report["passed"] is False
    first_doc = report["artifact_validation"]["documents"][0]
    assert "accepted_patch_missing_isa_values_value:study:study title" in first_doc["errors"]
    assert "accepted_patch_missing_excel_value:study:study title" in first_doc["errors"]


def test_merge_gate_fails_when_accepted_patch_not_materialized_in_excel(tmp_path):
    gate = _load_merge_gate()
    shadow = _eval_result("shadow", _metrics(), _doc_scores(6))
    tuned = _eval_result("tuned", _metrics(value_match_rate=0.17), _doc_scores(6))
    auto = _eval_result(
        "auto",
        _metrics(completeness=0.73, value_match_rate=0.165, llm_judge_score=0.75),
        _doc_scores(6, completeness=0.73, value_match_rate=0.165),
    )
    _write_auto_artifacts(tmp_path, [f"doc_{idx}" for idx in range(6)])
    for xlsx in tmp_path.glob("auto_model/doc_*/run_1/metadata_fairds.xlsx"):
        from openpyxl import load_workbook

        workbook = load_workbook(xlsx)
        worksheet = workbook["Study"]
        headers = {
            worksheet.cell(1, col).value: col
            for col in range(1, worksheet.max_column + 1)
        }
        worksheet.cell(2, headers["study title"]).value = None
        workbook.save(xlsx)

    report = gate.build_gate_report(
        auto_results=auto,
        shadow_results=shadow,
        tuned_results=tuned,
        auto_run_dir=tmp_path,
    )

    assert report["passed"] is False
    first_doc = report["artifact_validation"]["documents"][0]
    assert "accepted_patch_missing_excel_value:study:study title" in first_doc["errors"]


def test_merge_gate_fails_when_metadata_json_format_invalid(tmp_path):
    gate = _load_merge_gate()
    shadow = _eval_result("shadow", _metrics(), _doc_scores(6))
    tuned = _eval_result("tuned", _metrics(value_match_rate=0.17), _doc_scores(6))
    auto = _eval_result(
        "auto",
        _metrics(completeness=0.73, value_match_rate=0.165, llm_judge_score=0.75),
        _doc_scores(6, completeness=0.73, value_match_rate=0.165),
    )
    _write_auto_artifacts(
        tmp_path,
        [f"doc_{idx}" for idx in range(6)],
        include_document_source=False,
    )

    report = gate.build_gate_report(
        auto_results=auto,
        shadow_results=shadow,
        tuned_results=tuned,
        auto_run_dir=tmp_path,
    )

    assert report["passed"] is False
    first_doc = report["artifact_validation"]["documents"][0]
    assert first_doc["metadata_json_format"] == "failed"
    assert (
        "metadata_json_format_error:Missing required top-level field: document_source"
        in first_doc["errors"]
    )


def test_merge_gate_fails_on_schema_regression():
    gate = _load_merge_gate()
    shadow = _eval_result("shadow", _metrics(), _doc_scores(6))
    tuned = _eval_result("tuned", _metrics(value_match_rate=0.17), _doc_scores(6))
    auto = _eval_result(
        "auto",
        _metrics(schema_compliance=0.80),
        _doc_scores(6, schema_compliance=0.80),
    )

    report = gate.build_gate_report(
        auto_results=auto,
        shadow_results=shadow,
        tuned_results=tuned,
    )

    assert report["passed"] is False
    failed_checks = {
        check["name"] for check in report["checks"]
        if check["severity"] == "fail" and not check["passed"]
    }
    assert "schema_not_worse_than_shadow" in failed_checks
    assert "no_document_level_regressions" in failed_checks
