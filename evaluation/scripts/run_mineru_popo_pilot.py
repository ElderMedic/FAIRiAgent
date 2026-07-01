#!/usr/bin/env python3
"""Pilot: compare source-grounding proxies with and without MinerU-Popo enrichment.

This script does not require a full FAIRiAgent workflow run. It measures:
- heading count in raw MinerU markdown vs Popo section text (if available)
- structured block count from content_list_v2
- optional grounding coverage against existing evaluation metadata

Usage:
    mamba run -n FAIRiAgent python evaluation/scripts/run_mineru_popo_pilot.py \\
        --mineru-dir output/<project>/mineru_<doc>/
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from fairifier.config import config
from fairifier.services.mineru_paths import (
    discover_structured_artifacts,
    find_markdown_in_tree,
    load_content_list_v2,
)
from fairifier.services.mineru_popo import (
    is_popo_available,
    try_enrich_conversion_with_popo,
)


def _heading_count(text: str) -> int:
    return sum(1 for line in text.splitlines() if line.lstrip().startswith("#"))


def _analyze_mineru_tree(mineru_dir: Path, doc_stem: str) -> dict:
    located = find_markdown_in_tree(mineru_dir, doc_stem)
    if not located:
        return {"error": f"No markdown under {mineru_dir}"}

    markdown_path, _ = located
    markdown_text = markdown_path.read_text(encoding="utf-8", errors="ignore")
    parse_dir = markdown_path.parent
    artifacts = discover_structured_artifacts(parse_dir, doc_stem)

    structured_blocks: list = []
    cl_v2 = artifacts.get("content_list_v2")
    if cl_v2:
        structured_blocks = load_content_list_v2(cl_v2)

    conversion_info = {
        "markdown_path": str(markdown_path),
        "parse_dir": str(parse_dir),
        "structured_block_count": len(structured_blocks),
        "structured_blocks": structured_blocks[:50],
    }
    if cl_v2:
        conversion_info["content_list_v2_path"] = str(cl_v2)

    baseline = {
        "markdown_chars": len(markdown_text),
        "markdown_headings": _heading_count(markdown_text),
        "structured_block_count": len(structured_blocks),
        "text_blocks": sum(1 for b in structured_blocks if b.get("type") == "text"),
        "table_blocks": sum(1 for b in structured_blocks if b.get("type") == "table"),
    }

    popo_report = {"enabled": is_popo_available(), "applied": False}
    if is_popo_available() and conversion_info.get("parse_dir"):
        enriched = try_enrich_conversion_with_popo(dict(conversion_info))
        popo_report["applied"] = "popo_section_markdown" in enriched
        if enriched.get("popo_section_markdown"):
            section = enriched["popo_section_markdown"]
            popo_report.update(
                {
                    "section_chars": len(section),
                    "section_headings": _heading_count(section),
                    "heading_delta": _heading_count(section)
                    - baseline["markdown_headings"],
                    "popo_tree_path": enriched.get("popo_tree_path"),
                }
            )
        if enriched.get("popo_error"):
            popo_report["error"] = enriched["popo_error"]

    return {
        "mineru_dir": str(mineru_dir),
        "doc_stem": doc_stem,
        "baseline": baseline,
        "popo": popo_report,
        "conversion_info": {
            k: v
            for k, v in conversion_info.items()
            if k != "structured_blocks"
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="MinerU-Popo pilot metrics")
    parser.add_argument(
        "--mineru-dir",
        type=Path,
        required=True,
        help="Path to mineru_<doc>/ output directory",
    )
    parser.add_argument(
        "--doc-stem",
        type=str,
        default=None,
        help="Document stem (defaults to mineru_dir name minus mineru_ prefix)",
    )
    parser.add_argument("--output", type=Path, default=None, help="JSON report path")
    args = parser.parse_args()

    mineru_dir = args.mineru_dir.resolve()
    doc_stem = args.doc_stem
    if not doc_stem:
        name = mineru_dir.name
        doc_stem = name[len("mineru_") :] if name.startswith("mineru_") else name

    report = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "config": {
            "mineru_popo_enabled": config.mineru_popo_enabled,
            "mineru_popo_root": str(config.mineru_popo_root or ""),
        },
        "analysis": _analyze_mineru_tree(mineru_dir, doc_stem),
    }

    out_path = args.output
    if out_path is None:
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        out_dir = PROJECT_ROOT / "evaluation/runs" / f"mineru_popo_pilot_{stamp}"
        out_dir.mkdir(parents=True, exist_ok=True)
        out_path = out_dir / "popo_pilot_report.json"

    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report, indent=2))
    print(f"\nReport: {out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
