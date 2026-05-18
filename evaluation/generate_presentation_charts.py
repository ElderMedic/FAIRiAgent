import json
import glob
import os
from collections import defaultdict
import numpy as np
import matplotlib.pyplot as plt
import seaborn as sns

# Set plotting style
sns.set_theme(style="whitegrid", context="paper")
plt.rcParams.update({'font.size': 12, 'axes.labelsize': 14, 'axes.titlesize': 16})

# Documents (Tier A & Tier B from DATASET_README.md)
DOCUMENTS = [
    'arabidopsis_vacuolar_srna', 'pea_cold_stress', 'sea_cucumber_gut_metagenome',
    'human_gut_microbiome_temporal', 'aetherobacter_fasciculatus_genome', 
    'pseudomonas_recombinase_screen', 'biosensor', 'earthworm'
]

CONDITIONS = {
    'baseline_b1': 'B1: Zero-Shot',
    'baseline_b2': 'B2: RAG-priors',
    'baseline_b3': 'B3: Flat Agent',
    'full_pipeline': 'Full System (Critic+Rollback)'
}

RUNS_DIR = str(PROJECT_ROOT / 'evaluation' / 'paper_experiments_v1' / 'runs')
GT_DIR = str(PROJECT_ROOT / 'evaluation' / 'datasets' / 'annotated' / 'values')

def normalize_string(s):
    if not isinstance(s, str):
        return str(s).strip().lower()
    return s.strip().lower()

def load_ground_truth(doc):
    gt_path = os.path.join(GT_DIR, f'ground_truth_{doc}_values.json')
    if not os.path.exists(gt_path):
        return None
    with open(gt_path) as f:
        data = json.load(f)
    
    gt_fields = []
    if 'isa_sheets' in data:
        for sheet_name, sheet_content in data['isa_sheets'].items():
            if isinstance(sheet_content, dict) and 'expected_rows' in sheet_content:
                for row_idx, row in enumerate(sheet_content['expected_rows']):
                    for field_name, field_value in row.items():
                        if field_name != '_evidence':
                            gt_fields.append({
                                'sheet': sheet_name,
                                'row_idx': row_idx,
                                'field': field_name,
                                'value': str(field_value)
                            })
    return gt_fields

def load_predictions(condition, doc):
    pattern = f"{RUNS_DIR}/{condition}/*/{doc}/run_1/metadata.json"
    files = glob.glob(pattern)
    if not files:
        return []
    
    all_preds = []
    for file_path in files:
        with open(file_path) as f:
            data = json.load(f)
            
        pred_fields = []
        if 'isa_values' in data:
            for sheet_name, sheet_content in data['isa_values'].items():
                if isinstance(sheet_content, dict) and 'rows' in sheet_content:
                    for row_idx, row in enumerate(sheet_content['rows']):
                        for field_name, field_value in row.items():
                            if field_value and str(field_value).strip() not in ['', 'None', 'N/A', 'null']:
                                pred_fields.append({
                                    'sheet': sheet_name,
                                    'row_idx': row_idx,
                                    'field': field_name,
                                    'value': str(field_value)
                                })
        
        all_preds.append(pred_fields)
    return all_preds

results = []

