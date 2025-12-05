#!/usr/bin/env python3
"""
Add BIOREM ground truth by converting FAIRiAgent output to ground truth format.
"""

import json
from pathlib import Path
from datetime import datetime

# Paths
fairifier_output = Path("output/20251116_185736/metadata_json.json")
ground_truth_path = Path("evaluation/datasets/annotated/ground_truth_v1.json")

# Load FAIRiAgent output
with open(fairifier_output, 'r') as f:
    biorem_output = json.load(f)

# Extract fields from all ISA sheets
ground_truth_fields = []

# Process investigation fields
for field in biorem_output['isa_structure']['investigation']['fields']:
    # Only include confirmed fields with confidence > 0.5 as ground truth
    if field['status'] == 'confirmed' and field['confidence'] > 0.5:
        ground_truth_fields.append({
            "field_name": field['field_name'],
            "expected_value": field['value'],
            "isa_sheet": "investigation",
            "package_source": field['package_source'],
            "is_required": field['field_name'].lower() in ['investigation title', 'investigation description', 'investigation identifier'],
            "is_recommended": True,
            "acceptable_variations": [],
            "evidence_location": field['evidence'],
            "notes": f"Extracted from FAIRiAgent output with confidence {field['confidence']}"
        })

# Process study fields
for field in biorem_output['isa_structure']['study']['fields']:
    if field['status'] == 'confirmed' and field['confidence'] > 0.5:
        ground_truth_fields.append({
            "field_name": field['field_name'],
            "expected_value": field['value'],
            "isa_sheet": "study",
            "package_source": field['package_source'],
            "is_required": field['field_name'].lower() in ['study title', 'study description', 'study identifier'],
            "is_recommended": True,
            "acceptable_variations": [],
            "evidence_location": field['evidence'],
            "notes": f"Extracted from FAIRiAgent output with confidence {field['confidence']}"
        })

# Process assay fields
for field in biorem_output['isa_structure']['assay']['fields']:
    if field['status'] == 'confirmed' and field['confidence'] > 0.5:
        ground_truth_fields.append({
            "field_name": field['field_name'],
            "expected_value": field['value'],
            "isa_sheet": "assay",
            "package_source": field['package_source'],
            "is_required": field['field_name'].lower() in ['assay name', 'measurement type', 'technology type'],
            "is_recommended": True,
            "acceptable_variations": [],
            "evidence_location": field['evidence'],
            "notes": f"Extracted from FAIRiAgent output with confidence {field['confidence']}"
        })

# Process sample fields
for field in biorem_output['isa_structure']['sample']['fields']:
    if field['status'] == 'confirmed' and field['confidence'] > 0.5:
        ground_truth_fields.append({
            "field_name": field['field_name'],
            "expected_value": field['value'],
            "isa_sheet": "sample",
            "package_source": field['package_source'],
            "is_required": field['field_name'].lower() in ['sample name', 'organism'],
            "is_recommended": True,
            "acceptable_variations": [],
            "evidence_location": field['evidence'],
            "notes": f"Extracted from FAIRiAgent output with confidence {field['confidence']}"
        })

# Create BIOREM ground truth document
biorem_ground_truth = {
    "document_id": "biorem",
    "document_path": "evaluation/datasets/raw/biorem/BIOREM_appendix2.pdf",
    "metadata": {
        "domain": "metagenomics",
        "experiment_type": "bioremediation_project",
        "annotation_date": datetime.now().strftime("%Y-%m-%d"),
        "annotator": "changlinke",
        "annotation_time_minutes": 0,
        "notes": "Converted from high-confidence FAIRiAgent extraction (output/20251116_185736)"
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

print(f"📄 BIOREM ground truth:")
print(f"   Total fields: {len(ground_truth_fields)}")
print(f"   Required: {biorem_ground_truth['ground_truth_stats']['total_required_fields']}")
print(f"   Recommended: {biorem_ground_truth['ground_truth_stats']['total_recommended_fields']}")

# Load existing ground truth
with open(ground_truth_path, 'r') as f:
    ground_truth = json.load(f)

# Add BIOREM
ground_truth['documents'].append(biorem_ground_truth)
ground_truth['num_documents'] = len(ground_truth['documents'])
ground_truth['last_modified'] = datetime.now().strftime("%Y-%m-%d")

# Save
with open(ground_truth_path, 'w', encoding='utf-8') as f:
    json.dump(ground_truth, f, indent=2, ensure_ascii=False)

print(f"\n✅ Added BIOREM to {ground_truth_path}")
print(f"📊 Total documents now: {ground_truth['num_documents']}")

