#!/usr/bin/env python3
"""
Convert Excel/ISA-Tab metadata to Ground Truth JSON format.

This script converts your existing metadata templates (Excel files with ISA sheets)
into the ground truth format required by the evaluation framework.
"""

import sys
import argparse
import json
from pathlib import Path
from datetime import datetime
from typing import Dict, List, Any
import pandas as pd


def detect_isa_sheet_type(sheet_name: str) -> str:
    """Detect ISA sheet type from sheet name."""
    sheet_lower = sheet_name.lower()
    
    if 'investigation' in sheet_lower:
        return 'investigation'
    elif 'study' in sheet_lower:
        return 'study'
    elif 'assay' in sheet_lower:
        return 'assay'
    elif 'sample' in sheet_lower:
        return 'sample'
    elif 'observation' in sheet_lower:
        return 'observationunit'
    else:
        return 'unknown'


def extract_package_source(sheet_name: str) -> str:
    """Extract package source from sheet name (e.g., 'assay - Illumina' -> 'Illumina')."""
    if ' - ' in sheet_name:
        return sheet_name.split(' - ', 1)[1].strip()
    return 'default'


def convert_excel_to_ground_truth(
    excel_path: Path,
    pdf_path: Path,
    document_id: str,
    annotator: str = "manual_annotation"
) -> Dict[str, Any]:
    """
    Convert Excel/ISA-Tab file to ground truth format.
    
    Args:
        excel_path: Path to Excel file with ISA sheets
        pdf_path: Path to corresponding PDF paper
        document_id: Unique identifier for this document
        annotator: Name/ID of annotator
        
    Returns:
        Ground truth document structure
    """
    print(f"\n📄 Converting: {document_id}")
    print(f"   Excel: {excel_path.name}")
    print(f"   PDF: {pdf_path.name}")
    
    # Load all sheets
    excel_file = pd.ExcelFile(excel_path)
    sheet_names = excel_file.sheet_names
    
    print(f"   Sheets found: {', '.join(sheet_names)}")
    
    # Extract fields from all sheets
    ground_truth_fields = []
    
    for sheet_name in sheet_names:
        # Read sheet
        df = pd.read_excel(excel_path, sheet_name=sheet_name)
        
        # Detect ISA sheet type
        isa_sheet = detect_isa_sheet_type(sheet_name)
        package_source = extract_package_source(sheet_name)
        
        if isa_sheet == 'unknown':
            print(f"   ⚠️  Skipping unknown sheet type: {sheet_name}")
            continue
        
        # Extract fields from each column
        for col in df.columns:
            # Get values (take first non-null value)
            values = df[col].dropna()
            
            if len(values) == 0:
                continue
            
            # For investigation/study, there might be multiple rows (e.g., multiple people)
            # Take first value as primary, rest as variations
            primary_value = str(values.iloc[0]).strip()
            
            if primary_value in ['', 'nan', 'None']:
                continue
            
            # Collect other values as acceptable variations
            acceptable_variations = []
            if len(values) > 1:
                for val in values.iloc[1:]:
                    val_str = str(val).strip()
                    if val_str and val_str != primary_value and val_str not in ['nan', 'None']:
                        acceptable_variations.append(val_str)
            
            # Determine if required (heuristic based on common required fields)
            field_name_lower = col.lower()
            is_required = any(req in field_name_lower for req in [
                'title', 'description', 'identifier', 'name'
            ])
            
            ground_truth_fields.append({
                "field_name": col,
                "expected_value": primary_value,
                "isa_sheet": isa_sheet,
                "package_source": package_source,
                "is_required": is_required,
                "is_recommended": not is_required,  # If not required, consider recommended
                "acceptable_variations": acceptable_variations,
                "evidence_location": f"Provided in metadata template (sheet: {sheet_name})",
                "notes": f"Extracted from {sheet_name}"
            })
    
    # Create ground truth document structure
    ground_truth_doc = {
        "document_id": document_id,
        "document_path": f"evaluation/datasets/raw/{document_id}/{pdf_path.name}",
        "metadata": {
            "domain": "metagenomics",  # Update this based on your papers
            "experiment_type": "genomics_study",  # Update this based on your papers
            "annotation_date": datetime.now().strftime("%Y-%m-%d"),
            "annotator": annotator,
            "annotation_time_minutes": 0,  # Manual annotation from existing template
            "notes": f"Converted from existing ISA-Tab Excel file: {excel_path.name}"
        },
        "ground_truth_fields": ground_truth_fields,
        "ground_truth_stats": {
            "total_required_fields": sum(1 for f in ground_truth_fields if f['is_required']),
            "total_recommended_fields": sum(1 for f in ground_truth_fields if f['is_recommended']),
            "total_optional_fields": 0,
            "annotated_required": sum(1 for f in ground_truth_fields if f['is_required']),
            "annotated_recommended": sum(1 for f in ground_truth_fields if f['is_recommended']),
            "annotated_optional": 0
        }
    }
    
    print(f"   ✅ Extracted {len(ground_truth_fields)} fields")
    print(f"      - Required: {ground_truth_doc['ground_truth_stats']['total_required_fields']}")
    print(f"      - Recommended: {ground_truth_doc['ground_truth_stats']['total_recommended_fields']}")
    
    return ground_truth_doc


