"""Tests for mem0 service module."""

import pytest
from unittest.mock import Mock, patch, MagicMock


class TestMem0ServiceImport:
    """Test mem0 service import behavior."""
    
    def test_import_without_mem0_installed(self):
        """Test that import gracefully handles missing mem0."""
        # This should not raise an error
        from fairifier.services import (
            Mem0Service,
            get_mem0_service,
            build_mem0_config,
            reset_mem0_service
        )
        
        # Functions should be available (might be None if not installed)
        assert callable(get_mem0_service) or get_mem0_service is None
        assert callable(build_mem0_config) or build_mem0_config is None


class TestBuildMem0Config:
    """Test mem0 configuration builder."""
    
    def test_build_config_defaults(self):
        """Test building config with default values."""
        try:
            from fairifier.services.mem0_service import build_mem0_config
        except ImportError:
            pytest.skip("mem0 not installed")
        
        config = build_mem0_config()
        
        assert "llm" in config
        assert "embedder" in config
        assert "vector_store" in config
        
        assert config["llm"]["provider"] == "ollama"
        assert config["embedder"]["provider"] == "ollama"
        assert config["vector_store"]["provider"] == "qdrant"
    
    def test_build_config_custom(self):
        """Test building config with custom values."""
        try:
            from fairifier.services.mem0_service import build_mem0_config
        except ImportError:
            pytest.skip("mem0 not installed")
        
        config = build_mem0_config(
            llm_model="custom-model",
            llm_base_url="http://custom:1234",
            embedding_model="custom-embed",
            qdrant_host="qdrant-host",
            qdrant_port=9999,
            collection_name="custom_collection"
        )
        
        assert config["llm"]["config"]["model"] == "custom-model"
        assert config["llm"]["config"]["ollama_base_url"] == "http://custom:1234"
        assert config["embedder"]["config"]["model"] == "custom-embed"
        assert config["vector_store"]["config"]["host"] == "qdrant-host"
        assert config["vector_store"]["config"]["port"] == 9999
        assert config["vector_store"]["config"]["collection_name"] == "custom_collection"

    def test_build_config_openai_embedding(self):
        """Test building config for an OpenAI-compatible embedding provider."""
        try:
            from fairifier.services.mem0_service import build_mem0_config
        except ImportError:
            pytest.skip("mem0 not installed")

        config = build_mem0_config(
            llm_provider="openai",
            llm_model="qwen-flash",
            llm_base_url="https://dashscope-intl.aliyuncs.com/compatible-mode/v1",
            llm_api_key="llm-key",
            embedding_provider="openai",
            embedding_model="text-embedding-v4",
            embedding_base_url="https://dashscope-intl.aliyuncs.com/compatible-mode/v1",
            embedding_api_key="embed-key",
            embedding_model_dims=1024,
        )

        assert config["embedder"]["provider"] == "openai"
        assert config["embedder"]["config"]["model"] == "text-embedding-v4"
        assert config["embedder"]["config"]["openai_base_url"].startswith("https://dashscope")
        assert config["embedder"]["config"]["api_key"] == "embed-key"
        assert config["vector_store"]["config"]["embedding_model_dims"] == 1024

    def test_resolve_collection_name_changes_with_embedding_profile(self):
        """Collection naming should separate incompatible embedding configs."""
        try:
            from fairifier.services.mem0_service import (
                resolve_mem0_collection_name,
            )
        except ImportError:
            pytest.skip("mem0 not installed")

        first = resolve_mem0_collection_name(
            "fairifier_memories_quicktest",
            embedding_provider="ollama",
            embedding_model="nomic-embed-text-v2-moe:latest",
            embedding_dims=768,
            embedding_base_url="http://localhost:11434",
        )
        second = resolve_mem0_collection_name(
            "fairifier_memories_quicktest",
            embedding_provider="openai",
            embedding_model="text-embedding-v4",
            embedding_dims=1024,
            embedding_base_url="https://dashscope-intl.aliyuncs.com/compatible-mode/v1",
        )

        assert first != second
        assert first.startswith("fairifier_memories_quicktest__")
        assert second.startswith("fairifier_memories_quicktest__")


