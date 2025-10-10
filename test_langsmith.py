#!/usr/bin/env python3
"""
LangSmith Testing Script for FAIRiAgent

This script demonstrates how to test FAIRiAgent using LangSmith for debugging,
monitoring, and tracing the multi-agent workflow.
"""

import os
import asyncio
import logging
from pathlib import Path
from typing import Dict, Any

# Set up LangSmith before importing LangChain components
os.environ["LANGCHAIN_TRACING_V2"] = "true"
os.environ["LANGCHAIN_PROJECT"] = "fairifier-testing"

# Import LangSmith and LangChain components
from langsmith import Client
from langchain_core.callbacks import tracing_v2_enabled

# Import FAIRiAgent components
from fairifier.graph.workflow import FAIRifierWorkflow
from fairifier.config import config

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class LangSmithTester:
    """LangSmith integration tester for FAIRiAgent."""
    
    def __init__(self):
        self.client = None
        self.workflow = FAIRifierWorkflow()
        
        # Initialize LangSmith if API key is provided
        if config.enable_langsmith and config.langsmith_api_key:
            os.environ["LANGSMITH_API_KEY"] = config.langsmith_api_key
            os.environ["LANGSMITH_ENDPOINT"] = config.langsmith_endpoint
            self.client = Client(
                api_key=config.langsmith_api_key,
                api_url=config.langsmith_endpoint
            )
            logger.info(f"LangSmith initialized for project: {config.langsmith_project}")
        else:
            logger.warning("LangSmith not configured. Set LANGSMITH_API_KEY environment variable.")
    
    async def test_document_processing(self, document_path: str) -> Dict[str, Any]:
        """Test document processing with LangSmith tracing."""
        
        if not Path(document_path).exists():
            raise FileNotFoundError(f"Document not found: {document_path}")
        
        logger.info(f"Testing document processing: {document_path}")
        
        # Enable tracing for this run
        with tracing_v2_enabled(project_name=config.langsmith_project):
            try:
                # Run the workflow
                result = await self.workflow.run(document_path)
                
                logger.info("Document processing completed successfully")
                logger.info(f"Status: {result.get('status')}")
                logger.info(f"Confidence scores: {result.get('confidence_scores', {})}")
                logger.info(f"Artifacts generated: {list(result.get('artifacts', {}).keys())}")
                
                return result
                
            except Exception as e:
                logger.error(f"Document processing failed: {str(e)}")
                raise
    
    async def test_workflow_nodes(self, document_path: str) -> Dict[str, Any]:
        """Test individual workflow nodes with detailed tracing."""
        
        logger.info("Testing individual workflow nodes")
        
        # Initialize state
        from fairifier.models import FAIRifierState, ProcessingStatus
        from datetime import datetime
        
        initial_state = FAIRifierState(
            document_path=document_path,
            document_content="",
            document_info={},
            retrieved_knowledge=[],
            metadata_fields=[],
            rdf_graph="",
            validation_results={},
            confidence_scores={},
            needs_human_review=False,
            artifacts={},
            status=ProcessingStatus.PENDING.value,
            processing_start=datetime.now().isoformat(),
            processing_end=None,
            errors=[]
        )
        
        # Test each node individually with tracing
        with tracing_v2_enabled(project_name=f"{config.langsmith_project}-nodes"):
            
            # Test document parsing
            logger.info("Testing document parsing node...")
            parsed_state = await self.workflow._parse_document_node(initial_state)
            logger.info(f"Parsing completed. Status: {parsed_state.get('status')}")
            
            # Test knowledge retrieval
            logger.info("Testing knowledge retrieval node...")
            retrieved_state = await self.workflow._retrieve_knowledge_node(parsed_state)
            logger.info(f"Retrieval completed. Status: {retrieved_state.get('status')}")
            
            # Test template generation
            logger.info("Testing template generation node...")
            generated_state = await self.workflow._generate_template_node(retrieved_state)
            logger.info(f"Generation completed. Status: {generated_state.get('status')}")
            
            # Test RDF building
            logger.info("Testing RDF building node...")
            rdf_state = await self.workflow._build_rdf_node(generated_state)
            logger.info(f"RDF building completed. Status: {rdf_state.get('status')}")
            
            # Test validation
            logger.info("Testing validation node...")
            validated_state = await self.workflow._validate_node(rdf_state)
            logger.info(f"Validation completed. Status: {validated_state.get('status')}")
            
            return validated_state
    
    def get_langsmith_runs(self, limit: int = 10) -> list:
        """Get recent LangSmith runs for analysis."""
        if not self.client:
            logger.warning("LangSmith client not available")
            return []
        
        try:
            runs = list(self.client.list_runs(project_name=config.langsmith_project, limit=limit))
            logger.info(f"Retrieved {len(runs)} recent runs from LangSmith")
            return runs
        except Exception as e:
            logger.error(f"Failed to retrieve LangSmith runs: {str(e)}")
            return []
    
    def analyze_run(self, run_id: str) -> Dict[str, Any]:
        """Analyze a specific LangSmith run."""
        if not self.client:
            logger.warning("LangSmith client not available")
            return {}
        
        try:
            run = self.client.read_run(run_id)
            
            analysis = {
                "run_id": run_id,
                "status": run.status,
                "start_time": run.start_time,
                "end_time": run.end_time,
                "total_tokens": run.total_tokens,
                "total_cost": run.total_cost,
                "inputs": run.inputs,
                "outputs": run.outputs,
                "error": run.error,
                "child_runs": len(run.child_runs) if run.child_runs else 0
            }
            
            logger.info(f"Analyzed run {run_id}: {analysis['status']}")
            return analysis
            
        except Exception as e:
            logger.error(f"Failed to analyze run {run_id}: {str(e)}")
            return {}


