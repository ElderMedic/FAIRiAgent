#!/usr/bin/env python3
"""Compare extracted metadata.json values against ground truth using relaxed matching.

For each non-empty GT value, checks if it appears ANYWHERE in the extracted
output for that field (across all rows).  This is fair for comparing multi-row
GT against potentially merged/single-row LLM output.
"""

import json, sys
from pathlib import Path

def load_gt(gt_path):
    with open(gt_path) as f:
        return json.load(f)

def load_extracted(run_dir):
    meta_paths = list(Path(run_dir).rglob('metadata.json'))
    if not meta_paths:
        return None
    with open(meta_paths[0]) as f:
        return json.load(f)

def compare_relaxed(gt_sheet, ext_sheet):
    """Relaxed comparison: for each non-empty GT value, check if it appears
    in ANY extracted row for that field."""
    gt_rows = gt_sheet.get('expected_rows', [])
    
    # Collect all extracted values per field across all rows
    ext_rows = ext_sheet.get('rows', [])
    if not ext_rows:
        fields = ext_sheet.get('fields', [])
        if fields:
            row = {}
            for f in fields:
                row[f['field_name'].lower()] = str(f.get('value', ''))
            ext_rows = [row]
    
    # Build index: field_name -> set of values across all rows
    ext_values = {}
    for row in ext_rows:
        for k, v in row.items():
            if v:
                ext_values.setdefault(k.lower(), set()).add(str(v).lower())
    
    # Also collect from flat fields if present
    for f in ext_sheet.get('fields', []):
        name = f.get('field_name', '').lower()
        val = f.get('value')
        if name and val:
            ext_values.setdefault(name, set()).add(str(val).lower())
    
    matched = 0
    total = 0
    per_field = {}
    
    for gt_row in gt_rows:
        for field, expected in gt_row.items():
            if field.startswith('_'):
                continue
            if not expected or not str(expected).strip():
                continue
            total += 1
            
            exp_lower = str(expected).strip().lower()
            candidates = ext_values.get(field.lower(), set())
            
            # Check if any extracted value contains the GT value (or vice versa)
            is_match = False
            for cand in candidates:
                if exp_lower in cand or cand in exp_lower:
                    is_match = True
                    break
            
            if is_match:
                matched += 1
            else:
                per_field.setdefault(field, []).append(exp_lower[:60])
    
    return {'matched': matched, 'total': total, 'per_field': per_field, 'ext_fields': set(ext_values.keys())}

def main():
    if len(sys.argv) < 3:
        print("Usage: python compare_values_against_gt.py <gt_values.json> <run_dir>")
        sys.exit(1)
    
    gt = load_gt(sys.argv[1])
    extracted = load_extracted(sys.argv[2])
    
    if not extracted:
        print("❌ No metadata.json found")
        sys.exit(1)
    
    extracted_isa = extracted.get('isa_structure', {})
    gt_sheets = gt.get('isa_sheets', {})
    
    doc_id = gt.get('document_id', 'unknown')
    print(f"\n{'='*70}")
    print(f"  Value Accuracy (relaxed): {doc_id}")
    print(f"{'='*70}")
    
    grand_matched = 0
    grand_total = 0
    
    for sheet_name in ['investigation', 'study', 'observationunit', 'sample', 'assay']:
        gt_sheet = gt_sheets.get(sheet_name, {})
        ext_sheet = extracted_isa.get(sheet_name, {})
        
        result = compare_relaxed(gt_sheet, ext_sheet)
        
        if result['total'] == 0:
            print(f"  [{sheet_name}] No non-empty GT values")
            continue
        
        rate = result['matched'] / result['total'] * 100
        gt_rows = len(gt_sheet.get('expected_rows', []))
        ext_rows = len(ext_sheet.get('rows', []))
        
        print(f"  [{sheet_name}] GT={gt_rows}r ext={ext_rows}r → {result['matched']}/{result['total']} ({rate:.0f}%)")
        
        # Show top 3 missed fields
        missed = sorted(result['per_field'].items(), key=lambda x: -len(x[1]))[:3]
        if missed and rate < 100:
            for field, vals in missed:
                print(f"    ✗ '{field}': expected '{vals[0][:50]}'")
        
        grand_matched += result['matched']
        grand_total += result['total']
    
    if grand_total > 0:
        overall = grand_matched / grand_total * 100
        print(f"\n  {'='*50}")
        print(f"  OVERALL: {grand_matched}/{grand_total} ({overall:.0f}%)")
        print(f"  {'='*50}")

if __name__ == '__main__':
    main()
