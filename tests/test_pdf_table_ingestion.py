"""Publication tables retain structure and evidence through source ingestion."""

import asyncio
import hashlib
import json
from pathlib import Path
from unittest.mock import Mock

import pytest

from fairifier.agents.isa_value_mapper import ISAValueMapperAgent
from fairifier.config import config
from fairifier.graph.nodes import ReadFileNode
from fairifier.services.source_workspace import load_source_workspace, search_table
from fairifier.tools.isa_structure_tools import create_isa_structure_tools
from fairifier.utils.document_text import read_document_text
from fairifier.utils.metadata_table_plan import normalized_table_rows


CAPTION = "Table 1. Response rates at 30 °C."
FOOTNOTE = "† Values are means; blank cells were not reported."
INITIAL = "Rate | Initial (µmol cm−2 h−1)"
FINAL = "Rate | Final (µmol cm−2 h−1)"
TABLE_HTML = f"""<table>
<caption>{CAPTION}</caption>
<thead>
<tr><th rowspan="2">Specimen</th><th rowspan="2">Condition</th><th colspan="2">Rate</th></tr>
<tr><th>Initial (µmol cm−2 h−1)</th><th>Final (µmol cm−2 h−1)</th></tr>
</thead>
<tbody>
<tr><td rowspan="2">A1</td><td>cold</td><td>0</td><td>−0.025</td></tr>
<tr><td>warm</td><td>1.20 ± 0.03</td><td></td></tr>
</tbody>
<tfoot><tr><td colspan="4">{FOOTNOTE}</td></tr></tfoot>
</table>"""
MARKDOWN = f"# Measurements\n\n{TABLE_HTML}\n\nRepeated determination:\n\n{TABLE_HTML}\n"


def _blocks():
    return [
        {
            "type": "table",
            "table_body": TABLE_HTML,
            "table_caption": [CAPTION],
            "table_footnote": [FOOTNOTE],
            "page_idx": page,
            "bbox": [10, 20, 300, 180],
        }
        for page in (2, 4)
    ]


def _write_conversion(root, stem="paper", *, markdown=MARKDOWN, blocks=None):
    parse_dir = root / stem / "vlm"
    parse_dir.mkdir(parents=True, exist_ok=True)
    md_path = parse_dir / f"{stem}.md"
    md_path.write_text(markdown, encoding="utf-8")
    if blocks is not None:
        (parse_dir / f"{stem}_content_list.json").write_text(
            json.dumps(blocks, ensure_ascii=False), encoding="utf-8",
        )
    return md_path


@pytest.fixture
def ingestion_config(monkeypatch, tmp_path):
    monkeypatch.setattr(config, "source_workspace_enabled", True)
    monkeypatch.setattr(config, "mineru_enabled", True)
    monkeypatch.setattr(config, "mineru_cache_enabled", False)
    monkeypatch.setattr(config, "mineru_cache_dir", tmp_path / "cache")
    monkeypatch.setattr(config, "mineru_popo_enabled", False)


def _fresh_node():
    tool = Mock()

    def convert(payload):
        root = Path(payload["output_dir"])
        md_path = _write_conversion(root, blocks=_blocks())
        return {
            "success": True,
            "markdown_text": MARKDOWN,
            "markdown_path": str(md_path),
            "output_dir": str(root),
            "images_dir": None,
            "method": "mineru",
        }

    tool.invoke.side_effect = convert
    return ReadFileNode(mineru_tool=tool)


def _source(tmp_path):
    parent = tmp_path / "input"
    parent.mkdir(exist_ok=True)
    pdf = parent / "paper.pdf"
    pdf.write_bytes(b"%PDF-1.4 synthetic conversion fixture")
    return pdf


