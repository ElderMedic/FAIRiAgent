"""Tests for optional MinerU-Popo integration."""

from pathlib import Path

from fairifier.services.mineru_popo import (
    is_popo_available,
    try_enrich_conversion_with_popo,
)


def test_popo_disabled_by_default(monkeypatch):
    monkeypatch.setattr("fairifier.services.mineru_popo.config.mineru_popo_enabled", False)
    assert is_popo_available() is False
    info = {"parse_dir": "/tmp/parse"}
    assert try_enrich_conversion_with_popo(info) == info


def test_popo_pilot_metrics_on_vlm_layout(tmp_path: Path):
    doc = "paper"
    parse_dir = tmp_path / f"mineru_{doc}" / doc / "vlm"
    parse_dir.mkdir(parents=True)
    (parse_dir / f"{doc}.md").write_text("# Title\n\nParagraph.", encoding="utf-8")
    (parse_dir / f"{doc}_content_list_v2.json").write_text(
        '[{"type": "text", "text": "Paragraph.", "bbox": [1,2,3,4]}]',
        encoding="utf-8",
    )

    from evaluation.scripts.run_mineru_popo_pilot import _analyze_mineru_tree

    report = _analyze_mineru_tree(tmp_path / f"mineru_{doc}", doc)
    assert report["baseline"]["markdown_headings"] == 1
    assert report["baseline"]["structured_block_count"] == 1
    assert report["popo"]["enabled"] is False
