from fairifier.utils.llm_helper import LLMHelper


def test_metadata_generation_does_not_hard_truncate_short_context_below_config_budget():
    helper = object.__new__(LLMHelper)

    long_text = "A" * 7000 + "KEEP_THIS_TAIL"
    prepared = helper._prepare_metadata_document_context(
        long_text,
        [{"field_name": "study_location", "isa_sheet": "study"}],
    )

    assert prepared == long_text
    assert prepared.endswith("KEEP_THIS_TAIL")


def test_metadata_generation_budget_uses_configurable_start_and_tail_context(monkeypatch):
    helper = object.__new__(LLMHelper)
    monkeypatch.setattr("fairifier.utils.llm_helper.config.metadata_max_context_chars_per_field", 100)

    prepared = helper._prepare_metadata_document_context(
        "A" * 200 + "TAIL",
        [{"field_name": "study_location", "isa_sheet": "study"}],
    )

    assert len(prepared) > 100
    assert "metadata context budget omitted" in prepared
    assert prepared.endswith("TAIL")
