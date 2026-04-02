from fairifier.apps.api.services import runner
from fairifier.config import config
from fairifier.utils import llm_helper as llm_helper_module


def test_llm_helper_reinitializes_when_api_key_changes(
    monkeypatch,
):
    original_provider = config.llm_provider
    original_model = config.llm_model
    original_base_url = config.llm_base_url
    original_api_key = config.llm_api_key

    class FakeLLMHelper:
        created = 0

        def __init__(self):
            FakeLLMHelper.created += 1

    monkeypatch.setattr(
        llm_helper_module, "LLMHelper", FakeLLMHelper
    )
    llm_helper_module.reset_llm_helper()

    try:
        monkeypatch.setattr(config, "llm_provider", "openai")
        monkeypatch.setattr(config, "llm_model", "gpt-4.1")
        monkeypatch.setattr(
            config, "llm_base_url", "https://api.openai.com/v1"
        )
        monkeypatch.setattr(config, "llm_api_key", "key-one")

        first = llm_helper_module.get_llm_helper()
        second = llm_helper_module.get_llm_helper()
        assert first is second
        assert FakeLLMHelper.created == 1

        monkeypatch.setattr(config, "llm_api_key", "key-two")
        third = llm_helper_module.get_llm_helper()

        assert third is not first
        assert FakeLLMHelper.created == 2
    finally:
        monkeypatch.setattr(
            config, "llm_provider", original_provider
        )
        monkeypatch.setattr(config, "llm_model", original_model)
        monkeypatch.setattr(
            config, "llm_base_url", original_base_url
        )
        monkeypatch.setattr(config, "llm_api_key", original_api_key)
        llm_helper_module.reset_llm_helper()


def test_runner_config_override_cycle_resets_cached_clients(
    monkeypatch,
):
    reset_calls = {"llm": 0, "mem0": 0}

    monkeypatch.setattr(
        "fairifier.utils.llm_helper.reset_llm_helper",
        lambda: reset_calls.__setitem__(
            "llm", reset_calls["llm"] + 1
        ),
    )
    monkeypatch.setattr(
        "fairifier.services.mem0_service.reset_mem0_service",
        lambda: reset_calls.__setitem__(
            "mem0", reset_calls["mem0"] + 1
        ),
    )

    original_state = runner._snapshot_config_state()
    runner._apply_config_overrides(
        {
            "llm_provider": "openai",
            "llm_model": "gpt-4.1",
            "llm_base_url": "https://api.openai.com/v1",
            "llm_api_key": "session-key",
            "fair_ds_api_url": "https://fair-ds.example/api",
        }
    )
    runner._restore_config_state(original_state)

    assert reset_calls["llm"] == 2
    assert reset_calls["mem0"] == 2
