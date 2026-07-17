import importlib.util
import json
import sys
from pathlib import Path


def _load_readiness():
    root = Path(__file__).resolve().parents[1]
    path = (
        root
        / "evaluation"
        / "prototypes"
        / "auto_repair_classifier"
        / "readiness_report.py"
    )
    sys.path.insert(0, str(path.parent))
    try:
        spec = importlib.util.spec_from_file_location("auto_readiness_report", path)
        module = importlib.util.module_from_spec(spec)
        assert spec.loader is not None
        sys.modules[spec.name] = module
        spec.loader.exec_module(module)
        return module
    finally:
        sys.path.remove(str(path.parent))


def test_readiness_status_transitions():
    readiness = _load_readiness()

    assert (
        readiness.readiness_status(
            preflight_passed=False,
            auto_results_present=False,
            gate_passed=False,
        )
        == "blocked_preflight"
    )
    assert (
        readiness.readiness_status(
            preflight_passed=True,
            auto_results_present=False,
            gate_passed=False,
        )
        == "ready_for_full_auto_eval"
    )
    assert (
        readiness.readiness_status(
            preflight_passed=True,
            auto_results_present=True,
            gate_passed=False,
        )
        == "blocked_merge_gate"
    )
    assert (
        readiness.readiness_status(
            preflight_passed=True,
            auto_results_present=True,
            gate_passed=True,
        )
        == "ready_to_merge"
    )


def test_readiness_cli_checks_services_by_default():
    readiness = _load_readiness()

    assert readiness.parse_args([]).skip_service_check is False
    assert readiness.parse_args(["--skip-service-check"]).skip_service_check is True


def test_build_readiness_report_lists_failed_checks(tmp_path):
    readiness = _load_readiness()
    auto_results = tmp_path / "results" / "evaluation_results.json"
    preflight = {
        "passed": False,
        "checks": [
            {"name": "eval_env_exists", "passed": True, "detail": "ok"},
            {"name": "service_reachable:MINERU_SERVER_URL", "passed": False, "detail": "down"},
        ],
    }
    gate = {
        "status": "missing_auto_results",
        "passed": False,
        "checks": [
            {
                "name": "auto_results_present",
                "passed": False,
                "severity": "fail",
                "detail": "missing",
            }
        ],
    }

    report = readiness.build_readiness_report(
        preflight_report=preflight,
        gate_report=gate,
        auto_results_path=auto_results,
        auto_run_dir=tmp_path,
        preconvert_report={
            "executed": True,
            "task_count": 1,
            "success_count": 0,
            "failed_count": 1,
            "dependency_errors": ["missing_python_module:doclayout_yolo"],
            "dependency_install_hint": "pip install 'mineru[pipeline]>=3.4.0,<4'",
        },
    )

    assert report["status"] == "blocked_preflight"
    assert report["passed"] is False
    assert report["preflight"]["summary"]["failed_check_names"] == [
        "service_reachable:MINERU_SERVER_URL"
    ]
    assert {blocker["key"] for blocker in report["blocked_requirements"]} == {
        "mineru_service",
        "auto_results",
        "mineru_preconvert_dependency",
    }
    assert report["mineru_preconvert"]["dependency_errors"] == [
        "missing_python_module:doclayout_yolo"
    ]
    assert report["mineru_preconvert"]["dependency_install_hint"] == (
        "pip install 'mineru[pipeline]>=3.4.0,<4'"
    )
    assert report["preflight"]["failed_checks"][0]["name"] == "service_reachable:MINERU_SERVER_URL"
    assert report["merge_gate"]["failed_checks"][0]["name"] == "auto_results_present"
    assert "missing_python_module:doclayout_yolo" in report["next_action"]
    assert "mineru[pipeline]>=3.4.0,<4" in report["next_action"]
    assert "start MinerU" in report["next_action"]
    requirements = {item["key"]: item for item in report["requirements"]}
    assert requirements["temporary_feature_workspace"]["status"] == "passed"
    assert requirements["fallback_rules_and_classifier_shadow"]["status"] == "passed"
    assert requirements["service_and_input_preconditions"]["status"] == "blocked"
    assert requirements["service_and_input_preconditions"]["evidence"][
        "mineru_preconvert_dependency_errors"
    ] == ["missing_python_module:doclayout_yolo"]
    assert requirements["service_and_input_preconditions"]["evidence"][
        "mineru_preconvert_install_hints"
    ] == ["pip install 'mineru[pipeline]>=3.4.0,<4'"]
    assert requirements["full_six_document_auto_eval"]["status"] == "pending_full_eval"
    assert (
        requirements["fairds_metadata_artifact_contract"]["status"]
        == "pending_full_eval"
    )


def test_next_action_mentions_fairds_and_missing_mineru_docs():
    readiness = _load_readiness()

    action = readiness.next_action(
        "blocked_preflight",
        failed_preflight=[
            {
                "name": "service_reachable:FAIR_DS_API_URL",
                "passed": False,
                "detail": "down",
            },
            {
                "name": "document_mineru_preconverted:pea_cold_stress",
                "passed": False,
                "detail": "missing",
            },
            {
                "name": "service_reachable:RETRIEVAL_EMBEDDING",
                "passed": False,
                "detail": "http://localhost:11435/api/tags: unreachable:down",
            },
        ],
    )

    assert "docker compose -f docker/compose.yaml up -d fairds" in action
    assert "pea_cold_stress" in action
    assert "preconvert_mineru.py" in action
    assert "retrieval embedding endpoint (http://localhost:11435/api/tags)" in action


