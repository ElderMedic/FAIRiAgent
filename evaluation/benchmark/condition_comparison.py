"""Token-free audits for publication condition definitions.

Score-file comparisons are only interpretable when paired conditions differ in
the declared capability group.  This module checks that contract before any
model run is scheduled; it does not inspect outputs or contact services.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Dict, Mapping, Sequence

from .contracts import load_manifest


PROGRESSIVE_LADDER: tuple[tuple[str, str, tuple[str, ...]], ...] = (
    (
        "single_pass_structured_extraction",
        "standards_guided_extraction",
        ("standards_context",),
    ),
    (
        "standards_guided_extraction",
        "retrieval_assisted_extraction",
        ("document_retrieval",),
    ),
    (
        "retrieval_assisted_extraction",
        "iterative_agentic_extraction",
        ("planning_and_specialized_roles", "critique_and_revision"),
    ),
    (
        "iterative_agentic_extraction",
        "complete_fairiagent_system",
        ("deterministic_correction",),
    ),
)

FOCUSED_ABLATIONS: tuple[tuple[str, str, tuple[str, ...]], ...] = (
    (
        "lexical_retrieval_control",
        "hybrid_retrieval_system",
        ("retrieval_method",),
    ),
    (
        "hybrid_retrieval_system",
        "hybrid_retrieval_with_deterministic_metadata_correction",
        ("deterministic_correction",),
    ),
)


def _condition_map(manifest: Mapping[str, Any]) -> Dict[str, Mapping[str, Any]]:
    return {
        str(condition.get("condition_id")): condition
        for condition in manifest.get("conditions", [])
        if isinstance(condition, Mapping) and condition.get("condition_id")
    }


def _settings(condition: Mapping[str, Any]) -> Dict[str, Any]:
    value = condition.get("component_settings")
    return dict(value) if isinstance(value, Mapping) else {}


def compare_condition_definitions(
    manifest: Mapping[str, Any],
    left_condition_id: str,
    right_condition_id: str,
) -> Dict[str, Any]:
    """Return a field-level component diff for two manifest conditions."""

    conditions = _condition_map(manifest)
    missing = [
        condition_id
        for condition_id in (left_condition_id, right_condition_id)
        if condition_id not in conditions
    ]
    if missing:
        raise ValueError("unknown condition(s): " + ", ".join(missing))
    left = _settings(conditions[left_condition_id])
    right = _settings(conditions[right_condition_id])
    keys = sorted(set(left) | set(right))
    changed = {
        key: {"left": left.get(key), "right": right.get(key)}
        for key in keys
        if left.get(key) != right.get(key)
    }
    return {
        "left_condition_id": left_condition_id,
        "right_condition_id": right_condition_id,
        "changed_component_settings": changed,
        "changed_keys": list(changed),
    }


def audit_condition_pairs(
    manifest: Mapping[str, Any],
    pairs: Sequence[tuple[str, str, Sequence[str]]],
) -> Dict[str, Any]:
    """Audit expected component changes for a list of condition pairs."""

    audits = []
    errors: list[str] = []
    for left_id, right_id, expected_keys in pairs:
        try:
            diff = compare_condition_definitions(manifest, left_id, right_id)
        except ValueError as exc:
            errors.append(str(exc))
            continue
        expected = sorted(set(expected_keys))
        actual = sorted(diff["changed_keys"])
        if actual != expected:
            errors.append(
                "%s -> %s changes %s; expected exactly %s"
                % (left_id, right_id, actual, expected)
            )
        audits.append(
            {
                **diff,
                "expected_changed_keys": expected,
                "status": "passed" if actual == expected else "failed",
            }
        )
    return {
        "schema_version": "fairiagent.condition_comparison.v1",
        "status": "passed" if not errors else "failed",
        "errors": errors,
        "pairs": audits,
        "model_or_api_calls_performed": False,
    }


def audit_progressive_ladder(manifest: Mapping[str, Any]) -> Dict[str, Any]:
    """Check the five-condition progressive comparison ladder."""

    return audit_condition_pairs(manifest, PROGRESSIVE_LADDER)


def audit_focused_ablations(manifest: Mapping[str, Any]) -> Dict[str, Any]:
    """Check lexical/hybrid and deterministic-correction focused pairs."""

    return audit_condition_pairs(manifest, FOCUSED_ABLATIONS)


def main() -> int:
    parser = argparse.ArgumentParser(description="Audit v2 condition component differences")
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    manifest = load_manifest(args.manifest)
    result = {
        "schema_version": "fairiagent.condition_comparison.v1",
        "progressive_ladder": audit_progressive_ladder(manifest),
        "focused_ablations": audit_focused_ablations(manifest),
        "model_or_api_calls_performed": False,
    }
    result["status"] = (
        "passed"
        if result["progressive_ladder"]["status"] == "passed"
        and result["focused_ablations"]["status"] == "passed"
        else "failed"
    )
    rendered = json.dumps(result, indent=2, ensure_ascii=False)
    if args.output:
        args.output.write_text(rendered, encoding="utf-8")
    print(rendered)
    return 0 if result["status"] == "passed" else 2


if __name__ == "__main__":
    raise SystemExit(main())
