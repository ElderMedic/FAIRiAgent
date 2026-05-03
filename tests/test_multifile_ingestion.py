import json
import zipfile
from pathlib import Path

import pandas as pd

from fairifier.config import config
from fairifier.graph.langgraph_app import FAIRifierLangGraphApp


def _make_app_without_init() -> FAIRifierLangGraphApp:
    # We only exercise file-ingestion helpers, so bypass heavy agent initialization.
    return object.__new__(FAIRifierLangGraphApp)


def test_read_tabular_csv_preview(tmp_path: Path):
    app = _make_app_without_init()
    csv_path = tmp_path / "previous_run.csv"
    csv_path.write_text(
        "sample_id,value,unit\ns1,12.5,mg/L\ns2,11.8,mg/L\n",
        encoding="utf-8",
    )

    text = app._read_tabular_content(str(csv_path))
    assert "Table file: previous_run.csv" in text
    assert "sample_id\tvalue\tunit" in text
    assert "s1\t12.5\tmg/L" in text


def test_read_directory_bundle_aggregates_supported_files(tmp_path: Path, monkeypatch):
    app = _make_app_without_init()
    monkeypatch.setattr(config, "multi_file_max_inputs", 8)

    (tmp_path / "notes.txt").write_text("experiment notes", encoding="utf-8")
    (tmp_path / "values.tsv").write_text(
        "metric\tvalue\npH\t7.1\n",
        encoding="utf-8",
    )
    (tmp_path / "ignore.bin").write_bytes(b"\x00\x01")

    text, info = app._read_multi_file_bundle(
        root_dir=tmp_path,
        output_dir=None,
        source_method="directory_bundle",
    )

    assert "=== Source 1:" in text
    assert "notes.txt" in text
    assert "values.tsv" in text
    assert info["method"] == "directory_bundle"
    assert info["files_processed"] == 2
    assert info["files_discovered_supported"] == 2
    assert info["truncated_by_limit"] is False


def test_read_zip_bundle_via_entrypoint(tmp_path: Path, monkeypatch):
    app = _make_app_without_init()
    monkeypatch.setattr(config, "multi_file_max_inputs", 8)

    src_dir = tmp_path / "bundle_src"
    src_dir.mkdir()
    (src_dir / "main.txt").write_text("paper summary", encoding="utf-8")
    (src_dir / "history.csv").write_text(
        "timepoint,measurement\nT0,0.11\nT1,0.18\n",
        encoding="utf-8",
    )
    zip_path = tmp_path / "bundle.zip"
    with zipfile.ZipFile(zip_path, "w") as zf:
        zf.write(src_dir / "main.txt", arcname="main.txt")
        zf.write(src_dir / "history.csv", arcname="history.csv")

    text, info = app._read_document_content(str(zip_path), output_dir=None)
    assert "main.txt" in text
    assert "history.csv" in text
    assert info["method"] == "zip_bundle"
    assert info["files_processed"] == 2


def test_read_single_file_materializes_source_workspace(tmp_path: Path):
    app = _make_app_without_init()
    input_path = tmp_path / "paper.md"
    output_dir = tmp_path / "out"
    input_path.write_text("# Study\n\nrare accession PRJNA999999", encoding="utf-8")

    text, info = app._read_document_content(str(input_path), output_dir=str(output_dir))

    assert "rare accession" in text
    workspace = info["source_workspace"]
    manifest_path = Path(workspace["manifest_path"])
    assert manifest_path.exists()
    assert "paper.md" in manifest_path.read_text(encoding="utf-8")
    assert Path(workspace["summary_path"]).exists()


def test_read_directory_bundle_materializes_source_workspace(tmp_path: Path, monkeypatch):
    app = _make_app_without_init()
    monkeypatch.setattr(config, "multi_file_max_inputs", 8)

    output_dir = tmp_path / "out"
    (tmp_path / "main.md").write_text("# Main\n\nprimary study", encoding="utf-8")
    (tmp_path / "supplement.md").write_text("# Supplement\n\nextra method", encoding="utf-8")

    _, info = app._read_multi_file_bundle(
        root_dir=tmp_path,
        output_dir=str(output_dir),
        source_method="directory_bundle",
    )

    workspace = info["source_workspace"]
    manifest = Path(workspace["manifest_path"]).read_text(encoding="utf-8")
    assert '"source_count": 2' in manifest
    assert "supplement.md" in manifest


