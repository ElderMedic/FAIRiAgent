#!/usr/bin/env python3
"""
Build BIOREM_study_narrative.md from BIOREM_Metadata.xlsx.

The output is intended for evaluation/datasets/raw/biorem/ (gitignored).
No row data is embedded in this script; run with your local Excel path.
"""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import List

import pandas as pd


def _df_to_markdown_table(df: pd.DataFrame, max_rows: int = 200) -> str:
    if df.empty:
        return "_No rows in template._\n"
    show = df.head(max_rows).fillna("")
    return show.to_markdown(index=False) + "\n"


def _investigation_prose(df: pd.DataFrame) -> str:
    """First data row as bullet list; additional rows as contact lines."""
    if df.empty:
        return "_No investigation rows._\n"
    lines: List[str] = []
    cols = [c for c in df.columns if str(c).strip()]
    for idx, row in df.iterrows():
        lines.append(f"### Contact / row {idx + 1}\n")
        for c in cols:
            val = row.get(c)
            if pd.isna(val) or str(val).strip() in ("", "nan"):
                continue
            text = str(val).strip().replace("\n", " ")
            if len(text) > 800:
                text = text[:800] + "…"
            lines.append(f"- **{c}**: {text}\n")
        lines.append("\n")
    return "".join(lines)


def build_markdown(excel_path: Path) -> str:
    xf = pd.ExcelFile(excel_path)
    parts: List[str] = [
        "# BIOREM — study narrative for metadata extraction\n\n",
        "> **Confidential.** For local FAIRiAgent evaluation only. "
        "Do not distribute publicly. "
        "Generated from the project metadata template (Excel).\n\n",
        "---\n\n",
    ]

    order = [
        "investigation - minimal",
        "study - minimal",
        "observationunit - minimal",
        "sample - soil",
        "assay - Physical Properties",
        "assay - Biochemical Properties",
        "assay - Amplicon library",
        "assay - PacBio",
        "assay - Illumina",
        "assay - Proteomics",
        "assay - Metabolomics",
    ]
    seen = set(xf.sheet_names)
    for name in order:
        if name not in seen:
            continue
        parts.append(f"## Sheet: `{name}`\n\n")
        df = pd.read_excel(excel_path, sheet_name=name)
        if name == "investigation - minimal":
            parts.append(_investigation_prose(df))
        else:
            parts.append(_df_to_markdown_table(df))
        parts.append("\n")

    for name in xf.sheet_names:
        if name.strip().lower() == "help" or name in order:
            continue
        parts.append(f"## Sheet: `{name}`\n\n")
        df = pd.read_excel(excel_path, sheet_name=name)
        parts.append(_df_to_markdown_table(df))
        parts.append("\n")

    return "".join(parts)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Build BIOREM narrative MD from Excel template",
    )
    parser.add_argument(
        "--excel",
        type=Path,
        required=True,
        help="Path to BIOREM_Metadata.xlsx",
    )
    parser.add_argument(
        "--output",
        type=Path,
        required=True,
        help=(
            "Output .md path "
            "(e.g. evaluation/datasets/raw/biorem/BIOREM_study_narrative.md)"
        ),
    )
    args = parser.parse_args()
    if not args.excel.is_file():
        raise SystemExit(f"Excel not found: {args.excel}")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    md = build_markdown(args.excel)
    args.output.write_text(md, encoding="utf-8")
    print(f"Wrote {args.output} ({len(md)} chars)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
