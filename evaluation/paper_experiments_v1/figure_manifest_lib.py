"""Shared helpers for the manuscript-grade figure manifest."""

from __future__ import annotations

from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]
PAPER_ROOT = PROJECT_ROOT / "evaluation" / "paper_experiments_v1"
RUNS_DIR = PAPER_ROOT / "runs"
ANALYSIS_DIR = PAPER_ROOT / "analysis"
VALUES_DIR = PROJECT_ROOT / "evaluation" / "datasets" / "annotated" / "values"

MAIN_BENCHMARK_DOCS = {
    "aetherobacter_fasciculatus_genome",
    "arabidopsis_vacuolar_srna",
    "biosensor",
    "earthworm",
    "human_gut_microbiome_temporal",
    "pea_cold_stress",
    "pseudomonas_recombinase_screen",
    "sea_cucumber_gut_metagenome",
}

CONDITION_DISPLAY = {
    "baseline_b1": "B1",
    "baseline_b2": "B2",
    "baseline_b3": "B3",
    "full_pipeline": "Full",
}

MODEL_DISPLAY = {
    "ollama_qwen3.5-9b_v1.4.0": "qwen3.5-9b",
    "ollama_qwen3.6-27b_v1.4.0": "qwen3.6-27b",
    "ollama_qwen3.6-35b_v1.4.0": "qwen3.6-35b",
    "ollama_gemma4-31b_v1.4.0": "gemma4-31b",
    "ollama_gpt-oss-20b_v1.5.0": "gpt-oss-20b",
    "deepseek_v4-pro_v1.4.0": "deepseek-v4-pro",
}

MODEL_CONFIG_STEMS = {
    "qwen3.5-9b": "ollama_qwen3.5-9b_v1.4.0",
    "qwen3.6-27b": "ollama_qwen3.6-27b_v1.4.0",
    "qwen3.6-35b": "ollama_qwen3.6-35b_v1.4.0",
    "gemma4-31b": "ollama_gemma4-31b_v1.4.0",
    "gpt-oss-20b": "ollama_gpt-oss-20b_v1.5.0",
}

EXCLUDED_SOURCE_KINDS = {
    "legacy_multifile",
    "legacy_smoke",
    "supplementary_only",
}


def normalize_condition_name(raw: str) -> str:
    """Map run-directory condition names to manuscript labels."""
    return CONDITION_DISPLAY.get(raw, raw)


def normalize_model_name(raw: str) -> str:
    """Map config-stem names to manuscript model labels."""
    return MODEL_DISPLAY.get(raw, raw)


def expected_model_keys(condition: str) -> list[str]:
    """Return the expected model set for a Phase-0 condition."""
    if condition == "baseline_b1":
        return [
            "qwen3.5-9b",
            "qwen3.6-27b",
            "qwen3.6-35b",
            "gemma4-31b",
            "gpt-oss-20b",
        ]
    if condition in {"baseline_b2", "baseline_b3", "full_pipeline"}:
        return [
            "qwen3.6-27b",
            "qwen3.6-35b",
            "gemma4-31b",
            "gpt-oss-20b",
        ]
    return []


def detect_source_kind(condition: str, document: str) -> str:
    """Classify a run for inclusion logic."""
    if condition == "full_pipeline_multifile_derived":
        return "legacy_multifile"
    if condition in {"local_smoke", "baseline_b1_gemma4"}:
        return "legacy_smoke"
    if document in {"biorem", "pomato", "compbiobench"}:
        return "supplementary_only"
    return "phase0_run"


def include_main_text_cell(cell: dict) -> bool:
    """Return True if a cell can appear in main-text quantitative figures."""
    return (
        cell.get("condition") in CONDITION_DISPLAY
        and cell.get("document") in MAIN_BENCHMARK_DOCS
        and cell.get("has_metadata") is True
        and cell.get("has_eval_result") is True
        and cell.get("success") is True
        and cell.get("source_kind") not in EXCLUDED_SOURCE_KINDS
    )

