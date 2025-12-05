#!/usr/bin/env python3
"""
Clean ground truth by removing expected_value fields.
Only keep field names and metadata (is_required, isa_sheet, etc.)
"""

import json
import sys
from pathlib import Path
from typing import Dict, Any, List


def clean_ground_truth(input_path: Path, output_path: Path):
    """Remove expected_value from ground truth fields."""
    print(f"📖 Reading ground truth from: {input_path}")
    
    with open(input_path, 'r', encoding='utf-8') as f:
        data = json.load(f)
    
    documents = data.get('documents', [])
    cleaned_docs = []
    
    for doc in documents:
        doc_id = doc.get('document_id', 'unknown')
        print(f"\n📄 Processing document: {doc_id}")
        
        ground_truth_fields = doc.get('ground_truth_fields', [])
        cleaned_fields = []
        
        for field in ground_truth_fields:
            # Create cleaned field without expected_value
            cleaned_field = {
                'field_name': field.get('field_name'),
                'isa_sheet': field.get('isa_sheet'),
                'package_source': field.get('package_source'),
                'is_required': field.get('is_required', False),
                'is_recommended': field.get('is_recommended', False),
                'evidence_location': field.get('evidence_location', ''),
                'notes': field.get('notes', '')
            }
            
            # Remove None values
            cleaned_field = {k: v for k, v in cleaned_field.items() if v is not None and v != ''}
            
            cleaned_fields.append(cleaned_field)
        
        # Create cleaned document
        cleaned_doc = {
            'document_id': doc.get('document_id'),
            'document_path': doc.get('document_path'),
            'metadata': doc.get('metadata', {}),
            'ground_truth_fields': cleaned_fields
        }
        
        # Add ground_truth_stats if present
        if 'ground_truth_stats' in doc:
            cleaned_doc['ground_truth_stats'] = doc['ground_truth_stats']
        
        cleaned_docs.append(cleaned_doc)
        print(f"  ✅ Cleaned {len(cleaned_fields)} fields (removed expected_value)")
    
    # Create cleaned data structure
    cleaned_data = {
        'documents': cleaned_docs
    }
    
    # Add metadata if present
    if 'metadata' in data:
        cleaned_data['metadata'] = data['metadata']
    
    # Save cleaned ground truth
    print(f"\n💾 Saving cleaned ground truth to: {output_path}")
    with open(output_path, 'w', encoding='utf-8') as f:
        json.dump(cleaned_data, f, indent=2, ensure_ascii=False)
    
    print(f"✅ Done! Cleaned {len(cleaned_docs)} documents")
    
    # Print summary
    total_fields = sum(len(doc['ground_truth_fields']) for doc in cleaned_docs)
    print(f"\n📊 Summary:")
    print(f"  - Documents: {len(cleaned_docs)}")
    print(f"  - Total fields: {total_fields}")
    print(f"  - All expected_value fields removed")


if __name__ == '__main__':
    if len(sys.argv) < 2:
        print("Usage: python clean_ground_truth.py <input_ground_truth.json> [output_ground_truth.json]")
        print("\nExample:")
        print("  python clean_ground_truth.py evaluation/datasets/annotated/ground_truth_v1.json evaluation/datasets/annotated/ground_truth_v2.json")
        sys.exit(1)
    
    input_path = Path(sys.argv[1])
    if not input_path.exists():
        print(f"❌ Error: Input file not found: {input_path}")
        sys.exit(1)
    
    if len(sys.argv) >= 3:
        output_path = Path(sys.argv[2])
    else:
        # Default: add _cleaned suffix
        output_path = input_path.parent / f"{input_path.stem}_cleaned{input_path.suffix}"
    
    clean_ground_truth(input_path, output_path)

