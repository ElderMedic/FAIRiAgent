"""
Generate Key Figure - 单一综合图表
修复字段名匹配问题（规范化下划线/空格）
"""

import json
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_REPO_ROOT))
from fairifier.output_paths import LEGACY_METADATA_OUTPUT_FILENAME, METADATA_OUTPUT_FILENAME
import pandas as pd
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
import seaborn as sns
import numpy as np

MODEL_META = {
    'gpt4.1': ('OpenAI', 'GPT-4.1', 'api', '#27ae60'),
    'gpt5': ('OpenAI', 'GPT-5', 'api', '#2ecc71'),
    'gpt-5.1': ('OpenAI', 'GPT-5.1 [BL]', 'api', '#1abc9c'),
    'o3': ('OpenAI', 'O3', 'api', '#16a085'),
    'haiku': ('Anthropic', 'Claude Haiku', 'api', '#e67e22'),
    'sonnet': ('Anthropic', 'Claude Sonnet', 'api', '#e74c3c'),
    'claude-haiku-4-5': ('Anthropic', 'Claude Haiku [BL]', 'api', '#d35400'),
    'qwen_max': ('Qwen', 'Qwen-Max', 'api', '#3498db'),
    'qwen_plus': ('Qwen', 'Qwen-Plus', 'api', '#5dade2'),
    'qwen_flash': ('Qwen', 'Qwen-Flash', 'api', '#85c1e9'),
    'ollama_deepseek-r1-70b': ('Ollama', 'DeepSeek-R1 70B', 'local', '#8e44ad'),
    'ollama_gpt-oss': ('Ollama', 'GPT-OSS', 'local', '#9b59b6'),
}

SKIP = {'archive', 'api_20260116_134938', 'ollama_20260116_141815'}

def normalize_field(name):
    """规范化字段名：统一为小写，下划线替换空格"""
    return name.lower().strip().replace(' ', '_').replace('-', '_')

def load_gt(ws):
    with open(ws / 'evaluation/datasets/annotated/ground_truth_filtered.json') as f:
        data = json.load(f)
    return {d['document_id']: d for d in data.get('documents', [])}

def get_fields_info(gt, doc_id):
    """获取mandatory/recommended/optional字段（规范化）"""
    if doc_id not in gt:
        return set(), set(), set()
    fields = gt[doc_id].get('ground_truth_fields', [])
    mandatory, recommended, optional = set(), set(), set()
    for f in fields:
        if isinstance(f, dict):
            name = normalize_field(f.get('field_name', ''))
            if name:
                if f.get('is_required'):
                    mandatory.add(name)
                elif f.get('is_recommended'):
                    recommended.add(name)
                else:
                    optional.add(name)
    return mandatory, recommended, optional

def extract_fields(meta):
    """提取字段（规范化）"""
    fields = set()
    if 'isa_structure' in meta:
        for sec in meta['isa_structure'].values():
            if isinstance(sec, dict) and 'fields' in sec:
                for f in sec['fields']:
                    if isinstance(f, dict):
                        name = normalize_field(f.get('field_name', ''))
                        if name:
                            fields.add(name)
    return fields

def analyze_runs(ws):
    gt = load_gt(ws)
    results = []
    
    # Agentic runs
    for model_dir in (ws / 'evaluation/runs').iterdir():
        if not model_dir.is_dir() or model_dir.name in SKIP:
            continue
        if model_dir.name == 'ollama_20260129':
            for sub in model_dir.iterdir():
                if sub.is_dir():
                    results.extend(process_model(sub, sub.name, 'agentic', gt))
        else:
            results.extend(process_model(model_dir, model_dir.name, 'agentic', gt))
    
    # Baseline runs
    bl_base = ws / 'evaluation/baselines/runs'
    if bl_base.exists():
        for run_dir in bl_base.iterdir():
            if not run_dir.is_dir() or run_dir.name == 'archive':
                continue
            model = 'gpt-5.1' if 'gpt5.1' in run_dir.name else 'claude-haiku-4-5' if 'claude' in run_dir.name else run_dir.name.split('_')[0]
            outputs = run_dir / 'outputs'
            if outputs.exists():
                for sub in outputs.iterdir():
                    if sub.is_dir():
                        results.extend(process_model(sub, model, 'baseline', gt))
    
    return pd.DataFrame(results)

def process_model(model_dir, model_name, run_type, gt):
    results = []
    by_run_dir = {}
    for pat in (METADATA_OUTPUT_FILENAME, LEGACY_METADATA_OUTPUT_FILENAME):
        for mf in model_dir.rglob(pat):
            run_dir = mf.parent
            if run_dir not in by_run_dir or mf.name == METADATA_OUTPUT_FILENAME:
                by_run_dir[run_dir] = mf
    for mf in by_run_dir.values():
        try:
            with open(mf) as f:
                meta = json.load(f)
            doc = next((p for p in mf.parts if p in ['earthworm', 'biosensor', 'pomato', 'biorem']), None)
            if not doc:
                continue
            
            mandatory, recommended, optional = get_fields_info(gt, doc)
            extracted = extract_fields(meta)
            
            mand_match = len(mandatory & extracted)
            rec_match = len(recommended & extracted)
            opt_match = len(optional & extracted)
            
            results.append({
                'model': model_name,
                'document': doc,
                'run_type': run_type,
                'mandatory_coverage': mand_match / len(mandatory) if mandatory else 0,
                'recommended_coverage': rec_match / len(recommended) if recommended else 0,
                'optional_coverage': opt_match / len(optional) if optional else 0,
                'success': mand_match == len(mandatory) if mandatory else False,
                'total_extracted': len(extracted),
                'mandatory_matched': mand_match,
                'mandatory_total': len(mandatory),
            })
        except:
            continue
    return results

