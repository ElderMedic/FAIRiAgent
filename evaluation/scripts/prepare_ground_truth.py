#!/usr/bin/env python3
"""
Ground Truth Preparation Tool for FAIRiAgent Evaluation

This script helps create, validate, and merge ground truth annotations for evaluation.
"""

import json
import sys
import argparse
from pathlib import Path
from typing import Dict, List, Any, Optional
from datetime import datetime
import jsonschema
from jsonschema import validate, ValidationError


# Ground truth schema for validation
GROUND_TRUTH_SCHEMA = {
    "$schema": "http://json-schema.org/draft-07/schema#",
    "type": "object",
    "required": ["documents", "annotation_schema_version"],
    "properties": {
        "documents": {
            "type": "array",
            "items": {
                "type": "object",
                "required": ["document_id", "document_path", "metadata", "ground_truth_fields"],
                "properties": {
                    "document_id": {"type": "string"},
                    "document_path": {"type": "string"},
                    "metadata": {
                        "type": "object",
                        "required": ["domain", "experiment_type", "annotation_date", "annotator"],
                        "properties": {
                            "domain": {"type": "string"},
                            "experiment_type": {"type": "string"},
                            "annotation_date": {"type": "string"},
                            "annotator": {"type": "string"},
                            "annotation_time_minutes": {"type": "number"},
                            "notes": {"type": "string"}
                        }
                    },
                    "ground_truth_fields": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "required": ["field_name", "expected_value", "isa_sheet", "is_required"],
                            "properties": {
                                "field_name": {"type": "string"},
                                "expected_value": {"type": "string"},
                                "isa_sheet": {
                                    "type": "string",
                                    "enum": ["investigation", "study", "assay", "sample", "observationunit"]
                                },
                                "package_source": {"type": "string"},
                                "is_required": {"type": "boolean"},
                                "is_recommended": {"type": "boolean"},
                                "acceptable_variations": {
                                    "type": "array",
                                    "items": {"type": "string"}
                                },
                                "evidence_location": {"type": "string"},
                                "notes": {"type": "string"}
                            }
                        }
                    },
                    "ground_truth_stats": {
                        "type": "object",
                        "properties": {
                            "total_required_fields": {"type": "integer"},
                            "total_recommended_fields": {"type": "integer"},
                            "total_optional_fields": {"type": "integer"}
                        }
                    }
                }
            }
        },
        "annotation_schema_version": {"type": "string"},
        "created_date": {"type": "string"},
        "last_modified": {"type": "string"}
    }
}


def generate_template_from_fairifier_output(fairifier_output_path: Path, output_path: Path) -> None:
    """Generate a ground truth template from FAIRiAgent's output."""
    print(f"📄 Loading FAIRiAgent output from: {fairifier_output_path}")
    
    with open(fairifier_output_path, 'r', encoding='utf-8') as f:
        fairifier_data = json.load(f)
    
    # Extract document information
    document_source = fairifier_data.get('document_source', 'unknown.pdf')
    document_name = Path(document_source).stem
    
    # Build ground truth template
    ground_truth_fields = []
    
    # Process ISA structure if present
    isa_structure = fairifier_data.get('isa_structure', {})
    for isa_sheet_name, isa_sheet_data in isa_structure.items():
        if isa_sheet_name == 'description':
            continue
            
        fields = isa_sheet_data.get('fields', [])
        for field in fields:
            ground_truth_fields.append({
                "field_name": field.get('field_name', ''),
                "expected_value": field.get('value', ''),
                "isa_sheet": isa_sheet_name,
                "package_source": field.get('package_source', 'default'),
                "is_required": True,  # You should manually adjust this
                "is_recommended": False,
                "acceptable_variations": [],
                "evidence_location": "FILL_IN: Page X, Section Y",
                "notes": "Review and verify this value"
            })
    
    # Create template structure
    template = {
        "documents": [
            {
                "document_id": document_name,
                "document_path": f"evaluation/datasets/raw/{Path(document_source).name}",
                "metadata": {
                    "domain": "FILL_IN: metagenomics|genomics|ecology|...",
                    "experiment_type": "FILL_IN: soil_microbiome|16S_amplicon|...",
                    "annotation_date": datetime.now().strftime("%Y-%m-%d"),
                    "annotator": "FILL_IN: your_name",
                    "annotation_time_minutes": 0,
                    "notes": "Generated from FAIRiAgent output - requires manual review"
                },
                "ground_truth_fields": ground_truth_fields,
                "ground_truth_stats": {
                    "total_required_fields": 0,  # Fill in manually
                    "total_recommended_fields": 0,
                    "total_optional_fields": 0,
                    "annotated_required": len(ground_truth_fields),
                    "annotated_recommended": 0,
                    "annotated_optional": 0
                }
            }
        ],
        "annotation_schema_version": "1.0",
        "created_date": datetime.now().strftime("%Y-%m-%d"),
        "last_modified": datetime.now().strftime("%Y-%m-%d")
    }
    
    # Write template
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, 'w', encoding='utf-8') as f:
        json.dump(template, f, indent=2, ensure_ascii=False)
    
    print(f"✅ Generated template with {len(ground_truth_fields)} fields")
    print(f"📝 Saved to: {output_path}")
    print("\n⚠️  IMPORTANT: Review and edit the template:")
    print("   - Fill in 'FILL_IN' placeholders")
    print("   - Verify all field values are correct")
    print("   - Add evidence_location for each field")
    print("   - Set is_required/is_recommended flags")
    print("   - Add acceptable_variations where appropriate")


