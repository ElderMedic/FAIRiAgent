"""Token-free development-pilot manifest builder.

The pilot is a separate manifest release derived from an approved benchmark
manifest.  It expands repetitions only for an explicitly selected non-held-out
split and never schedules held-out instances.  Execution remains the
approval-gated responsibility of the baseline/agentic runners.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Dict, Mapping, Sequence

from .contracts import load_manifest


class PilotManifestError(ValueError):
    """Raised when a pilot would violate the benchmark split contract."""


def build_pilot_manifest(
    manifest: Mapping[str, Any],
    *,
    pilot_split: str = "development",
    repetitions: int = 3,
    condition_ids: Sequence[str] | None = None,
    model_ids: Sequence[str] | None = None,
) -> Dict[str, Any]:
    """Build a reproducible pilot manifest without model/API access."""

    if not isinstance(pilot_split, str) or not pilot_split.strip():
        raise PilotManifestError("pilot_split must be a non-empty string")
    if not isinstance(repetitions, int) or isinstance(repetitions, bool) or repetitions < 1:
        raise PilotManifestError("repetitions must be a positive integer")
    if pilot_split in {"held_out", "verified"}:
        raise PilotManifestError("pilot cannot use held-out or verified split: %s" % pilot_split)

    instances = [
        dict(instance)
        for instance in manifest.get("instances", [])
        if isinstance(instance, Mapping) and instance.get("split") == pilot_split
    ]
    if not instances:
        raise PilotManifestError("no instances are assigned to pilot split: %s" % pilot_split)

    all_conditions = [
        dict(condition)
        for condition in manifest.get("conditions", [])
        if isinstance(condition, Mapping)
    ]
    all_models = [
        dict(model) for model in manifest.get("models", []) if isinstance(model, Mapping)
    ]
    requested_conditions = set(condition_ids) if condition_ids else {
        str(condition.get("condition_id")) for condition in all_conditions
    }
    requested_models = set(model_ids) if model_ids else {
        str(model.get("model_id")) for model in all_models
    }
    conditions = [
        condition
        for condition in all_conditions
        if condition.get("condition_id") in requested_conditions
    ]
    models = [model for model in all_models if model.get("model_id") in requested_models]
    unknown_conditions = requested_conditions - {
        str(condition.get("condition_id")) for condition in all_conditions
    }
    unknown_models = requested_models - {str(model.get("model_id")) for model in all_models}
    if unknown_conditions:
        raise PilotManifestError("unknown pilot conditions: " + ", ".join(sorted(unknown_conditions)))
    if unknown_models:
        raise PilotManifestError("unknown pilot models: " + ", ".join(sorted(unknown_models)))
    if not conditions:
        raise PilotManifestError("pilot condition selection is empty")
    if not models:
        raise PilotManifestError("pilot model selection is empty")

    scheduled_runs: list[Dict[str, Any]] = []
    for instance in instances:
        for condition in conditions:
            for model in models:
                for repetition in range(1, repetitions + 1):
                    scheduled_runs.append(
                        {
                            "run_id": "%s__%s__%s__r%02d"
                            % (
                                instance["instance_id"],
                                condition["condition_id"],
                                model["model_id"],
                                repetition,
                            ),
                            "instance_id": instance["instance_id"],
                            "condition_id": condition["condition_id"],
                            "model_id": model["model_id"],
                            "repetition": repetition,
                        }
                    )

    copied = dict(manifest)
    copied["benchmark_release"] = "%s.pilot_%s_r%02d" % (
        manifest.get("benchmark_release", "benchmark"),
        pilot_split,
        repetitions,
    )
    selected_model_ids = [str(model.get("model_id")) for model in models]
    if model_ids:
        copied["benchmark_release"] += ".models_%s" % "_".join(selected_model_ids)
    copied["instances"] = instances
    copied["conditions"] = conditions
    copied["models"] = models
    copied["scheduled_runs"] = scheduled_runs
    provenance = dict(manifest.get("provenance") or {})
    provenance.update(
        {
            "pilot_source_release": manifest.get("benchmark_release"),
            "pilot_split": pilot_split,
            "pilot_repetitions": repetitions,
            "pilot_model_ids": selected_model_ids,
            "pilot_model_selection_explicit": bool(model_ids),
            "held_out_excluded": True,
            "model_or_api_calls_performed": False,
            "repetitions_by_split": {pilot_split: repetitions},
        }
    )
    copied["provenance"] = provenance
    return copied


def main() -> int:
    parser = argparse.ArgumentParser(description="Build a token-free development pilot manifest")
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--pilot-split", default="development")
    parser.add_argument("--repetitions", type=int, default=3)
    parser.add_argument("--condition", action="append", default=[])
    parser.add_argument("--model", action="append", default=[])
    args = parser.parse_args()
    manifest = load_manifest(args.manifest)
    pilot = build_pilot_manifest(
        manifest,
        pilot_split=args.pilot_split,
        repetitions=args.repetitions,
        condition_ids=args.condition or None,
        model_ids=args.model or None,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    rendered = json.dumps(pilot, indent=2, ensure_ascii=False)
    args.output.write_text(rendered, encoding="utf-8")
    print(rendered)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
