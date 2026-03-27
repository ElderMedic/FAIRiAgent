#!/usr/bin/env python3
"""Organize latest FAIRiAgent harness runs by model and dataset without moving originals."""

from __future__ import annotations

import json
import shutil
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Dict, Iterable, List, Optional


REPO_ROOT = Path(__file__).resolve().parents[2]
RUNS_ROOT = REPO_ROOT / "evaluation/harness/runs"
OUT_ROOT = REPO_ROOT / "evaluation/harness/organized"


@dataclass(frozen=True)
class HarnessCampaign:
    campaign_id: str
    model: str
    workflow: str
    dataset: str
    documents: List[str]
    source_path: str
    source_batch: str
    n_completed_runs: int
    has_batch_evaluation_results: bool
    notes: str


MODEL_ALIASES = {
    "baseline_qwen_flash_presentation": "qwen-flash",
    "presentation_qwen_flash": "qwen-flash",
    "presentation_openai_gpt54_traced": "gpt-5.4",
    "presentation_qwen_max_traced": "qwen3-max",
    "presentation_gemini_31_pro": "gemini-3.1-pro-preview",
    "presentation_ollama_qwen35_35b_mem0_mineru": "qwen3.5:35b",
    "presentation_ollama_qwen35_9b_mem0_mineru": "qwen3.5:9b",
    "presentation_claude_opus46_mem0_mineru": "claude-opus-4-6",
    "presentation_claude_opus46": "claude-opus-4-6",
    "presentation_claude_sonnet4_traced": "claude-sonnet-4-6",
    "presentation_claude_sonnet46": "claude-sonnet-4-6",
}


def slug(value: str) -> str:
    chars = []
    for ch in value.lower():
        if ch.isalnum():
            chars.append(ch)
        else:
            chars.append("_")
    text = "".join(chars).strip("_")
    while "__" in text:
        text = text.replace("__", "_")
    return text


def safe_link(src: Path, dst: Path) -> None:
    dst.parent.mkdir(parents=True, exist_ok=True)
    if dst.exists() or dst.is_symlink():
        dst.unlink()
    dst.symlink_to(src.resolve())


def reset_output_dir() -> None:
    if OUT_ROOT.exists():
        shutil.rmtree(OUT_ROOT)
    OUT_ROOT.mkdir(parents=True, exist_ok=True)


def discover_campaigns() -> List[HarnessCampaign]:
    campaigns: List[HarnessCampaign] = []

    for batch_dir in sorted(RUNS_ROOT.iterdir()):
        if not batch_dir.is_dir():
            continue

        outputs_dir = batch_dir / "outputs"
        if not outputs_dir.exists():
            continue

        for config_dir in sorted(outputs_dir.iterdir()):
            if not config_dir.is_dir():
                continue

            metadata_files = sorted(config_dir.rglob("metadata_json.json"))
            if not metadata_files:
                continue

            docs = sorted({path.parent.parent.name for path in metadata_files})
            dataset = "_".join(docs)
            model = MODEL_ALIASES.get(config_dir.name, config_dir.name)
            workflow = "baseline" if "baseline" in config_dir.name.lower() else "fairiagent"

            campaign_id = slug(f"{model}__{workflow}__{dataset}")
            has_eval = (
                (batch_dir / "results" / "evaluation_results.json").exists()
                or (batch_dir / "evaluation_results.json").exists()
            )

            notes = []
            if workflow == "baseline":
                notes.append("single-prompt / baseline-style run")
            else:
                notes.append("agentic FAIRiAgent workflow")
            if has_eval:
                notes.append("batch-level evaluation results available")
            campaigns.append(
                HarnessCampaign(
                    campaign_id=campaign_id,
                    model=model,
                    workflow=workflow,
                    dataset=dataset,
                    documents=docs,
                    source_path=str(config_dir.relative_to(REPO_ROOT)),
                    source_batch=batch_dir.name,
                    n_completed_runs=len(metadata_files),
                    has_batch_evaluation_results=has_eval,
                    notes="; ".join(notes),
                )
            )

    return campaigns


def build_links(campaigns: Iterable[HarnessCampaign]) -> None:
    for campaign in campaigns:
        src = REPO_ROOT / campaign.source_path
        safe_link(src, OUT_ROOT / "all_campaigns" / campaign.campaign_id)
        safe_link(src, OUT_ROOT / "by_model" / slug(campaign.model) / campaign.campaign_id)
        safe_link(src, OUT_ROOT / "by_dataset" / campaign.dataset / campaign.campaign_id)
        for doc in campaign.documents:
            safe_link(src, OUT_ROOT / "by_document" / doc / campaign.campaign_id)


def write_manifest(campaigns: List[HarnessCampaign]) -> None:
    manifest = {
        "description": "Unified latest-harness hub organized by model and dataset. Uses symlinks; original harness runs remain in place.",
        "campaigns": [asdict(c) for c in campaigns],
    }
    (OUT_ROOT / "harness_manifest.json").write_text(
        json.dumps(manifest, indent=2),
        encoding="utf-8",
    )


def write_readme(campaigns: List[HarnessCampaign]) -> None:
    lines = [
        "# Harness Hub",
        "",
        "This is the single entry point for the latest FAIRiAgent harness runs.",
        "",
        "The organization ignores phase labels and groups runs by:",
        "",
        "- `all_campaigns/`: one entry per model × workflow × dataset combination",
        "- `by_model/`: all harness campaigns for the same model",
        "- `by_dataset/`: all campaigns using the same input document set",
        "- `by_document/`: all campaigns that include a given document",
        "",
        "Original run directories under `evaluation/harness/runs/` are not moved.",
        "",
        "## Campaigns",
        "",
    ]

    for c in campaigns:
        lines.extend(
            [
                f"- `{c.campaign_id}`",
                f"  model: `{c.model}`",
                f"  workflow: `{c.workflow}`",
                f"  dataset: `{c.dataset}`",
                f"  documents: `{', '.join(c.documents)}`",
                f"  completed metadata outputs: `{c.n_completed_runs}`",
                f"  source: `{c.source_path}`",
                f"  source batch: `{c.source_batch}`",
                f"  batch evaluation results: `{c.has_batch_evaluation_results}`",
                f"  notes: {c.notes}",
            ]
        )

    lines.extend(
        [
            "",
            "## Manifest",
            "",
            "- `harness_manifest.json` contains the same information in machine-readable form.",
        ]
    )
    (OUT_ROOT / "README.md").write_text("\n".join(lines), encoding="utf-8")


def main() -> None:
    reset_output_dir()
    campaigns = discover_campaigns()
    build_links(campaigns)
    write_manifest(campaigns)
    write_readme(campaigns)
    print(f"Created harness hub at {OUT_ROOT}")


if __name__ == "__main__":
    main()
