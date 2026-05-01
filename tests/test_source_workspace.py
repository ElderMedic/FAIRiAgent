import json
from pathlib import Path

from fairifier.services.source_workspace import (
    SourceRecord,
    build_source_workspace,
    grep_sources,
    load_source_workspace,
    read_source_span,
    search_table,
)


def test_source_workspace_preserves_full_text_and_manifest(tmp_path: Path):
    records = [
        SourceRecord(
            source_id="source_001",
            path="main.md",
            method="mineru_preconverted",
            content="# Title\n\n" + ("middle text\n" * 200) + "rare accession PRJNA999999",
            content_type="markdown",
        )
    ]

    workspace = build_source_workspace(records, tmp_path)

    manifest = json.loads(workspace.manifest_path.read_text(encoding="utf-8"))
    assert manifest["source_count"] == 1
    assert manifest["sources"][0]["source_id"] == "source_001"
    assert workspace.source_paths["source_001"].read_text(encoding="utf-8").endswith(
        "rare accession PRJNA999999"
    )


def test_source_workspace_grep_and_read_span_find_text_outside_prompt_preview(tmp_path: Path):
    long_content = "start\n" + ("unrelated\n" * 1000) + "target sampling site: Wadden Sea\nend"
    workspace = build_source_workspace(
        [
            SourceRecord(
                source_id="source_001",
                path="supplement.md",
                method="direct_read",
                content=long_content,
                content_type="markdown",
            )
        ],
        tmp_path,
    )

    matches = grep_sources(workspace, "Wadden Sea", context_chars=20, max_results=5)

    assert matches
    assert matches[0]["source_id"] == "source_001"
    assert "Wadden Sea" in matches[0]["excerpt"]
    span = read_source_span(
        workspace,
        "source_001",
        matches[0]["start"] - 30,
        matches[0]["end"] + 20,
    )
    assert "target sampling site: Wadden Sea" in span["text"]


def test_source_workspace_table_search_uses_full_table_not_preview(tmp_path: Path):
    rows = [{"sample_id": f"S{i}", "organism": "none"} for i in range(200)]
    rows.append({"sample_id": "S201", "organism": "Eisenia fetida"})
    workspace = build_source_workspace(
        [
            SourceRecord(
                source_id="source_001",
                path="samples.csv",
                method="tabular_csv",
                content="Table file: samples.csv\nPreview rows: 120 / 201",
                content_type="table",
                tables=[{"name": "samples", "rows": rows}],
            )
        ],
        tmp_path,
    )

    matches = search_table(workspace, "Eisenia", max_matches=10)

    assert matches == [
        {
            "source_id": "source_001",
            "table": "samples",
            "row_index": 200,
            "column": "organism",
            "value": "Eisenia fetida",
            "row": {"sample_id": "S201", "organism": "Eisenia fetida"},
        }
    ]


def test_load_source_workspace_from_serialized_metadata(tmp_path: Path):
    workspace = build_source_workspace(
        [
            SourceRecord(
                source_id="source_001",
                path="main.md",
                method="direct_read",
                content="sampling site: Wadden Sea",
            )
        ],
        tmp_path,
    )
    serialized = {
        "root_dir": str(workspace.root_dir),
        "manifest_path": str(workspace.manifest_path),
        "summary_path": str(workspace.summary_path),
        "source_paths": {key: str(path) for key, path in workspace.source_paths.items()},
        "table_paths": {key: str(path) for key, path in workspace.table_paths.items()},
    }

    loaded = load_source_workspace(serialized)
    matches = grep_sources(loaded, "Wadden Sea", max_results=1)

    assert matches[0]["source_id"] == "source_001"