async def main():
    """Main testing function."""
    
    # Initialize tester
    tester = LangSmithTester()
    
    # Test document path
    test_document = "examples/inputs/soil_metagenomics_paper.txt"
    
    if not Path(test_document).exists():
        logger.error(f"Test document not found: {test_document}")
        logger.info("Please ensure you have sample documents in examples/inputs/")
        return
    
    print("🧪 FAIRiAgent LangSmith Testing")
    print("=" * 50)
    
    try:
        # Test 1: Complete workflow
        print("\n1️⃣ Testing complete workflow...")
        result = await tester.test_document_processing(test_document)
        
        print(f"✅ Workflow completed with status: {result.get('status')}")
        print(f"📊 Confidence scores: {result.get('confidence_scores', {})}")
        print(f"📁 Generated artifacts: {list(result.get('artifacts', {}).keys())}")
        
        # Test 2: Individual nodes
        print("\n2️⃣ Testing individual workflow nodes...")
        node_result = await tester.test_workflow_nodes(test_document)
        
        print(f"✅ Node testing completed with status: {node_result.get('status')}")
        
        # Test 3: LangSmith analysis
        if tester.client:
            print("\n3️⃣ Analyzing LangSmith runs...")
            runs = tester.get_langsmith_runs(limit=5)
            
            if runs:
                print(f"📈 Found {len(runs)} recent runs")
                for run in runs[:3]:  # Show first 3 runs
                    analysis = tester.analyze_run(str(run.id))
                    if analysis:
                        print(f"   Run {run.id[:8]}... - Status: {analysis.get('status')}")
                        print(f"   Duration: {analysis.get('end_time', 'N/A')}")
                        print(f"   Tokens: {analysis.get('total_tokens', 'N/A')}")
            else:
                print("📈 No recent runs found")
        
        print("\n🎉 LangSmith testing completed successfully!")
        print("\n📋 Next steps:")
        print("   1. Check your LangSmith dashboard for detailed traces")
        print("   2. Analyze performance metrics and token usage")
        print("   3. Debug any issues using the trace visualization")
        print("   4. Optimize prompts and workflows based on insights")
        
    except Exception as e:
        logger.error(f"Testing failed: {str(e)}")
        print(f"\n❌ Testing failed: {str(e)}")
        print("\n🔧 Troubleshooting:")
        print("   1. Ensure LangSmith API key is set correctly")
        print("   2. Check that test documents exist")
        print("   3. Verify all dependencies are installed")
        print("   4. Check network connectivity to LangSmith")


if __name__ == "__main__":
    # Run the async main function
    asyncio.run(main())