def validate_ground_truth(ground_truth_path: Path) -> bool:
    """Validate ground truth file against schema."""
    print(f"🔍 Validating ground truth: {ground_truth_path}")
    
    try:
        with open(ground_truth_path, 'r', encoding='utf-8') as f:
            data = json.load(f)
        
        # Schema validation
        validate(instance=data, schema=GROUND_TRUTH_SCHEMA)
        
        # Additional checks
        issues = []
        
        for doc_idx, doc in enumerate(data.get('documents', [])):
            doc_id = doc.get('document_id', f'document_{doc_idx}')
            
            # Check for FILL_IN placeholders
            metadata = doc.get('metadata', {})
            for key, value in metadata.items():
                if isinstance(value, str) and 'FILL_IN' in value:
                    issues.append(f"Document '{doc_id}': metadata.{key} contains FILL_IN placeholder")
            
            # Check fields
            fields = doc.get('ground_truth_fields', [])
            for field_idx, field in enumerate(fields):
                field_name = field.get('field_name', f'field_{field_idx}')
                
                # Check for missing evidence
                if not field.get('evidence_location') or 'FILL_IN' in field.get('evidence_location', ''):
                    issues.append(f"Document '{doc_id}', field '{field_name}': missing evidence_location")
                
                # Check for empty expected values
                if not field.get('expected_value'):
                    issues.append(f"Document '{doc_id}', field '{field_name}': empty expected_value")
        
        if issues:
            print("\n⚠️  Validation passed but found issues to review:")
            for issue in issues[:10]:  # Show first 10
                print(f"   - {issue}")
            if len(issues) > 10:
                print(f"   ... and {len(issues) - 10} more issues")
            print(f"\n📊 Total issues: {len(issues)}")
            return False
        else:
            print("✅ Validation passed! No issues found.")
            return True
            
    except ValidationError as e:
        print(f"❌ Schema validation failed: {e.message}")
        return False
    except json.JSONDecodeError as e:
        print(f"❌ Invalid JSON: {e}")
        return False
    except Exception as e:
        print(f"❌ Validation error: {e}")
        return False


def merge_annotations(input_dir: Path, output_path: Path) -> None:
    """Merge multiple ground truth annotation files into one."""
    print(f"📁 Merging annotations from: {input_dir}")
    
    all_documents = []
    annotation_files = list(input_dir.glob('*_ground_truth.json'))
    
    if not annotation_files:
        annotation_files = [f for f in input_dir.glob('*.json') 
                          if f.name != 'ground_truth_template.json' 
                          and not f.name.startswith('ground_truth_v')]
    
    print(f"Found {len(annotation_files)} annotation files")
    
    for anno_file in annotation_files:
        try:
            with open(anno_file, 'r', encoding='utf-8') as f:
                data = json.load(f)
            
            docs = data.get('documents', [])
            all_documents.extend(docs)
            print(f"  ✓ Loaded {len(docs)} document(s) from {anno_file.name}")
        except Exception as e:
            print(f"  ✗ Failed to load {anno_file.name}: {e}")
    
    # Create merged structure
    merged = {
        "documents": all_documents,
        "annotation_schema_version": "1.0",
        "created_date": datetime.now().strftime("%Y-%m-%d"),
        "last_modified": datetime.now().strftime("%Y-%m-%d"),
        "num_documents": len(all_documents),
        "source_files": [f.name for f in annotation_files]
    }
    
    # Write merged file
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, 'w', encoding='utf-8') as f:
        json.dump(merged, f, indent=2, ensure_ascii=False)
    
    print(f"\n✅ Merged {len(all_documents)} documents from {len(annotation_files)} files")
    print(f"📝 Saved to: {output_path}")
    
    # Validate merged file
    print("\n🔍 Validating merged file...")
    validate_ground_truth(output_path)