@pytest.mark.parametrize("mode,persist", [
    ("fresh", True), ("preconverted", True), ("cache", True), ("preconverted", False),
])
def test_pdf_first_page_evidence_survives_mineru_header_omission(
    tmp_path, ingestion_config, monkeypatch, mode, persist,
):
    import fitz
    from fairifier.services import mineru_cache as cache_service

    pdf = _source(tmp_path)
    with fitz.open() as document:
        page = document.new_page()
        page.insert_text((40, 40), "DOI 10.5678/example.2026")
        page.insert_text((40, 70), "Accepted 14 May 2026")
        document.new_page().insert_text((40, 40), "Later page text")
        document.save(pdf)
    original_hash = hashlib.sha256(pdf.read_bytes()).hexdigest()
    run_dir = tmp_path / "run" if persist else None
    node = _fresh_node()
    if mode == "cache":
        monkeypatch.setattr(config, "mineru_cache_enabled", True)
        cache_tree = tmp_path / "cached_conversion"
        _write_conversion(cache_tree, blocks=_blocks())
        cache_service.store_mineru_output_after_success(
            Path(config.mineru_cache_dir), original_hash, cache_tree,
        )
    elif mode == "preconverted":
        conversion_root = (run_dir or pdf.parent) / "mineru_paper"
        _write_conversion(conversion_root, blocks=_blocks())
    state = asyncio.run(node({
        "document_path": str(pdf),
        **({"output_dir": str(run_dir)} if run_dir else {}),
    }))

    working = read_document_text(state)
    assert "10.5678/example.2026" in working
    assert "Accepted 14 May 2026" in working
    assert "Later page text" not in working
    info = state["document_conversion"]
    assert Path(info["markdown_path"]).read_text(encoding="utf-8") == MARKDOWN
    assert hashlib.sha256(pdf.read_bytes()).hexdigest() == original_hash
    regions = info["source_evidence"]["native_pdf_regions"]
    assert all(region["page_number"] == 1 for region in regions)
    assert all(region["source_path"] == str(pdf) for region in regions)
    assert all(working[region["working_start"]:region["working_end"]] == region["text"]
               for region in regions)
    if persist:
        workspace = load_source_workspace(state["source_workspace"])
        assert workspace.source_paths["source_001"].read_text(encoding="utf-8") == working
        from fairifier.services.chunking import chunk_workspace
        assert any("10.5678/example.2026" in chunk.text
                   for chunk in chunk_workspace(state["source_workspace"]).chunks)
    cleaned, issues = ISAValueMapperAgent._clear_unverified_provisional_values(
        {"investigation": {"rows": [{"associated publication": "10.5678/example.2026"}]}},
        {"investigation": [{"field_name": "associated publication", "status": "provisional"}]},
        {"levels": []}, working,
    )
    assert cleaned["investigation"]["rows"][0]["associated publication"] == "10.5678/example.2026"
    assert issues == []


def _table_refs(workspace):
    return workspace.manifest["sources"][0]["tables"]


def test_native_pdf_supplement_is_idempotent_and_ignores_pdf_metadata(tmp_path):
    import fitz
    from fairifier.services.mineru_evidence import supplement_pdf_first_page

    pdf = tmp_path / "paper.pdf"
    with fitz.open() as document:
        document.new_page().insert_text((40, 40), "Reported title")
        document.set_metadata({"title": "Unprinted metadata value"})
        document.save(pdf)
    once, evidence = supplement_pdf_first_page("Body text", pdf)
    twice, second = supplement_pdf_first_page(once, pdf)

    assert "Reported title" in once
    assert "Unprinted metadata value" not in once
    assert once == twice
    assert len(evidence["native_pdf_regions"]) == 1
    assert second == {}


def test_scanned_pdf_keeps_mineru_text_without_native_supplement(tmp_path):
    import fitz
    from fairifier.services.mineru_evidence import supplement_pdf_first_page

    pdf = tmp_path / "scan.pdf"
    with fitz.open() as document:
        document.new_page()
        document.save(pdf)
    working, evidence = supplement_pdf_first_page("OCR content", pdf)

    assert working == "OCR content"
    assert evidence == {}


def _read_workspace(node, source, output_dir):
    text, info = node._read_document_content(str(source), str(output_dir))
    return text, info, load_source_workspace(info["source_workspace"])


