#!/usr/bin/env python3
"""Build a combined readiness report for the auto retrieval/repair rollout."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Dict, Optional

import merge_gate
import run_auto_eval


DEFAULT_READINESS_REPORT = (
    run_auto_eval.ARTIFACTS_DIR / "auto_readiness_report.json"
)
DEFAULT_PRECONVERT_REPORT = (
    run_auto_eval.ARTIFACTS_DIR / "mineru_preconvert_report.json"
)

REQUIRED_PROTOTYPE_FILES = (
    "README.md",
    "PLAN.md",
    "rules.py",
    "build_dataset.py",
    "train_decision_model.py",
    "export_shadow_predictions.py",
    "preconvert_mineru.py",
    "run_auto_eval.py",
    "merge_gate.py",
    "readiness_report.py",
)


def load_optional_json(path: Path) -> Optional[Dict[str, Any]]:
    if not path.exists():
        return None
    with path.open("r", encoding="utf-8") as handle:
        data = json.load(handle)
    if not isinstance(data, dict):
        raise ValueError(f"{path} did not contain a JSON object")
    return data


def readiness_status(
    *,
    preflight_passed: bool,
    auto_results_present: bool,
    gate_passed: bool,
) -> str:
    if not preflight_passed:
        return "blocked_preflight"
    if not auto_results_present:
        return "ready_for_full_auto_eval"
    if gate_passed:
        return "ready_to_merge"
    return "blocked_merge_gate"


def _check_by_name(preflight_report: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
    return {
        str(check.get("name")): check
        for check in preflight_report.get("checks", [])
        if isinstance(check, dict)
    }


def build_requirement_audit(
    *,
    preflight_report: Dict[str, Any],
    gate_report: Dict[str, Any],
    auto_results_present: bool,
    blocked_requirements: list[Dict[str, Any]],
) -> list[Dict[str, Any]]:
    """Map the rollout objective to concrete readiness evidence."""
    checks = _check_by_name(preflight_report)
    blocker_keys = {str(item.get("key")) for item in blocked_requirements}
    prototype_root = run_auto_eval.PROTOTYPE_ROOT
    missing_prototype_files = [
        name for name in REQUIRED_PROTOTYPE_FILES
        if not (prototype_root / name).exists()
    ]

    auto_config_checks = [
        "retrieval_mode_auto",
        "auto_repair_enabled",
        "auto_repair_apply_patches",
        "auto_repair_classifier_shadow_enabled",
    ]
    failed_auto_config = [
        name for name in auto_config_checks
        if not checks.get(name, {}).get("passed")
    ]
    service_blockers = [
        key for key in ("fair_ds", "mineru_service", "retrieval_embedding", "qdrant")
        if key in blocker_keys
    ]
    mineru_missing = "mineru_missing_docs" in blocker_keys
    mineru_preconvert_dependency_errors = [
        str(error)
        for item in blocked_requirements
        if item.get("key") == "mineru_preconvert_dependency"
        for error in item.get("dependency_errors", [])
    ]
    mineru_preconvert_install_hints = [
        str(item.get("install_hint"))
        for item in blocked_requirements
        if item.get("key") == "mineru_preconvert_dependency"
        and item.get("install_hint")
    ]
    gate_passed = bool(gate_report.get("passed"))

    requirements: list[Dict[str, Any]] = [
        {
            "key": "temporary_feature_workspace",
            "status": "passed" if not missing_prototype_files else "failed",
            "detail": (
                "prototype workspace contains classifier, auto eval, preconvert, "
                "readiness, and merge-gate tooling"
                if not missing_prototype_files
                else "prototype workspace is missing required files"
            ),
            "evidence": {
                "path": str(prototype_root),
                "missing_files": missing_prototype_files,
            },
        },
        {
            "key": "single_auto_pipeline_default",
            "status": "passed" if not failed_auto_config else "failed",
            "detail": (
                "generated auto env resolves to FAIRIFIER_RETRIEVAL_MODE=auto "
                "with deterministic repair enabled"
                if not failed_auto_config
                else "generated auto env does not satisfy required auto flags"
            ),
            "evidence": {
                "checks": {
                    name: checks.get(name, {}).get("detail")
                    for name in auto_config_checks
                },
                "failed_checks": failed_auto_config,
            },
        },
        {
            "key": "fallback_rules_and_classifier_shadow",
            "status": "passed",
            "detail": (
                "production acceptance is deterministic rules/guards first; "
                "classifier predictions are shadow-only provenance"
            ),
            "evidence": {
                "rules": str(prototype_root / "rules.py"),
                "shadow_export": str(prototype_root / "export_shadow_predictions.py"),
            },
        },
        {
            "key": "service_and_input_preconditions",
            "status": "passed" if bool(preflight_report.get("passed")) else "blocked",
            "detail": (
                "all service and input preflight checks passed"
                if bool(preflight_report.get("passed"))
                else "service or input preflight checks are blocking full auto eval"
            ),
            "evidence": {
                "service_blockers": service_blockers,
                "mineru_missing_docs": mineru_missing,
                "mineru_preconvert_dependency_errors": (
                    mineru_preconvert_dependency_errors
                ),
                "mineru_preconvert_install_hints": (
                    mineru_preconvert_install_hints
                ),
                "failed_checks": [
                    check.get("name")
                    for check in preflight_report.get("checks", [])
                    if isinstance(check, dict) and not check.get("passed")
                ],
            },
        },
        {
            "key": "fairds_metadata_artifact_contract",
            "status": (
                "passed"
                if gate_passed
                else ("pending_full_eval" if not auto_results_present else "failed")
            ),
            "detail": (
                "merge gate validated metadata.json, workflow_report.json, "
                "runtime_config.json, auto_repair_trace.json, isa_values_json.json, "
                "and metadata_fairds.xlsx for all target documents"
                if gate_passed
                else "artifact contract still needs a full auto run and merge-gate validation"
            ),
            "evidence": {
                "gate_status": gate_report.get("status"),
                "auto_results_present": auto_results_present,
            },
        },
        {
            "key": "full_six_document_auto_eval",
            "status": "passed" if auto_results_present else "pending_full_eval",
            "detail": (
                "full auto evaluation results are present"
                if auto_results_present
                else "full auto evaluation results are not present"
            ),
            "evidence": {
                "auto_results_present": auto_results_present,
            },
        },
        {
            "key": "shadow_tuned_synthesis_merge_gate",
            "status": "passed" if gate_passed else "pending_or_failed",
            "detail": (
                "auto run passed metric and artifact gates against Shadow/Tuned baselines"
                if gate_passed
                else "auto run has not yet passed metric and artifact gates"
            ),
            "evidence": {
                "gate_status": gate_report.get("status"),
                "failed_gate_checks": [
                    check.get("name")
                    for check in gate_report.get("checks", [])
                    if isinstance(check, dict)
                    and check.get("severity") == "fail"
                    and not check.get("passed")
                ],
            },
        },
    ]
    return requirements


def build_readiness_report(
    *,
    preflight_report: Dict[str, Any],
    gate_report: Dict[str, Any],
    auto_results_path: Path,
    auto_run_dir: Path,
    preconvert_report: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    auto_results_present = auto_results_path.exists()
    status = readiness_status(
        preflight_passed=bool(preflight_report.get("passed")),
        auto_results_present=auto_results_present,
        gate_passed=bool(gate_report.get("passed")),
    )
    failed_preflight = [
        check for check in preflight_report.get("checks", [])
        if not check.get("passed")
    ]
    failed_gate = [
        check for check in gate_report.get("checks", [])
        if check.get("severity") == "fail" and not check.get("passed")
    ]
    preflight_summary = preflight_report.get("summary") or run_auto_eval.summarize_preflight(
        preflight_report.get("checks", []),
    )
    blocked_requirements = list(preflight_summary.get("blocked_requirements") or [])
    if not auto_results_present:
        blocked_requirements.append(
            {
                "key": "auto_results",
                "detail": "full auto evaluation results are not present",
                "path": str(auto_results_path),
            }
        )
    preconvert_dependency_errors = []
    preconvert_install_hint = None
    for item in blocked_requirements:
        if item.get("key") != "mineru_preconvert_dependency":
            continue
        preconvert_dependency_errors.extend(
            str(error) for error in item.get("dependency_errors") or []
        )
        preconvert_install_hint = preconvert_install_hint or item.get("install_hint")
    if isinstance(preconvert_report, dict):
        preconvert_dependency_errors.extend(
            str(item) for item in preconvert_report.get("dependency_errors") or []
        )
        preconvert_install_hint = (
            preconvert_install_hint or preconvert_report.get("dependency_install_hint")
        )
    preconvert_dependency_errors = list(dict.fromkeys(preconvert_dependency_errors))
    if preconvert_dependency_errors:
        existing_dependency_blocker = next(
            (
                item
                for item in blocked_requirements
                if item.get("key") == "mineru_preconvert_dependency"
            ),
            None,
        )
        if existing_dependency_blocker is None:
            blocked_requirements.append(
                {
                    "key": "mineru_preconvert_dependency",
                    "detail": "local MinerU preconversion dependency is missing",
                    "dependency_errors": preconvert_dependency_errors,
                    "install_hint": preconvert_install_hint,
                }
            )
        else:
            existing_dependency_blocker["dependency_errors"] = (
                preconvert_dependency_errors
            )
            if preconvert_install_hint:
                existing_dependency_blocker["install_hint"] = preconvert_install_hint
    if status == "blocked_merge_gate":
        blocked_requirements.append(
            {
                "key": "merge_gate",
                "detail": "auto results exist but metric or artifact gate failed",
                "failed_checks": [check.get("name") for check in failed_gate],
            }
        )
    requirement_audit = build_requirement_audit(
        preflight_report=preflight_report,
        gate_report=gate_report,
        auto_results_present=auto_results_present,
        blocked_requirements=blocked_requirements,
    )
    return {
        "status": status,
        "passed": status == "ready_to_merge",
        "auto_results_path": str(auto_results_path),
        "auto_results_present": auto_results_present,
        "auto_run_dir": str(auto_run_dir),
        "blocked_requirements": blocked_requirements,
        "preflight": {
            "passed": bool(preflight_report.get("passed")),
            "summary": preflight_summary,
            "failed_checks": failed_preflight,
        },
        "merge_gate": {
            "status": gate_report.get("status"),
            "passed": bool(gate_report.get("passed")),
            "failed_checks": failed_gate,
        },
        "mineru_preconvert": {
            "report_path": str(DEFAULT_PRECONVERT_REPORT),
            "present": isinstance(preconvert_report, dict),
            "executed": preconvert_report.get("executed")
            if isinstance(preconvert_report, dict)
            else None,
            "task_count": preconvert_report.get("task_count")
            if isinstance(preconvert_report, dict)
            else None,
            "success_count": preconvert_report.get("success_count")
            if isinstance(preconvert_report, dict)
            else None,
            "failed_count": preconvert_report.get("failed_count")
            if isinstance(preconvert_report, dict)
            else None,
            "dependency_errors": preconvert_dependency_errors,
            "dependency_install_hint": preconvert_install_hint,
        },
        "requirements": requirement_audit,
        "next_action": next_action(
            status,
            failed_preflight=failed_preflight,
            preconvert_dependency_errors=preconvert_dependency_errors,
            preconvert_install_hint=preconvert_install_hint,
        ),
    }


def next_action(
    status: str,
    *,
    failed_preflight: Optional[list[Dict[str, Any]]] = None,
    preconvert_dependency_errors: Optional[list[str]] = None,
    preconvert_install_hint: Optional[str] = None,
) -> str:
    if status == "blocked_preflight":
        failed_preflight = failed_preflight or []
        preconvert_dependency_errors = preconvert_dependency_errors or []
        missing_mineru_docs = [
            str(check.get("name", "")).split(":", 1)[1]
            for check in failed_preflight
            if str(check.get("name", "")).startswith("document_mineru_preconverted:")
        ]
        service_names = {
            str(check.get("name", "")).split(":", 1)[1]
            for check in failed_preflight
            if str(check.get("name", "")).startswith("service_reachable:")
            and ":" in str(check.get("name", ""))
        }
        actions = []
        if preconvert_dependency_errors:
            hint = (
                f"; install with {preconvert_install_hint}"
                if preconvert_install_hint
                else ""
            )
            actions.append(
                "repair the FAIRiAgent environment so MinerU pipeline imports succeed "
                + "("
                + ", ".join(preconvert_dependency_errors)
                + ")"
                + hint
            )
        if "FAIR_DS_API_URL" in service_names:
            actions.append(
                "start FAIR-DS, for example `docker compose -f docker/compose.yaml up -d fairds`"
            )
        if "MINERU_SERVER_URL" in service_names or missing_mineru_docs:
            if missing_mineru_docs:
                actions.append(
                    "start MinerU or preconvert missing documents: "
                    + ", ".join(missing_mineru_docs)
                    + " with `mamba run -n FAIRiAgent python "
                    + "evaluation/prototypes/auto_repair_classifier/"
                    + "preconvert_mineru.py`"
                )
            else:
                actions.append("start MinerU or provide preconverted MinerU outputs")
        if "QDRANT" in service_names:
            actions.append("start Qdrant on the configured MEM0_QDRANT_HOST/PORT")
        if "RETRIEVAL_EMBEDDING" in service_names:
            embedding_details = [
                str(check.get("detail") or "")
                for check in failed_preflight
                if check.get("name") == "service_reachable:RETRIEVAL_EMBEDDING"
            ]
            endpoint = embedding_details[0].split(": unreachable", 1)[0] if embedding_details else ""
            actions.append(
                "start the configured retrieval embedding endpoint"
                + (f" ({endpoint})" if endpoint else "")
            )
        if not actions:
            actions.append("restore required services/configuration")
        return "; ".join(actions) + ", then rerun readiness."
    if status == "ready_for_full_auto_eval":
        return (
            "Run run_auto_eval.py --execute to produce the six-document auto "
            "evaluation results."
        )
    if status == "blocked_merge_gate":
        return (
            "Inspect auto_merge_gate_report.md and fix metric or artifact "
            "regressions before merge."
        )
    return "Merge readiness evidence is complete."


def render_markdown(report: Dict[str, Any]) -> str:
    lines = [
        "# Auto Readiness Report",
        "",
        f"Status: **{report.get('status')}**",
        "",
        f"- Auto results: `{report.get('auto_results_path')}`",
        f"- Auto results present: `{report.get('auto_results_present')}`",
        f"- Auto run dir: `{report.get('auto_run_dir')}`",
        f"- Next action: {report.get('next_action')}",
        "",
        "## Blocked Requirements",
        "",
    ]
    blockers = report.get("blocked_requirements") or []
    if blockers:
        for blocker in blockers:
            lines.append(f"- `{blocker.get('key')}`: {blocker.get('detail')}")
    else:
        lines.append("- None")
    preconvert = report.get("mineru_preconvert") or {}
    lines.extend(["", "## MinerU Preconversion", ""])
    lines.append(f"- Report present: `{preconvert.get('present', False)}`")
    if preconvert.get("present"):
        lines.append(f"- Executed: `{preconvert.get('executed')}`")
        lines.append(f"- Tasks: `{preconvert.get('task_count')}`")
        lines.append(f"- Failures: `{preconvert.get('failed_count')}`")
        errors = preconvert.get("dependency_errors") or []
        if errors:
            lines.append("- Dependency errors: " + ", ".join(f"`{err}`" for err in errors))
            if preconvert.get("dependency_install_hint"):
                lines.append(
                    f"- Dependency install: `{preconvert.get('dependency_install_hint')}`"
                )
    lines.extend(["", "## Requirement Audit", ""])
    requirements = report.get("requirements") or []
    if requirements:
        for item in requirements:
            lines.append(
                f"- `{item.get('key')}`: `{item.get('status')}` - {item.get('detail')}"
            )
    else:
        lines.append("- None")
    lines.extend([
        "",
        "## Failed Preflight Checks",
        "",
    ])
    failed_preflight = report.get("preflight", {}).get("failed_checks", [])
    if failed_preflight:
        for check in failed_preflight:
            lines.append(f"- `{check.get('name')}`: {check.get('detail')}")
    else:
        lines.append("- None")
    lines.extend(["", "## Failed Merge Gate Checks", ""])
    failed_gate = report.get("merge_gate", {}).get("failed_checks", [])
    if failed_gate:
        for check in failed_gate:
            lines.append(f"- `{check.get('name')}`: {check.get('detail')}")
    else:
        lines.append("- None")
    lines.append("")
    return "\n".join(lines)


def write_readiness_report(report: Dict[str, Any], output_path: Path) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    output_path.with_suffix(".md").write_text(
        render_markdown(report),
        encoding="utf-8",
    )


def parse_args(argv: Optional[list[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--skip-service-check",
        action="store_true",
        help="Inspect local files/configuration only; not valid merge evidence.",
    )
    parser.add_argument("--auto-results", type=Path, default=merge_gate.DEFAULT_AUTO)
    parser.add_argument("--auto-run-dir", type=Path)
    parser.add_argument("--preconvert-report", type=Path, default=DEFAULT_PRECONVERT_REPORT)
    parser.add_argument("--shadow-results", type=Path, default=merge_gate.DEFAULT_SHADOW)
    parser.add_argument("--tuned-results", type=Path, default=merge_gate.DEFAULT_TUNED)
    parser.add_argument("--output", type=Path, default=DEFAULT_READINESS_REPORT)
    return parser.parse_args(argv)


def main(argv: Optional[list[str]] = None) -> int:
    args = parse_args(argv)
    docs = run_auto_eval.read_target_documents(run_auto_eval.DEFAULT_BASELINE_METADATA)
    auto_model_config = run_auto_eval.write_auto_model_config(
        run_auto_eval.DEFAULT_BASE_MODEL_CONFIG,
        run_auto_eval.DEFAULT_AUTO_MODEL_CONFIG,
    )
    auto_eval_env = run_auto_eval.write_auto_eval_env(
        run_auto_eval.DEFAULT_EVAL_ENV,
        run_auto_eval.DEFAULT_AUTO_EVAL_ENV,
    )
    preflight = run_auto_eval.preflight_check(
        eval_env=auto_eval_env,
        model_config=auto_model_config,
        ground_truth=run_auto_eval.DEFAULT_GROUND_TRUTH,
        output_dir=run_auto_eval.DEFAULT_OUTPUT_DIR,
        documents=docs,
        # Merge-facing readiness must verify runtime dependencies by default.
        check_services=not args.skip_service_check,
    )
    run_auto_eval.write_preflight_report(
        preflight,
        run_auto_eval.DEFAULT_PREFLIGHT_REPORT,
    )

    shadow_results = merge_gate.load_json(args.shadow_results)
    tuned_results = merge_gate.load_json(args.tuned_results)
    auto_results = load_optional_json(args.auto_results)
    preconvert_report = load_optional_json(args.preconvert_report)
    auto_run_dir = args.auto_run_dir or merge_gate.resolve_run_dir(args.auto_results)
    gate_report = merge_gate.build_gate_report(
        auto_results=auto_results,
        shadow_results=shadow_results,
        tuned_results=tuned_results,
        auto_run_dir=auto_run_dir,
    )

    report = build_readiness_report(
        preflight_report=preflight,
        gate_report=gate_report,
        auto_results_path=args.auto_results,
        auto_run_dir=auto_run_dir,
        preconvert_report=preconvert_report,
    )
    write_readiness_report(report, args.output)
    print(f"wrote {args.output}")
    print(f"wrote {args.output.with_suffix('.md')}")
    print(f"status={report['status']}")
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