class TestMem0Service:
    """Test Mem0Service class."""
    
    def test_service_initialization_without_mem0(self):
        """Test service initialization fails gracefully without mem0."""
        try:
            from fairifier.services.mem0_service import Mem0Service
        except ImportError:
            pytest.skip("mem0 not installed")
        
        # Mock Memory.from_config to fail (simulating mem0 import error)
        with patch('mem0.Memory.from_config', side_effect=ImportError("mem0 not found")):
            config = {"test": "config"}
            service = Mem0Service(config)
            
            assert not service.is_available()
            assert not service.enabled
            assert service.memory is None
    
    def test_service_is_available_when_disabled(self):
        """Test is_available returns False when disabled."""
        try:
            from fairifier.services.mem0_service import Mem0Service
        except ImportError:
            pytest.skip("mem0 not installed")
        
        with patch('mem0.Memory.from_config', side_effect=Exception("Connection failed")):
            service = Mem0Service({})
            assert not service.is_available()
    
    @patch('mem0.Memory')
    def test_search_when_unavailable(self, mock_memory):
        """Test search returns empty list when service unavailable."""
        try:
            from fairifier.services.mem0_service import Mem0Service
        except ImportError:
            pytest.skip("mem0 not installed")
        
        # Service fails to initialize
        mock_memory.from_config.side_effect = Exception("Failed")
        service = Mem0Service({})
        
        result = service.search("test query", "session_id")
        assert result == []
    
    @patch('mem0.Memory')
    def test_search_success(self, mock_memory):
        """Test successful memory search."""
        try:
            from fairifier.services.mem0_service import Mem0Service
        except ImportError:
            pytest.skip("mem0 not installed")
        
        # Mock successful initialization and search
        mock_mem = MagicMock()
        mock_mem.search.return_value = {
            "results": [
                {"memory": "Test memory 1", "id": "1"},
                {"memory": "Test memory 2", "id": "2"}
            ]
        }
        mock_memory.from_config.return_value = mock_mem
        
        service = Mem0Service({"test": "config"})
        results = service.search("test query", "session_123", agent_id="TestAgent", limit=5)
        
        assert len(results) == 2
        assert results[0]["memory"] == "Test memory 1"
        # Called twice: health_check during init + actual search
        assert mock_mem.search.call_count == 2
        mock_mem.search.assert_called_with(
            query="test query",
            filters={"user_id": "session_123", "agent_id": "TestAgent"},
            top_k=5,
            threshold=0.0
        )
    
    @patch('mem0.Memory')
    def test_add_when_unavailable(self, mock_memory):
        """Test add returns empty dict when service unavailable."""
        try:
            from fairifier.services.mem0_service import Mem0Service
        except ImportError:
            pytest.skip("mem0 not installed")
        
        mock_memory.from_config.side_effect = Exception("Failed")
        service = Mem0Service({})
        
        result = service.add([{"role": "user", "content": "test"}], "session_id")
        assert result == {}
    
    @patch('mem0.Memory')
    def test_add_success(self, mock_memory):
        """Test successful memory addition."""
        try:
            from fairifier.services.mem0_service import Mem0Service
        except ImportError:
            pytest.skip("mem0 not installed")
        
        mock_mem = MagicMock()
        mock_mem.add.return_value = {
            "results": ["mem_id_1", "mem_id_2"]
        }
        mock_memory.from_config.return_value = mock_mem
        
        service = Mem0Service({"test": "config"})
        messages = [{"role": "assistant", "content": "Test content"}]
        metadata = {"test": "meta"}
        
        result = service.add(messages, "session_123", agent_id="TestAgent", metadata=metadata)
        
        assert "results" in result
        assert len(result["results"]) == 2
        _, call_kwargs = mock_mem.add.call_args
        assert call_kwargs["user_id"] == "session_123"
        assert call_kwargs["agent_id"] == "TestAgent"
        assert call_kwargs["messages"] == messages
        # add() injects lifecycle metadata (written_at, expires_at, schema_version)
        # in addition to the caller-supplied metadata; verify both are present
        assert call_kwargs["metadata"]["test"] == "meta"
        assert "schema_version" in call_kwargs["metadata"]
        assert "written_at" in call_kwargs["metadata"]
        assert "expires_at" in call_kwargs["metadata"]

    @patch('mem0.Memory')
    def test_add_skips_duplicate_messages(self, mock_memory):
        """Test duplicate message writes are suppressed before reaching mem0."""
        try:
            from fairifier.services.mem0_service import Mem0Service
        except ImportError:
            pytest.skip("mem0 not installed")

        mock_mem = MagicMock()
        mock_mem.add.return_value = {"results": ["mem_id_1"]}
        mock_memory.from_config.return_value = mock_mem

        service = Mem0Service({"test": "config"})
        messages = [{"role": "assistant", "content": "Repeated insight"}]

        first = service.add(messages, "session_123", agent_id="TestAgent")
        second = service.add(messages, "session_123", agent_id="TestAgent")

        assert first["results"] == ["mem_id_1"]
        assert second.get("skipped") == "duplicate_messages"
        mock_mem.add.assert_called_once()
    
    @patch('mem0.Memory')
    def test_list_memories(self, mock_memory):
        """Test listing memories."""
        try:
            from fairifier.services.mem0_service import Mem0Service
        except ImportError:
            pytest.skip("mem0 not installed")
        
        mock_mem = MagicMock()
        mock_mem.get_all.return_value = {
            "results": [
                {"memory": "Memory 1", "id": "1"},
                {"memory": "Memory 2", "id": "2"}
            ]
        }
        mock_memory.from_config.return_value = mock_mem
        
        service = Mem0Service({"test": "config"})
        results = service.list_memories("session_123", agent_id="TestAgent")
        
        assert len(results) == 2
        mock_mem.get_all.assert_called_once_with(
            filters={"user_id": "session_123", "agent_id": "TestAgent"},
            top_k=1000
        )
    
    @patch('mem0.Memory')
    def test_delete_session_memories(self, mock_memory):
        """Test deleting session memories."""
        try:
            from fairifier.services.mem0_service import Mem0Service
        except ImportError:
            pytest.skip("mem0 not installed")
        
        mock_mem = MagicMock()
        mock_mem.get_all.return_value = {
            "results": [
                {"memory": "Memory 1", "id": "mem_1"},
                {"memory": "Memory 2", "id": "mem_2"}
            ]
        }
        mock_memory.from_config.return_value = mock_mem
        
        service = Mem0Service({"test": "config"})
        count = service.delete_session_memories("session_123")
        
        assert count == 2
        assert mock_mem.delete.call_count == 2


