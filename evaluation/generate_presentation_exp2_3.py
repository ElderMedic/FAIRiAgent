import json
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


def _structural_confidence_from_log(processing_log: Path) -> float:
    """Last aggregate.structural confidence_score in processing_log.jsonl."""
    structural = 0.0
    if not processing_log.is_file():
        return structural
    with open(processing_log, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue
            if row.get("event") != "confidence_score":
                continue
            if row.get("component") == "aggregate.structural":
                structural = float(row.get("score", 0.0))
    return structural


COMPOSITE_ALPHA = 0.15  # weight on structural confidence S
COMPOSITE_BETA = 0.85   # weight on powered grounding term
COMPOSITE_GAMMA = 3.0   # exponent on (1−U/T); >1 penalises ungrounded mass more sharply


def load_ablation_run_metrics(run_dir: Path) -> dict:
    """
    Metrics from workflow_report.json + processing_log (no external GT).

    composite_quality: α·S + β·(1 − U/T)^γ  (S from processing_log aggregate.structural;
    U,T from workflow_report). Larger γ separates runs where U/T differs only slightly.
    ungrounded_rate_pct: 100 * ungrounded_high_confidence_fields / total_fields
    """
    wr_path = run_dir / "workflow_report.json"
    log_path = run_dir / "processing_log.jsonl"
    if not wr_path.is_file():
        raise FileNotFoundError(wr_path)
    with open(wr_path, encoding="utf-8") as f:
        wr = json.load(f)
    qm = wr.get("quality_metrics") or {}
    total = int(qm.get("total_fields") or 0)
    sg = qm.get("source_grounding") or {}
    ung = int(sg.get("ungrounded_high_confidence_fields") or 0)
    if total <= 0:
        raise ValueError(f"total_fields missing or zero in {wr_path}")
    structural = _structural_confidence_from_log(log_path)
    grounded_trust = 1.0 - (ung / total)
    powered_ground = float(np.clip(grounded_trust, 0.0, 1.0)) ** COMPOSITE_GAMMA
    composite = COMPOSITE_ALPHA * structural + COMPOSITE_BETA * powered_ground
    ungrounded_pct = 100.0 * ung / total
    return {
        "run_dir": str(run_dir),
        "workflow_generated_at": wr.get("generated_at"),
        "total_fields": total,
        "ungrounded_high_confidence_fields": ung,
        "structural_confidence": round(structural, 4),
        "grounded_trust": round(grounded_trust, 4),
        "powered_ground_term": round(powered_ground, 4),
        "composite_quality": round(composite, 4),
        "ungrounded_high_conf_frac": round(ung / total, 4),
        "ungrounded_rate_pct": round(ungrounded_pct, 2),
    }


output_dir = str(PROJECT_ROOT / 'evaluation' / 'paper_experiments_v1' / 'figures' / 'presentation')
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
# 2. Exp 3: Ablation Study (same document, three toggle settings)
# ---------------------------------------------------------
ABLATION_ROOT = PROJECT_ROOT / "evaluation" / "ablation_quick_run"
ABLATION_VARIANTS = [
    ("Full pipeline", ABLATION_ROOT / "full_system"),
    ("Without critic", ABLATION_ROOT / "no_critic"),
    ("Without rollback", ABLATION_ROOT / "no_rollback"),
]
ablation_metrics = []
for label, run_dir in ABLATION_VARIANTS:
    m = load_ablation_run_metrics(run_dir)
    m["label"] = label
    ablation_metrics.append(m)

summary_path = ABLATION_ROOT / "ablation_chart_metrics.json"
with open(summary_path, "w", encoding="utf-8") as f:
    json.dump(
        {
            "document": "evaluation/datasets/raw/aetherobacter_fasciculatus_genome/study_narrative.md",
            "composite_formula": (
                f"{COMPOSITE_ALPHA} * S + {COMPOSITE_BETA} * (1 - U/T) ** {COMPOSITE_GAMMA}; "
                "S = aggregate.structural (processing_log); U,T = ungrounded_high_confidence_fields, "
                "total_fields (workflow_report)"
            ),
            "hallucination_rate_in_figure": (
                "Same as ungrounded_rate_pct: 100 * ungrounded_high_confidence_fields / total_fields "
                "(workflow_report quality_metrics.source_grounding)"
            ),
            "variants": ablation_metrics,
        },
        f,
        indent=2,
    )

df_ablation = pd.DataFrame(
    {
        "Condition": [m["label"] for m in ablation_metrics],
        "Composite quality": [m["composite_quality"] for m in ablation_metrics],
        # Operational proxy: confident-in-output but not source-grounded (workflow_report)
        "Hallucination rate (%)": [m["ungrounded_rate_pct"] for m in ablation_metrics],
    }
)

fig, ax1 = plt.subplots(figsize=(10, 7))
ax2 = ax1.twinx()

sns.barplot(x='Condition', y='Composite quality', data=df_ablation, ax=ax1, color=colors[2], alpha=0.9)
sns.lineplot(x='Condition', y='Hallucination rate (%)', data=df_ablation, ax=ax2, color=colors[0], marker='o', linewidth=4, markersize=12)

ax1.set_ylabel(
    'Composite score',
    color=colors[2],
    fontweight='bold',
)
ax2.set_ylabel(
    'Hallucination rate (%)',
    color=colors[0],
    fontweight='bold',
)
ax1.set_ylim(0, 1.05)
u_max = float(df_ablation['Hallucination rate (%)'].max())
ax2.set_ylim(0, max(50.0, u_max * 1.15))
ax1.set_xlabel('')

for p in ax1.patches:
    ax1.annotate(
        f"{p.get_height():.2f}",
        (p.get_x() + p.get_width() / 2.0, p.get_height()),
        ha='center',
        va='bottom',
        fontweight='bold',
        fontsize=12,
        xytext=(0, 5),
        textcoords='offset points',
        color=colors[2],
    )

for i, v in enumerate(df_ablation['Hallucination rate (%)']):
    ax2.text(
        i,
        v + u_max * 0.04,
        f"{v:.1f}%",
        ha='center',
        va='bottom',
        fontweight='bold',
        color=colors[0],
        fontsize=12,
    )

plt.title('Does each part of the architecture matter?', pad=20, fontweight='bold')
plt.tight_layout()
plt.subplots_adjust(bottom=0.28)
footnote = (
    f"Bar — composite: {COMPOSITE_ALPHA}·S + {COMPOSITE_BETA}·(1−U/T)^{int(COMPOSITE_GAMMA)}. "
    "S = structural confidence at end of run (processing_log: aggregate.structural). "
    "U = ungrounded_high_confidence fields, T = total fields (workflow_report). "
    "The cube on (1−U/T) stresses evidence grounding: small increases in U/T lower the bar clearly. "
    "Red line — hallucination rate: 100×(U/T) (higher is worse)."
)
plt.figtext(
    0.5,
    0.015,
    footnote,
    ha="center",
    fontsize=9,
    style="italic",
    color="#555555",
)
ablation_fig_path = os.path.join(output_dir, 'exp3_ablation.png')
plt.savefig(ablation_fig_path, dpi=300, transparent=False, facecolor='white', bbox_inches='tight')
plt.close()

from evaluation.paper_experiments_v1.sync_presentation_assets import sync_presentation_assets

sync_presentation_assets()
print("Synced presentation-v2/public/figs")
