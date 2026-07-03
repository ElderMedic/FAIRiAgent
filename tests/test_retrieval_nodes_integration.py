"""Integration tests for retrieval graph nodes."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

from fairifier.graph.retrieval_nodes import IndexSourcesNode, SectionMapReduceNode
from fairifier.services.source_workspace import SourceRecord, build_source_workspace


SAMPLE_TEXT = """# Introduction

Earthworm transcriptomics in contaminated soil.

## Methods

RNA was extracted and sequenced on Illumina NovaSeq.

## Results

Differential expression identified stress-response genes near the Wadden Sea sampling site.
"""


def test_index_sources_and_section_map_reduce_nodes(tmp_path: Path):
    workspace = build_source_workspace(
        [
            SourceRecord(
                source_id="source_001",
                path="paper.md",
                method="test",
                content=SAMPLE_TEXT,
                content_type="markdown",
            )
        ],
        tmp_path,
    )
    workspace_meta = {
        "root_dir": str(workspace.root_dir),
        "manifest_path": str(workspace.manifest_path),
        "summary_path": str(workspace.summary_path),
        "source_paths": {sid: str(path) for sid, path in workspace.source_paths.items()},
        "table_paths": {tid: str(path) for tid, path in workspace.table_paths.items()},
    }
    state = {
        "session_id": "test_session",
        "source_workspace": workspace_meta,
        "evidence_packets": [],
        "errors": [],
    }

    async def _run() -> dict:
        state_after_index = await IndexSourcesNode()(state)
        return await SectionMapReduceNode()(state_after_index)

    final_state = asyncio.run(_run())

    assert final_state.get("source_chunks")
    assert final_state.get("source_sections")
    assert final_state.get("semantic_index")
    section_coverage = final_state.get("section_coverage") or {}
    assert section_coverage.get("sections_processed", 0) >= 1
    assert final_state.get("evidence_packets")
    assert (workspace.root_dir / "chunks" / "chunks.jsonl").is_file()
    assert (workspace.root_dir / "evidence_store.jsonl").is_file()

    chunks_manifest = [
        json.loads(line)
        for line in (workspace.root_dir / "chunks" / "chunks.jsonl").read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    assert chunks_manifest
    assert any("Wadden Sea" in chunk.get("text", "") for chunk in chunks_manifest)
