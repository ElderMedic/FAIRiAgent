#!/usr/bin/env python3
"""
Quick LangSmith Test Runner for FAIRiAgent

This script provides a simple way to test FAIRiAgent with LangSmith integration.
"""

import os
import sys
import asyncio
from pathlib import Path


def check_requirements():
    """Check if all requirements are met."""
    print("🔍 Checking requirements...")
    
    # Check if LangSmith API key is set
    if not os.getenv("LANGSMITH_API_KEY"):
        print("❌ LANGSMITH_API_KEY environment variable not set")
        print("   Get your API key from: https://smith.langchain.com/")
        print("   Then run: export LANGSMITH_API_KEY='your_key_here'")
        return False
    
    # Check if test document exists
    test_doc = Path("examples/inputs/soil_metagenomics_paper.txt")
    if not test_doc.exists():
        print(f"❌ Test document not found: {test_doc}")
        print("   Please ensure sample documents are in examples/inputs/")
        return False
    
    # Check if dependencies are installed
    try:
        import langsmith  # noqa: F401
        import langchain  # noqa: F401
        import langgraph  # noqa: F401
        print("✅ All dependencies are installed")
    except ImportError as e:
        print(f"❌ Missing dependency: {e}")
        print("   Run: pip install -r requirements.txt")
        return False
    
    print("✅ All requirements met!")
    return True


async def run_quick_test():
    """Run a quick test of FAIRiAgent with LangSmith."""
    print("\n🚀 Running FAIRiAgent LangSmith test...")
    
    try:
        from test_langsmith import LangSmithTester
        
        tester = LangSmithTester()
        
        # Test with sample document
        test_doc = "examples/inputs/soil_metagenomics_paper.txt"
        result = await tester.test_document_processing(test_doc)
        
        print("\n✅ Test completed successfully!")
        print(f"📊 Status: {result.get('status')}")
        print(f"🎯 Confidence: {result.get('confidence_scores', {}).get('overall', 'N/A')}")
        print(f"📁 Artifacts: {list(result.get('artifacts', {}).keys())}")
        
        print("\n📈 Check your LangSmith dashboard for detailed traces:")
        print("   https://smith.langchain.com/")
        
        return True
        
    except Exception as e:
        print(f"\n❌ Test failed: {str(e)}")
        return False


def main():
    """Main function."""
    print("🧪 FAIRiAgent LangSmith Quick Test")
    print("=" * 40)
    
    # Check requirements
    if not check_requirements():
        print("\n🔧 Please fix the issues above and try again.")
        sys.exit(1)
    
    # Run test
    success = asyncio.run(run_quick_test())
    
    if success:
        print("\n🎉 Quick test completed successfully!")
        print("\n📋 Next steps:")
        print("   1. Check your LangSmith dashboard for detailed traces")
        print("   2. Run 'python test_langsmith.py' for comprehensive testing")
        print("   3. Explore the trace visualization and debugging tools")
    else:
        print("\n🔧 Test failed. Check the error messages above.")
        sys.exit(1)


if __name__ == "__main__":
    main()