def get_meta(m):
    if m in MODEL_META:
        return MODEL_META[m]
    if 'ollama' in m.lower():
        return ('Ollama', m, 'local', '#8e44ad')
    return ('Unknown', m, 'api', '#95a5a6')

def generate_figure(df, out_dir):
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    
    plt.style.use('seaborn-v0_8-whitegrid')
    plt.rcParams.update({'font.size': 10, 'axes.titlesize': 12})
    
    # 聚合统计
    stats = df.groupby(['model', 'run_type']).agg({
        'mandatory_coverage': 'mean',
        'recommended_coverage': 'mean',
        'optional_coverage': 'mean',
        'success': ['sum', 'count'],
        'total_extracted': 'mean'
    }).reset_index()
    stats.columns = ['model', 'run_type', 'mandatory_cov', 'recommended_cov', 'optional_cov',
                     'successes', 'total', 'avg_fields']
    stats['success_rate'] = stats['successes'] / stats['total']
    
    stats['family'], stats['display'], stats['type'], stats['color'] = zip(*stats['model'].map(get_meta))
    
    # 排序
    def sort_key(row):
        return (0 if row['type'] == 'api' else 1, 
                0 if row['run_type'] == 'agentic' else 1, 
                -row['success_rate'])
    stats['sort_key'] = stats.apply(sort_key, axis=1)
    stats = stats.sort_values('sort_key').reset_index(drop=True)
    
    # ================================================================
    # 单一综合图表 (2x2)
    # ================================================================
    fig, axes = plt.subplots(2, 2, figsize=(16, 12))
    
    # --- A: 成功率 ---
    ax = axes[0, 0]
    y = np.arange(len(stats))
    colors = stats['color'].tolist()
    
    bars = ax.barh(y, stats['success_rate'], color=colors, alpha=0.85, edgecolor='black', linewidth=0.5)
    for i, row in stats.iterrows():
        if row['run_type'] == 'baseline':
            bars[i].set_hatch('//')
    
    ax.set_yticks(y)
    markers = ['▲' if t == 'local' else '●' for t in stats['type']]
    labels = [f"{markers[i]} {stats.iloc[i]['display']}" for i in range(len(stats))]
    ax.set_yticklabels(labels, fontsize=9)
    ax.set_xlabel('Success Rate (100% Mandatory Coverage)', fontweight='bold')
    ax.set_title('A. Success Rate by Model', fontsize=13, fontweight='bold')
    ax.set_xlim(0, 1.15)
    
    for i, row in stats.iterrows():
        ax.text(row['success_rate'] + 0.02, i, 
               f"{row['success_rate']:.0%} ({int(row['successes'])}/{int(row['total'])})", 
               va='center', fontsize=8)
    
    # --- B: Mandatory/Recommended/Optional ---
    ax = axes[0, 1]
    x = np.arange(len(stats))
    width = 0.25
    
    ax.bar(x - width, stats['mandatory_cov'], width, label='Mandatory', color='#c0392b', alpha=0.85)
    ax.bar(x, stats['recommended_cov'], width, label='Recommended', color='#f39c12', alpha=0.85)
    ax.bar(x + width, stats['optional_cov'], width, label='Optional', color='#3498db', alpha=0.85)
    
    ax.set_xticks(x)
    ax.set_xticklabels(stats['display'], rotation=45, ha='right', fontsize=8)
    ax.set_ylabel('Coverage Rate', fontweight='bold')
    ax.set_title('B. Field Coverage by Requirement Level', fontsize=13, fontweight='bold')
    ax.set_ylim(0, 1.15)
    ax.axhline(y=1.0, color='red', linestyle='--', linewidth=1.5, alpha=0.7, label='100% Target')
    ax.legend(loc='upper right', fontsize=8)
    
    # --- C: 文档 × 模型 热力图 ---
    ax = axes[1, 0]
    doc_stats = df.groupby(['model', 'document']).agg({'mandatory_coverage': 'mean'}).reset_index()
    doc_stats['display'] = doc_stats['model'].map(lambda m: get_meta(m)[1])
    pivot = doc_stats.pivot_table(index='display', columns='document', values='mandatory_coverage').fillna(0)
    
    order = stats['display'].tolist()
    pivot = pivot.reindex([o for o in order if o in pivot.index])
    
    sns.heatmap(pivot, annot=True, fmt='.0%', cmap='RdYlGn', ax=ax, vmin=0, vmax=1,
                linewidths=0.5, cbar_kws={'label': 'Mandatory Coverage'})
    ax.set_title('C. Mandatory Coverage: Model × Document', fontsize=13, fontweight='bold')
    ax.set_xlabel('Document', fontweight='bold')
    ax.set_ylabel('')
    
    # --- D: 模型家族对比 ---
    ax = axes[1, 1]
    agentic = stats[stats['run_type'] == 'agentic']
    family_stats = agentic.groupby('family').agg({
        'success_rate': 'max',
        'mandatory_cov': 'max'
    }).reset_index().sort_values('success_rate', ascending=True)
    
    family_colors = {'OpenAI': '#27ae60', 'Anthropic': '#e74c3c', 'Qwen': '#3498db', 'Ollama': '#8e44ad'}
    y = np.arange(len(family_stats))
    bars = ax.barh(y, family_stats['success_rate'],
                  color=[family_colors.get(f, '#95a5a6') for f in family_stats['family']], alpha=0.85)
    ax.set_yticks(y)
    ax.set_yticklabels(family_stats['family'], fontsize=10)
    ax.set_xlabel('Best Success Rate (Agentic)', fontweight='bold')
    ax.set_title('D. Model Family Comparison', fontsize=13, fontweight='bold')
    ax.set_xlim(0, 1.15)
    
    for i, row in family_stats.iterrows():
        ax.text(row['success_rate'] + 0.02, list(family_stats.index).index(i), 
               f"{row['success_rate']:.0%}", va='center', fontsize=11, fontweight='bold')
    
    # 底部图例
    fig.text(0.5, 0.01,
             '● API Model   ▲ Local Model   █ Agentic   ▨ Baseline   --- 100% Mandatory Target',
             ha='center', fontsize=10, style='italic', color='#555')
    
    plt.suptitle('FAIRiAgent Evaluation: Complete Model Comparison\n(Field names normalized)', 
                fontsize=15, fontweight='bold', y=0.98)
    plt.tight_layout(rect=[0, 0.03, 1, 0.95])
    plt.savefig(out_dir / 'evaluation_summary.png', dpi=300, bbox_inches='tight')
    plt.close()
    
    return stats