def test_next_action_prioritizes_mineru_preconvert_dependency():
    readiness = _load_readiness()

    action = readiness.next_action(
        "blocked_preflight",
        failed_preflight=[
            {
                "name": "document_mineru_preconverted:pea_cold_stress",
                "passed": False,
                "detail": "missing",
            }
        ],
        preconvert_dependency_errors=["missing_python_module:doclayout_yolo"],
        preconvert_install_hint="pip install 'mineru[pipeline]>=3.4.0,<4'",
    )

    assert action.startswith("repair the FAIRiAgent environment")
    assert "missing_python_module:doclayout_yolo" in action
    assert "mineru[pipeline]>=3.4.0,<4" in action
    assert "preconvert_mineru.py" in action


def test_build_readiness_report_deduplicates_preconvert_dependency(tmp_path):
    readiness = _load_readiness()
    auto_results = tmp_path / "results" / "evaluation_results.json"
    preflight = {
        "passed": False,
        "checks": [
            {
                "name": "local_mineru_preconvert_dependencies",
                "passed": False,
                "detail": "missing_python_module:doclayout_yolo",
            }
        ],
        "summary": {
            "blocked_requirements": [
                {
                    "key": "mineru_preconvert_dependency",
                    "detail": "local MinerU preconversion dependency is missing",
                    "dependency_errors": ["missing_python_module:doclayout_yolo"],
                }
            ]
        },
    }
    gate = {
        "status": "missing_auto_results",
        "passed": False,
        "checks": [],
    }

    report = readiness.build_readiness_report(
        preflight_report=preflight,
        gate_report=gate,
        auto_results_path=auto_results,
        auto_run_dir=tmp_path,
        preconvert_report={
            "executed": True,
            "task_count": 1,
            "success_count": 0,
            "failed_count": 1,
            "dependency_errors": ["missing_python_module:doclayout_yolo"],
            "dependency_install_hint": "pip install 'mineru[pipeline]>=3.4.0,<4'",
        },
    )

    dependency_blockers = [
        item
        for item in report["blocked_requirements"]
        if item["key"] == "mineru_preconvert_dependency"
    ]
    assert len(dependency_blockers) == 1
    assert dependency_blockers[0]["dependency_errors"] == [
        "missing_python_module:doclayout_yolo"
    ]
    assert dependency_blockers[0]["install_hint"] == (
        "pip install 'mineru[pipeline]>=3.4.0,<4'"
    )


def test_requirement_audit_marks_ready_to_merge_when_gate_passes(tmp_path):
    readiness = _load_readiness()
    auto_results = tmp_path / "results" / "evaluation_results.json"
    auto_results.parent.mkdir(parents=True)
    auto_results.write_text("{}", encoding="utf-8")
    preflight = {
        "passed": True,
        "checks": [
            {"name": "retrieval_mode_auto", "passed": True, "detail": "auto"},
            {"name": "auto_repair_enabled", "passed": True, "detail": "true"},
            {"name": "auto_repair_apply_patches", "passed": True, "detail": "true"},
            {
                "name": "auto_repair_classifier_shadow_enabled",
                "passed": True,
                "detail": "true",
            },
        ],
    }
    gate = {
        "status": "passed",
        "passed": True,
        "checks": [
            {
                "name": "auto_results_present",
                "passed": True,
                "severity": "fail",
                "detail": "ok",
            }
        ],
    }

    report = readiness.build_readiness_report(
        preflight_report=preflight,
        gate_report=gate,
        auto_results_path=auto_results,
        auto_run_dir=tmp_path,
    )

    requirements = {item["key"]: item for item in report["requirements"]}
    assert report["status"] == "ready_to_merge"
    assert report["passed"] is True
    assert requirements["single_auto_pipeline_default"]["status"] == "passed"
    assert requirements["service_and_input_preconditions"]["status"] == "passed"
    assert requirements["fairds_metadata_artifact_contract"]["status"] == "passed"
    assert requirements["full_six_document_auto_eval"]["status"] == "passed"
    assert requirements["shadow_tuned_synthesis_merge_gate"]["status"] == "passed"


def test_write_readiness_report_writes_json_and_markdown(tmp_path):
    readiness = _load_readiness()
    report = {
        "status": "ready_for_full_auto_eval",
        "passed": False,
        "auto_results_path": "evaluation/runs/auto/results/evaluation_results.json",
        "auto_results_present": False,
        "auto_run_dir": "evaluation/runs/auto",
        "next_action": "Run full eval.",
        "preflight": {"failed_checks": []},
        "merge_gate": {"failed_checks": []},
        "mineru_preconvert": {
            "present": True,
            "executed": True,
            "task_count": 2,
            "failed_count": 2,
            "dependency_errors": ["missing_python_module:doclayout_yolo"],
            "dependency_install_hint": "pip install 'mineru[pipeline]>=3.4.0,<4'",
        },
        "requirements": [
            {
                "key": "full_six_document_auto_eval",
                "status": "pending_full_eval",
                "detail": "missing",
            }
        ],
    }
    path = tmp_path / "auto_readiness_report.json"

    readiness.write_readiness_report(report, path)

    assert json.loads(path.read_text(encoding="utf-8")) == report
    markdown = path.with_suffix(".md").read_text(encoding="utf-8")
    assert "Status: **ready_for_full_auto_eval**" in markdown
    assert "## Blocked Requirements" in markdown
    assert "## Requirement Audit" in markdown
    assert "## MinerU Preconversion" in markdown
    assert "`missing_python_module:doclayout_yolo`" in markdown
    assert "`pip install 'mineru[pipeline]>=3.4.0,<4'`" in markdown
    assert "`full_six_document_auto_eval`: `pending_full_eval`" in markdown