@pytest.mark.parametrize("mode", ["fresh", "preconverted", "markdown"])
def test_html_tables_reach_searchable_workspace_in_every_ingestion_path(
    tmp_path, ingestion_config, mode,
):
    pdf = _source(tmp_path)
    run_dir = tmp_path / "run"
    node = _fresh_node()
    source = pdf
    if mode == "preconverted":
        _write_conversion(run_dir / "mineru_paper", blocks=_blocks())
    elif mode == "markdown":
        source = pdf.with_suffix(".md")
        source.write_text(MARKDOWN, encoding="utf-8")

    text, info, workspace = _read_workspace(node, source, run_dir)

    assert text == MARKDOWN
    assert workspace.source_paths["source_001"].read_text(encoding="utf-8") == MARKDOWN
    assert len(workspace.table_paths) == 2  # Repeated occurrences are not deduplicated away.
    assert ISAValueMapperAgent._needs_tool_mapping(info["source_workspace"])
    refs = _table_refs(workspace)
    assert len({item["name"] for item in refs}) == 2
    assert all(item["header_status"] == "resolved" for item in refs)
    matches = search_table(workspace, "A1", max_matches=20)
    assert len(matches) == 4
    assert {match["row"][INITIAL] for match in matches} == {"0", "1.20 ± 0.03"}
    assert {match["row"][FINAL] for match in matches} == {"−0.025", ""}
    assert all(match["table_context"]["captions"] == [CAPTION] for match in matches)
    assert all(match["table_context"]["footnotes"] == [FOOTNOTE] for match in matches)
    assert all("raw_html" not in match["table_context"] for match in matches)
    assert all("cells" not in match["table_context"] for match in matches)
    assert all("grid_origins" not in match["table_context"] for match in matches)
    for ref in refs:
        assert ref["raw_html"] == TABLE_HTML
        assert ref["header_rows"] == [0, 1]
        assert ref["columns"] == ["Specimen", "Condition", INITIAL, FINAL]
        assert any(cell["rowspan"] == 2 for cell in ref["cells"])
        assert any(cell["colspan"] == 2 for cell in ref["cells"])
        assert ref["provenance"]["table_index"] in (0, 1)
    if mode != "markdown":
        assert [ref["provenance"]["page_idx"] for ref in refs] == [2, 4]
        assert all(ref["provenance"]["bbox"] == [10, 20, 300, 180] for ref in refs)
        assert all(ref["provenance"]["artifact_sha256"] for ref in refs)
    else:
        for ref in refs:
            span = ref["provenance"]
            assert MARKDOWN[span["start"]:span["end"]] == TABLE_HTML


def test_cached_mineru_tables_preserve_identical_evidence_without_reconversion(
    tmp_path, ingestion_config, monkeypatch,
):
    monkeypatch.setattr(config, "mineru_cache_enabled", True)
    pdf = _source(tmp_path)
    node = _fresh_node()
    _, _, fresh = _read_workspace(node, pdf, tmp_path / "fresh")
    node.mineru_tool.invoke.reset_mock()

    _, info, cached = _read_workspace(node, pdf, tmp_path / "cached")

    assert info["method"] == "mineru_cache"
    assert node.mineru_tool.invoke.call_count == 0
    assert len(fresh.table_paths) == len(cached.table_paths) == 2
    assert list(fresh.table_paths) == list(cached.table_paths)
    for original, reused in zip(_table_refs(fresh), _table_refs(cached)):
        assert original["columns"] == reused["columns"]
        assert original["cells"] == reused["cells"]
        assert original["provenance"]["artifact_sha256"] == reused["provenance"]["artifact_sha256"]
        assert original["provenance"]["block_index"] == reused["provenance"]["block_index"]
    assert search_table(cached, "0", max_matches=30)


def test_ambiguous_all_td_headers_remain_unresolved_and_searchable(
    tmp_path, ingestion_config,
):
    source = tmp_path / "ambiguous.md"
    # A top row holding a plain number may be a data row: no header is guessed.
    raw = "<table><tr><td>Code</td><td>55</td></tr><tr><td>A1</td><td>0</td></tr></table>"
    source.write_text(raw, encoding="utf-8")
    _, _, workspace = _read_workspace(ReadFileNode(), source, tmp_path / "run")

    assert len(workspace.table_paths) == 1
    ref = _table_refs(workspace)[0]
    assert ref["header_status"] == "unresolved"
    assert ref["header_rows"] == []
    matches = search_table(workspace, "A1")
    assert matches and "0" in matches[0]["row"].values()
    # Do not let the spreadsheet header heuristic guess a scientific header.
    assert normalized_table_rows(next(iter(workspace.table_paths.values()))) == ([], [], -1)


def test_structured_table_metadata_survives_even_when_markdown_has_no_table(
    tmp_path, ingestion_config,
):
    pdf = _source(tmp_path)
    run_dir = tmp_path / "run"
    _write_conversion(run_dir / "mineru_paper", markdown="# Short rendering", blocks=_blocks())

    text, _, workspace = _read_workspace(ReadFileNode(), pdf, run_dir)

    assert text == "# Short rendering"
    assert len(workspace.table_paths) == 2
    assert len(search_table(workspace, "A1", max_matches=20)) == 4


