"""Approval-gated preflight runner tests; no model calls are made."""

from __future__ import annotations

import json
from pathlib import Path

from evaluation.benchmark.model_preflight_runner import (
    TOOL_NAME,
    _context_check,
    _extract_tool_args,
    _endpoint_model_present,
    main,
    retry_failed_preflight,
)


class _Message:
    tool_calls = [{"name": TOOL_NAME, "args": {"value": "ok"}}]
    additional_kwargs = {}


def test_tool_probe_arguments_are_validated() -> None:
    ok, args, detail = _extract_tool_args(_Message())
    assert ok is True
    assert args == {"value": "ok"}
    assert detail == "tool_and_structured_arguments_passed"


def test_context_check_uses_model_card_metadata() -> None:
    assert _context_check({"model_card": {"context_length": 262144}})[0] is True
    assert _context_check({"model_card": {"context_length": 4096}})[0] is False


def test_ollama_tag_check_returns_exact_model_metadata(monkeypatch) -> None:
    class _Response:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def read(self):
            return json.dumps(
                {"models": [{"name": "qwen3.6:27b", "digest": "sha256:test"}]}
            ).encode()

    monkeypatch.setattr(
        "urllib.request.urlopen",
        lambda *args, **kwargs: _Response(),
    )
    ok, detail, metadata = _endpoint_model_present("http://localhost:11434", "qwen3.6:27b")
    assert (ok, detail) == (True, "ollama_tags_passed")
    assert metadata == {"name": "qwen3.6:27b", "digest": "sha256:test"}


def test_runner_dry_run_requires_no_approval_or_model_calls(tmp_path: Path, monkeypatch) -> None:
    inventory = {"candidates": []}
    plan = {"jobs": [{"model_id": "m", "instance_id": "d", "repetition": 1}]}
    inventory_path = tmp_path / "inventory.json"
    plan_path = tmp_path / "plan.json"
    output_path = tmp_path / "dry.json"
    inventory_path.write_text(json.dumps(inventory))
    plan_path.write_text(json.dumps(plan))
    monkeypatch.setattr(
        "sys.argv",
        [
            "model_preflight_runner",
            "--inventory",
            str(inventory_path),
            "--preflight-plan",
            str(plan_path),
            "--output",
            str(output_path),
        ],
    )
    assert main() == 0
    result = json.loads(output_path.read_text())
    assert result["status"] == "dry_run"
    assert result["model_or_api_calls_performed"] is False


def test_retry_failed_preflight_preserves_denominator_and_replaces_only_failed_job(monkeypatch) -> None:
    inventory = {"candidates": []}
    plan = {
        "schema_version": "fairiagent.model_preflight_plan.v2",
        "jobs": [
            {"model_id": "m", "instance_id": "ok", "repetition": 1},
            {"model_id": "m", "instance_id": "failed", "repetition": 1},
        ],
    }
    previous = [
        {"model_id": "m", "instance_id": "ok", "repetition": 1, "status": "passed"},
        {"model_id": "m", "instance_id": "failed", "repetition": 1, "status": "failed"},
    ]

    def fake_execute(inventory, retry_plan, **kwargs):
        assert [job["instance_id"] for job in retry_plan["jobs"]] == ["failed"]
        return {
            "records": [
                {
                    "model_id": "m",
                    "instance_id": "failed",
                    "repetition": 1,
                    "status": "passed",
                }
            ],
            "model_or_api_calls_performed": True,
        }

    monkeypatch.setattr(
        "evaluation.benchmark.model_preflight_runner.execute_preflight",
        fake_execute,
    )
    result = retry_failed_preflight(
        inventory,
        plan,
        previous,
        model_config_dir=Path("."),
        approval_id="researcher-approved:fixture",
    )
    assert result["retry_job_count"] == 1
    assert result["retry_mode"] == "failed_jobs_only_preserve_original_denominator"
    assert [record["status"] for record in result["records"]] == ["passed", "passed"]
