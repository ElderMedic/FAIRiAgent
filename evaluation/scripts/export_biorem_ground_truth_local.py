#!/usr/bin/env python3
"""
Export ground_truth_biorem.local.json from BIOREM_Metadata.xlsx.

Uses convert_excel_to_ground_truth from evaluation/archive/scripts/.
Output is confidential — in .gitignore; do not push to public remotes.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import sys
from datetime import datetime
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]


def _load_converter():
    path = REPO_ROOT / "evaluation/archive/scripts/convert_excel_to_ground_truth.py"
    spec = importlib.util.spec_from_file_location("excel_gt_convert", path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Cannot load {path}")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod.convert_excel_to_ground_truth


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Export biorem ground truth JSON (local/confidential)",
    )
    parser.add_argument(
        "--excel",
        type=Path,
        default=REPO_ROOT / "evaluation/datasets/raw/biorem/BIOREM_Metadata.xlsx",
        help="Path to BIOREM_Metadata.xlsx.",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=(
            REPO_ROOT / "evaluation/datasets/annotated/ground_truth_biorem.local.json"
        ),
        help="Output JSON path.",
    )
    parser.add_argument("--annotator", type=str, default="changlinke")
    args = parser.parse_args()

    if not args.excel.is_file():
        print(f"ERROR: Excel not found: {args.excel}", file=sys.stderr)
        return 1

    convert = _load_converter()
    doc = convert(
        excel_path=args.excel,
        pdf_path=Path("BIOREM_study_narrative.md"),
        document_id="biorem",
        annotator=args.annotator,
        document_filename="BIOREM_study_narrative.md",
        domain="bioremediation",
        experiment_type="multi_omics",
        metadata_notes_extra=(
            "Expert template; narrative md co-generated from same workbook. "
            "Confidential — use .local.json for public repos."
        ),
    )

    payload = {
        "documents": [doc],
        "annotation_schema_version": "1.0",
        "created_date": datetime.now().strftime("%Y-%m-%d"),
        "last_modified": datetime.now().strftime("%Y-%m-%d"),
        "num_documents": 1,
        "conversion_method": "excel_isa_tab_to_ground_truth",
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with open(args.output, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2, ensure_ascii=False)
    print(f"Wrote {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