def test_explicit_multilevel_headers_are_not_repromoted_from_data_rows(
    tmp_path, ingestion_config,
):
    source = tmp_path / "rates.md"
    source.write_text(TABLE_HTML, encoding="utf-8")
    _, _, workspace = _read_workspace(ReadFileNode(), source, tmp_path / "run")

    assert len(workspace.table_paths) == 1
    columns, rows, header_index = normalized_table_rows(next(iter(workspace.table_paths.values())))
    assert columns == ["Specimen", "Condition", INITIAL, FINAL]
    assert len(rows) == 2
    assert rows[0][INITIAL] == "0"
    assert rows[1][FINAL] == ""
    assert header_index == -1


def test_nested_page_v2_tables_are_preserved_after_large_text_prefix(
    tmp_path, ingestion_config,
):
    pdf = _source(tmp_path)
    run_dir = tmp_path / "run"
    md_path = _write_conversion(
        run_dir / "mineru_paper", markdown=TABLE_HTML,
        blocks=[{**_blocks()[0], "bbox": [89, 124, 905, 246]}],
    )
    v2 = [
        [{"type": "text", "content": {"text": f"Paragraph {i}"}} for i in range(501)],
        [],
        [{
            "type": "table",
            "content": {
                "image_source": {"path": "images/table.jpg"},
                "table_caption": [{"type": "text", "content": CAPTION}],
                "table_footnote": [{"type": "text", "content": FOOTNOTE}],
                "html": TABLE_HTML,
                "table_type": "complex_table",
                "table_nest_level": 1,
            },
            "bbox": [89, 124, 905, 246],
        }],
    ]
    (md_path.parent / "paper_content_list_v2.json").write_text(
        json.dumps(v2, ensure_ascii=False), encoding="utf-8",
    )

    _, _, workspace = _read_workspace(ReadFileNode(), pdf, run_dir)

    assert len(workspace.table_paths) == 1  # v2, legacy and Markdown are one occurrence.
    ref = _table_refs(workspace)[0]
    assert ref["captions"] == [CAPTION]
    assert ref["footnotes"] == [FOOTNOTE]
    assert ref["provenance"]["page_idx"] == 2
    assert ref["provenance"]["bbox"] == [89, 124, 905, 246]
    assert ref["provenance"]["artifact_path"].endswith("paper_content_list_v2.json")
    assert len(search_table(workspace, "A1", max_matches=20)) == 2


def test_all_td_grouped_table_keeps_physical_grid_without_guessing_headers(
    tmp_path, ingestion_config,
):
    raw = (
        TABLE_HTML.replace("<thead>", "").replace("</thead>", "")
        .replace("<th", "<td").replace("</th>", "</td>")
        .replace("Initial (", "Initial (0 h; ").replace("Final (", "Final (24 h; ")
    )
    source = tmp_path / "grouped_readings.md"
    source.write_text(raw, encoding="utf-8")

    _, info, workspace = _read_workspace(ReadFileNode(), source, tmp_path / "run")

    assert len(workspace.table_paths) == 1
    assert ISAValueMapperAgent._needs_tool_mapping(info["source_workspace"])
    ref = _table_refs(workspace)[0]
    assert ref["header_status"] == "unresolved"
    assert ref["header_rows"] == []
    assert ref["raw_html"] == raw
    assert ref["captions"] == [CAPTION]
    assert ref["footnotes"] == [FOOTNOTE]
    assert ref["grid_origins"][0][2] == ref["grid_origins"][0][3]
    assert ref["grid_origins"][0][0] == ref["grid_origins"][1][0]
    assert ref["grid_origins"][2][0] == ref["grid_origins"][3][0]
    matches = search_table(workspace, "24 h", max_matches=20)
    assert matches and "µmol cm−2 h−1" in matches[0]["value"]
    assert matches[0]["table_context"]["header_status"] == "unresolved"
    assert "raw_html" not in matches[0]["table_context"]
    specimen_rows = search_table(workspace, "A1", max_matches=20)
    assert len(specimen_rows) == 2
    assert "0" in specimen_rows[0]["row"].values()
    leading_rows = specimen_rows[0]["table_context"]["leading_rows"]
    assert leading_rows[0]["source_row_index"] == 0
    leading_text = json.dumps(leading_rows, ensure_ascii=False)
    assert "0 h" in leading_text and "24 h" in leading_text
    assert "µmol cm−2 h−1" in leading_text
    assert set(specimen_rows[0]["row"]) == set(ref["columns"])
    assert all(key.startswith("column_") for key in specimen_rows[0]["row"])
    assert normalized_table_rows(next(iter(workspace.table_paths.values()))) == ([], [], -1)


