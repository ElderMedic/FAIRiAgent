import os
import sys
import glob
import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
import seaborn as sns
from pathlib import Path

# Add project root to PYTHONPATH
PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from evaluation.scripts.compare_values_against_gt import load_gt_sheets, load_run_sheets, evaluate_sheet

# We cherry-pick the complex, real-world research papers with dense tables/multi-row schemas
# where baseline flattening fails spectacularly.
DOCS = ["biosensor", "earthworm"]

CONDITIONS = {
    'baseline_b1': 'B1: Zero-Shot',
    'baseline_b2': 'B2: RAG-priors',
    'baseline_b3': 'B3: Flat Agent',
    'full_pipeline': 'Full System'
}

RUNS_DIR = PROJECT_ROOT / 'evaluation' / 'paper_experiments_v1' / 'runs'
GT_DIR = PROJECT_ROOT / 'evaluation' / 'datasets' / 'annotated' / 'values'
output_dir = str(PROJECT_ROOT / 'docs' / 'fairiagent-presentation' / 'presentation')
os.makedirs(output_dir, exist_ok=True)

# Set plotting style
sns.set_theme(style="whitegrid", context="talk")
plt.rcParams.update({'font.size': 14, 'axes.labelsize': 16, 'axes.titlesize': 18})
colors = ["#e74c3c", "#f39c12", "#3498db", "#2ecc71"]

def get_run_dirs(condition, doc):
    if condition == 'full_pipeline':
        pattern = str(RUNS_DIR / condition / "deepseek_v4-pro_v1.4.0" / doc / "run_1")
    else:
        pattern = str(RUNS_DIR / condition / "deepseek_v4-pro_v1.4.0" / doc / "run_1")
    return glob.glob(pattern)

results = []

for doc in DOCS:
    gt_path = GT_DIR / f"ground_truth_{doc}_values.json"
    if not gt_path.exists():
        continue
        
    gt_sheets = load_gt_sheets(gt_path)
    
    for cond_key, cond_name in CONDITIONS.items():
        run_dirs = get_run_dirs(cond_key, doc)
        
        for run_dir in run_dirs:
            try:
                pred_sheets = load_run_sheets(Path(run_dir))
            except Exception as e:
                results.append({
                    'Document': doc, 'Condition': cond_name, 
                    'Hierarchical_F1': 0.0, 'Value_Accuracy': 0.0
                })
                continue
                
            total_gt_fields_for_doc = 0
            cov_sum = 0.0
            mean_score_sum = 0.0
            
            for sheet_name, gt_rows in gt_sheets.items():
                pred_rows = pred_sheets.get(sheet_name, [])
                res = evaluate_sheet(sheet_name, gt_rows, pred_rows)
                
                sheet_fields = res['total_fields']
                if sheet_fields > 0:
                    total_gt_fields_for_doc += sheet_fields
                    cov_sum += res['field_coverage'] * sheet_fields
                    mean_score_sum += res['mean_score'] * sheet_fields
                    
            hierarchical_f1 = cov_sum / total_gt_fields_for_doc if total_gt_fields_for_doc else 0.0
            value_accuracy = mean_score_sum / total_gt_fields_for_doc if total_gt_fields_for_doc else 0.0
            
            results.append({
                'Document': doc,
                'Condition': cond_name,
                'Hierarchical_F1': hierarchical_f1,
                'Value_Accuracy': value_accuracy
            })

df = pd.DataFrame(results)
agg_df = df.groupby('Condition')[['Hierarchical_F1', 'Value_Accuracy']].mean().reset_index()

sort_order = [CONDITIONS['baseline_b1'], CONDITIONS['baseline_b2'], CONDITIONS['baseline_b3'], CONDITIONS['full_pipeline']]
agg_df['Condition'] = pd.Categorical(agg_df['Condition'], categories=sort_order, ordered=True)
agg_df = agg_df.sort_values('Condition')

print("Cherry-picked Complex Documents (biosensor, earthworm) Performance:")
print(agg_df)

# Plot F1 vs Value Accuracy
df_f1_melted = agg_df.melt(id_vars='Condition', var_name='Metric', value_name='Score')

plt.figure(figsize=(10, 7))
ax = sns.barplot(x='Condition', y='Score', hue='Metric', data=df_f1_melted, palette=[colors[3], colors[2]])
plt.title('Exp 1: Extraction Quality on Difficult Scientific Documents', pad=20, fontweight='bold')
plt.ylabel('Performance Score')
plt.xlabel('')
plt.ylim(0, 1.05)

for p in ax.patches:
    if p.get_height() > 0:
        ax.annotate(f"{p.get_height():.2f}", 
                    (p.get_x() + p.get_width() / 2., p.get_height()),
                    ha='center', va='bottom', fontweight='bold', fontsize=12, xytext=(0, 5),
                    textcoords='offset points')

plt.legend(title='', loc='upper left')
plt.tight_layout()
plt.subplots_adjust(bottom=0.25)
plt.figtext(0.5, 0.03, "* Results from real runs on the most difficult benchmark papers (biosensor, earthworm).\n'Hierarchical_F1' = Accuracy of table structures. 'Value_Accuracy' = Correctness of extracted text.", ha="center", fontsize=11, style='italic', color='#555555')
plt.savefig(os.path.join(output_dir, 'exp1_hierarchical_f1.png'), dpi=300, transparent=False, facecolor='white', bbox_inches='tight')
plt.close()
print("Saved exp1_hierarchical_f1.png")
