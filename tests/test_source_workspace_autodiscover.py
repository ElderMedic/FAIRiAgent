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
