"""Token-free benchmark budget tests."""

from pathlib import Path

from evaluation.benchmark.budget import estimate_manifest_budget
from evaluation.benchmark.contracts import load_manifest


FIXTURES = Path(__file__).parents[1] / "evaluation" / "benchmark" / "fixtures"


def test_budget_estimate_is_explicit_and_does_not_call_models() -> None:
    manifest_path = FIXTURES / "benchmark_v2_smoke_manifest.json"
    manifest = load_manifest(manifest_path)
    estimate = estimate_manifest_budget(
        manifest,
        manifest_path,
        project_root=FIXTURES,
        condition_calls={"complete_fairiagent_system": 3},
        output_tokens_per_call=100,
        fixed_prompt_characters=0,
    )
    assert estimate["scheduled_run_count"] == 3
    assert estimate["estimated_llm_calls"] == 9
    assert estimate["estimated_total_tokens"] > 0
    assert estimate["estimated_cost_usd"] is None
    assert estimate["model_or_api_calls_performed"] is False