class TestGetMem0Service:
    """Test get_mem0_service singleton."""
    
    def test_get_service_when_disabled(self):
        """Test getting service returns None when disabled."""
        try:
            from fairifier.services.mem0_service import get_mem0_service, reset_mem0_service
            import fairifier.config
        except ImportError:
            pytest.skip("mem0 not installed")
        
        # Reset singleton
        reset_mem0_service()
        
        # Save original value and disable
        original_enabled = fairifier.config.config.mem0_enabled
        fairifier.config.config.mem0_enabled = False
        
        try:
            service = get_mem0_service()
            assert service is None
        finally:
            # Restore original value
            fairifier.config.config.mem0_enabled = original_enabled
            reset_mem0_service()
    
    def test_singleton_behavior(self):
        """Test that get_mem0_service returns same instance."""
        try:
            from fairifier.services.mem0_service import get_mem0_service, reset_mem0_service
            import fairifier.config
        except ImportError:
            pytest.skip("mem0 not installed")
        
        reset_mem0_service()
        
        # Save original and disable
        original_enabled = fairifier.config.config.mem0_enabled
        fairifier.config.config.mem0_enabled = False
        
        try:
            service1 = get_mem0_service()
            service2 = get_mem0_service()
            
            # Both should be None or same instance
            assert service1 is service2
        finally:
            fairifier.config.config.mem0_enabled = original_enabled
            reset_mem0_service()


class TestMem0ConfigIntegration:
    """Test mem0 configuration in FAIRifierConfig."""
    
    def test_config_has_mem0_fields(self):
        """Test that config has all required mem0 fields."""
        from fairifier.config import config
        
        required_fields = [
            'mem0_enabled',
            'mem0_auto_setup',
            'mem0_auto_start_qdrant',
            'mem0_qdrant_container_name',
            'mem0_healthcheck_timeout_seconds',
            'mem0_ollama_base_url',
            'mem0_embedding_provider',
            'mem0_embedding_model',
            'mem0_embedding_base_url',
            'mem0_embedding_api_key',
            'mem0_llm_model',
            'mem0_qdrant_host',
            'mem0_qdrant_port',
            'mem0_collection_name',
        ]
        
        for field in required_fields:
            assert hasattr(config, field), f"Config missing {field}"
    
    def test_config_mem0_defaults(self):
        """Test mem0 config default values."""
        from fairifier.config import FAIRifierConfig
        
        config = FAIRifierConfig()
        
        assert config.mem0_enabled is True
        assert config.mem0_auto_setup is True
        assert config.mem0_auto_start_qdrant is True
        assert config.mem0_embedding_provider == "ollama"
        assert config.mem0_embedding_model == "nomic-embed-text-v2-moe:latest"
        assert config.mem0_qdrant_host == "localhost"
        assert config.mem0_qdrant_port == 6333
        assert config.mem0_collection_name == "fairifier_memories"