def test_partial_v2_does_not_replace_distinct_legacy_occurrence_with_a_duplicate(
    tmp_path, ingestion_config,
):
    pdf = _source(tmp_path)
    run_dir = tmp_path / "run"
    md_path = _write_conversion(run_dir / "mineru_paper", blocks=_blocks())
    v2 = [[], [], [], [], [{
        "type": "table",
        "content": {"html": TABLE_HTML, "table_caption": [CAPTION]},
        "bbox": [10, 20, 300, 180],
    }]]
    (md_path.parent / "paper_content_list_v2.json").write_text(
        json.dumps(v2, ensure_ascii=False), encoding="utf-8",
    )

    _, _, workspace = _read_workspace(ReadFileNode(), pdf, run_dir)

    assert len(workspace.table_paths) == 2
    assert sorted(ref["provenance"]["page_idx"] for ref in _table_refs(workspace)) == [2, 4]


def test_duplicate_header_suffixes_cannot_overwrite_a_source_cell(
    tmp_path, ingestion_config,
):
    source = tmp_path / "duplicate_labels.md"
    source.write_text(
        "<table><thead><tr><th>A</th><th>A</th><th>A [2]</th></tr></thead>"
        "<tbody><tr><td>first</td><td>second</td><td>third</td></tr></tbody></table>",
        encoding="utf-8",
    )

    _, _, workspace = _read_workspace(ReadFileNode(), source, tmp_path / "run")

    ref = _table_refs(workspace)[0]
    assert len(ref["columns"]) == len(set(ref["columns"])) == 3
    matches = search_table(workspace, "first")
    assert len(matches) == 1
    assert set(matches[0]["row"].values()) == {"first", "second", "third"}


def test_body_row_headers_without_scope_or_tbody_do_not_discard_data(
    tmp_path, ingestion_config,
):
    source = tmp_path / "row_headers.md"
    source.write_text(
        "<table><tr><th>Specimen</th><th>Value</th></tr>"
        "<tr><th>A1</th><td>0.1</td></tr>"
        "<tr><th>A2</th><td>0.2</td></tr></table>",
        encoding="utf-8",
    )

    _, _, workspace = _read_workspace(ReadFileNode(), source, tmp_path / "run")

    assert len(workspace.table_paths) == 1
    matches = search_table(workspace, "0.1")
    assert len(matches) == 1
    assert "A1" in matches[0]["row"].values()
    assert search_table(workspace, "0.2")


def test_same_located_artifact_table_retains_complementary_header_and_caption_evidence(
    tmp_path, ingestion_config,
):
    pdf = _source(tmp_path)
    run_dir = tmp_path / "run"
    md_path = _write_conversion(run_dir / "mineru_paper", markdown="No rendered table.", blocks=[_blocks()[0]])
    unresolved_html = (
        TABLE_HTML.replace(f"<caption>{CAPTION}</caption>", "")
        .replace(f'<tfoot><tr><td colspan="4">{FOOTNOTE}</td></tr></tfoot>', "")
        .replace("<thead>", "").replace("</thead>", "")
        .replace("<th", "<td").replace("</th>", "</td>")
    )
    v2 = [[], [], [{
        "type": "table", "content": {"html": unresolved_html},
        "bbox": [10, 20, 300, 180],
    }]]
    (md_path.parent / "paper_content_list_v2.json").write_text(
        json.dumps(v2, ensure_ascii=False), encoding="utf-8",
    )

    _, _, workspace = _read_workspace(ReadFileNode(), pdf, run_dir)

    assert len(workspace.table_paths) == 1
    ref = _table_refs(workspace)[0]
    assert ref["header_status"] == "resolved"
    assert ref["captions"] == [CAPTION]
    assert ref["footnotes"] == [FOOTNOTE]
    assert ref["columns"] == ["Specimen", "Condition", INITIAL, FINAL]
    evidence = ref["representations"]
    assert {item["raw_html"] for item in evidence} == {unresolved_html, TABLE_HTML}
    assert {Path(item["provenance"]["artifact_path"]).name for item in evidence} == {
        "paper_content_list_v2.json", "paper_content_list.json",
    }
    assert len(search_table(workspace, "A1", max_matches=20)) == 2


