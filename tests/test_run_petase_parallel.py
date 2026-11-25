"""Batch runner: degraded runs are rerun, earlier attempts are kept."""

import importlib.util
import json
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def runner(monkeypatch, tmp_path):
    spec = importlib.util.spec_from_file_location(
        "run_petase_parallel", ROOT / "evaluation/scripts/run_petase_parallel.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    monkeypatch.setattr(module, "prepare_input", lambda instance, root: tmp_path / "in")
    return module


def _run(runner, tmp_path, monkeypatch, log_lines, code=0):
    def fake_run(cmd, stdout, **kwargs):
        stdout.write("\n".join(log_lines) + "\n")
        return subprocess.CompletedProcess(cmd, code)

    monkeypatch.setattr(runner.subprocess, "run", fake_run)
    args = SimpleNamespace(out=tmp_path / "out", timeout=60, degraded_after=3)
    args.out.mkdir(exist_ok=True)
    instance = {"instance_id": "petase_x", "split": "dev", "source_path": "x.pdf"}
    return runner.run_one(instance, args, tmp_path / "run.env", args.out / "status.jsonl")


def test_run_that_lost_its_model_is_marked_degraded(runner, tmp_path, monkeypatch):
    record = _run(runner, tmp_path, monkeypatch, ["ok"] + ["❌ Ollama call failed for Critic: "] * 3)
    assert record["exit"] == "degraded" and record["failed_llm_calls"] == 3


def test_clean_run_and_a_single_retry_stay_successful(runner, tmp_path, monkeypatch):
    record = _run(runner, tmp_path, monkeypatch, ["ok", "❌ Ollama call failed for Critic: "])
    assert record["exit"] == 0


def test_rerun_keeps_the_earlier_attempt(runner, tmp_path, monkeypatch):
    (tmp_path / "out" / "petase_x").mkdir(parents=True)
    (tmp_path / "out" / "petase_x" / "metadata.json").write_text("{}")
    (tmp_path / "out" / "petase_x.log").write_text("first attempt\n")
    _run(runner, tmp_path, monkeypatch, ["second attempt"])
    kept = list((tmp_path / "out" / "_attempts" / "petase_x").iterdir())
    assert len(kept) == 1 and (kept[0] / "petase_x.log").read_text() == "first attempt\n"
    assert (kept[0] / "petase_x" / "metadata.json").exists()
    assert json.loads((tmp_path / "out" / "status.jsonl").read_text())["exit"] == 0


def test_skipped_paper_counts_as_done_for_skip_done(runner, tmp_path, monkeypatch):
    """A paper set aside on purpose (e.g. a review that explodes into 800k cells) is not retried."""
    out = tmp_path / "out"
    out.mkdir()
    (out / "run_status.jsonl").write_text(
        json.dumps({"instance_id": "a", "exit": "skipped", "reason": "plan too large"}) + "\n"
        + json.dumps({"instance_id": "b", "exit": 1}) + "\n")
    manifest = tmp_path / "manifest.json"
    manifest.write_text(json.dumps({"instances": [
        {"instance_id": i, "split": "dev", "source_path": "x.pdf"} for i in ("a", "b", "c")]}))
    monkeypatch.setattr(runner, "MANIFEST", manifest)
    env = tmp_path / "e.env"
    env.write_text("X=1\n")
    monkeypatch.setattr("sys.argv", ["run", "--env", str(env), "--out", str(out), "--skip-done", "--dry-run"])
    printed = []
    monkeypatch.setattr("builtins.print", lambda *a, **k: printed.append(" ".join(map(str, a))))
    runner.main()
    assert printed[0].startswith("2 papers")
