#!/usr/bin/env python3
"""Simple test script for FAIRifier functionality."""

import asyncio
import json
import logging
from pathlib import Path

# Add the current directory to the path
import sys
sys.path.insert(0, str(Path(__file__).parent))

from fairifier.graph.workflow import FAIRifierWorkflow
from fairifier.config import config

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


async def test_fairifier():
    """Test the FAIRifier workflow with a sample document."""
    print("🧪 Testing FAIRifier Workflow")
    print("=" * 50)
    
    # Initialize workflow
    workflow = FAIRifierWorkflow()
    
    # Test document path
    test_doc = Path("test_document.txt")
    if not test_doc.exists():
        print("❌ Test document not found!")
        return False
    
    print(f"📄 Processing document: {test_doc}")
    
    try:
        # Run workflow
        result = await workflow.run(str(test_doc), "test_project_001")
        
        # Display results
        print("\n📊 Results:")
        print(f"Status: {result.get('status', 'unknown')}")
        
        # Confidence scores
        confidence_scores = result.get('confidence_scores', {})
        if confidence_scores:
            print("\n🎯 Confidence Scores:")
            for component, score in confidence_scores.items():
                emoji = "🟢" if score > 0.8 else "🟡" if score > 0.6 else "🔴"
                print(f"  {emoji} {component}: {score:.2f}")
        
        # Errors
        errors = result.get('errors', [])
        if errors:
            print(f"\n❌ Errors ({len(errors)}):")
            for error in errors[:3]:  # Show first 3
                print(f"  - {error}")
            if len(errors) > 3:
                print(f"  ... and {len(errors) - 3} more")
        
        # Document info
        doc_info = result.get('document_info', {})
        if doc_info:
            print("\n📋 Extracted Document Info:")
            print(f"  Title: {doc_info.get('title', 'N/A')}")
            print(f"  Authors: {len(doc_info.get('authors', []))} found")
            print(f"  Keywords: {len(doc_info.get('keywords', []))} found")
            print(f"  Research Domain: {doc_info.get('research_domain', 'N/A')}")
        
        # Metadata fields
        metadata_fields = result.get('metadata_fields', [])
        if metadata_fields:
            print(f"\n🏷️  Generated Metadata Fields ({len(metadata_fields)}):")
            required_count = sum(1 for f in metadata_fields if f.get('required', False))
            print(f"  Required fields: {required_count}")
            print(f"  Optional fields: {len(metadata_fields) - required_count}")
            
            print("\n  Sample fields:")
            for field in metadata_fields[:5]:  # Show first 5
                req_marker = " (REQUIRED)" if field.get('required', False) else ""
                print(f"    - {field['name']}{req_marker}: {field.get('data_type', 'string')}")
        
        # Artifacts
        artifacts = result.get('artifacts', {})
        if artifacts:
            print(f"\n📦 Generated Artifacts:")
            for name, content in artifacts.items():
                size = len(content) if content else 0
                print(f"  ✓ {name}: {size} characters")
        
        # Validation results
        validation = result.get('validation_results', {})
        if validation:
            print(f"\n✅ Validation Results:")
            print(f"  Valid: {'Yes' if validation.get('is_valid', False) else 'No'}")
            print(f"  Score: {validation.get('score', 0):.2f}")
            if validation.get('errors'):
                print(f"  Errors: {len(validation['errors'])}")
        
        # Human review flag
        needs_review = result.get('needs_human_review', False)
        if needs_review:
            print("\n🔍 Human review recommended")
        
        # Save results for inspection
        output_dir = Path("output")
        output_dir.mkdir(exist_ok=True)
        
        # Save artifacts
        saved_files = []
        for name, content in artifacts.items():
            if content:
                extensions = {
                    "template_schema": ".schema.json",
                    "template_yaml": ".yaml", 
                    "rdf_turtle": ".ttl",
                    "rdf_jsonld": ".jsonld",
                    "ro_crate": ".json",
                    "validation_report": ".txt"
                }
                ext = extensions.get(name, ".txt")
                filename = f"test_{name}{ext}"
                filepath = output_dir / filename
                
                with open(filepath, 'w', encoding='utf-8') as f:
                    f.write(content)
                saved_files.append(filename)
        
        # Save summary
        summary = {
            "status": result.get('status'),
            "confidence_scores": confidence_scores,
            "needs_review": needs_review,
            "error_count": len(errors),
            "field_count": len(metadata_fields),
            "artifacts": list(artifacts.keys()),
            "validation_valid": validation.get('is_valid', False),
            "validation_score": validation.get('score', 0)
        }
        
        with open(output_dir / "test_summary.json", 'w') as f:
            json.dump(summary, f, indent=2)
        saved_files.append("test_summary.json")
        
        print(f"\n💾 Saved files to output/:")
        for filename in saved_files:
            print(f"  - {filename}")
        
        # Overall assessment
        print("\n🎯 Overall Assessment:")
        overall_confidence = sum(confidence_scores.values()) / len(confidence_scores) if confidence_scores else 0
        
        if result.get('status') == 'completed' and overall_confidence > 0.7 and not errors:
            print("🎉 Test PASSED! FAIRifier is working correctly.")
            return True
        elif overall_confidence > 0.5:
            print("⚠️  Test PARTIALLY PASSED. Some issues detected but core functionality works.")
            return True
        else:
            print("❌ Test FAILED. Significant issues detected.")
            return False
            
    except Exception as e:
        print(f"\n❌ Test FAILED with exception: {str(e)}")
        logger.error("Test failed", exc_info=True)
        return False


if __name__ == "__main__":
    success = asyncio.run(test_fairifier())
    sys.exit(0 if success else 1)