def test_get_mem0_service_keeps_explicit_ollama_embeddings_for_qwen(monkeypatch):
    """Qwen main LLM should not make Ollama embeddings use the DashScope URL."""
    from fairifier.config import config as runtime_config
    from fairifier.services.mem0_service import get_mem0_service, reset_mem0_service

    reset_mem0_service()

    original_values = {
        "mem0_enabled": runtime_config.mem0_enabled,
        "mem0_auto_setup": runtime_config.mem0_auto_setup,
        "llm_provider": runtime_config.llm_provider,
        "llm_model": runtime_config.llm_model,
        "llm_base_url": runtime_config.llm_base_url,
        "llm_api_key": runtime_config.llm_api_key,
        "mem0_collection_name": runtime_config.mem0_collection_name,
        "mem0_embedding_provider": runtime_config.mem0_embedding_provider,
        "mem0_embedding_model": runtime_config.mem0_embedding_model,
        "mem0_embedding_base_url": runtime_config.mem0_embedding_base_url,
        "mem0_embedding_api_key": runtime_config.mem0_embedding_api_key,
        "mem0_embedding_dims": runtime_config.mem0_embedding_dims,
    }

    monkeypatch.setattr(runtime_config, "mem0_enabled", True)
    monkeypatch.setattr(runtime_config, "llm_provider", "qwen")
    monkeypatch.setattr(runtime_config, "llm_model", "qwen-flash")
    monkeypatch.setattr(
        runtime_config,
        "llm_base_url",
        "https://dashscope-intl.aliyuncs.com/compatible-mode/v1",
    )
    monkeypatch.setattr(runtime_config, "llm_api_key", "dashscope-key")
    monkeypatch.setattr(
        runtime_config,
        "mem0_collection_name",
        "fairifier_memories_quicktest",
    )
    monkeypatch.setattr(runtime_config, "mem0_embedding_provider", "ollama")
    monkeypatch.setattr(runtime_config, "mem0_embedding_model", "nomic-embed-text-v2-moe:latest")
    monkeypatch.setattr(runtime_config, "mem0_embedding_base_url", None)
    monkeypatch.setattr(runtime_config, "mem0_embedding_api_key", None)
    monkeypatch.setattr(runtime_config, "mem0_embedding_dims", 768)
    monkeypatch.setattr(runtime_config, "mem0_auto_setup", False)

    with patch("fairifier.services.mem0_service.Mem0Service") as mock_service_cls:
        mock_service = mock_service_cls.return_value
        mock_service.is_available.return_value = True

        service = get_mem0_service()

        assert service is mock_service
        mem0_config = mock_service_cls.call_args.args[0]
        assert mem0_config["llm"]["provider"] == "openai"
        assert mem0_config["embedder"]["provider"] == "ollama"
        assert mem0_config["embedder"]["config"]["model"] == "nomic-embed-text-v2-moe:latest"
        assert mem0_config["embedder"]["config"]["ollama_base_url"] == "http://localhost:11434"
        assert "api_key" not in mem0_config["embedder"]["config"]
        assert mem0_config["vector_store"]["config"]["embedding_model_dims"] == 768
        assert (
            mem0_config["vector_store"]["config"]["collection_name"]
            != "fairifier_memories_quicktest"
        )

    for key, value in original_values.items():
        monkeypatch.setattr(runtime_config, key, value)
    reset_mem0_service()


