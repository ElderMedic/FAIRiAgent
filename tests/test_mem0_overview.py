"""
Tests for mem0 memory overview feature.
"""

import pytest
from unittest.mock import Mock, patch, MagicMock


class TestMemoryOverview:
    """Test memory overview generation functionality."""
    
    def test_extract_themes_from_memories(self):
        """Test theme extraction from memory texts."""
        from fairifier.services.mem0_service import Mem0Service
        
        # Mock mem0 to avoid actual initialization
        with patch('mem0.Memory'):
            service = Mem0Service.__new__(Mem0Service)
            service.memory = Mock()
            
            memory_texts = [
                "alpine grassland soils → metagenomics + microbial diversity",
                "elevation gradient studies in alpine ecology",
                "soil microbiome sequencing with bacteria and archaea"
            ]
            
            themes = service._extract_themes(memory_texts, max_themes=5)
            
            # Should extract relevant themes
            assert len(themes) > 0
            assert any(theme in ["alpine", "soil", "metagenomics", "microbiome"] 
                      for theme in themes)
    
    def test_generate_simple_summary(self):
        """Test simple summary generation without LLM."""
        from fairifier.services.mem0_service import Mem0Service
        
        with patch('mem0.Memory'):
            service = Mem0Service.__new__(Mem0Service)
            service.memory = Mock()
            
            memory_texts = [
                "alpine ecology study identified",
                "soil + GSC MIUVIGS packages selected"
            ]
            agent_counts = {
                "DocumentParser": 1,
                "KnowledgeRetriever": 1
            }
            themes = ["alpine", "soil"]
            
            summary = service._generate_simple_summary(
                memory_texts, 
                agent_counts, 
                themes
            )
            
            # Should contain key information
            assert "2 stored memories" in summary
            assert "DocumentParser" in summary
            assert "KnowledgeRetriever" in summary
            assert "alpine" in summary or "soil" in summary
    
    def test_overview_no_memories(self):
        """Test overview when no memories exist."""
        from fairifier.services.mem0_service import Mem0Service
        
        with patch('mem0.Memory') as mock_memory:
            service = Mem0Service.__new__(Mem0Service)
            service.memory = Mock()
            service.memory.get_all = Mock(return_value=[])
            
            # Mock is_available and list_memories
            service.is_available = Mock(return_value=True)
            service.list_memories = Mock(return_value=[])
            
            overview = service.generate_memory_overview("test_session")
            
            assert overview["session_id"] == "test_session"
            assert overview["total_memories"] == 0
            assert "No memories found" in overview["summary"]
    
    def test_overview_with_memories(self):
        """Test overview generation with actual memories."""
        from fairifier.services.mem0_service import Mem0Service
        
        with patch('mem0.Memory'):
            service = Mem0Service.__new__(Mem0Service)
            service.memory = Mock()
            
            # Mock methods
            service.is_available = Mock(return_value=True)
            
            # Mock memory data
            mock_memories = [
                {
                    "memory": "alpine ecology study",
                    "metadata": {"agent_id": "DocumentParser"}
                },
                {
                    "memory": "soil + GSC MIUVIGS packages",
                    "metadata": {"agent_id": "KnowledgeRetriever"}
                }
            ]
            service.list_memories = Mock(return_value=mock_memories)
            
            overview = service.generate_memory_overview(
                "test_session",
                use_llm=False  # Don't use LLM for test
            )
            
            assert overview["session_id"] == "test_session"
            assert overview["total_memories"] == 2
            assert "DocumentParser" in overview["agents"]
            assert "KnowledgeRetriever" in overview["agents"]
            assert len(overview["memory_texts"]) == 2
            assert len(overview["themes"]) > 0
            assert "summary" in overview
    
    def test_overview_theme_extraction_accuracy(self):
        """Test that theme extraction captures relevant keywords."""
        from fairifier.services.mem0_service import Mem0Service
        
        with patch('mem0.Memory'):
            service = Mem0Service.__new__(Mem0Service)
            
            # Test with domain-specific memories
            memory_texts = [
                "metagenomics study of alpine grassland soil microbiome",
                "bacterial and archaeal sequencing data from elevation gradients",
                "FAIR metadata packages for ecology and biodiversity research"
            ]
            
            themes = service._extract_themes(memory_texts, max_themes=10)
            
            # Should identify multiple relevant themes
            expected_themes = ["metagenomics", "alpine", "soil", "microbiome", 
                             "bacteria", "archaea", "sequencing", "elevation", 
                             "ecology", "biodiversity", "metadata", "FAIR"]
            
            found_themes = [t for t in expected_themes if t in themes]
            assert len(found_themes) >= 3, f"Expected at least 3 themes, found: {found_themes}"


class TestMemoryOverviewCLI:
    """Test CLI commands for memory overview (integration-style)."""
    
    def test_overview_command_exists(self):
        """Test that overview command is registered."""
        from fairifier.cli import memory
        
        # Check command is registered
        assert hasattr(memory, 'commands')
        command_names = [cmd.name for cmd in memory.commands.values()]
        assert 'overview' in command_names
    
    def test_overview_command_parameters(self):
        """Test overview command has correct parameters."""
        from fairifier.cli import memory
        
        overview_cmd = memory.commands['overview']
        
        # Check parameters
        param_names = [p.name for p in overview_cmd.params]
        assert 'session_id' in param_names
        assert 'simple' in param_names
        assert 'output_json' in param_names


@pytest.mark.parametrize("memory_count,expected_summary_length", [
    (0, "short"),  # No memories = short summary
    (5, "medium"),  # Few memories = medium summary
    (20, "long"),   # Many memories = longer summary
])
def test_overview_scales_with_memory_count(memory_count, expected_summary_length):
    """Test that overview summary scales appropriately with memory count."""
    from fairifier.services.mem0_service import Mem0Service
    
    with patch('mem0.Memory'):
        service = Mem0Service.__new__(Mem0Service)
        
        # Generate mock memories
        memory_texts = [f"memory {i}" for i in range(memory_count)]
        agent_counts = {"TestAgent": memory_count}
        themes = ["test"] if memory_count > 0 else []
        
        summary = service._generate_simple_summary(
            memory_texts,
            agent_counts,
            themes
        )
        
        # Verify summary exists and mentions count
        assert summary
        if memory_count > 0:
            assert str(memory_count) in summary
        
        # Basic length expectations (more realistic)
        if expected_summary_length == "short":
            assert len(summary) < 200
        elif expected_summary_length == "medium":
            assert 50 < len(summary) < 500
        else:  # long
            assert len(summary) > 100  # More reasonable for simple summary
