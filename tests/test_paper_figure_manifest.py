"""Tests for the paper_experiments_v1 figure manifest scope rules."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[1]))

from evaluation.paper_experiments_v1.figure_manifest_lib import (  # type: ignore[attr-defined]
    MAIN_BENCHMARK_DOCS,
    expected_model_keys,
    include_main_text_cell,
    normalize_condition_name,
    normalize_model_name,
)


def test_include_main_text_cell_accepts_main_benchmark_phase0_cell():
    cell = {
        "condition": "baseline_b1",
        "document": "earthworm",
        "model_key": "qwen3.6-27b",
        "has_metadata": True,
        "has_eval_result": True,
        "success": True,
        "source_kind": "phase0_run",
    }
    assert include_main_text_cell(cell) is True


def test_include_main_text_cell_rejects_supplementary_document():
    cell = {
        "condition": "baseline_b1",
        "document": "biorem",
        "model_key": "qwen3.6-27b",
        "has_metadata": True,
        "has_eval_result": True,
        "success": True,
        "source_kind": "phase0_run",
    }
    assert include_main_text_cell(cell) is False


def test_include_main_text_cell_rejects_legacy_multifile_artifact():
    cell = {
        "condition": "full_pipeline_multifile_derived",
        "document": "earthworm",
        "model_key": "qwen3.6-35b",
        "has_metadata": True,
        "has_eval_result": True,
        "success": True,
        "source_kind": "legacy_multifile",
    }
    assert include_main_text_cell(cell) is False


def test_normalize_condition_name_maps_phase0_names():
    assert normalize_condition_name("baseline_b1") == "B1"
    assert normalize_condition_name("baseline_b2") == "B2"
    assert normalize_condition_name("baseline_b3") == "B3"
    assert normalize_condition_name("full_pipeline") == "Full"


def test_normalize_model_name_maps_deepseek():
    assert normalize_model_name("deepseek_v4-pro_v1.4.0") == "deepseek-v4-pro"


def test_main_benchmark_docs_contains_exact_eight_documents():
    assert MAIN_BENCHMARK_DOCS == {
        "aetherobacter_fasciculatus_genome",
        "arabidopsis_vacuolar_srna",
        "biosensor",
        "earthworm",
        "human_gut_microbiome_temporal",
        "pea_cold_stress",
        "pseudomonas_recombinase_screen",
        "sea_cucumber_gut_metagenome",
    }


def test_expected_model_keys_match_phase0_policy():
    assert expected_model_keys("baseline_b1") == [
        "qwen3.5-9b",
        "qwen3.6-27b",
        "qwen3.6-35b",
        "gemma4-31b",
        "gpt-oss-20b",
    ]


def test_include_main_text_cell_rejects_unsuccessful_run_even_with_metadata():
    cell = {
        "condition": "full_pipeline",
        "document": "biosensor",
        "model_key": "gemma4-31b",
        "has_metadata": True,
        "has_eval_result": True,
        "success": False,
        "source_kind": "phase0_run",
    }
    assert include_main_text_cell(cell) is False
    assert expected_model_keys("baseline_b2") == [
        "qwen3.6-27b",
        "qwen3.6-35b",
        "gemma4-31b",
        "gpt-oss-20b",
    ]
