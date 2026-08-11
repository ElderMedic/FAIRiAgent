"""Token-free call, token, cost, and stop-condition estimates."""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
from typing import Any, Dict, Mapping, Sequence

from .assets import resolve_manifest_path
from .contracts import load_manifest


def _read_content(path: Path) -> tuple[int, str]:
    """Return approximate character count and the method used."""

    if path.suffix.lower() == ".pdf":
        try:
            import fitz  # type: ignore

            with fitz.open(str(path)) as document:
                return sum(len(page.get_text()) for page in document), "pdf_text"
        except (ImportError, OSError, RuntimeError):
            return len(path.read_bytes()), "pdf_bytes_fallback"
    return len(path.read_text(encoding="utf-8", errors="replace")), "text"


def estimate_manifest_budget(
    manifest: Mapping[str, Any],
    manifest_path: Path,
    *,
    project_root: Path,
    condition_calls: Mapping[str, int] | None = None,
    output_tokens_per_call: int = 1_500,
    fixed_prompt_characters: int = 2_000,
    price_table: Mapping[str, Mapping[str, float]] | None = None,
) -> Dict[str, Any]:
    """Estimate a manifest's lower-bound resource budget without execution.

    ``condition_calls`` is deliberately explicit because an agentic condition
    may make more than one model call per scheduled document-run. Missing price
    entries produce ``cost_usd: null`` rather than an invented price.
    """

    if output_tokens_per_call < 0 or fixed_prompt_characters < 0:
        raise ValueError("token and prompt estimates must be non-negative")
    call_multipliers = dict(condition_calls or {})
    for condition_id, count in call_multipliers.items():
        if not isinstance(count, int) or isinstance(count, bool) or count < 1:
            raise ValueError("condition call estimates must be positive integers: %s" % condition_id)

    instances = {item["instance_id"]: item for item in manifest.get("instances", [])}
    content_cache: Dict[str, Dict[str, Any]] = {}
    for instance_id, instance in instances.items():
        paths = {"source": instance.get("source_path")}
        for manifest_key, label in (
            ("standards_context_path", "standards_context"),
            ("retrieved_context_path", "retrieved_context"),
        ):
            if instance.get(manifest_key):
                paths[label] = instance[manifest_key]
        supplementary = instance.get("supplementary_paths") or []
        if not isinstance(supplementary, list):
            raise ValueError("%s.supplementary_paths must be a list" % instance_id)
        for index, value in enumerate(supplementary):
            if not isinstance(value, str) or not value:
                raise ValueError("%s.supplementary_paths[%d] is invalid" % (instance_id, index))
            paths["supplementary_%d" % index] = value
        chars = 0
        methods: Dict[str, str] = {}
        for label, value in paths.items():
            if not isinstance(value, str) or not value:
                raise FileNotFoundError("%s.%s path is missing" % (instance_id, label))
            path = resolve_manifest_path(value, manifest_path, project_root)
            if not path.is_file():
                raise FileNotFoundError("%s.%s file does not exist: %s" % (instance_id, label, path))
            count, method = _read_content(path)
            chars += count
            methods[label] = method
        prompt_characters = chars + fixed_prompt_characters
        content_cache[instance_id] = {
            "document_characters": chars,
            "prompt_characters": prompt_characters,
            "estimated_input_tokens_per_call": max(1, math.ceil(prompt_characters / 4)),
            "asset_read_methods": methods,
        }

    jobs: list[Dict[str, Any]] = []
    total_calls = 0
    total_input_tokens = 0
    total_output_tokens = 0
    cost_usd: float | None = 0.0
    pricing_complete = True
    for run in manifest.get("scheduled_runs", []):
        instance_id = run["instance_id"]
        condition_id = run["condition_id"]
        model_id = run["model_id"]
        calls = int(call_multipliers.get(condition_id, 1))
        input_tokens = content_cache[instance_id]["estimated_input_tokens_per_call"] * calls
        output_tokens = output_tokens_per_call * calls
        total_calls += calls
        total_input_tokens += input_tokens
        total_output_tokens += output_tokens
        price = (price_table or {}).get(model_id)
        if not isinstance(price, Mapping):
            pricing_complete = False
            cost_usd = None
        elif cost_usd is not None:
            input_rate = float(price.get("input_usd_per_million", 0.0))
            output_rate = float(price.get("output_usd_per_million", 0.0))
            cost_usd += input_tokens * input_rate / 1_000_000
            cost_usd += output_tokens * output_rate / 1_000_000
        jobs.append(
            {
                "run_id": run["run_id"],
                "instance_id": instance_id,
                "condition_id": condition_id,
                "model_id": model_id,
                "repetition": run["repetition"],
                "estimated_llm_calls": calls,
                "estimated_input_tokens": input_tokens,
                "estimated_output_tokens": output_tokens,
            }
        )
    return {
        "schema_version": "fairiagent.benchmark_budget.v2",
        "scheduled_run_count": len(jobs),
        "estimated_llm_calls": total_calls,
        "estimated_input_tokens": total_input_tokens,
        "estimated_output_tokens": total_output_tokens,
        "estimated_total_tokens": total_input_tokens + total_output_tokens,
        "estimated_cost_usd": cost_usd,
        "pricing_complete": pricing_complete,
        "model_or_api_calls_performed": False,
        "assumptions": {
            "input_tokens_per_character": 0.25,
            "fixed_prompt_characters": fixed_prompt_characters,
            "output_tokens_per_call": output_tokens_per_call,
            "condition_calls": call_multipliers,
            "document_assets": content_cache,
        },
        "stop_conditions": [
            "do not execute if the approved split or model panel differs from this manifest",
            "stop on any asset checksum mismatch before the first model call",
            "stop the batch when the observed failure rate exceeds the approved ceiling",
            "stop when estimated or observed cost exceeds the approved budget",
            "preserve every failure and missing run in the final denominator",
        ],
        "jobs": jobs,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Estimate benchmark calls/tokens/cost without model access")
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--project-root", type=Path, default=Path.cwd())
    parser.add_argument("--output", type=Path)
    parser.add_argument("--output-tokens-per-call", type=int, default=1_500)
    parser.add_argument("--fixed-prompt-characters", type=int, default=2_000)
    parser.add_argument("--condition-calls", type=Path, help="JSON object mapping condition_id to calls per run")
    parser.add_argument("--price-table", type=Path, help="JSON object mapping model_id to input/output USD per million")
    args = parser.parse_args()
    manifest = load_manifest(args.manifest)
    condition_calls = json.loads(args.condition_calls.read_text()) if args.condition_calls else None
    price_table = json.loads(args.price_table.read_text()) if args.price_table else None
    estimate = estimate_manifest_budget(
        manifest,
        args.manifest,
        project_root=args.project_root,
        condition_calls=condition_calls,
        output_tokens_per_call=args.output_tokens_per_call,
        fixed_prompt_characters=args.fixed_prompt_characters,
        price_table=price_table,
    )
    rendered = json.dumps(estimate, indent=2, ensure_ascii=False)
    if args.output:
        args.output.write_text(rendered, encoding="utf-8")
    print(rendered)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
