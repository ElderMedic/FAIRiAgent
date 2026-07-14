import importlib.util
import json
import sys
from pathlib import Path
from types import SimpleNamespace


def _load_batch_runner():
    path = (
        Path(__file__).resolve().parents[1]
        / "evaluation"
        / "scripts"
        / "run_batch_evaluation.py"
    )
    spec = importlib.util.spec_from_file_location("batch_evaluation_runner", path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_missing_resume_artifacts_auto_requires_gate_files(tmp_path):
    runner = _load_batch_runner()
    (tmp_path / "metadata.json").write_text("{}", encoding="utf-8")

    missing = runner.missing_resume_artifacts(tmp_path, auto_mode=True)

    assert "metadata.json" not in missing
    assert missing == [
        "workflow_report.json",
        "runtime_config.json",
        "auto_repair_trace.json",
        "isa_values_json.json",
        "metadata_fairds.xlsx",
    ]


def test_missing_resume_artifacts_non_auto_accepts_metadata_only(tmp_path):
    runner = _load_batch_runner()
    (tmp_path / "metadata.json").write_text("{}", encoding="utf-8")

    assert runner.missing_resume_artifacts(tmp_path, auto_mode=False) == []


def test_single_document_resume_skips_non_auto_metadata_only(tmp_path, monkeypatch):
    runner = _load_batch_runner()
    doc = tmp_path / "paper.md"
    doc.write_text("# paper", encoding="utf-8")
    output = tmp_path / "runs"
    run_dir = output / "doc_a" / "run_1"
    run_dir.mkdir(parents=True)
    (run_dir / "eval_result.json").write_text(
        json.dumps({"success": True, "document_id": "doc_a"}),
        encoding="utf-8",
    )
    (run_dir / "metadata.json").write_text("{}", encoding="utf-8")
    monkeypatch.delenv("FAIRIFIER_RETRIEVAL_MODE", raising=False)

    def fail_run(*args, **kwargs):
        raise AssertionError("subprocess.run should not be called")

    monkeypatch.setattr(runner.subprocess, "run", fail_run)

    result = runner.BatchEvaluationRunner._run_single_document(
        object(),
        doc_id="doc_a",
        doc_path=str(doc),
        config_name="config",
        config_path=tmp_path / "config.env",
        config_output_dir=output,
        run_idx=1,
        timeout=1,
    )

    assert result["success"] is True


def test_single_document_resume_reruns_auto_metadata_only(tmp_path, monkeypatch):
    runner = _load_batch_runner()
    doc = tmp_path / "paper.md"
    doc.write_text("# paper", encoding="utf-8")
    output = tmp_path / "runs"
    run_dir = output / "doc_a" / "run_1"
    run_dir.mkdir(parents=True)
    (run_dir / "eval_result.json").write_text(
        json.dumps({"success": True, "document_id": "doc_a"}),
        encoding="utf-8",
    )
    (run_dir / "metadata.json").write_text(
        json.dumps({"isa_structure": {}}),
        encoding="utf-8",
    )
    monkeypatch.setenv("FAIRIFIER_RETRIEVAL_MODE", "auto")
    calls = []

    def fake_run(cmd, **kwargs):
        calls.append(cmd)
        return SimpleNamespace(returncode=0, stdout="ok", stderr="")

    monkeypatch.setattr(runner.subprocess, "run", fake_run)

    result = runner.BatchEvaluationRunner._run_single_document(
        object(),
        doc_id="doc_a",
        doc_path=str(doc),
        config_name="config",
        config_path=tmp_path / "config.env",
        config_output_dir=output,
        run_idx=1,
        timeout=1,
    )

    assert calls
    assert result["success"] is True
    assert result["metadata_json_path"] == str(run_dir / "metadata.json")
