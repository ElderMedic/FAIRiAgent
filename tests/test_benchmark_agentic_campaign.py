"""Token-free agentic campaign planning tests."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from evaluation.benchmark.agentic_campaign import (
    build_agentic_campaign_plan,
    execute_agentic_campaign,
)
from evaluation.benchmark.contracts import load_manifest


FIXTURES = Path(__file__).parents[1] / "evaluation" / "benchmark" / "fixtures"


def _files(tmp_path: Path) -> tuple[Path, Path]:
    model = tmp_path / "model.env"
    base = tmp_path / "base.env"
    model.write_text("LLM_PROVIDER=fixture\nFAIRIFIER_LLM_MODEL=fixture\n", encoding="utf-8")
    base.write_text("FAIRIFIER_RETRIEVAL_MODE=hybrid\n", encoding="utf-8")
    return model, base


def test_agentic_plan_is_explicit_and_token_free(tmp_path: Path) -> None:
    manifest_path = FIXTURES / "benchmark_v2_smoke_manifest.json"
    manifest = load_manifest(manifest_path)
    model, base = _files(tmp_path)
    plan = build_agentic_campaign_plan(
        manifest,
        manifest_path,
        project_root=FIXTURES,
        output_dir=tmp_path / "runs",
        model_configs={"fixture_model": model},
        base_env=base,
        selected_conditions=["complete_fairiagent_system"],
    )
    assert plan["status"] == "ready"
    assert plan["scheduled_count"] == 3
    assert plan["planned_job_count"] == 3
    assert plan["model_or_api_calls_performed"] is False
    assert plan["approval_required_before_execution"] is True
    assert plan["jobs"][0]["execution_adapter"] == "fairifier.cli.process_with_merged_environment"


def test_agentic_plan_preserves_supplementary_paths(tmp_path: Path) -> None:
    manifest = json.loads((FIXTURES / "benchmark_v2_smoke_manifest.json").read_text())
    supplement = tmp_path / "supplement.md"
    supplement.write_text("supplement", encoding="utf-8")
    manifest["instances"][0]["supplementary_paths"] = [str(supplement)]
    model, base = _files(tmp_path)
    plan = build_agentic_campaign_plan(
        manifest,
        FIXTURES / "benchmark_v2_smoke_manifest.json",
        project_root=FIXTURES,
        output_dir=tmp_path / "runs",
        model_configs={"fixture_model": model},
        base_env=base,
        selected_conditions=["complete_fairiagent_system"],
    )
    assert plan["status"] == "ready"
    assert plan["jobs"][0]["supplementary_paths"] == [str(supplement)]


def test_agentic_plan_fails_closed_without_model_config(tmp_path: Path) -> None:
    manifest_path = FIXTURES / "benchmark_v2_smoke_manifest.json"
    manifest = load_manifest(manifest_path)
    _, base = _files(tmp_path)
    plan = build_agentic_campaign_plan(
        manifest,
        manifest_path,
        project_root=FIXTURES,
        output_dir=tmp_path / "runs",
        model_configs={},
        base_env=base,
        selected_conditions=["complete_fairiagent_system"],
    )
    assert plan["status"] == "blocked"
    assert any("missing model config" in error for error in plan["errors"])
    assert plan["model_or_api_calls_performed"] is False


def test_agentic_executor_requires_approval_before_writing_or_calling(tmp_path: Path) -> None:
    manifest_path = FIXTURES / "benchmark_v2_smoke_manifest.json"
    manifest = load_manifest(manifest_path)
    model, base = _files(tmp_path)
    plan = build_agentic_campaign_plan(
        manifest,
        manifest_path,
        project_root=FIXTURES,
        output_dir=tmp_path / "runs",
        model_configs={"fixture_model": model},
        base_env=base,
        selected_conditions=["complete_fairiagent_system"],
    )
    with pytest.raises(ValueError, match="approval_id"):
        execute_agentic_campaign(
            plan,
            manifest_path=manifest_path,
            project_root=FIXTURES,
            output_dir=tmp_path / "runs",
            approval_id="",
        )
    assert not (tmp_path / "runs" / "run_index.json").exists()