def test_get_mem0_service_fallbacks_embedding_when_ollama_unavailable(monkeypatch):
    """When Ollama embedder is unavailable, mem0 should auto-fallback to API embeddings."""
    from fairifier.config import config as runtime_config
    from fairifier.services.mem0_service import get_mem0_service, reset_mem0_service

    reset_mem0_service()
    original_values = {
        "mem0_enabled": runtime_config.mem0_enabled,
        "mem0_auto_setup": runtime_config.mem0_auto_setup,
        "mem0_strict": runtime_config.mem0_strict,
        "llm_provider": runtime_config.llm_provider,
        "llm_model": runtime_config.llm_model,
        "llm_base_url": runtime_config.llm_base_url,
        "llm_api_key": runtime_config.llm_api_key,
        "mem0_collection_name": runtime_config.mem0_collection_name,
        "mem0_embedding_provider": runtime_config.mem0_embedding_provider,
        "mem0_embedding_model": runtime_config.mem0_embedding_model,
        "mem0_embedding_dims": runtime_config.mem0_embedding_dims,
        "mem0_qdrant_host": runtime_config.mem0_qdrant_host,
        "mem0_qdrant_port": runtime_config.mem0_qdrant_port,
        "mem0_auto_start_qdrant": runtime_config.mem0_auto_start_qdrant,
    }

    monkeypatch.setattr(runtime_config, "mem0_enabled", True)
    monkeypatch.setattr(runtime_config, "mem0_auto_setup", True)
    monkeypatch.setattr(runtime_config, "mem0_strict", False)
    monkeypatch.setattr(runtime_config, "llm_provider", "qwen")
    monkeypatch.setattr(runtime_config, "llm_model", "qwen-flash")
    monkeypatch.setattr(runtime_config, "llm_base_url", "https://dashscope-intl.aliyuncs.com/compatible-mode/v1")
    monkeypatch.setattr(runtime_config, "llm_api_key", "dashscope-key")
    monkeypatch.setattr(
        runtime_config,
        "mem0_collection_name",
        "fairifier_memories_quicktest",
    )
    monkeypatch.setattr(runtime_config, "mem0_embedding_provider", "ollama")
    monkeypatch.setattr(runtime_config, "mem0_embedding_model", "nomic-embed-text-v2-moe:latest")
    monkeypatch.setattr(runtime_config, "mem0_embedding_dims", 768)
    monkeypatch.setattr(runtime_config, "mem0_qdrant_host", "localhost")
    monkeypatch.setattr(runtime_config, "mem0_qdrant_port", 6333)
    monkeypatch.setattr(runtime_config, "mem0_auto_start_qdrant", False)

    with patch("fairifier.services.mem0_service._is_qdrant_available", return_value=True), \
         patch("fairifier.services.mem0_service._is_ollama_available", return_value=False), \
         patch("fairifier.services.mem0_service.Mem0Service") as mock_service_cls:
        mock_service = mock_service_cls.return_value
        mock_service.is_available.return_value = True

        service = get_mem0_service()

        assert service is mock_service
        mem0_config = mock_service_cls.call_args.args[0]
        assert mem0_config["embedder"]["provider"] == "openai"
        assert mem0_config["embedder"]["config"]["model"] == "text-embedding-v4"
        assert mem0_config["vector_store"]["config"]["embedding_model_dims"] == 1024
        assert (
            mem0_config["vector_store"]["config"]["collection_name"]
            != "fairifier_memories_quicktest"
        )

    for key, value in original_values.items():
        monkeypatch.setattr(runtime_config, key, value)
    reset_mem0_service()


def test_get_mem0_service_attempts_qdrant_autostart(monkeypatch):
    """If Qdrant is down, auto-setup should try to start local Qdrant before init."""
    from fairifier.config import config as runtime_config
    from fairifier.services.mem0_service import get_mem0_service, reset_mem0_service

    reset_mem0_service()
    original_values = {
        "mem0_enabled": runtime_config.mem0_enabled,
        "mem0_auto_setup": runtime_config.mem0_auto_setup,
        "mem0_auto_start_qdrant": runtime_config.mem0_auto_start_qdrant,
        "mem0_qdrant_host": runtime_config.mem0_qdrant_host,
        "mem0_qdrant_port": runtime_config.mem0_qdrant_port,
        "mem0_embedding_provider": runtime_config.mem0_embedding_provider,
        "mem0_embedding_model": runtime_config.mem0_embedding_model,
        "mem0_ollama_base_url": runtime_config.mem0_ollama_base_url,
    }

    monkeypatch.setattr(runtime_config, "mem0_enabled", True)
    monkeypatch.setattr(runtime_config, "mem0_auto_setup", True)
    monkeypatch.setattr(runtime_config, "mem0_auto_start_qdrant", True)
    monkeypatch.setattr(runtime_config, "mem0_qdrant_host", "localhost")
    monkeypatch.setattr(runtime_config, "mem0_qdrant_port", 6333)
    monkeypatch.setattr(runtime_config, "mem0_embedding_provider", "ollama")
    monkeypatch.setattr(runtime_config, "mem0_embedding_model", "nomic-embed-text-v2-moe:latest")
    monkeypatch.setattr(runtime_config, "mem0_ollama_base_url", "http://localhost:11434")

    with patch("fairifier.services.mem0_service._is_qdrant_available", side_effect=[False, True]), \
         patch("fairifier.services.mem0_service._try_auto_start_qdrant", return_value=True) as start_mock, \
         patch("fairifier.services.mem0_service._is_ollama_available", return_value=True), \
         patch("fairifier.services.mem0_service._ollama_has_model", return_value=True), \
         patch("fairifier.services.mem0_service.Mem0Service") as mock_service_cls:
        mock_service = mock_service_cls.return_value
        mock_service.is_available.return_value = True

        service = get_mem0_service()
        assert service is mock_service
        start_mock.assert_called_once()

    for key, value in original_values.items():
        monkeypatch.setattr(runtime_config, key, value)
    reset_mem0_service()