def test_read_tabular_file_workspace_preserves_rows_outside_preview(tmp_path: Path, monkeypatch):
    app = _make_app_without_init()
    monkeypatch.setattr(config, "table_preview_max_rows", 1)
    csv_path = tmp_path / "samples.csv"
    output_dir = tmp_path / "out"
    csv_path.write_text(
        "sample_id,organism\nS1,not relevant\nS2,Eisenia fetida\n",
        encoding="utf-8",
    )

    _, info = app._read_document_content(str(csv_path), output_dir=str(output_dir))

    workspace = info["source_workspace"]
    table_paths = workspace["table_paths"]
    assert table_paths
    table_text = Path(next(iter(table_paths.values()))).read_text(encoding="utf-8")
    assert "Eisenia fetida" in table_text


def test_read_directory_bundle_tracks_failures_and_limit_truncation(tmp_path: Path, monkeypatch):
    app = _make_app_without_init()
    monkeypatch.setattr(config, "multi_file_max_inputs", 1)

    bad_pdf = tmp_path / "99_bad.pdf"
    ok_txt = tmp_path / "01_notes.txt"
    bad_pdf.write_text("dummy", encoding="utf-8")
    ok_txt.write_text("ok", encoding="utf-8")

    def fake_read_single(path: str, output_dir=None):
        if path.endswith("bad.pdf"):
            raise ValueError("forced parse error")
        return "notes", {"method": "direct_read"}

    monkeypatch.setattr(app, "_read_single_document_content", fake_read_single)

    text, info = app._read_multi_file_bundle(
        root_dir=tmp_path,
        output_dir=None,
        source_method="directory_bundle",
    )

    assert "=== Source 1:" in text
    assert info["files_discovered_supported"] == 2
    assert info["files_processed"] == 1
    assert info["truncated_by_limit"] is True
    assert info["failed_sources"] == []


def test_read_directory_bundle_prioritizes_research_sources_before_limit(tmp_path: Path, monkeypatch):
    app = _make_app_without_init()
    monkeypatch.setattr(config, "multi_file_max_inputs", 2)

    (tmp_path / "00_random_notes.txt").write_text("unrelated admin notes", encoding="utf-8")
    (tmp_path / "main_paper.md").write_text("# Main paper\n\nstudy title", encoding="utf-8")
    (tmp_path / "supplement_methods.md").write_text("# Supplement\n\nprotocol", encoding="utf-8")

    text, info = app._read_multi_file_bundle(
        root_dir=tmp_path,
        output_dir=None,
        source_method="directory_bundle",
    )

    assert "main_paper.md" in text
    assert "supplement_methods.md" in text
    assert "00_random_notes.txt" not in text
    assert info["truncated_by_limit"] is True


def test_read_directory_bundle_records_failed_sources(tmp_path: Path, monkeypatch):
    app = _make_app_without_init()
    monkeypatch.setattr(config, "multi_file_max_inputs", 8)

    bad_pdf = tmp_path / "99_bad.pdf"
    ok_txt = tmp_path / "01_notes.txt"
    bad_pdf.write_text("dummy", encoding="utf-8")
    ok_txt.write_text("ok", encoding="utf-8")

    def fake_read_single(path: str, output_dir=None):
        if path.endswith("99_bad.pdf"):
            raise ValueError("forced parse error")
        return "notes", {"method": "direct_read"}

    monkeypatch.setattr(app, "_read_single_document_content", fake_read_single)

    text, info = app._read_multi_file_bundle(
        root_dir=tmp_path,
        output_dir=None,
        source_method="directory_bundle",
    )

    assert "notes" in text
    assert info["files_discovered_supported"] == 2
    assert info["files_processed"] == 1
    assert info["truncated_by_limit"] is False
    assert len(info["failed_sources"]) == 1
    assert info["failed_sources"][0]["path"] == "99_bad.pdf"


