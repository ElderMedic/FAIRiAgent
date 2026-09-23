"""The historical aggregate evaluator must not choose a best repetition."""

from pathlib import Path

import pytest

from evaluation.scripts.evaluate_outputs import EvaluationOrchestrator


def test_legacy_evaluator_rejects_multiple_repetitions(tmp_path: Path) -> None:
    model_dir = tmp_path / "model"
    document_dir = model_dir / "document_a"
    (document_dir / "run_01").mkdir(parents=True)
    (document_dir / "run_02").mkdir()

    orchestrator = EvaluationOrchestrator.__new__(EvaluationOrchestrator)
    with pytest.raises(ValueError, match="refuses to select a best run"):
        orchestrator._evaluate_model_config(model_dir, "model")