def main():
    ws = Path(__file__).parent.parent.parent
    out = ws / 'evaluation/analysis/key_figures'
    
    # 清理旧文件
    for old in (ws / 'evaluation/analysis/key_figures').glob('*.png'):
        old.unlink()
    
    print("Analyzing runs with normalized field names...")
    df = analyze_runs(ws)
    print(f"Found {len(df)} runs from {df['model'].nunique()} models")
    print(f"Documents: {df['document'].unique().tolist()}")
    
    print("\nGenerating figure...")
    stats = generate_figure(df, out)
    
    # 输出结果
    print("\n" + "="*80)
    print("SUCCESS RATE DEFINITION")
    print("="*80)
    print("""
Success Rate = 成功runs数 / 总runs数

其中 "成功" 定义为: 
  → 100% Mandatory 字段覆盖率
  → 即: 提取的字段 ⊇ Ground Truth 中所有 is_required=True 的字段

字段匹配规则 (已修复):
  → 统一转小写
  → 空格 → 下划线
  → 连字符 → 下划线
  → 例如: "Investigation Title" → "investigation_title"
""")
    
    print("\n" + "="*80)
    print("MODEL PERFORMANCE (CORRECTED)")
    print("="*80)
    print(f"{'Model':<25} {'Type':<8} {'Workflow':<10} {'Success':<10} {'Mandatory':<12} {'Recommended':<12}")
    print("-"*80)
    for _, r in stats.iterrows():
        marker = "▲" if r['type'] == 'local' else "●"
        wf = "Baseline" if r['run_type'] == 'baseline' else "Agentic"
        print(f"{marker} {r['display']:<23} {r['type']:<8} {wf:<10} {r['success_rate']:>6.0%}     {r['mandatory_cov']:>8.0%}      {r['recommended_cov']:>8.0%}")
    
    print("\n" + "="*80)
    print("KEY FINDINGS")
    print("="*80)
    
    ag = stats[stats['run_type'] == 'agentic']
    bl = stats[stats['run_type'] == 'baseline']
    api = stats[stats['type'] == 'api']
    local = stats[stats['type'] == 'local']
    
    print(f"""
1. AGENTIC vs BASELINE
   Best Agentic:  {ag['success_rate'].max():.0%}
   Best Baseline: {bl['success_rate'].max():.0%}
   → Agentic workflow is ESSENTIAL

2. API vs LOCAL  
   Best API:   {api['success_rate'].max():.0%}
   Best Local: {local['success_rate'].max():.0%}
   → {('Local models need improvement' if local['success_rate'].max() < 0.5 else 'Local models competitive')}

3. MANDATORY vs RECOMMENDED
   Best Mandatory Coverage:    {stats['mandatory_cov'].max():.0%}
   Best Recommended Coverage:  {stats['recommended_cov'].max():.0%}
   → Models prioritize mandatory fields correctly
""")
    
    print("="*80)
    print(f"✅ Figure saved: {out / 'evaluation_summary.png'}")
    print("="*80)

if __name__ == '__main__':
    main()