def test_read_directory_bundle_ignores_existing_mineru_artifacts(tmp_path: Path, monkeypatch):
    app = _make_app_without_init()
    monkeypatch.setattr(config, "multi_file_max_inputs", 8)

    (tmp_path / "earthworm_4n_paper_bioRxiv.pdf").write_text("root pdf placeholder", encoding="utf-8")
    mineru_dir = tmp_path / "mineru_earthworm_4n_paper_bioRxiv" / "earthworm_4n_paper_bioRxiv" / "vlm"
    mineru_dir.mkdir(parents=True)
    (mineru_dir / "earthworm_4n_paper_bioRxiv.md").write_text("# Converted\n", encoding="utf-8")
    (mineru_dir / "earthworm_4n_paper_bioRxiv_layout.pdf").write_text("layout pdf", encoding="utf-8")
    (mineru_dir / "earthworm_4n_paper_bioRxiv_origin.pdf").write_text("origin pdf", encoding="utf-8")

    seen_paths = []

    def fake_read_single(path: str, output_dir=None):
        seen_paths.append(Path(path).name)
        return f"content for {Path(path).name}", {"method": "direct_read"}

    monkeypatch.setattr(app, "_read_single_document_content", fake_read_single)

    text, info = app._read_multi_file_bundle(
        root_dir=tmp_path,
        output_dir=None,
        source_method="directory_bundle",
    )

    assert "earthworm_4n_paper_bioRxiv.pdf" in text
    assert "earthworm_4n_paper_bioRxiv_layout.pdf" not in text
    assert "earthworm_4n_paper_bioRxiv_origin.pdf" not in text
    assert seen_paths == ["earthworm_4n_paper_bioRxiv.pdf"]
    assert info["files_discovered_supported"] == 1


def test_read_tabular_tables_normalizes_timestamp_values(tmp_path: Path):
    app = _make_app_without_init()
    output_dir = tmp_path / "out"
    xlsx_path = tmp_path / "samples.xlsx"

    df = pd.DataFrame(
        [
            {
                "sample_id": "S1",
                "collection_time": pd.Timestamp("2024-01-02T03:04:05"),
            }
        ]
    )
    df.to_excel(xlsx_path, index=False)

    _, info = app._read_document_content(str(xlsx_path), output_dir=str(output_dir))

    workspace = info["source_workspace"]
    table_path = Path(next(iter(workspace["table_paths"].values())))
    serialized = table_path.read_text(encoding="utf-8")

    assert "2024-01-02T03:04:05" in serialized


def test_read_tabular_tables_preserves_numeric_types_in_jsonl(tmp_path: Path):
    app = _make_app_without_init()
    output_dir = tmp_path / "out"
    xlsx_path = tmp_path / "measurements.xlsx"
    df = pd.DataFrame(
        [
            {
                "sample_id": "S1",
                "n_reads": 1000,
                "ratio": 0.25,
                "collection_time": pd.Timestamp("2024-01-02T03:04:05"),
            }
        ]
    )
    df.to_excel(xlsx_path, index=False)

    _, info = app._read_document_content(str(xlsx_path), output_dir=str(output_dir))

    workspace = info["source_workspace"]
    table_path = Path(next(iter(workspace["table_paths"].values())))
    row = json.loads(table_path.read_text(encoding="utf-8").splitlines()[0])

    assert row["n_reads"] == 1000
    assert isinstance(row["n_reads"], int)
    assert row["ratio"] == 0.25
    assert isinstance(row["ratio"], float)
    assert row["collection_time"] == "2024-01-02T03:04:05"


def test_directory_bundle_collects_bio_file_paths(tmp_path: Path):
    """Multi-file bundles must aggregate host_path for BioMetadataAgent."""
    app = _make_app_without_init()
    out = tmp_path / "out"
    bundle = tmp_path / "bundle"
    bundle.mkdir()
    (bundle / "note.txt").write_text("companion doc", encoding="utf-8")
    bam = bundle / "reads.bam"
    bam.write_bytes(b"")
    _, info = app._read_document_content(str(bundle), output_dir=str(out))

    assert info.get("method") == "directory_bundle"
    bio_paths = info.get("bio_file_paths") or []
    assert len(bio_paths) == 1
    assert Path(bio_paths[0]).resolve() == bam.resolve()
    bio_docs = [d for d in info["input_documents"] if d.get("content_type") == "bio_binary"]
    assert len(bio_docs) == 1
    assert Path(bio_docs[0]["host_path"]).resolve() == bam.resolve()
