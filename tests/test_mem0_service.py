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
        mock_mem.search.assert_called_once_with(
            query="test query",
            user_id="session_123",
            agent_id="TestAgent",
            limit=5
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
        mock_mem.add.assert_called_once_with(
            messages=messages,
            user_id="session_123",
            agent_id="TestAgent",
            metadata=metadata
        )
    
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
            user_id="session_123",
            agent_id="TestAgent"
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
            'mem0_ollama_base_url',
            'mem0_embedding_model',
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
        
        assert config.mem0_enabled is False
        assert config.mem0_embedding_model == "nomic-embed-text"
        assert config.mem0_qdrant_host == "localhost"
        assert config.mem0_qdrant_port == 6333
        assert config.mem0_collection_name == "fairifier_memories"


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
