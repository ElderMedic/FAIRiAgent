#!/usr/bin/env python3
"""Quick integration test for LangChain tools refactor."""

import logging
logging.basicConfig(level=logging.INFO)

from fairifier.tools import create_fair_ds_tools, create_mineru_convert_tool
from fairifier.config import config

def test_fair_ds_tools():
    """Test FAIR-DS tools creation and basic invocation."""
    print("\n🧪 Testing FAIR-DS Tools")
    print("=" * 60)
    
    # Create tools
    tools = create_fair_ds_tools()
    print(f"✅ Created {len(tools)} FAIR-DS tools")
    assert len(tools) == 5, "Should create 5 FAIR-DS tools"
    
    # List tool names
    for tool in tools:
        print(f"   - {tool.name}: {tool.description[:80]}...")
    
    # Test get_available_packages (if FAIR-DS is available)
    get_packages_tool = tools[0]  # First tool should be get_available_packages
    result = get_packages_tool.invoke({"force_refresh": False})
    
    print(f"\n📦 get_available_packages result:")
    print(f"   Success: {result['success']}")
    if result['success']:
        print(f"   Packages: {result['data']}")
        assert isinstance(result['data'], list), "Should return list of packages"
    else:
        print(f"   Error: {result['error']}")
    
    assert isinstance(result, dict), "Should return dict result"
    assert 'success' in result, "Result should have 'success' key"


def test_mineru_tool():
    """Test MinerU tool creation."""
    print("\n🧪 Testing MinerU Tool")
    print("=" * 60)
    
    # Create tool
    tool = create_mineru_convert_tool()
    print(f"✅ Created MinerU tool: {tool.name}")
    print(f"   Description: {tool.description[:100]}...")
    
    assert tool is not None, "Tool should be created"
    assert tool.name == "convert_document", "Tool name should be 'convert_document'"
    assert len(tool.description) > 0, "Tool should have description"
    
    # Don't invoke without a document, just verify creation
    print("   ✅ Tool creation successful (skipping actual conversion test)")


def test_knowledge_retriever_has_tools():
    """Test that KnowledgeRetriever agent has tools attribute."""
    print("\n🧪 Testing KnowledgeRetriever Integration")
    print("=" * 60)
    
    from fairifier.agents.knowledge_retriever import KnowledgeRetrieverAgent
    
    agent = KnowledgeRetrieverAgent()
    
    # Check if tools exist
    assert hasattr(agent, 'tools'), "KnowledgeRetriever should have 'tools' attribute"
    assert isinstance(agent.tools, dict), "Tools should be a dictionary"
    
    print(f"✅ KnowledgeRetriever has tools dict with {len(agent.tools)} tools")
    for name in agent.tools.keys():
        print(f"   - {name}")
    
    assert len(agent.tools) == 5, "Should have 5 FAIR-DS tools"


def test_document_parser_has_tool():
    """Test that DocumentParser agent has mineru_tool attribute."""
    print("\n🧪 Testing DocumentParser Integration")
    print("=" * 60)
    
    from fairifier.agents.document_parser import DocumentParserAgent
    
    agent = DocumentParserAgent()
    
    # Check if tool exists (may be None if MinerU not enabled)
    assert hasattr(agent, 'mineru_tool'), "DocumentParser should have 'mineru_tool' attribute"
    
    if agent.mineru_tool:
        print(f"✅ DocumentParser has mineru_tool: {agent.mineru_tool.name}")
        assert agent.mineru_tool.name == "convert_document", "Tool should be named 'convert_document'"
    else:
        print("⚠️  DocumentParser.mineru_tool is None (MinerU not enabled)")


def test_langgraph_app_has_tool():
    """Test that LangGraph app has mineru_tool attribute."""
    print("\n🧪 Testing LangGraph App Integration")
    print("=" * 60)
    
    from fairifier.graph.langgraph_app import FAIRifierLangGraphApp
    
    app = FAIRifierLangGraphApp()
    
    # Check if tool exists (may be None if MinerU not enabled)
    assert hasattr(app, 'mineru_tool'), "LangGraph app should have 'mineru_tool' attribute"
    
    if app.mineru_tool:
        print(f"✅ LangGraph app has mineru_tool: {app.mineru_tool.name}")
        assert app.mineru_tool.name == "convert_document", "Tool should be named 'convert_document'"
    else:
        print("⚠️  LangGraph app.mineru_tool is None (MinerU not enabled)")


# Note: This file can be run as a pytest test or standalone script
if __name__ == "__main__":
    # Standalone execution mode for quick manual testing
    print("\n" + "=" * 60)
    print("🚀 LangChain Tools Integration Test Suite")
    print("=" * 60)
    print("\n💡 Note: For full test execution, use: pytest tests/test_tools_integration.py -v\n")
    
    # Run tests manually
    try:
        test_fair_ds_tools()
        test_mineru_tool()
        test_knowledge_retriever_has_tools()
        test_document_parser_has_tool()
        test_langgraph_app_has_tool()
        
        print("\n" + "=" * 60)
        print("✅ All integration tests passed!")
        print("=" * 60)
    except AssertionError as e:
        print(f"\n❌ Test failed: {e}")
        exit(1)
    except Exception as e:
        print(f"\n❌ Unexpected error: {e}")
        exit(1)
