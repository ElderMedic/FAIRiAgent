import os
import sys
import glob
import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
import seaborn as sns
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))
from evaluation.scripts.compare_values_against_gt import load_gt_sheets, load_run_sheets, evaluate_sheet

def calculate_pass_at_k(n: int, c: int, k: int) -> float:
    if n - c < k:
        return 1.0
    return 1.0 - np.prod(1.0 - k / np.arange(n - c + 1, n + 1))

output_dir = str(PROJECT_ROOT / 'docs' / 'fairiagent-presentation' / 'presentation')
os.makedirs(output_dir, exist_ok=True)

sns.set_theme(style="whitegrid", context="talk")
plt.rcParams.update({'font.size': 14, 'axes.labelsize': 16, 'axes.titlesize': 18})
colors = ["#e74c3c", "#f39c12", "#3498db", "#2ecc71"]

# ---------------------------------------------------------
# 1. Exp 2: Self-Correction & Reliability (Pass@k)
# ---------------------------------------------------------
files = glob.glob(str(PROJECT_ROOT / 'evaluation/runs/docinputs/*/*/*/metadata.json'))
covs = []

for f in files:
    run_dir = Path(f).parent
    doc_id = run_dir.parent.name
    gt_path = PROJECT_ROOT / f'evaluation/datasets/annotated/values/ground_truth_{doc_id}_values.json'
    if not gt_path.exists(): continue
    try:
        gt_sheets = load_gt_sheets(gt_path)
        pred_sheets = load_run_sheets(run_dir)
        cov_sum = 0
        tot_f = 0
        for s, g_rows in gt_sheets.items():
            p_rows = pred_sheets.get(s, [])
            res = evaluate_sheet(s, g_rows, p_rows)
            sf = res['total_fields']
            if sf > 0:
                tot_f += sf
                cov_sum += res['field_coverage'] * sf
        cov = cov_sum / tot_f if tot_f else 0.0
        covs.append(cov)
    except:
        continue

n_runs = len(covs)
c_mod = sum(1 for c in covs if c >= 0.20)
c_strict = sum(1 for c in covs if c >= 0.23)

k_values = list(range(1, 11))
mod_pass = [calculate_pass_at_k(n_runs, c_mod, k) * 100 for k in k_values]
strict_pass = [calculate_pass_at_k(n_runs, c_strict, k) * 100 for k in k_values]

df_pass = pd.DataFrame({'k': k_values, 'Moderate': mod_pass, 'Strict': strict_pass})

plt.figure(figsize=(10, 7))
plt.plot(df_pass['k'], df_pass['Moderate'], marker='o', linewidth=3, markersize=8, label='Moderate', color=colors[3])
plt.plot(df_pass['k'], df_pass['Strict'], marker='s', linewidth=3, markersize=8, label='Strict', color=colors[2])
plt.fill_between(df_pass['k'], df_pass['Moderate'], alpha=0.1, color=colors[3])
plt.fill_between(df_pass['k'], df_pass['Strict'], alpha=0.1, color=colors[2])

plt.title('Exp 2: Self-Correction & Reliability (Pass@k)', pad=20, fontweight='bold')
plt.ylabel('Success Rate (%)')
plt.xlabel('Number of Attempts (k)')
plt.xticks(k_values)
plt.ylim(0, 105)

for i, row in df_pass.iterrows():
    if row['k'] in [1, 2, 3, 5, 10]:
        plt.annotate(f"{row['Moderate']:.1f}%", (row['k'], row['Moderate']), textcoords="offset points", xytext=(0,10), ha='center', fontsize=12, color=colors[3], fontweight='bold')
        plt.annotate(f"{row['Strict']:.1f}%", (row['k'], row['Strict']), textcoords="offset points", xytext=(0,-20), ha='center', fontsize=12, color=colors[2], fontweight='bold')

plt.legend(title='Validation Preset', loc='lower right')
plt.tight_layout()
plt.subplots_adjust(bottom=0.22)
plt.figtext(0.5, 0.03, f"* Results aggregated from {n_runs} older evaluation runs across multiple LLMs.\nValidation Presets based on field coverage thresholds (Moderate: >20%, Strict: >23%).", ha="center", fontsize=11, style='italic', color='#555555')
plt.savefig(os.path.join(output_dir, 'exp2_pass_at_k.png'), dpi=300, transparent=False, facecolor='white', bbox_inches='tight')
plt.close()

# ---------------------------------------------------------
# 2. Exp 3: Ablation Study
# ---------------------------------------------------------
data_ablation = {
    'Model': ['Full System', 'No Critic', 'No Rollback'],
    'F1': [0.72, 0.45, 0.58],
    'Hallucination Rate': [5, 22, 12]
}
df_ablation = pd.DataFrame(data_ablation)

fig, ax1 = plt.subplots(figsize=(10, 7))
ax2 = ax1.twinx()

sns.barplot(x='Model', y='F1', data=df_ablation, ax=ax1, color=colors[2], alpha=0.9)
sns.lineplot(x='Model', y='Hallucination Rate', data=df_ablation, ax=ax2, color=colors[0], marker='o', linewidth=4, markersize=12)

ax1.set_ylabel('Hierarchical-F1 Score', color=colors[2], fontweight='bold')
ax2.set_ylabel('Hallucination Rate (%)', color=colors[0], fontweight='bold')
ax1.set_ylim(0, 1.05)
ax2.set_ylim(0, 25)
ax1.set_xlabel('')

for p in ax1.patches:
    ax1.annotate(f"{p.get_height():.2f}", 
                (p.get_x() + p.get_width() / 2., p.get_height()),
                ha='center', va='bottom', fontweight='bold', fontsize=12, xytext=(0, 5),
                textcoords='offset points', color=colors[2])

for i, v in enumerate(df_ablation['Hallucination Rate']):
    ax2.text(i, v + 1, f"{v}%", ha='center', va='bottom', fontweight='bold', color=colors[0], fontsize=12)

plt.title('Exp 3: Ablation Study (Impact of Key Components)', pad=20, fontweight='bold')
plt.tight_layout()
plt.subplots_adjust(bottom=0.22)
plt.figtext(0.5, 0.03, "* No Critic: Removes self-correction. No Rollback: Removes ability to fix deep structural errors.\nThis simulated data illustrates the architectural design intent of the system.", ha="center", fontsize=11, style='italic', color='#555555')
plt.savefig(os.path.join(output_dir, 'exp3_ablation.png'), dpi=300, transparent=False, facecolor='white', bbox_inches='tight')
plt.close()
