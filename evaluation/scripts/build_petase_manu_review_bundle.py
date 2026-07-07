#!/usr/bin/env python3
"""Build a lean, non-technical review bundle for the PETase package (for Manu).

Produces exactly:
  share_for_manu_review/
    petase_package_review_dashboard.html   (single self-contained explainer page)
    petase_enzyme_engineering_package.json (the FAIR-DS package definition)
    expert_reference/
      original_annotations/                (all 19 expert-curated source JSON/TXT files)
      converted_ground_truth/               (all 19 papers converted to FAIR-DS package format)
    outputs/
      <paper_slug>/                        (the complete, unedited run folder for that paper:
                                             metadata.json, metadata_fairds.xlsx, workflow_report.*,
                                             processing_log.jsonl, llm_responses.json, runtime_config.json,
                                             full_output.log, cli_output.txt, extracted_document_content.txt,
                                             isa_values_json.json, eval_result.json, source_workspace/, etc.
                                             Nothing cherry-picked or summarized.)
    README.md                               (one short summary)
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
PKG_PATH = PROJECT_ROOT / "evaluation/config/packages/petase_enzyme_engineering_package.json"
DATA_DIR = PROJECT_ROOT / "evaluation/datasets/PETase_papers_json"
DASHBOARD_SRC = DATA_DIR / "petase_package_design_story.html"
SHARE_DIR = DATA_DIR / "share_for_manu_review"
VALUES_DIR = PROJECT_ROOT / "evaluation/datasets/annotated/values"

# Only complete (all-19-paper) FAIRiAgent run available for the corpus.
OUTPUTS_RUN_DIR = PROJECT_ROOT / "evaluation/runs/petase_full_run_20260619/deepseek_v4-pro_v1.4.0"


def original_annotation_files() -> list[Path]:
    """Same selection logic as convert_petase_to_fairds.py: 19 expert-annotation JSON files."""
    return sorted(f for f in DATA_DIR.iterdir() if f.is_file() and f.suffix == ".json")


def slug_from_values_filename(path: Path) -> str:
    # ground_truth_petase_<slug>_values.json -> petase_<slug>
    name = path.stem  # ground_truth_petase_<slug>_values
    name = name.removeprefix("ground_truth_").removesuffix("_values")
    return name


def main() -> None:
    if SHARE_DIR.exists():
        shutil.rmtree(SHARE_DIR)
    SHARE_DIR.mkdir(parents=True)

    # 1. Dashboard (single explainer page, self-contained)
    shutil.copy2(DASHBOARD_SRC, SHARE_DIR / "petase_package_review_dashboard.html")

    # 2. Package JSON
    shutil.copy2(PKG_PATH, SHARE_DIR / "petase_enzyme_engineering_package.json")

    # 3. Expert reference: originals + converted ground truth, for all 19 papers
    ref_dir = SHARE_DIR / "expert_reference"
    orig_dir = ref_dir / "original_annotations"
    conv_dir = ref_dir / "converted_ground_truth"
    orig_dir.mkdir(parents=True)
    conv_dir.mkdir(parents=True)

    for f in original_annotation_files():
        shutil.copy2(f, orig_dir / f.name)

    values_files = sorted(VALUES_DIR.glob("ground_truth_petase_*_values.json"))
    for f in values_files:
        shutil.copy2(f, conv_dir / f.name)

    # 4. Outputs: one run per paper, all 19 papers, complete run folder (no cherry-picking)
    outputs_dir = SHARE_DIR / "outputs"
    outputs_dir.mkdir(parents=True)
    missing = []
    for f in values_files:
        slug = slug_from_values_filename(f)
        src_dir = OUTPUTS_RUN_DIR / slug / "run_1"
        if not src_dir.exists():
            missing.append(slug)
            continue
        dest = outputs_dir / slug
        shutil.copytree(src_dir, dest)

    # 5. README
    readme = f"""# PETase Metadata Package — Review Request

Hi Manu,

This folder contains the FAIR-DS metadata "package" we built for PET hydrolase
enzyme-engineering papers, plus what our AI agent produces when it uses it.

**Start here:** open `petase_package_review_dashboard.html` in any web browser (just
double-click it, no internet needed). It walks through everything below with plain-language
explanations and examples — no technical background required. It also reports results
honestly, including a couple of things that did not work perfectly (see "Does it actually
help?" and the results table further down).

## What we'd like you to check

1. Does the package ({len(json.loads(PKG_PATH.read_text())['metadata'])} fields) fit the PETase / plastic-degradation topic?
2. Is it scientifically valid and realistic for wet-lab practice?
3. Are fields grouped/categorised correctly (paper → study → subject → materials → measurements)?
4. Do the example outputs actually capture what matters in a paper?
5. Is anything missing, or anything unnecessary?

## What's in this folder

- `petase_package_review_dashboard.html` — the main explainer (open this first)
- `petase_enzyme_engineering_package.json` — the package itself, machine-readable
- `expert_reference/original_annotations/` — our team's original notes on all 19 papers
- `expert_reference/converted_ground_truth/` — the same notes converted into the package format
- `outputs/<paper>/` — the complete, unedited output folder for that paper (all 19), from running the
  agent once each. Nothing cherry-picked:
  - `metadata_fairds.xlsx` — easiest to read
  - `metadata.json` — same data, machine-readable
  - everything else (workflow report, full run log, raw LLM responses, run configuration, etc.) is
    included as-is for full transparency, in case you want to see exactly how a result was produced

Thank you so much for taking the time to look this over!
"""
    (SHARE_DIR / "README.md").write_text(readme, encoding="utf-8")

    n_outputs = len(list(outputs_dir.iterdir()))
    print(f"Dashboard:  {SHARE_DIR / 'petase_package_review_dashboard.html'}")
    print(f"Package:    {SHARE_DIR / 'petase_enzyme_engineering_package.json'}")
    print(f"Expert ref: {len(original_annotation_files())} original + {len(values_files)} converted")
    print(f"Outputs:    {n_outputs} paper folders" + (f" (missing: {missing})" if missing else " (complete)"))
    print(f"README:     {SHARE_DIR / 'README.md'}")


if __name__ == "__main__":
    main()