def interactive_annotate(template_path: Optional[Path], pdf_path: Path, output_path: Path) -> None:
    """Interactive annotation (simplified - shows structure)."""
    print(f"📝 Interactive Annotation Tool")
    print(f"PDF: {pdf_path}")
    
    if template_path and template_path.exists():
        with open(template_path, 'r', encoding='utf-8') as f:
            data = json.load(f)
        print(f"✓ Loaded template from {template_path}")
    else:
        # Create minimal structure
        doc_id = pdf_path.stem
        data = {
            "documents": [{
                "document_id": doc_id,
                "document_path": f"evaluation/datasets/raw/{pdf_path.name}",
                "metadata": {
                    "domain": "",
                    "experiment_type": "",
                    "annotation_date": datetime.now().strftime("%Y-%m-%d"),
                    "annotator": "",
                    "annotation_time_minutes": 0,
                    "notes": ""
                },
                "ground_truth_fields": [],
                "ground_truth_stats": {}
            }],
            "annotation_schema_version": "1.0"
        }
        print("Created new annotation structure")
    
    print("\n" + "="*60)
    print("INTERACTIVE ANNOTATION - Simplified Mode")
    print("="*60)
    print("\nFor full annotation, please edit the JSON file directly.")
    print("This tool provides a basic structure.\n")
    
    doc = data['documents'][0]
    
    # Collect basic metadata
    print("📋 Document Metadata:")
    domain = input(f"  Domain (e.g., metagenomics, genomics): ").strip()
    if domain:
        doc['metadata']['domain'] = domain
    
    exp_type = input(f"  Experiment type (e.g., soil_microbiome): ").strip()
    if exp_type:
        doc['metadata']['experiment_type'] = exp_type
    
    annotator = input(f"  Annotator name: ").strip()
    if annotator:
        doc['metadata']['annotator'] = annotator
    
    print(f"\n💡 To add ground truth fields, edit the output JSON file directly.")
    print(f"   Use the template structure as a guide.")
    
    # Save
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, 'w', encoding='utf-8') as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    
    print(f"\n✅ Saved annotation structure to: {output_path}")
    print(f"\n📝 Next steps:")
    print(f"   1. Open {output_path} in your editor")
    print(f"   2. Add ground_truth_fields for each metadata field")
    print(f"   3. Fill in expected_value, evidence_location, etc.")
    print(f"   4. Run validation: python {Path(__file__).name} validate --ground-truth {output_path}")


def main():
    parser = argparse.ArgumentParser(
        description="Ground Truth Preparation Tool for FAIRiAgent Evaluation",
        formatter_class=argparse.RawDescriptionHelpFormatter
    )
    
    subparsers = parser.add_subparsers(dest='command', help='Command to execute')
    
    # Generate template command
    gen_parser = subparsers.add_parser('generate-template', 
                                       help='Generate template from FAIRiAgent output')
    gen_parser.add_argument('--fairifier-output', type=Path, required=True,
                           help='Path to metadata_json.json from FAIRiAgent')
    gen_parser.add_argument('--output', type=Path, required=True,
                           help='Output path for template')
    
    # Annotate command
    anno_parser = subparsers.add_parser('annotate',
                                        help='Interactively annotate a paper')
    anno_parser.add_argument('--template', type=Path,
                            help='Optional: Load existing template')
    anno_parser.add_argument('--pdf', type=Path, required=True,
                            help='Path to PDF paper')
    anno_parser.add_argument('--output', type=Path, required=True,
                            help='Output path for ground truth annotation')
    
    # Merge command
    merge_parser = subparsers.add_parser('merge',
                                        help='Merge multiple annotations')
    merge_parser.add_argument('--input-dir', type=Path, required=True,
                             help='Directory with annotation files')
    merge_parser.add_argument('--output', type=Path, required=True,
                             help='Output path for merged ground truth')
    
    # Validate command
    val_parser = subparsers.add_parser('validate',
                                       help='Validate ground truth format')
    val_parser.add_argument('--ground-truth', type=Path, required=True,
                           help='Ground truth file to validate')
    
    args = parser.parse_args()
    
    if not args.command:
        parser.print_help()
        return 1
    
    try:
        if args.command == 'generate-template':
            generate_template_from_fairifier_output(args.fairifier_output, args.output)
        elif args.command == 'annotate':
            interactive_annotate(args.template, args.pdf, args.output)
        elif args.command == 'merge':
            merge_annotations(args.input_dir, args.output)
        elif args.command == 'validate':
            valid = validate_ground_truth(args.ground_truth)
            return 0 if valid else 1
        
        return 0
        
    except Exception as e:
        print(f"\n❌ Error: {e}", file=sys.stderr)
        import traceback
        traceback.print_exc()
        return 1


if __name__ == '__main__':
    sys.exit(main())

