#!/usr/bin/env python3
"""
Test script for the reflective workflow with Orchestrator and Critic agents.

This demonstrates the self-reflective architecture where:
1. Orchestrator controls the overall workflow
2. Critic evaluates each step's output
3. Based on Critic feedback, steps may be retried with improvements
4. Feedback is passed back to agents for refinement
"""

import asyncio
import sys
import json
from pathlib import Path
from datetime import datetime

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent))

from fairifier.graph.workflow import FAIRifierWorkflow
from fairifier.config import config

# Enable LangSmith tracing
import os
os.environ["LANGCHAIN_TRACING_V2"] = "true"
os.environ["LANGCHAIN_PROJECT"] = "fairifier-reflective-test"


async def test_reflective_workflow():
    """Test the reflective workflow with Orchestrator and Critic."""
    
    print("=" * 80)
    print("🧪 Testing Reflective Workflow (Orchestrator + Critic)")
    print("=" * 80)
    print()
    
    # Setup
    test_document = "examples/inputs/test_document.txt"
    output_dir = Path("output_reflective_test")
    output_dir.mkdir(exist_ok=True)
    
    print(f"📄 Test Document: {test_document}")
    print(f"📁 Output Directory: {output_dir}")
    print(f"🤖 LLM Model: {config.llm_model} ({config.llm_provider})")
    print()
    
    # Check if test document exists
    if not Path(test_document).exists():
        print(f"❌ Test document not found: {test_document}")
        print("\n💡 Tip: Create a test document at examples/inputs/test_document.txt")
        return
    
    print("=" * 80)
    print("🚀 Starting Reflective Workflow")
    print("=" * 80)
    print()
    
    try:
        # Initialize workflow
        workflow = FAIRifierWorkflow()
        
        # Run workflow
        print("▶️  Initializing workflow...")
        result = await workflow.run(test_document, f"test_{datetime.now().strftime('%Y%m%d_%H%M%S')}")
        
        # Extract results
        status = result.get("status", "unknown")
        confidence_scores = result.get("confidence_scores", {})
        needs_review = result.get("needs_human_review", False)
        execution_history = result.get("execution_history", [])
        execution_summary = result.get("execution_summary", {})
        
        print("\n" + "=" * 80)
        print("📊 Workflow Results")
        print("=" * 80)
        print()
        
        # Status
        status_emoji = "✅" if status == "completed" else "⚠️" if status == "reviewing" else "❌"
        print(f"{status_emoji} Status: {status.upper()}")
        print(f"👁️  Needs Review: {'Yes' if needs_review else 'No'}")
        print()
        
        # Confidence Scores
        print("🎯 Confidence Scores:")
        for component, score in confidence_scores.items():
            emoji = "✅" if score >= 0.8 else "⚠️" if score >= 0.6 else "❌"
            print(f"  {emoji} {component}: {score:.2%}")
        print()
        
        # Execution Summary
        if execution_summary:
            print("📋 Execution Summary:")
            print(f"  • Total Steps: {execution_summary.get('total_steps', 0)}")
            print(f"  • Successful: {execution_summary.get('successful_steps', 0)}")
            print(f"  • Failed: {execution_summary.get('failed_steps', 0)}")
            print(f"  • Total Retries: {execution_summary.get('total_retries', 0)}")
            print(f"  • Steps Requiring Retry: {execution_summary.get('steps_requiring_retry', 0)}")
            print(f"  • Average Confidence: {execution_summary.get('average_confidence', 0):.2%}")
            print()
        
        # Execution History with Critic Evaluations
        if execution_history:
            print("🔍 Execution History (with Critic Evaluations):")
            print("-" * 80)
            
            for i, exec_record in enumerate(execution_history, 1):
                agent_name = exec_record.get("agent_name", "Unknown")
                attempt = exec_record.get("attempt", 1)
                success = exec_record.get("success", False)
                critic_eval = exec_record.get("critic_evaluation", {})
                
                success_icon = "✓" if success else "✗"
                attempt_text = f"(attempt {attempt})" if attempt > 1 else ""
                
                print(f"\n{i}. {agent_name} {attempt_text}")
                print(f"   Execution: {success_icon} {'Success' if success else 'Failed'}")
                
                if critic_eval:
                    decision = critic_eval.get("decision", "N/A")
                    confidence = critic_eval.get("confidence", 0.0)
                    feedback = critic_eval.get("feedback", "")
                    issues = critic_eval.get("issues", [])
                    suggestions = critic_eval.get("suggestions", [])
                    
                    decision_icon = "✅" if decision == "ACCEPT" else "🔄" if decision == "RETRY" else "🚨"
                    
                    print(f"   Critic: {decision_icon} {decision} (confidence: {confidence:.2f})")
                    print(f"   Feedback: {feedback}")
                    
                    if issues:
                        print(f"   Issues ({len(issues)}):")
                        for issue in issues[:3]:
                            print(f"     - {issue}")
                    
                    if suggestions:
                        print(f"   Suggestions ({len(suggestions)}):")
                        for suggestion in suggestions[:2]:
                            print(f"     - {suggestion}")
            
            print("-" * 80)
            print()
        
        # Save detailed results
        results_file = output_dir / "workflow_results.json"
        with open(results_file, 'w', encoding='utf-8') as f:
            json.dump({
                "status": status,
                "confidence_scores": confidence_scores,
                "needs_human_review": needs_review,
                "execution_summary": execution_summary,
                "execution_history": execution_history,
                "timestamp": datetime.now().isoformat()
            }, f, indent=2, ensure_ascii=False)
        
        print(f"💾 Detailed results saved to: {results_file}")
        print()
        
        # Key insights
        print("=" * 80)
        print("💡 Key Insights")
        print("=" * 80)
        
        total_retries = execution_summary.get('total_retries', 0)
        if total_retries > 0:
            print(f"✓ Reflective system performed {total_retries} retries to improve quality")
        else:
            print("✓ All steps passed on first attempt - excellent quality!")
        
        if needs_review:
            print("⚠ Some outputs need human review for final approval")
        else:
            print("✓ All outputs meet quality thresholds automatically")
        
        avg_conf = execution_summary.get('average_confidence', 0)
        if avg_conf >= 0.8:
            print(f"✓ High overall confidence: {avg_conf:.2%}")
        elif avg_conf >= 0.6:
            print(f"⚠ Moderate confidence: {avg_conf:.2%} - consider review")
        else:
            print(f"✗ Low confidence: {avg_conf:.2%} - manual review recommended")
        
        print()
        print("=" * 80)
        print("✨ Test Complete!")
        print("=" * 80)
        
    except Exception as e:
        print(f"\n❌ Error during workflow execution: {str(e)}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


def main():
    """Main entry point."""
    asyncio.run(test_reflective_workflow())


if __name__ == "__main__":
    main()

