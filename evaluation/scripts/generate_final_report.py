"""
Generate Final Evaluation Report
综合报告：包含模型性能 + 字段分析 + Emergent验证
回应会议意见：highlight mandatory/optional，验证emergent fields
"""

import json
from pathlib import Path
import pandas as pd
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
import seaborn as sns
import numpy as np

# Model metadata
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
    'ollama_deepseek-r1-70b': ('Ollama', 'DeepSeek-R1', 'local', '#8e44ad'),
    'ollama_gpt-oss': ('Ollama', 'GPT-OSS', 'local', '#9b59b6'),
}

def normalize(name):
    return name.lower().strip().replace(' ', '_').replace('-', '_')

def load_data(ws):
    # Ground truth
    with open(ws / 'evaluation/datasets/annotated/ground_truth_filtered.json') as f:
        gt_data = json.load(f)
    
    gt_fields = {}
    for doc in gt_data['documents']:
        for f in doc.get('ground_truth_fields', []):
            if isinstance(f, dict):
                name = normalize(f.get('field_name', ''))
                if name:
                    status = 'mandatory' if f.get('is_required') else 'recommended' if f.get('is_recommended') else 'optional'
                    gt_fields[name] = {'status': status, 'original': f.get('field_name', '')}
    
    # Biological insights
    with open(ws / 'evaluation/analysis/output/biological_insights.json') as f:
        bio = json.load(f)
    
    return gt_fields, bio

def analyze_emergent_fields(gt_fields, bio):
    """分析emergent fields的有效性"""
    ep = bio['emergent_patterns_analysis']
    top_candidates = ep['top_candidates']
    
    results = []
    for item in top_candidates:
        field_name = item['field_name']
        norm_name = normalize(field_name)
        
        # 检查是否真的是emergent
        if norm_name in gt_fields:
            gt_status = gt_fields[norm_name]['status']
            is_true_emergent = False
        else:
            gt_status = 'emergent'
            is_true_emergent = True
        
        results.append({
            'field': field_name,
            'normalized': norm_name,
            'gt_status': gt_status,
            'is_true_emergent': is_true_emergent,
            'category': item.get('category', 'other'),
            'extension_score': item.get('extension_score', 0),
            'model_coverage': item.get('model_coverage', 0),
            'document_coverage': item.get('document_coverage', 0),
            'occurrence': item.get('occurrence_count', 0),
            'sample_values': item.get('sample_values', [])[:2]
        })
    
    return pd.DataFrame(results)