class TestMem0StateIntegration:
    """Test mem0 integration with FAIRifierState."""
    
    def test_state_has_session_id(self):
        """Test that FAIRifierState supports session_id."""
        from fairifier.models import FAIRifierState
        
        # TypedDict doesn't have runtime validation, but we can check structure
        # by inspecting __annotations__
        annotations = FAIRifierState.__annotations__
        
        assert 'session_id' in annotations
        assert 'Optional[str]' in str(annotations['session_id'])
        assert 'memory_scope_id' in annotations
        assert 'Optional[str]' in str(annotations['memory_scope_id'])

    def test_store_memory_insight_writes_run_and_long_term_scopes(self):
        """Agent memory writes should support both current-run and cross-session use."""
        from fairifier.graph.langgraph_app import FAIRifierLangGraphApp

        app = FAIRifierLangGraphApp.__new__(FAIRifierLangGraphApp)
        app.mem0_service = Mock()
        state = {
            "session_id": "project-123",
            "memory_scope_id": "user-abc",
        }

        app._store_memory_insight(
            state=state,
            session_id="project-123",
            agent_id="KnowledgeRetriever",
            insight="soil studies prefer MIxS fields",
            metadata={"workflow_step": "KnowledgeRetriever"},
        )

        assert app.mem0_service.add.call_count == 2
        calls = app.mem0_service.add.call_args_list
        assert [call.kwargs["session_id"] for call in calls] == [
            "project-123",
            "user-abc",
        ]
        assert [
            call.kwargs["metadata"]["memory_scope_type"]
            for call in calls
        ] == ["run", "long_term"]

    def test_retrieve_relevant_memories_merges_run_and_long_term_scopes(self):
        """Memory retrieval should expose prior agent writes and user-level history."""
        from fairifier.graph.langgraph_app import FAIRifierLangGraphApp

        app = FAIRifierLangGraphApp.__new__(FAIRifierLangGraphApp)
        app.mem0_service = Mock()
        app.mem0_service.search.side_effect = [
            [{"id": "run-1", "memory": "current run package choice"}],
            [{"id": "user-1", "memory": "long term ontology preference"}],
        ]

        memories = app._retrieve_relevant_memories(
            agent_name="JSONGenerator",
            state={
                "session_id": "project-123",
                "memory_scope_id": "user-abc",
                "document_info": {"research_domain": "soil ecology"},
            },
            session_id="project-123",
            top_k=10,
        )

        assert [memory["id"] for memory in memories] == [
            "run-1",
            "user-1",
        ]
        assert [
            call.kwargs["session_id"]
            for call in app.mem0_service.search.call_args_list
        ] == ["project-123", "user-abc"]


class TestBaseAgentMemoryMethods:
    """Test BaseAgent memory-related methods."""
    
    def test_get_context_feedback_includes_memories(self):
        """Test that get_context_feedback includes retrieved_memories."""
        from fairifier.agents.base import BaseAgent
        from fairifier.models import FAIRifierState
        
        # Create concrete agent class for testing
        class TestAgent(BaseAgent):
            async def execute(self, state):
                return state
        
        agent = TestAgent("test_agent")
        
        state: FAIRifierState = {
            "context": {
                "retrieved_memories": [
                    {"memory": "Test memory 1"},
                    {"memory": "Test memory 2"}
                ]
            }
        }
        
        feedback = agent.get_context_feedback(state)
        
        assert "retrieved_memories" in feedback
        assert len(feedback["retrieved_memories"]) == 2
    
    def test_get_memory_query_hint_default(self):
        """Test that get_memory_query_hint returns None by default."""
        from fairifier.agents.base import BaseAgent
        
        class TestAgent(BaseAgent):
            async def execute(self, state):
                return state
        
        agent = TestAgent("test_agent")
        
        hint = agent.get_memory_query_hint({})
        assert hint is None


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
