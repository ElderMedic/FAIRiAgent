"""Cloud providers must ignore Compose's host Ollama base URL."""

from fairifier.config import FAIRifierConfig, apply_env_overrides, is_default_ollama_base_url


def test_compose_ollama_address_counts_as_the_default():
    assert is_default_ollama_base_url("http://host.docker.internal:11434")
    assert is_default_ollama_base_url("http://localhost:11434/")
    assert is_default_ollama_base_url(None)
    assert not is_default_ollama_base_url("https://api.deepseek.com")


def test_cloud_providers_replace_compose_ollama_base(monkeypatch):
    monkeypatch.setenv("FAIRIFIER_LLM_BASE_URL", "http://host.docker.internal:11434")
    monkeypatch.setenv("LLM_API_KEY", "sk-test")
    monkeypatch.delenv("FAIRIFIER_LLM_MODEL", raising=False)
    monkeypatch.delenv("QWEN_API_BASE_URL", raising=False)
    monkeypatch.delenv("DEEPSEEK_API_BASE_URL", raising=False)
    monkeypatch.delenv("ZHIPU_API_BASE_URL", raising=False)

    expected = {
        "deepseek": "https://api.deepseek.com",
        "zhipu": "https://open.bigmodel.cn/api/paas/v4",
        "qwen": "https://dashscope-intl.aliyuncs.com/compatible-mode/v1",
    }
    for provider, base_url in expected.items():
        monkeypatch.setenv("LLM_PROVIDER", provider)
        cfg = FAIRifierConfig()
        apply_env_overrides(cfg)
        assert cfg.llm_base_url == base_url


def test_explicit_provider_base_url_still_wins(monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "zhipu")
    monkeypatch.setenv("LLM_API_KEY", "sk-test")
    monkeypatch.setenv("FAIRIFIER_LLM_BASE_URL", "http://host.docker.internal:11434")
    monkeypatch.setenv("ZHIPU_API_BASE_URL", "https://zhipu.example/v4")
    monkeypatch.delenv("FAIRIFIER_LLM_MODEL", raising=False)

    cfg = FAIRifierConfig()
    apply_env_overrides(cfg)

    assert cfg.llm_base_url == "https://zhipu.example/v4"