def main():
    parser = argparse.ArgumentParser(
        description="Convert Excel ISA-Tab metadata to ground truth JSON format",
        formatter_class=argparse.RawDescriptionHelpFormatter
    )
    
    parser.add_argument('--raw-dir', type=Path, 
                       default=Path('evaluation/datasets/raw'),
                       help='Directory containing paper subdirectories')
    parser.add_argument('--output', type=Path,
                       default=Path('evaluation/datasets/annotated/ground_truth_v1.json'),
                       help='Output ground truth JSON file')
    parser.add_argument('--annotator', type=str, default='manual_annotation',
                       help='Annotator name/ID')
    
    args = parser.parse_args()
    
    print(f"🔍 Scanning for papers in: {args.raw_dir}")
    
    # Find all paper directories with Excel + PDF
    paper_dirs = [d for d in args.raw_dir.iterdir() if d.is_dir()]
    
    all_documents = []
    
    for paper_dir in paper_dirs:
        document_id = paper_dir.name
        
        # Find Excel and PDF files
        excel_files = list(paper_dir.glob('*.xlsx')) + list(paper_dir.glob('*.xls'))
        pdf_files = list(paper_dir.glob('*.pdf'))
        
        if not excel_files:
            print(f"\n⚠️  No Excel file found in {document_id}, skipping")
            continue
        
        if not pdf_files:
            print(f"\n⚠️  No PDF file found in {document_id}, skipping")
            continue
        
        # Use first Excel and PDF found
        excel_path = excel_files[0]
        pdf_path = pdf_files[0]
        
        try:
            ground_truth_doc = convert_excel_to_ground_truth(
                excel_path=excel_path,
                pdf_path=pdf_path,
                document_id=document_id,
                annotator=args.annotator
            )
            all_documents.append(ground_truth_doc)
        except Exception as e:
            print(f"\n❌ Error processing {document_id}: {e}")
            import traceback
            traceback.print_exc()
            continue
    
    if not all_documents:
        print("\n❌ No documents were successfully converted!")
        return 1
    
    # Create final ground truth structure
    ground_truth = {
        "documents": all_documents,
        "annotation_schema_version": "1.0",
        "created_date": datetime.now().strftime("%Y-%m-%d"),
        "last_modified": datetime.now().strftime("%Y-%m-%d"),
        "num_documents": len(all_documents),
        "conversion_method": "excel_isa_tab_to_ground_truth"
    }
    
    # Save ground truth
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with open(args.output, 'w', encoding='utf-8') as f:
        json.dump(ground_truth, f, indent=2, ensure_ascii=False)
    
    print(f"\n{'='*70}")
    print(f"✅ Conversion complete!")
    print(f"{'='*70}")
    print(f"📊 Total documents: {len(all_documents)}")
    print(f"📝 Saved to: {args.output}")
    print(f"\n💡 Next steps:")
    print(f"   1. Review the ground truth file: {args.output}")
    print(f"   2. Update 'domain' and 'experiment_type' in metadata if needed")
    print(f"   3. Validate: python evaluation/scripts/prepare_ground_truth.py validate --ground-truth {args.output}")
    
    return 0


if __name__ == '__main__':
    sys.exit(main())

