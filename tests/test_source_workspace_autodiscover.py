import tempfile
from pathlib import Path

import pytest

from fairifier.graph.nodes import ReadFileNode
from fairifier.graph.state import FAIRifierState


@pytest.mark.asyncio
async def test_autodiscover_supplementary_files():
    with tempfile.TemporaryDirectory() as tmp_dir:
        parent = Path(tmp_dir)
        # Create primary text file
        doc_file = parent / "paper.txt"
        doc_file.write_text("This is main manuscript content.", encoding="utf-8")

        # Create supplementary spreadsheet
        sheet_file = parent / "supplementary.csv"
        sheet_file.write_text("col1,col2\nval1,val2\n", encoding="utf-8")

        node = ReadFileNode()
        state = FAIRifierState(document_path=str(doc_file), output_dir=tmp_dir)
        updated_state = await node(state)

        source_workspace = updated_state.get("source_workspace", {})
        manifest = source_workspace.get("manifest", {})
        sources = manifest.get("sources", [])

        assert len(sources) >= 2
        source_ids = [s["source_id"] for s in sources]
        assert "source_001" in source_ids
        assert "source_002" in source_ids

        csv_source = [s for s in sources if s["source_id"] == "source_002"][0]
        assert "supplementary.csv" in csv_source["path"]


@pytest.mark.asyncio
async def test_autodiscovery_does_not_treat_adjacent_readme_as_source():
    with tempfile.TemporaryDirectory() as tmp_dir:
        parent = Path(tmp_dir)
        doc_file = parent / "input.md"
        doc_file.write_text("Research abstract.", encoding="utf-8")
        (parent / "README.md").write_text(
            "Operator notes that must not become scientific evidence.", encoding="utf-8"
        )

        state = FAIRifierState(document_path=str(doc_file), output_dir=tmp_dir)
        updated_state = await ReadFileNode()(state)
        sources = updated_state["source_workspace"]["manifest"]["sources"]

        assert len(sources) == 1
        assert sources[0]["path"].endswith("input.md")
