#!/usr/bin/env python3
"""Prepare the PETase benchmark for FAIRiAgent evaluation (one-shot pipeline)."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[2]
SCRIPTS = Path(__file__).resolve().parent
RAW_DIR = PROJECT_ROOT / "evaluation" / "datasets" / "raw" / "petase_enzyme_engineering"
VALUES_DIR = PROJECT_ROOT / "evaluation" / "datasets" / "annotated" / "values"
FILTERED_PATH = PROJECT_ROOT / "evaluation/datasets/annotated/ground_truth_filtered.json"
PETASE_ONLY_PATH = PROJECT_ROOT / "evaluation/datasets/annotated/ground_truth_petase_only.json"
PACKAGE_PATH = PROJECT_ROOT / "evaluation/config/packages/pet_hydrolase_enzyme_engineering_package.json"

# Papers with PDF but no expert GT — excluded from benchmark
EXCLUDED_DOCUMENT_IDS = {"unknown_for_manu_petase_papers_no_1"}


def run_step(label: str, script_name: str) -> None:
    script = SCRIPTS / script_name
    print(f"\n{'=' * 70}\n{label}\n{'=' * 70}")
    result = subprocess.run(
        [sys.executable, str(script)],
        cwd=str(PROJECT_ROOT),
        check=False,
    )
    if result.returncode != 0:
        raise SystemExit(f"Step failed: {script_name} (exit {result.returncode})")


def build_petase_only_index() -> dict[str, Any]:
    master = json.loads(FILTERED_PATH.read_text(encoding="utf-8"))
    petase_docs = [
        doc
        for doc in master.get("documents", [])
        if doc.get("document_id", "").startswith("petase_")
        and doc.get("document_id") not in EXCLUDED_DOCUMENT_IDS
    ]
    petase_only = {
        "description": "PETase enzyme engineering benchmark (19 papers with expert GT)",
        "dataset_id": "petase_enzyme_engineering",
        "generated_by": "prepare_petase_benchmark.py",
        "documents": petase_docs,
    }
    PETASE_ONLY_PATH.write_text(
        json.dumps(petase_only, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    return petase_only


def validate_benchmark(petase_docs: list[dict[str, Any]]) -> list[str]:
    issues: list[str] = []
    value_files = sorted(VALUES_DIR.glob("ground_truth_petase_*_values.json"))
    value_ids = {f.stem.replace("ground_truth_", "").replace("_values", "") for f in value_files}

    filtered_ids = {doc["document_id"] for doc in petase_docs}
    missing_gt = filtered_ids - value_ids
    missing_filtered = value_ids - filtered_ids
    if missing_gt:
        issues.append(f"Filtered index missing values files: {sorted(missing_gt)}")
    if missing_filtered:
        issues.append(f"Values files not in filtered index: {sorted(missing_filtered)}")

    for doc in petase_docs:
        doc_id = doc["document_id"]
        rel_path = doc.get("document_path", "")
        pdf_path = PROJECT_ROOT / rel_path if rel_path else None
        if not pdf_path or not pdf_path.exists():
            issues.append(f"{doc_id}: PDF missing at {rel_path}")
            continue
        gt_path = VALUES_DIR / f"ground_truth_{doc_id}_values.json"
        if not gt_path.exists():
            issues.append(f"{doc_id}: values GT missing at {gt_path.name}")

    if not PACKAGE_PATH.exists():
        issues.append(f"Package definition missing: {PACKAGE_PATH}")

    manifest_path = RAW_DIR / "paper_manifest.json"
    if manifest_path.exists():
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        eval_papers = [
            p for p in manifest.get("papers", [])
            if p.get("has_ground_truth_json") and p.get("slug") not in EXCLUDED_DOCUMENT_IDS
        ]
        if len(eval_papers) != len(petase_docs):
            issues.append(
                f"Manifest eval papers ({len(eval_papers)}) != filtered PETase docs ({len(petase_docs)})"
            )

    return issues


def print_run_commands(n_papers: int) -> None:
    env_file = PROJECT_ROOT / "evaluation/config/env.evaluation"
    model_example = PROJECT_ROOT / "evaluation/config/model_configs/deepseek_v4-pro_v1.4.0.env"
    print(f"\n{'=' * 70}")
    print("Ready to run FAIRiAgent evaluation on PETase benchmark")
    print(f"{'=' * 70}")
    print(f"Papers in benchmark: {n_papers}")
    print(f"Ground truth index:  {PETASE_ONLY_PATH.relative_to(PROJECT_ROOT)}")
    print(f"Values directory:    {VALUES_DIR.relative_to(PROJECT_ROOT)}/ground_truth_petase_*_values.json")
    print()
    print("Smoke test (single paper via batch runner):")
    print(
        "  mamba run -n FAIRiAgent python evaluation/scripts/run_petase_evaluation.py \\\n"
        f"    --env-file {env_file.relative_to(PROJECT_ROOT)} \\\n"
        f"    --model-config {model_example.relative_to(PROJECT_ROOT)} \\\n"
        "    --include-documents petase_10_1038_s41586-020-2149-4 \\\n"
        "    --output-dir evaluation/runs/petase_smoke --repeats 1 --workers 1 --timeout 7200"
    )
    print()
    print("Smoke test (direct CLI):")
    print(
        "  mamba run -n FAIRiAgent python -m fairifier.cli process \\\n"
        "    evaluation/datasets/raw/petase_enzyme_engineering/papers/10_1038_s41586-020-2149-4/paper.pdf \\\n"
        f"    --env-file {model_example.relative_to(PROJECT_ROOT)} \\\n"
        "    --output-dir output/petase_smoke \\\n"
        "    --project-id petase_smoke_nature2020"
    )
    print()
    print("Full PETase batch evaluation:")
    print(
        "  mamba run -n FAIRiAgent python evaluation/scripts/run_petase_evaluation.py \\\n"
        f"    --env-file {env_file.relative_to(PROJECT_ROOT)} \\\n"
        f"    --model-config {model_example.relative_to(PROJECT_ROOT)} \\\n"
        "    --repeats 1 --workers 1 --timeout 7200"
    )
    print()
    print("Value-level comparison (after a run):")
    print(
        "  mamba run -n FAIRiAgent python evaluation/scripts/compare_values_against_gt.py \\\n"
        "    evaluation/datasets/annotated/values/ground_truth_petase_10_1038_s41586-020-2149-4_values.json \\\n"
        "    output/petase_smoke --json"
    )


def main() -> None:
    run_step("[1/4] Organize raw PDFs and manifest", "organize_petase_dataset.py")
    run_step("[2/4] Convert expert JSON → FAIR-DS values GT", "convert_petase_to_fairds.py")
    run_step("[3/4] Register PETase papers in ground_truth_filtered.json", "update_filtered_with_petase.py")

    print(f"\n{'=' * 70}\n[4/4] Build PETase-only index and validate\n{'=' * 70}")
    petase_only = build_petase_only_index()
    n_papers = len(petase_only["documents"])
    print(f"✓ Wrote {PETASE_ONLY_PATH} ({n_papers} documents)")

    issues = validate_benchmark(petase_only["documents"])
    if issues:
        print("\n❌ Validation issues:")
        for issue in issues:
            print(f"  - {issue}")
        raise SystemExit(1)

    print("\n✅ PETase benchmark validation passed")
    print_run_commands(n_papers)


if __name__ == "__main__":
    main()