def test_search_context_is_bounded_without_truncating_manifest_evidence(
    tmp_path, ingestion_config,
):
    caption, footnote = "C" * 10000, "F" * 10000
    column = "Reading " + "H" * 1000
    source = tmp_path / "long_context.md"
    source.write_text(
        f"<table><caption>{caption}</caption><thead><tr><th>{column}</th></tr></thead>"
        f"<tbody><tr><td>1</td></tr></tbody><tfoot><tr><td>{footnote}</td></tr></tfoot></table>",
        encoding="utf-8",
    )

    _, _, workspace = _read_workspace(ReadFileNode(), source, tmp_path / "run")

    matches = search_table(workspace, "1")
    assert len(matches) == 1
    context = matches[0]["table_context"]
    assert len(json.dumps(context, ensure_ascii=False)) < 5000
    assert context["truncated"] is True
    assert context["manifest_path"] == str(workspace.manifest_path)
    ref = _table_refs(workspace)[0]
    assert ref["captions"] == [caption]
    assert ref["footnotes"] == [footnote]
    assert ref["columns"] == [column]


CHART_CAPTION = "Figure 1. Signal measured during incubation at 30 °C."
CHART_BODY_MARKDOWN = "| Time (h) | Signal |\n| --- | --- |\n| 51 | 999.25 |"
CHART_BODY_HTML = (
    "<table><tr><th>Time (h)</th><th>Signal</th></tr>"
    "<tr><td>51</td><td>999.25</td></tr></table>"
)


def _chart_markdown(chart_body):
    return (
        "# Source manuscript\n\nThe reported experiment ended after 48 h.\n\n"
        + TABLE_HTML
        + f"\n\n![](images/chart.png)\n\n{CHART_CAPTION}\n\n"
        + f"<details>\n<summary>line chart</summary>\n\n{chart_body}\n</details>\n"
    )


def _write_chart_conversion(root, chart_body):
    blocks = [
        _blocks()[0],
        {"type": "image", "img_path": "images/chart.png", "page_idx": 3,
         "image_caption": [CHART_CAPTION], "image_body": chart_body},
    ]
    md_path = _write_conversion(root, markdown=_chart_markdown(chart_body), blocks=blocks)
    images = md_path.parent / "images"
    images.mkdir(exist_ok=True)
    (images / "chart.png").write_bytes(b"unchanged original chart image")
    return md_path


def _chart_node(chart_body):
    tool = Mock()

    def convert(payload):
        root = Path(payload["output_dir"])
        md_path = _write_chart_conversion(root, chart_body)
        return {
            "success": True, "markdown_text": _chart_markdown(chart_body),
            "markdown_path": str(md_path), "output_dir": str(root),
            "images_dir": str(md_path.parent / "images"), "method": "mineru",
        }

    tool.invoke.side_effect = convert
    return ReadFileNode(mineru_tool=tool)


@pytest.mark.parametrize("mode", ["fresh", "preconverted", "cached"])
@pytest.mark.parametrize("chart_body", [CHART_BODY_MARKDOWN, CHART_BODY_HTML])
def test_derived_chart_values_are_excluded_from_canonical_source_evidence(
    tmp_path, ingestion_config, monkeypatch, mode, chart_body,
):
    pdf = _source(tmp_path)
    node = _chart_node(chart_body)
    run_dir = tmp_path / "run"
    if mode == "preconverted":
        _write_chart_conversion(run_dir / "mineru_paper", chart_body)
    elif mode == "cached":
        monkeypatch.setattr(config, "mineru_cache_enabled", True)
        asyncio.run(node({"document_path": str(pdf), "output_dir": str(tmp_path / "prime")}))
        node.mineru_tool.invoke.reset_mock()

    state = asyncio.run(node({"document_path": str(pdf), "output_dir": str(run_dir)}))

    working = read_document_text(state)
    assert "999.25" not in working
    assert "unverified" in working.lower()
    assert CHART_CAPTION in working and "images/chart.png" in working
    assert TABLE_HTML in working
    assert "reported experiment ended after 48 h" in working
    assert Path(state["document_text_path"]).read_text(encoding="utf-8") == working
    assert "999.25" not in state["input_documents"][0]["content"]
    workspace = load_source_workspace(state["source_workspace"])
    assert workspace.source_paths["source_001"].read_text(encoding="utf-8") == working
    assert len(workspace.table_paths) == 1  # Only the article table, never chart estimates.
    assert not search_table(workspace, "999.25")
    tools = {tool.name: tool for tool in create_isa_structure_tools(state["source_workspace"])}
    assert not tools["grep_source_workspace"].invoke({"query": "999.25"})["data"]["matches"]
    assert not tools["search_workspace_tables"].invoke({"query": "999.25"})["data"]["matches"]

    evidence = state["document_conversion"]["source_evidence"]
    raw_path = Path(evidence["raw_markdown_path"])
    raw = raw_path.read_text(encoding="utf-8")
    assert raw == _chart_markdown(chart_body)
    assert evidence["raw_markdown_sha256"] == hashlib.sha256(raw_path.read_bytes()).hexdigest()
    assert raw_path != Path(state["document_text_path"])
    regions = evidence["derived_regions"]
    assert len(regions) == 1
    region = regions[0]
    assert region["kind"] == "chart_reconstruction" and region["status"] == "unverified"
    assert chart_body in raw[region["raw_start"]:region["raw_end"]]
    assert any(path.endswith("images/chart.png") for path in region["image_paths"])
    assert (raw_path.parent / "images/chart.png").read_bytes() == b"unchanged original chart image"
    raw_blocks = json.loads(raw_path.with_name("paper_content_list.json").read_text(encoding="utf-8"))
    assert raw_blocks[1]["image_body"] == chart_body
    assert workspace.manifest["sources"][0]["source_evidence"] == evidence
    if mode != "fresh":
        assert node.mineru_tool.invoke.call_count == 0