def generate_report(ws, out_dir):
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    
    gt_fields, bio = load_data(ws)
    emergent_df = analyze_emergent_fields(gt_fields, bio)
    
    # 设置样式
    plt.style.use('seaborn-v0_8-whitegrid')
    plt.rcParams.update({'font.size': 9, 'axes.titlesize': 11})
    
    # ================================================================
    # 创建综合图表 (2x3 布局)
    # ================================================================
    fig = plt.figure(figsize=(18, 12))
    
    # --- 1. Emergent Fields 验证 (左上) ---
    ax1 = fig.add_subplot(2, 3, 1)
    
    status_counts = emergent_df['gt_status'].value_counts()
    colors = {'mandatory': '#c0392b', 'recommended': '#f39c12', 'optional': '#3498db', 'emergent': '#27ae60'}
    
    bars = ax1.bar(status_counts.index, status_counts.values, 
                  color=[colors.get(s, '#95a5a6') for s in status_counts.index], alpha=0.85)
    ax1.set_ylabel('Count', fontweight='bold')
    ax1.set_title('A. "Emergent" Fields Validation\n(Top candidates from models)', fontsize=11, fontweight='bold')
    
    for bar, count in zip(bars, status_counts.values):
        ax1.text(bar.get_x() + bar.get_width()/2, bar.get_height() + 0.5, 
                str(count), ha='center', fontsize=10, fontweight='bold')
    
    # --- 2. Emergent by Category (右上) ---
    ax2 = fig.add_subplot(2, 3, 2)
    
    true_emergent = emergent_df[emergent_df['is_true_emergent']]
    if len(true_emergent) > 0:
        cat_counts = true_emergent['category'].value_counts()
        cat_colors = {'biological': '#3498db', 'sample_collection': '#2ecc71', 
                     'experimental_design': '#f39c12', 'technical_sequencing': '#9b59b6',
                     'administrative': '#e74c3c', 'other': '#95a5a6'}
        
        ax2.pie(cat_counts.values, labels=cat_counts.index, autopct='%1.0f%%',
               colors=[cat_colors.get(c, '#95a5a6') for c in cat_counts.index],
               startangle=90)
        ax2.set_title(f'B. True Emergent Fields by Category\n({len(true_emergent)} genuine new fields)', 
                     fontsize=11, fontweight='bold')
    else:
        ax2.text(0.5, 0.5, 'No true emergent fields', ha='center', va='center')
        ax2.set_title('B. True Emergent Fields', fontsize=11, fontweight='bold')
    
    # --- 3. Top Emergent Fields Table (中上) ---
    ax3 = fig.add_subplot(2, 3, 3)
    ax3.axis('off')
    
    # 显示top true emergent fields
    true_em = emergent_df[emergent_df['is_true_emergent']].head(10)
    if len(true_em) > 0:
        table_data = []
        for _, row in true_em.iterrows():
            samples = ', '.join(str(v)[:30] for v in row['sample_values'][:1]) if row['sample_values'] else 'N/A'
            table_data.append([row['field'], row['category'], f"{row['extension_score']:.2f}", samples[:40]])
        
        table = ax3.table(cellText=table_data,
                         colLabels=['Field Name', 'Category', 'Score', 'Sample Value'],
                         loc='center', cellLoc='left')
        table.auto_set_font_size(False)
        table.set_fontsize(8)
        table.scale(1.2, 1.5)
        
        # 设置header颜色
        for i in range(4):
            table[(0, i)].set_facecolor('#27ae60')
            table[(0, i)].set_text_props(color='white', fontweight='bold')
    
    ax3.set_title('C. Top True Emergent Fields\n(Candidates for standard extension)', 
                 fontsize=11, fontweight='bold', pad=20)
    
    # --- 4. Field Importance by GT Status (左下) ---
    ax4 = fig.add_subplot(2, 3, 4)
    
    # 按GT status分组的extension score
    status_scores = emergent_df.groupby('gt_status')['extension_score'].mean().sort_values(ascending=True)
    y = np.arange(len(status_scores))
    bars = ax4.barh(y, status_scores.values, 
                   color=[colors.get(s, '#95a5a6') for s in status_scores.index], alpha=0.85)
    ax4.set_yticks(y)
    ax4.set_yticklabels(status_scores.index)
    ax4.set_xlabel('Average Extension Score', fontweight='bold')
    ax4.set_title('D. Extraction Quality by Field Type\n(Higher = More consistently extracted)', 
                 fontsize=11, fontweight='bold')
    
    for i, (bar, score) in enumerate(zip(bars, status_scores.values)):
        ax4.text(score + 0.01, i, f'{score:.2f}', va='center', fontsize=9)
    
    # --- 5. Consensus Heatmap (中下) ---
    ax5 = fig.add_subplot(2, 3, 5)
    
    # 从consensus分析提取核心字段 (consensus是list格式)
    consensus = bio['consensus_analysis']
    core_fields_data = []
    
    for doc_id, field_list in consensus.items():
        if isinstance(field_list, list):
            for item in field_list:
                if isinstance(item, dict):
                    # 确定GT状态
                    if item.get('is_required'):
                        gt_status = 'mandatory'
                    elif item.get('is_recommended'):
                        gt_status = 'recommended'
                    elif item.get('in_ground_truth'):
                        gt_status = 'optional'
                    else:
                        gt_status = 'emergent'
                    
                    core_fields_data.append({
                        'field': item.get('field_name', ''),
                        'document': doc_id,
                        'consensus': item.get('consensus_score', 0),
                        'gt_status': gt_status
                    })
    
    if core_fields_data:
        core_df = pd.DataFrame(core_fields_data)
        # 只取高共识字段 (>=90%)
        high_consensus = core_df[core_df['consensus'] >= 0.9]
        
        if len(high_consensus) > 0:
            # 按GT status分组统计
            status_doc = high_consensus.groupby(['document', 'gt_status']).size().unstack(fill_value=0)
            
            # 重新排序列
            col_order = ['mandatory', 'recommended', 'optional', 'emergent']
            status_doc = status_doc.reindex(columns=[c for c in col_order if c in status_doc.columns])
            
            sns.heatmap(status_doc, annot=True, fmt='d', cmap='YlGn', ax=ax5,
                       cbar_kws={'label': 'Field Count'})
            ax5.set_title('E. High-Consensus Fields (≥90%)\nby Document & Type', 
                         fontsize=11, fontweight='bold')
            ax5.set_xlabel('Field Type', fontweight='bold')
            ax5.set_ylabel('Document', fontweight='bold')
    
    # --- 6. Summary Statistics (右下) ---
    ax6 = fig.add_subplot(2, 3, 6)
    ax6.axis('off')
    
    # 计算统计
    total_emergent_claimed = len(emergent_df)
    true_emergent_count = len(emergent_df[emergent_df['is_true_emergent']])
    mandatory_misclass = len(emergent_df[emergent_df['gt_status'] == 'mandatory'])
    recommended_misclass = len(emergent_df[emergent_df['gt_status'] == 'recommended'])
    
    summary_text = f"""
EMERGENT FIELDS ANALYSIS SUMMARY

📊 Total "emergent" candidates: {total_emergent_claimed}

✅ TRUE Emergent (not in GT): {true_emergent_count} ({true_emergent_count/total_emergent_claimed*100:.0f}%)
   → These are genuine new fields discovered by models
   
⚠️  FALSE Emergent (actually in GT):
   • Mandatory fields: {mandatory_misclass}
   • Recommended fields: {recommended_misclass}
   → These indicate field name normalization issues

🔬 TOP EMERGENT CATEGORIES:
"""
    if len(true_emergent) > 0:
        for cat, count in true_emergent['category'].value_counts().head(3).items():
            summary_text += f"   • {cat}: {count} fields\n"
    
    summary_text += f"""
💡 KEY INSIGHT:
   Models discover {true_emergent_count} biologically relevant fields
   beyond the standard schema - candidates for extension.
"""
    
    ax6.text(0.05, 0.95, summary_text, transform=ax6.transAxes, fontsize=10,
            verticalalignment='top', fontfamily='monospace',
            bbox=dict(boxstyle='round', facecolor='#f8f9fa', edgecolor='#dee2e6'))
    ax6.set_title('F. Summary', fontsize=11, fontweight='bold')
    
    # 保存
    plt.suptitle('FAIRiAgent Field Analysis: Emergent Patterns & Ground Truth Validation', 
                fontsize=14, fontweight='bold', y=0.98)
    plt.tight_layout(rect=[0, 0, 1, 0.96])
    plt.savefig(out_dir / 'field_analysis_report.png', dpi=300, bbox_inches='tight')
    plt.close()
    
    # ================================================================
    # 打印详细报告
    # ================================================================
    print("\n" + "="*80)
    print("EMERGENT FIELDS VALIDATION REPORT")
    print("="*80)
    
    print(f"\n📊 SUMMARY")
    print(f"   Total 'emergent' candidates: {total_emergent_claimed}")
    print(f"   TRUE emergent (not in GT): {true_emergent_count} ({true_emergent_count/total_emergent_claimed*100:.1f}%)")
    print(f"   FALSE emergent (in GT): {total_emergent_claimed - true_emergent_count}")
    
    print(f"\n⚠️  MISCLASSIFIED AS EMERGENT (actually in GT):")
    misclass = emergent_df[~emergent_df['is_true_emergent']].head(15)
    for _, row in misclass.iterrows():
        print(f"   [{row['gt_status']:>11}] {row['field']}")
    
    print(f"\n✅ TRUE EMERGENT FIELDS (Top 15):")
    true_em = emergent_df[emergent_df['is_true_emergent']].head(15)
    for _, row in true_em.iterrows():
        samples = str(row['sample_values'][0])[:40] if row['sample_values'] else 'N/A'
        print(f"   [{row['category']:>20}] {row['field']:<30} → {samples}...")
    
    print("\n" + "="*80)
    print(f"✅ Report saved: {out_dir / 'field_analysis_report.png'}")
    print("="*80)
    
    return emergent_df

def main():
    ws = Path(__file__).parent.parent.parent
    out = ws / 'evaluation/analysis/key_figures'
    
    print("Generating field analysis report...")
    emergent_df = generate_report(ws, out)

if __name__ == '__main__':
    main()
