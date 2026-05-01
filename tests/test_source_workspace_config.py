from fairifier.config import FAIRifierConfig, apply_env_overrides


def test_source_workspace_env_overrides(monkeypatch):
    monkeypatch.setenv("FAIRIFIER_SOURCE_WORKSPACE_ENABLED", "false")
    monkeypatch.setenv("FAIRIFIER_SOURCE_WORKSPACE_DIR_NAME", "custom_sources")
    monkeypatch.setenv("FAIRIFIER_SOURCE_MAX_SELECTED_INPUTS", "13")
    monkeypatch.setenv("FAIRIFIER_SOURCE_INVENTORY_MAX_CHARS_PER_SOURCE", "1234")
    monkeypatch.setenv("FAIRIFIER_SOURCE_READ_MAX_CHARS", "5678")
    monkeypatch.setenv("FAIRIFIER_SOURCE_GREP_CONTEXT_CHARS", "321")
    monkeypatch.setenv("FAIRIFIER_SOURCE_MAX_SEARCH_RESULTS", "17")
    monkeypatch.setenv("FAIRIFIER_SOURCE_MIN_RELEVANCE_SCORE", "0.42")
    monkeypatch.setenv("FAIRIFIER_SOURCE_OUTLIER_POLICY", "exclude")
    monkeypatch.setenv("FAIRIFIER_METADATA_CONTEXT_MODE", "evidence_only")
    monkeypatch.setenv("FAIRIFIER_METADATA_MAX_CONTEXT_CHARS_PER_FIELD", "2222")
    monkeypatch.setenv("FAIRIFIER_TABLE_SEARCH_MAX_ROWS", "3333")

    cfg = FAIRifierConfig()
    apply_env_overrides(cfg)

    assert cfg.source_workspace_enabled is False
    assert cfg.source_workspace_dir_name == "custom_sources"
    assert cfg.source_max_selected_inputs == 13
    assert cfg.source_inventory_max_chars_per_source == 1234
    assert cfg.source_read_max_chars == 5678
    assert cfg.source_grep_context_chars == 321
    assert cfg.source_max_search_results == 17
    assert cfg.source_min_relevance_score == 0.42
    assert cfg.source_outlier_policy == "exclude"
    assert cfg.metadata_context_mode == "evidence_only"
    assert cfg.metadata_max_context_chars_per_field == 2222
    assert cfg.table_search_max_rows == 3333
