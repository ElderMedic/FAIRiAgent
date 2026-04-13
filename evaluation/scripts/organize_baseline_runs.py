#!/usr/bin/env python3
"""Create a single organized baseline hub without moving original artifacts."""

from __future__ import annotations

import json
import shutil
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import List, Optional


REPO_ROOT = Path(__file__).resolve().parents[2]
OUT_ROOT = REPO_ROOT / "evaluation/baselines/organized"


@dataclass(frozen=True)
class Campaign:
    campaign_id: str
    model: str
    method: str
    prompt_style: str
    docset: str
    documents: List[str]
    n_runs_per_document: Optional[int]
    source_path: str
    has_evaluation_results: bool
    status: str
    notes: str


CURATED_CAMPAIGNS = [
    Campaign(
        campaign_id="qwen_flash__single_prompt__earthworm_biosensor_pomato__20260326",
        model="qwen-flash",
        method="baseline",
        prompt_style="single_prompt",
        docset="earthworm_biosensor_pomato",
        documents=["earthworm", "biosensor", "pomato"],
        n_runs_per_document=1,
        source_path="evaluation/harness/runs/presentation_phase1_baseline_qwenflash",
        has_evaluation_results=True,
        status="curated_campaign",
        notes="Current harness baseline campaign; same 3-document set used for current phase-1 workflow comparison.",
    ),
    Campaign(
        campaign_id="gpt_5_1__openai_api_call__earthworm_biosensor__20260130",
        model="gpt-5.1",
        method="baseline",
        prompt_style="few_shot_or_direct_api",
        docset="earthworm_biosensor",
        documents=["earthworm", "biosensor"],
        n_runs_per_document=10,
        source_path="evaluation/baselines/runs/openai_gpt5.1_20260130",
        has_evaluation_results=True,
        status="curated_campaign",
        notes="Older formal baseline batch with evaluation results.",
    ),
    Campaign(
        campaign_id="claude_haiku_4_5__few_shot_manual__earthworm__20260130",
        model="claude-haiku-4-5",
        method="baseline",
        prompt_style="few_shot_manual",
        docset="earthworm",
        documents=["earthworm"],
        n_runs_per_document=10,
        source_path="evaluation/baselines/runs/claude-haiku-4-5_20260130",
        has_evaluation_results=True,
        status="curated_campaign",
        notes="Manual Claude Code few-shot baseline campaign; earthworm only.",
    ),
    Campaign(
        campaign_id="gpt_5_1__openai_api_call__earthworm__adhoc",
        model="gpt-5.1",
        method="baseline",
        prompt_style="direct_api_call",
        docset="earthworm",
        documents=["earthworm"],
        n_runs_per_document=1,
        source_path="evaluation/runs/archive/openai_test",
        has_evaluation_results=False,
        status="ad_hoc_campaign",
        notes="Single-run ad hoc baseline; comparable in method, but not a full formal batch.",
    ),
]


def safe_link(src: Path, dst: Path) -> None:
    dst.parent.mkdir(parents=True, exist_ok=True)
    if dst.exists() or dst.is_symlink():
        dst.unlink()
    dst.symlink_to(src.resolve())


def reset_output_dir() -> None:
    if OUT_ROOT.exists():
        shutil.rmtree(OUT_ROOT)
    OUT_ROOT.mkdir(parents=True, exist_ok=True)


def build_links() -> None:
    for campaign in CURATED_CAMPAIGNS:
        src = REPO_ROOT / campaign.source_path
        if not src.exists():
            continue

        safe_link(src, OUT_ROOT / "all_campaigns" / campaign.campaign_id)
        safe_link(src, OUT_ROOT / "by_model" / campaign.model / campaign.campaign_id)
        safe_link(src, OUT_ROOT / "by_docset" / campaign.docset / campaign.campaign_id)
        for doc in campaign.documents:
            safe_link(src, OUT_ROOT / "by_document" / doc / campaign.campaign_id)


def build_raw_unresolved() -> List[str]:
    unresolved: List[str] = []
    raw_dirs = [
        REPO_ROOT / "evaluation/baselines/claude-code",
        REPO_ROOT / "evaluation/baselines/moltbot",
    ]
    for folder in raw_dirs:
        if not folder.exists():
            continue
        for path in sorted(folder.glob("*.json")):
            rel = str(path.relative_to(REPO_ROOT))
            unresolved.append(rel)
            safe_link(path, OUT_ROOT / "raw_unresolved" / folder.name / path.name)
    return unresolved


def write_manifest(unresolved: List[str]) -> None:
    manifest = {
        "description": "Unified baseline hub organized by model and document set. Uses symlinks; original artifacts remain in place.",
        "curated_campaigns": [asdict(c) for c in CURATED_CAMPAIGNS],
        "raw_unresolved_files": unresolved,
    }
    (OUT_ROOT / "baseline_manifest.json").write_text(
        json.dumps(manifest, indent=2),
        encoding="utf-8",
    )


def write_readme(unresolved: List[str]) -> None:
    lines = [
        "# Baseline Hub",
        "",
        "This directory is the single entry point for comparable baseline artifacts.",
        "",
        "It does not move original runs. Instead, it creates symlinks grouped in four ways:",
        "",
        "- `all_campaigns/`: one link per baseline campaign",
        "- `by_model/`: grouped by model name",
        "- `by_docset/`: grouped by input document set",
        "- `by_document/`: grouped by individual document",
        "",
        "## Curated comparable campaigns",
        "",
    ]
    for campaign in CURATED_CAMPAIGNS:
        lines.extend(
            [
                f"- `{campaign.campaign_id}`",
                f"  model: `{campaign.model}`",
                f"  docset: `{campaign.docset}`",
                f"  source: `{campaign.source_path}`",
                f"  status: `{campaign.status}`",
                f"  notes: {campaign.notes}",
            ]
        )

    lines.extend(
        [
            "",
            "## Raw unresolved baseline files",
            "",
            "These JSON files appear to be baseline outputs, but they do not yet carry enough structured run metadata to safely merge into the curated campaign set.",
            "",
        ]
    )
    for path in unresolved:
        lines.append(f"- `{path}`")

    lines.extend(
        [
            "",
            "## Manifest",
            "",
            "- `baseline_manifest.json` contains the same information in machine-readable form.",
        ]
    )
    (OUT_ROOT / "README.md").write_text("\n".join(lines), encoding="utf-8")


def main() -> None:
    reset_output_dir()
    build_links()
    unresolved = build_raw_unresolved()
    write_manifest(unresolved)
    write_readme(unresolved)
    print(f"Created baseline hub at {OUT_ROOT}")


if __name__ == "__main__":
    main()
