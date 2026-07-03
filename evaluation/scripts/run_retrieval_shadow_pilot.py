#!/usr/bin/env python3
"""Retrieval-only shadow pilot: chunk, index, and compare lexical vs hybrid hits.

This script does not run the full FAIRiAgent LLM workflow. It exercises the
retrieval stack on local source documents and writes a shadow comparison report.

Full eval-gate batch runs still require:
  - evaluation/datasets/annotated/ground_truth_filtered.json
  - evaluation/datasets/raw/{document_id}/paper.pdf|paper.md
  - LLM API credentials for run_batch_evaluation.py
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Dict, List

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from fairifier.config import config
from fairifier.services.chunking import chunk_workspace
from fairifier.services.semantic_index import SemanticIndex
from fairifier.services.source_workspace import (
    SourceRecord,
    build_source_workspace,
    hybrid_search_sources,
    load_source_workspace,
)


def missing_prerequisites(ground_truth_path: Path) -> List[str]:
    missing: List[str] = []
    if not ground_truth_path.is_file():
        missing.append(str(ground_truth_path))
    raw_root = ROOT / "evaluation/datasets/raw"
    if not raw_root.is_dir() or not any(raw_root.iterdir()):
        missing.append("evaluation/datasets/raw/{document_id}/paper.pdf or paper.md")
    return missing


def load_field_queries(ground_truth_path: Path, document_id: str, limit: int = 12) -> List[str]:
    payload = json.loads(ground_truth_path.read_text(encoding="utf-8"))
    for doc in payload.get("documents", []):
        if doc.get("document_id") != document_id:
            continue
        names = []
        for field in doc.get("ground_truth_fields", []):
            name = str(field.get("field_name") or "").strip()
            if name:
                names.append(name)
            if len(names) >= limit:
                break
        return names
    return []


def resolve_input_document(document_id: str) -> Path:
    doc_dir = ROOT / "evaluation/datasets/raw" / document_id
    for candidate in (doc_dir / "paper.md", doc_dir / "paper.pdf", doc_dir / "study_narrative.md"):
        if candidate.is_file():
            return candidate
    raise FileNotFoundError(f"No input document found under {doc_dir}")


def run_shadow_pilot(
    *,
    document_id: str,
    output_dir: Path,
    field_queries: List[str],
) -> Dict[str, Any]:
    input_path = resolve_input_document(document_id)
    text = input_path.read_text(encoding="utf-8", errors="replace") if input_path.suffix.lower() != ".pdf" else ""
    if input_path.suffix.lower() == ".pdf":
        raise ValueError(
            f"PDF input requires MinerU conversion first: {input_path}. "
            "Use a paper.md or study_narrative.md for retrieval-only pilot."
        )

    workspace = build_source_workspace(
        [
            SourceRecord(
                source_id=document_id,
                path=str(input_path.name),
                method="shadow_pilot",
                content=text,
                content_type="markdown",
            )
        ],
        output_dir,
    )
    workspace_meta = {
        "root_dir": str(workspace.root_dir),
        "manifest_path": str(workspace.manifest_path),
        "summary_path": str(workspace.summary_path),
        "source_paths": {sid: str(path) for sid, path in workspace.source_paths.items()},
        "table_paths": {tid: str(path) for tid, path in workspace.table_paths.items()},
    }

    chunk_result = chunk_workspace(workspace_meta)
    semantic_index = SemanticIndex(f"shadow_{document_id}")
    indexed = 0
    if semantic_index.connect():
        indexed = semantic_index.index_chunks(chunk_result.chunks)

    loaded_workspace = load_source_workspace(workspace_meta)
    comparisons = []
    original_shadow = config.retrieval_shadow_mode

    for query in field_queries:
        shadow_telemetry: Dict[str, Any] = {}
        config.retrieval_shadow_mode = True
        lexical_hits = hybrid_search_sources(
            loaded_workspace,
            [query],
            semantic_index=semantic_index if semantic_index.is_available() else None,
            telemetry=shadow_telemetry,
        )
        config.retrieval_shadow_mode = False
        hybrid_telemetry: Dict[str, Any] = {}
        hybrid_hits = hybrid_search_sources(
            loaded_workspace,
            [query],
            semantic_index=semantic_index if semantic_index.is_available() else None,
            telemetry=hybrid_telemetry,
        )
        comparisons.append(
            {
                "query": query,
                "lexical_hit_count": shadow_telemetry.get("lexical_hit_count", 0),
                "hybrid_hit_count": hybrid_telemetry.get("hybrid_hit_count", 0),
                "lexical_only": [f"{h.get('source_id')}:{h.get('start')}-{h.get('end')}" for h in lexical_hits[:5]],
                "hybrid_only": [f"{h.get('source_id')}:{h.get('start')}-{h.get('end')}" for h in hybrid_hits[:5]],
                "hybrid_gain": hybrid_telemetry.get("hybrid_hit_count", 0) > shadow_telemetry.get("lexical_hit_count", 0),
            }
        )

    config.retrieval_shadow_mode = original_shadow

    report = {
        "document_id": document_id,
        "input_path": str(input_path),
        "chunk_count": len(chunk_result.chunks),
        "section_count": len(chunk_result.sections),
        "indexed_chunk_count": indexed,
        "semantic_index_status": semantic_index.status(),
        "shadow_mode": original_shadow,
        "field_comparisons": comparisons,
        "summary": {
            "queries": len(comparisons),
            "queries_with_hybrid_gain": sum(1 for item in comparisons if item["hybrid_gain"]),
            "mean_lexical_hits": sum(item["lexical_hit_count"] for item in comparisons) / len(comparisons) if comparisons else 0.0,
            "mean_hybrid_hits": sum(item["hybrid_hit_count"] for item in comparisons) / len(comparisons) if comparisons else 0.0,
        },
    }
    output_dir.mkdir(parents=True, exist_ok=True)
    report_path = output_dir / "shadow_comparison.json"
    report_path.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    report["report_path"] = str(report_path)
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description="Run retrieval shadow pilot on one document")
    parser.add_argument("--document-id", default="earthworm", help="Dataset ID under evaluation/datasets/raw/")
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=ROOT / "evaluation/runs/retrieval_shadow_pilot",
        help="Directory for shadow_comparison.json",
    )
    parser.add_argument(
        "--ground-truth",
        type=Path,
        default=ROOT / "evaluation/datasets/annotated/ground_truth_filtered.json",
        help="Ground truth index for field-name queries",
    )
    parser.add_argument("--field-limit", type=int, default=12, help="Number of GT field names to query")
    parser.add_argument(
        "--check-only",
        action="store_true",
        help="Only print missing prerequisites and exit",
    )
    args = parser.parse_args()

    missing = missing_prerequisites(args.ground_truth)
    if missing:
        print("Missing prerequisites:")
        for item in missing:
            print(f"  - {item}")
        print("\nRetrieval-only pilot can still run if you pass a local markdown via a populated raw/ folder.")
        if args.check_only:
            return 2

    if args.check_only:
        print(f"Prerequisites look sufficient (ground truth: {args.ground_truth}).")
        return 0

    field_queries = load_field_queries(args.ground_truth, args.document_id, limit=args.field_limit)
    if not field_queries:
        field_queries = ["sample", "organism", "sequencing", "study", "elevation", "location"]

    try:
        report = run_shadow_pilot(
            document_id=args.document_id,
            output_dir=args.output_dir,
            field_queries=field_queries,
        )
    except Exception as exc:
        print(f"Shadow pilot failed: {exc}")
        return 1

    print(json.dumps(report["summary"], indent=2))
    print(f"Report written to: {report['report_path']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
