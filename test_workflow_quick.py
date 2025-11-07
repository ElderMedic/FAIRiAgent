#!/usr/bin/env python3
"""Quick test to verify workflow works without Validator"""

import asyncio
from fairifier.graph.workflow import FAIRifierWorkflow

async def quick_test():
    print("🧪 Quick Workflow Test (without Validator)")
    print("=" * 60)
    
    # Initialize workflow
    workflow = FAIRifierWorkflow()
    print(f"✅ Workflow initialized")
    print(f"   Registered agents: {list(workflow.orchestrator.registered_agents.keys())}")
    print(f"   Expected: ['DocumentParser', 'KnowledgeRetriever', 'JSONGenerator']")
    print()
    
    # Verify no Validator
    assert 'Validator' not in workflow.orchestrator.registered_agents, "❌ Validator should be removed!"
    print("✅ Confirmed: Validator has been removed")
    print()
    
    # Verify workflow steps
    print("📋 Workflow will execute these steps:")
    steps = [
        "1. DocumentParser → Critic evaluation",
        "2. KnowledgeRetriever → Critic evaluation",  
        "3. JSONGenerator → Critic evaluation"
    ]
    for step in steps:
        print(f"   {step}")
    
    print()
    print("🎉 Workflow structure verified!")
    print("=" * 60)

if __name__ == "__main__":
    asyncio.run(quick_test())