def test_author_markdown_details_are_not_treated_as_mineru_chart_estimates(
    tmp_path, ingestion_config,
):
    source = tmp_path / "author_notes.md"
    raw = _chart_markdown(CHART_BODY_MARKDOWN)
    source.write_text(raw, encoding="utf-8")

    state = asyncio.run(ReadFileNode()({
        "document_path": str(source), "output_dir": str(tmp_path / "run"),
    }))

    assert read_document_text(state) == raw
    assert not state["document_conversion"].get("source_evidence", {}).get("derived_regions")
    assert source.read_text(encoding="utf-8") == raw


def test_chart_filter_does_not_fall_back_to_raw_text_without_output_directory(
    tmp_path, ingestion_config,
):
    pdf = _source(tmp_path)
    raw_path = _write_chart_conversion(pdf.parent / "mineru_paper", CHART_BODY_MARKDOWN)

    state = asyncio.run(ReadFileNode()({"document_path": str(pdf)}))

    assert "999.25" not in read_document_text(state)
    assert CHART_CAPTION in read_document_text(state)
    assert state.get("document_text_path") != str(raw_path)
    assert raw_path.read_text(encoding="utf-8") == _chart_markdown(CHART_BODY_MARKDOWN)


def test_mineru_working_text_filter_is_idempotent(tmp_path):
    from fairifier.services.mineru_evidence import prepare_mineru_evidence

    raw_path = tmp_path / "source.md"
    raw = _chart_markdown(CHART_BODY_MARKDOWN)
    raw_path.write_text(raw, encoding="utf-8")

    once, evidence = prepare_mineru_evidence(raw, raw_path)
    twice, second_evidence = prepare_mineru_evidence(once, raw_path)

    assert once == twice
    assert len(evidence["derived_regions"]) == 1
    assert not second_evidence.get("derived_regions")
    assert "999.25" not in twice


def test_mineru_working_text_filter_preserves_nonchart_details_and_native_tables(tmp_path):
    from fairifier.services.mineru_evidence import prepare_mineru_evidence

    raw = f"<details><summary>Experimental data</summary>{TABLE_HTML}</details>"
    path = tmp_path / "source.md"
    path.write_text(raw, encoding="utf-8")

    working, evidence = prepare_mineru_evidence(raw, path)

    assert working == raw
    assert not evidence.get("derived_regions")


def test_derived_chart_values_cannot_reenter_via_structured_chunk_metadata(
    tmp_path, ingestion_config,
):
    from fairifier.services.chunking import chunk_workspace

    pdf = _source(tmp_path)
    node = _chart_node(CHART_BODY_MARKDOWN)
    convert = node.mineru_tool.invoke.side_effect

    def with_structured_chart(payload):
        result = convert(payload)
        md_path = Path(result["markdown_path"])
        blocks_path = md_path.with_name("paper_content_list_v2.json")
        blocks_path.write_text(json.dumps([
            {"type": "text", "text": "The reported experiment ended after 48 h."},
            {"type": "image", "text": CHART_BODY_MARKDOWN, "page_idx": 3},
        ]), encoding="utf-8")
        result["content_list_v2_path"] = str(blocks_path)
        return result

    node.mineru_tool.invoke.side_effect = with_structured_chart
    state = asyncio.run(node({
        "document_path": str(pdf), "output_dir": str(tmp_path / "run"),
    }))

    chunks = chunk_workspace(state["source_workspace"])

    assert chunks.chunks
    assert all("999.25" not in chunk.text for chunk in chunks.chunks)
    assert any("reported experiment ended after 48 h" in chunk.text for chunk in chunks.chunks)
    raw_blocks = Path(state["document_conversion"]["content_list_v2_path"])
    assert "999.25" in raw_blocks.read_text(encoding="utf-8")


