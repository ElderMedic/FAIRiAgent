import zipfile
from pathlib import Path

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
