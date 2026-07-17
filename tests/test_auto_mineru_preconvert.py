import importlib.util
import json
import sys
from types import SimpleNamespace
from pathlib import Path


def _load_preconvert():
    root = Path(__file__).resolve().parents[1]
    proto = root / "evaluation" / "prototypes" / "auto_repair_classifier"
    sys.path.insert(0, str(proto))
    path = proto / "preconvert_mineru.py"
    spec = importlib.util.spec_from_file_location("auto_mineru_preconvert", path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_build_preconvert_tasks_targets_missing_pdf_outputs(tmp_path):
    preconvert = _load_preconvert()
    source = tmp_path / "paper.pdf"
    source.write_text("pdf placeholder", encoding="utf-8")
    ground_truth = tmp_path / "gt.json"
    ground_truth.write_text(
        json.dumps(
            {
                "documents": [
                    {
                        "document_id": "doc_a",
                        "document_path": str(source),
                    }
                ]
            }
        ),
        encoding="utf-8",
    )

    tasks = preconvert.build_preconvert_tasks(
        ground_truth=ground_truth,
        documents=["doc_a"],
        cli="mineru",
        backend="pipeline",
        method="txt",
        lang="en",
        url=None,
    )

    assert len(tasks) == 1
    task = tasks[0]
    assert task.document_id == "doc_a"
    assert task.source_path == source
    assert task.output_dir == tmp_path / "mineru_paper"
    assert task.command == [
        "mineru",
        "-p",
        str(source),
        "-o",
        str(tmp_path / "mineru_paper"),
        "-b",
        "pipeline",
        "-m",
        "txt",
        "-l",
        "en",
    ]


def test_build_preconvert_tasks_skips_already_preconverted_pdf(tmp_path):
    preconvert = _load_preconvert()
    source = tmp_path / "paper.pdf"
    source.write_text("pdf placeholder", encoding="utf-8")
    converted = tmp_path / "mineru_paper" / "paper" / "auto" / "paper.md"
    converted.parent.mkdir(parents=True)
    converted.write_text("# converted", encoding="utf-8")
    ground_truth = tmp_path / "gt.json"
    ground_truth.write_text(
        json.dumps(
            {
                "documents": [
                    {
                        "document_id": "doc_a",
                        "document_path": str(source),
                    }
                ]
            }
        ),
        encoding="utf-8",
    )

    assert (
        preconvert.build_preconvert_tasks(
            ground_truth=ground_truth,
            documents=["doc_a"],
        )
        == []
    )


def test_preconvert_report_writes_json_and_markdown(tmp_path):
    preconvert = _load_preconvert()
    source = tmp_path / "paper.pdf"
    task = preconvert.PreconvertTask(
        document_id="doc_a",
        source_path=source,
        output_dir=tmp_path / "mineru_paper",
        command=["mineru", "-p", str(source)],
    )
    report = preconvert.build_report(tasks=[task], executed=False)
    output = tmp_path / "report.json"

    preconvert.write_report(report, output)

    saved = json.loads(output.read_text(encoding="utf-8"))
    assert saved["task_count"] == 1
    markdown = output.with_suffix(".md").read_text(encoding="utf-8")
    assert "MinerU Preconversion Report" in markdown
    assert "mineru -p" in markdown


def test_run_tasks_requires_markdown_after_zero_exit(tmp_path, monkeypatch):
    preconvert = _load_preconvert()
    source = tmp_path / "paper.pdf"
    source.write_text("pdf placeholder", encoding="utf-8")
    task = preconvert.PreconvertTask(
        document_id="doc_a",
        source_path=source,
        output_dir=tmp_path / "mineru_paper",
        command=["mineru", "-p", str(source)],
    )

    def fake_run(*args, **kwargs):
        return SimpleNamespace(returncode=0, stdout="ok", stderr="")

    monkeypatch.setattr(preconvert.subprocess, "run", fake_run)

    results = preconvert.run_tasks([task], timeout=1)

    assert results[0]["status"] == "failed_missing_markdown"
    assert results[0]["preconverted_after"] is False
    assert "no reusable Markdown" in results[0]["stderr_tail"]


def test_run_tasks_marks_success_only_when_markdown_is_reusable(tmp_path, monkeypatch):
    preconvert = _load_preconvert()
    source = tmp_path / "paper.pdf"
    source.write_text("pdf placeholder", encoding="utf-8")
    output_dir = tmp_path / "mineru_paper"
    task = preconvert.PreconvertTask(
        document_id="doc_a",
        source_path=source,
        output_dir=output_dir,
        command=["mineru", "-p", str(source)],
    )

    def fake_run(*args, **kwargs):
        markdown = output_dir / "paper" / "auto" / "paper.md"
        markdown.parent.mkdir(parents=True)
        markdown.write_text("# converted", encoding="utf-8")
        return SimpleNamespace(returncode=0, stdout="ok", stderr="")

    monkeypatch.setattr(preconvert.subprocess, "run", fake_run)

    results = preconvert.run_tasks([task], timeout=1)

    assert results[0]["status"] == "success"
    assert results[0]["preconverted_after"] is True


def test_pipeline_dependency_errors_report_missing_modules(monkeypatch):
    preconvert = _load_preconvert()

    monkeypatch.setattr(
        "fairifier.services.mineru_health.importlib.util.find_spec",
        lambda name: None,
    )

    assert preconvert.dependency_errors_for_backend("pipeline") == [
        "missing_python_module:doclayout_yolo"
    ]
    assert preconvert.dependency_errors_for_backend("vlm-http-client") == []


def test_skipped_results_for_dependency_errors_do_not_invoke_mineru(tmp_path):
    preconvert = _load_preconvert()
    source = tmp_path / "paper.pdf"
    task = preconvert.PreconvertTask(
        document_id="doc_a",
        source_path=source,
        output_dir=tmp_path / "mineru_paper",
        command=["mineru", "-p", str(source)],
    )

    results = preconvert.skipped_results_for_dependency_errors(
        [task],
        ["missing_python_module:doclayout_yolo"],
    )
    report = preconvert.build_report(
        tasks=[task],
        executed=True,
        results=results,
        dependency_errors=["missing_python_module:doclayout_yolo"],
    )

    assert results[0]["status"] == "skipped_missing_dependency"
    assert results[0]["returncode"] is None
    assert report["failed_count"] == 1
    assert report["dependency_errors"] == ["missing_python_module:doclayout_yolo"]
    assert report["dependency_install_hint"] == (
        "pip install 'mineru[pipeline]>=3.4.0,<4'"
    )
    assert "Install missing MinerU pipeline dependencies" in report["next_action"]
    assert "mineru[pipeline]>=3.4.0,<4" in report["next_action"]
    assert "missing_python_module:doclayout_yolo" in preconvert.render_markdown(report)
    assert "mineru[pipeline]>=3.4.0,<4" in preconvert.render_markdown(report)