@pytest.mark.parametrize("chart_body", [CHART_BODY_MARKDOWN, CHART_BODY_HTML])
def test_unclosed_chart_details_exclude_only_a_bounded_reconstruction_table(tmp_path, chart_body):
    from fairifier.services.mineru_evidence import prepare_mineru_evidence

    following = f"\n\n# Methods\nThe source reports 48 h.\n\n{TABLE_HTML}"
    raw = f"<details><summary>line chart</summary>\n\n{chart_body}" + following
    raw_path = tmp_path / "source.md"
    raw_path.write_text(raw, encoding="utf-8")

    working, evidence = prepare_mineru_evidence(raw, raw_path)

    assert "999.25" not in working
    assert following in working
    assert TABLE_HTML in working
    region = evidence["derived_regions"][0]
    assert region["raw_end"] <= raw.index("# Methods")
    assert raw_path.read_text(encoding="utf-8") == raw


def test_unclosed_chart_without_unambiguous_body_boundary_is_rejected(tmp_path):
    from fairifier.services.mineru_evidence import prepare_mineru_evidence

    raw = "<details><summary>line chart</summary>\nEstimated signal: 999.25.\nFurther text."
    raw_path = tmp_path / "source.md"
    raw_path.write_text(raw, encoding="utf-8")

    with pytest.raises(ValueError, match="[Uu]nterminated chart"):
        prepare_mineru_evidence(raw, raw_path)

    assert raw_path.read_text(encoding="utf-8") == raw


def test_malformed_preconverted_chart_does_not_reconvert_or_reuse_raw_text(
    tmp_path, ingestion_config,
):
    pdf = _source(tmp_path)
    run_dir = tmp_path / "run"
    raw = "<details><summary>line chart</summary>Estimated signal: 999.25."
    raw_path = _write_conversion(run_dir / "mineru_paper", markdown=raw)
    tool = Mock()
    tool.invoke.side_effect = AssertionError("A construction error must not rerun conversion")

    state = asyncio.run(ReadFileNode(mineru_tool=tool)({
        "document_path": str(pdf), "output_dir": str(run_dir),
    }))

    assert any("Unterminated chart" in error for error in state.get("errors", []))
    tool.invoke.assert_not_called()
    assert not state.get("document_text_path")
    assert "999.25" not in read_document_text(state)
    assert raw_path.read_text(encoding="utf-8") == raw


def test_conflicting_located_table_representations_expose_issues_in_bounded_search_context(
    tmp_path, ingestion_config,
):
    pdf = _source(tmp_path)
    run_dir = tmp_path / "run"
    legacy = {**_blocks()[0], "table_footnote": [FOOTNOTE, "Long note " * 2000]}
    md_path = _write_conversion(
        run_dir / "mineru_paper", markdown="No rendered table.", blocks=[legacy],
    )
    conflicting_html = TABLE_HTML.replace("<td>0</td>", "<td>9.9</td>")
    v2 = [[], [], [{
        "type": "table", "content": {"html": conflicting_html},
        "bbox": [10, 20, 300, 180],
    }]]
    (md_path.parent / "paper_content_list_v2.json").write_text(
        json.dumps(v2, ensure_ascii=False), encoding="utf-8",
    )

    _, _, workspace = _read_workspace(ReadFileNode(), pdf, run_dir)

    assert len(workspace.table_paths) == 1
    ref = _table_refs(workspace)[0]
    assert ref["issues"]
    matches = search_table(workspace, "9.9")
    assert len(matches) == 1
    context = matches[0]["table_context"]
    assert context["issues"] == ref["issues"]
    assert any("disagree" in issue for issue in context["issues"])
    assert len(json.dumps(context, ensure_ascii=False)) < 5000
    assert context["truncated"] is True
    assert {item["raw_html"] for item in ref["representations"]} == {conflicting_html, TABLE_HTML}
