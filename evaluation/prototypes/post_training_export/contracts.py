"""Post-training export contracts derived from agent-tuning / preference literature.

What we need for local-model post-training (without touching FAIRiAgent runtime):

1. SFT (FireAct / AgentTuning style)
   - messages or prompt/completion with a *correct* target
   - provenance: model, run_id, operation, doc_id

2. Preference / DPO
   - prompt + chosen + rejected (same context, different answers)
   - for metadata fields: chosen = ground-truth value, rejected = model wrong value
   - optional trajectory preference: successful agent attempt vs failed attempt

3. Error profile / steer lab (J-lens)
   - typed mismatch with gt/pred snippets and optional swap candidates
   - does *not* require full prompts; works from evaluation_results alone

4. Trajectory index (Learning-from-Failure / FireAct)
   - pointers into existing run dirs (llm_responses, processing_log, metadata)
   - success label from eval + critic; full prompts may be absent in older runs

Provenance quality gate (critical for training readiness):
- full_prompt: llm_responses entry has serialized prompt messages
- response_only: have model response + GT, but not the original prompt
- field_pair_only: only gt/pred snippets from value_accuracy (still usable for DPO-lite)

References (design drivers, not dependencies):
- FireAct (Chen et al., 2023): trajectory SFT for agents
- Learning From Failure (Wang et al., 2024): keep negative trajectories with labels
- DPO / preference optimization: offline chosen/rejected pairs
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, TypedDict


ERROR_TYPES = (
    "value_wrong",
    "value_partial",
    "value_missing",
    "unsupported_fabrication",
    "entity_confusion_candidate",
    "product_confusion_candidate",
    "numeric_mixup_candidate",
)


class ErrorEvent(TypedDict, total=False):
    event_id: str
    doc_id: str
    model_config: str
    run_dir: str
    isa_sheet: str
    field_name: str
    status: str
    score: float
    gt_snippet: str
    pred_snippet: str
    error_type: str
    swap_from: Optional[str]
    swap_to: Optional[str]
    steer_polarity: str  # corrective | adversarial_demo
    provenance: str


class SFTExample(TypedDict, total=False):
    id: str
    doc_id: str
    model_config: str
    operation: str
    messages: List[Dict[str, str]]
    provenance: str
    source_run_dir: str


class DPOExample(TypedDict, total=False):
    id: str
    doc_id: str
    model_config: str
    field_name: str
    isa_sheet: str
    prompt: str
    chosen: str
    rejected: str
    provenance: str
    source_run_dir: str


class TrajectoryRecord(TypedDict, total=False):
    doc_id: str
    model_config: str
    run_dir: str
    success: Optional[bool]
    n_llm_calls: int
    has_full_prompts: bool
    operations: List[str]
    artifacts: Dict[str, bool]
    value_summary: Dict[str, Any]


def field_dpo_prompt(field_name: str, isa_sheet: str, context_hint: str = "") -> str:
    """Minimal preference prompt when original LLM prompt is unavailable."""
    hint = f"\nContext: {context_hint}" if context_hint else ""
    return (
        "Extract the FAIR metadata value for the following field from the document.\n"
        f"ISA sheet: {isa_sheet}\n"
        f"Field: {field_name}\n"
        "Return only the value string."
        f"{hint}"
    )


def heuristic_swap_candidates(gt: str, pred: str) -> Dict[str, Optional[str]]:
    """Cheap token-level hints for J-lens lab; not a full entity linker."""
    gt_t = (gt or "").strip()
    pred_t = (pred or "").strip()
    pred_l = pred_t.lower()
    if (
        not gt_t
        or not pred_t
        or gt_t.lower() == pred_l
        or pred_l in {"(not found)", "not found", "not specified", "n/a", "none"}
        or pred_l.startswith("(not")
    ):
        return {"swap_from": None, "swap_to": None}

    # Prefer first whitespace-delimited token that differs (single-token J-lens friendly).
    gt_toks = gt_t.replace(",", " ").split()
    pred_toks = pred_t.replace(",", " ").split()
    for a, b in zip(pred_toks, gt_toks):
        if a.lower() != b.lower() and a.isalpha() and b.isalpha():
            return {"swap_from": a, "swap_to": b}
    if pred_toks and gt_toks:
        return {"swap_from": pred_toks[0], "swap_to": gt_toks[0]}
    return {"swap_from": pred_t[:32], "swap_to": gt_t[:32]}


def classify_error_type(status: str, field_name: str, gt: str, pred: str) -> str:
    status_l = (status or "").lower()
    if status_l == "missing":
        return "value_missing"
    if status_l == "partial":
        return "value_partial"
    if status_l != "wrong":
        return f"value_{status_l}" if status_l else "value_wrong"

    fl = (field_name or "").lower()
    blob = f"{gt} {pred}".lower()
    if any(k in fl for k in ("organism", "taxonomy", "scientific name", "host")):
        return "entity_confusion_candidate"
    if any(k in blob for k in ("bhet", "mhet", "tpa", "terephthal")):
        return "product_confusion_candidate"
    if any(ch.isdigit() for ch in gt + pred) and any(
        k in fl for k in ("temperature", "time", "ph", "concentration")
    ):
        return "numeric_mixup_candidate"
    return "value_wrong"
