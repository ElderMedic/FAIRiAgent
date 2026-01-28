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
    else:
        print(f"   Error: {result['error']}")
    
    return result['success']


def test_mineru_tool():
    """Test MinerU tool creation."""
    print("\n🧪 Testing MinerU Tool")
    print("=" * 60)
    
    # Create tool
    tool = create_mineru_convert_tool()
    print(f"✅ Created MinerU tool: {tool.name}")
    print(f"   Description: {tool.description[:100]}...")
    
    # Don't invoke without a document, just verify creation
    print("   ✅ Tool creation successful (skipping actual conversion test)")
    
    return True


def test_knowledge_retriever_has_tools():
    """Test that KnowledgeRetriever agent has tools attribute."""
    print("\n🧪 Testing KnowledgeRetriever Integration")
    print("=" * 60)
    
    from fairifier.agents.knowledge_retriever import KnowledgeRetrieverAgent
    
    agent = KnowledgeRetrieverAgent()
    
    # Check if tools exist
    if hasattr(agent, 'tools') and isinstance(agent.tools, dict):
        print(f"✅ KnowledgeRetriever has tools dict with {len(agent.tools)} tools")
        for name in agent.tools.keys():
            print(f"   - {name}")
        return True
    else:
        print("❌ KnowledgeRetriever missing tools attribute")
        return False


def test_document_parser_has_tool():
    """Test that DocumentParser agent has mineru_tool attribute."""
    print("\n🧪 Testing DocumentParser Integration")
    print("=" * 60)
    
    from fairifier.agents.document_parser import DocumentParserAgent
    
    agent = DocumentParserAgent()
    
    # Check if tool exists (may be None if MinerU not enabled)
    if hasattr(agent, 'mineru_tool'):
        if agent.mineru_tool:
            print(f"✅ DocumentParser has mineru_tool: {agent.mineru_tool.name}")
        else:
            print("⚠️  DocumentParser.mineru_tool is None (MinerU not enabled)")
        return True
    else:
        print("❌ DocumentParser missing mineru_tool attribute")
        return False


def test_langgraph_app_has_tool():
    """Test that LangGraph app has mineru_tool attribute."""
    print("\n🧪 Testing LangGraph App Integration")
    print("=" * 60)
    
    from fairifier.graph.langgraph_app import FAIRifierLangGraphApp
    
    app = FAIRifierLangGraphApp()
    
    # Check if tool exists (may be None if MinerU not enabled)
    if hasattr(app, 'mineru_tool'):
        if app.mineru_tool:
            print(f"✅ LangGraph app has mineru_tool: {app.mineru_tool.name}")
        else:
            print("⚠️  LangGraph app.mineru_tool is None (MinerU not enabled)")
        return True
    else:
        print("❌ LangGraph app missing mineru_tool attribute")
        return False


def main():
    """Run all integration tests."""
    print("\n" + "=" * 60)
    print("🚀 LangChain Tools Integration Test Suite")
    print("=" * 60)
    
    results = []
    
    try:
        results.append(("FAIR-DS Tools", test_fair_ds_tools()))
    except Exception as e:
        print(f"❌ FAIR-DS Tools test failed: {e}")
        results.append(("FAIR-DS Tools", False))
    
    try:
        results.append(("MinerU Tool", test_mineru_tool()))
    except Exception as e:
        print(f"❌ MinerU Tool test failed: {e}")
        results.append(("MinerU Tool", False))
    
    try:
        results.append(("KnowledgeRetriever", test_knowledge_retriever_has_tools()))
    except Exception as e:
        print(f"❌ KnowledgeRetriever test failed: {e}")
        results.append(("KnowledgeRetriever", False))
    
    try:
        results.append(("DocumentParser", test_document_parser_has_tool()))
    except Exception as e:
        print(f"❌ DocumentParser test failed: {e}")
        results.append(("DocumentParser", False))
    
    try:
        results.append(("LangGraph App", test_langgraph_app_has_tool()))
    except Exception as e:
        print(f"❌ LangGraph App test failed: {e}")
        results.append(("LangGraph App", False))
    
    # Summary
    print("\n" + "=" * 60)
    print("📊 Test Summary")
    print("=" * 60)
    
    passed = sum(1 for _, result in results if result)
    total = len(results)
    
    for name, result in results:
        status = "✅ PASS" if result else "❌ FAIL"
        print(f"{status}: {name}")
    
    print(f"\n🎯 Total: {passed}/{total} tests passed")
    
    if passed == total:
        print("✅ All tests passed! Tools integration successful.")
        return 0
    else:
        print("⚠️  Some tests failed. Please review the output above.")
        return 1


if __name__ == "__main__":
    exit(main())