for doc in DOCUMENTS:
    gt_fields = load_ground_truth(doc)
    if not gt_fields:
        continue
        
    # Proxy for Hierarchical F1: (sheet, row_idx, field) must match
    gt_keys = set([f"{f['sheet']}||{f['row_idx']}||{f['field']}" for f in gt_fields])
    
    for condition in CONDITIONS:
        all_preds = load_predictions(condition, doc)
        if not all_preds:
            continue
            
        for pred_fields in all_preds:
            # Order-independent Hierarchical comparison (Greedy match)
            tp = 0
            fp = 0
            fn = 0
            
            # Group by sheet
            pred_sheets = defaultdict(list)
            for p in pred_fields:
                pred_sheets[p['sheet']].append(p)
                
            gt_sheets = defaultdict(list)
            for g in gt_fields:
                gt_sheets[g['sheet']].append(g)
                
            matched_pred_rows = set()
            matched_gt_rows = set()
            
            value_correct = 0
            total_eval = 0
            
            for sheet in set(list(pred_sheets.keys()) + list(gt_sheets.keys())):
                p_rows = defaultdict(list)
                for p in pred_sheets[sheet]: p_rows[p['row_idx']].append(p)
                
                g_rows = defaultdict(list)
                for g in gt_sheets[sheet]: g_rows[g['row_idx']].append(g)
                
                # For each GT row, find best Pred row
                used_p = set()
                for g_idx, g_row_fields in g_rows.items():
                    best_p_idx = -1
                    best_overlap = -1
                    best_overlap_fields = []
                    
                    g_field_names = set([f['field'] for f in g_row_fields])
                    
                    for p_idx, p_row_fields in p_rows.items():
                        if p_idx in used_p: continue
                        p_field_names = set([f['field'] for f in p_row_fields])
                        overlap = len(g_field_names & p_field_names)
                        if overlap > best_overlap:
                            best_overlap = overlap
                            best_p_idx = p_idx
                            best_overlap_fields = p_row_fields
                            
                    if best_p_idx != -1:
                        used_p.add(best_p_idx)
                        # We have a match!
                        p_field_names = set([f['field'] for f in best_overlap_fields])
                        tp += best_overlap
                        fp += len(p_field_names - g_field_names)
                        fn += len(g_field_names - p_field_names)
                        
                        # Calculate value correctness for the matched fields
                        for g_f in g_row_fields:
                            for p_f in best_overlap_fields:
                                if g_f['field'] == p_f['field']:
                                    total_eval += 1
                                    p_val = normalize_string(p_f['value'])
                                    g_val = normalize_string(g_f['value'])
                                    if p_val == g_val or (p_val in g_val) or (g_val in p_val and len(g_val) > 2):
                                        value_correct += 1
                                    break
                    else:
                        fn += len(g_field_names)
                        
                for p_idx, p_row_fields in p_rows.items():
                    if p_idx not in used_p:
                        fp += len(p_row_fields)
                
            precision = tp / (tp + fp) if (tp + fp) > 0 else 0
            recall = tp / (tp + fn) if (tp + fn) > 0 else 0
            f1_structure = 2 * precision * recall / (precision + recall) if (precision + recall) > 0 else 0
            
            value_accuracy = value_correct / total_eval if total_eval > 0 else 0

            
            results.append({
                'document': doc,
                'condition': CONDITIONS[condition],
                'f1_structure': f1_structure,
                'value_accuracy': value_accuracy
            })

import pandas as pd
df = pd.DataFrame(results)

if df.empty:
    print("No data extracted. Exiting.")
    exit()

# Aggregate over documents
agg_df = df.groupby('condition')[['f1_structure', 'value_accuracy']].mean().reset_index()

# Sort to follow baseline_b1 -> full_pipeline order
sort_order = [CONDITIONS['baseline_b1'], CONDITIONS['baseline_b2'], CONDITIONS['baseline_b3'], CONDITIONS['full_pipeline']]
agg_df['condition'] = pd.Categorical(agg_df['condition'], categories=sort_order, ordered=True)
agg_df = agg_df.sort_values('condition')

print("Aggregated Scores across Documents:")
print(agg_df)

# Colors aligning with standard paper visualization
colors = ["#e74c3c", "#f39c12", "#3498db", "#2ecc71"]

# 1. Chart for Metadata Generation
plt.figure(figsize=(8, 6))
ax = sns.barplot(x='condition', y='f1_structure', data=agg_df, palette=colors)
plt.title('Hierarchical Metadata Reconstruction Quality\n(Field Presence + ISA Sheet Assignment F1)', pad=15)
plt.ylabel('Hierarchical-F1 Score')
plt.xlabel('')
plt.ylim(0, 1.0)
for i, v in enumerate(agg_df['f1_structure']):
    ax.text(i, v + 0.02, f"{v:.2f}", ha='center', va='bottom', fontweight='bold')
plt.xticks(rotation=15)
plt.tight_layout()
plt.savefig('metadata_generation_f1.png', dpi=300)
print("Saved metadata_generation_f1.png")

# 2. Chart for Value Extraction
plt.figure(figsize=(8, 6))
ax = sns.barplot(x='condition', y='value_accuracy', data=agg_df, palette=colors)
plt.title('Value Extraction Accuracy\n(Correctness of Extracted Values)', pad=15)
plt.ylabel('Value Extraction Accuracy')
plt.xlabel('')
plt.ylim(0, 1.0)
for i, v in enumerate(agg_df['value_accuracy']):
    ax.text(i, v + 0.02, f"{v:.2f}", ha='center', va='bottom', fontweight='bold')
plt.xticks(rotation=15)
plt.tight_layout()
plt.savefig('value_extraction_accuracy.png', dpi=300)
print("Saved value_extraction_accuracy.png")
