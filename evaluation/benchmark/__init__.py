"""Versioned FAIRiAgent benchmark contracts and scoring utilities."""

from .contracts import ManifestValidationError, load_manifest, load_result, validate_manifest
from .attach_evaluator import attach_evaluator_results
from .condition_comparison import (
    audit_focused_ablations,
    audit_progressive_ladder,
    compare_condition_definitions,
)
from .context_snapshots import (
    ContextSnapshotError,
    manifest_with_context_paths,
    materialize_context_snapshots,
)
from .current_evaluator import evaluate_current_run
from .evaluator_adapter import (
    EvaluatorAdapterError,
    adapt_evaluator_batch_record,
    adapt_evaluator_record,
)
from .legacy_adapter import adapt_legacy_run
from .output_validation import validate_isa_projection_round_trip, validate_output_payload
from .model_preflight import validate_preflight_plan_coverage
from .run_index import validate_run_index
from .run_index import merge_run_indices
from .scorer import (
    BenchmarkProfile,
    ScoreError,
    score_batch,
    score_run,
)
from .statistics import (
    bootstrap_mean_interval,
    paired_comparison,
    pareto_frontier,
    stratified_axis_summary,
)

__all__ = [
    "BenchmarkProfile",
    "attach_evaluator_results",
    "build_agentic_campaign_plan",
    "audit_focused_ablations",
    "audit_progressive_ladder",
    "compare_condition_definitions",
    "ContextSnapshotError",
    "manifest_with_context_paths",
    "materialize_context_snapshots",
    "EvaluatorAdapterError",
    "adapt_legacy_run",
    "adapt_evaluator_batch_record",
    "adapt_evaluator_record",
    "evaluate_current_run",
    "validate_isa_projection_round_trip",
    "validate_output_payload",
    "PilotManifestError",
    "build_pilot_manifest",
    "validate_preflight_plan_coverage",
    "execute_preflight",
    "ModelPanelError",
    "freeze_model_panel",
    "validate_run_index",
    "merge_run_indices",
    "bootstrap_mean_interval",
    "paired_comparison",
    "pareto_frontier",
    "stratified_axis_summary",
    "ManifestValidationError",
    "ScoreError",
    "load_manifest",
    "load_result",
    "score_batch",
    "score_run",
    "validate_manifest",
]


def execute_preflight(*args, **kwargs):
    """Lazily expose the approval-gated preflight executor.

    Keeping the import lazy avoids ``runpy``'s module-already-imported warning
    when the runner is invoked with ``python -m``.
    """

    from .model_preflight_runner import execute_preflight as _execute_preflight

    return _execute_preflight(*args, **kwargs)


def __getattr__(name):
    """Lazily expose entry-point symbols for ``python -m`` invocations."""

    if name in {"ModelPanelError", "freeze_model_panel"}:
        from .model_panel import ModelPanelError, freeze_model_panel

        return {"ModelPanelError": ModelPanelError, "freeze_model_panel": freeze_model_panel}[name]
    if name in {"PilotManifestError", "build_pilot_manifest"}:
        from .pilot import PilotManifestError, build_pilot_manifest

        return {"PilotManifestError": PilotManifestError, "build_pilot_manifest": build_pilot_manifest}[name]
    if name == "build_agentic_campaign_plan":
        from .agentic_campaign import build_agentic_campaign_plan

        return build_agentic_campaign_plan
    raise AttributeError(name)
