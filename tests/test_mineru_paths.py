"""Tests for MinerU output path resolution."""

from pathlib import Path

from fairifier.services.mineru_paths import (
    discover_structured_artifacts,
    find_markdown_in_tree,
    is_parse_subdir,
    load_content_list_v2,
)


def test_is_parse_subdir():
    assert is_parse_subdir("vlm")
    assert is_parse_subdir("office")
    assert is_parse_subdir("hybrid_auto")
    assert is_parse_subdir("auto")
    assert not is_parse_subdir("images")


def test_find_markdown_vlm_layout(tmp_path: Path):
    doc = "paper"
    md = tmp_path / doc / "vlm" / f"{doc}.md"
    md.parent.mkdir(parents=True)
    md.write_text("# Title\n\nBody", encoding="utf-8")

    located = find_markdown_in_tree(tmp_path, doc)
    assert located is not None
    path, images = located
    assert path == md
    assert images is None


def test_find_markdown_hybrid_layout(tmp_path: Path):
    doc = "paper"
    md = tmp_path / doc / "hybrid_auto" / f"{doc}.md"
    md.parent.mkdir(parents=True)
    md.write_text("# Hybrid", encoding="utf-8")

    located = find_markdown_in_tree(tmp_path, doc)
    assert located is not None
    assert located[0] == md


def test_discover_structured_artifacts(tmp_path: Path):
    parse_dir = tmp_path / "vlm"
    parse_dir.mkdir(parents=True)
    cl_v2 = parse_dir / "doc_content_list_v2.json"
    cl_v2.write_text('[{"type": "text", "text": "hello", "bbox": [0,0,1,1]}]', encoding="utf-8")

    artifacts = discover_structured_artifacts(parse_dir, "doc")
    assert "content_list_v2" in artifacts
    blocks = load_content_list_v2(artifacts["content_list_v2"])
    assert blocks[0]["type"] == "text"
    assert blocks[0]["text"] == "hello"
