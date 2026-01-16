#!/usr/bin/env python3
"""诊断评估数据集和分析结果的问题"""

import json
import sys
from pathlib import Path
from collections import defaultdict

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from evaluation.analysis.config import (
    EXCLUDED_MODELS,
    EXCLUDED_DOCUMENTS,
    EXCLUDED_DIRECTORIES,
)


def check_ground_truth():
    """检查 ground truth 数据集的问题"""
    print("=" * 70)
    print("1. Ground Truth 数据集检查")
    print("=" * 70)
    
    # Try multiple possible paths
    possible_paths = [
        Path("evaluation/datasets/annotated/ground_truth_filtered.json"),
        Path(__file__).parent.parent / "datasets/annotated/ground_truth_filtered.json",
        Path(__file__).parent.parent.parent / "evaluation/datasets/annotated/ground_truth_filtered.json",
    ]
    
    gt_file = None
    for path in possible_paths:
        if path.exists():
            gt_file = path
            break
    
    if not gt_file or not gt_file.exists():
        print(f"❌ Ground truth 文件不存在")
        for path in possible_paths:
            print(f"   尝试: {path} ({path.exists()})")
        return []
    
    with open(gt_file, 'r', encoding='utf-8') as f:
        data = json.load(f)
    
    documents = data.get("documents", [])
    print(f"\n✅ 找到 {len(documents)} 个文档")
    
    issues = []
    for doc in documents:
        doc_id = doc.get("document_id", "unknown")
        print(f"\n📄 文档: {doc_id}")
        
        # 检查文档路径
        doc_path = doc.get("document_path", "")
        if doc_path:
            full_path = Path(doc_path)
            if not full_path.is_absolute():
                full_path = Path("evaluation") / doc_path
            
            if full_path.exists():
                print(f"   ✅ 文档路径存在: {full_path}")
            else:
                print(f"   ❌ 文档路径不存在: {full_path}")
                issues.append(f"{doc_id}: 文档路径不存在")
                
                # 尝试查找替代路径
                doc_name = Path(doc_path).stem
                possible_paths = [
                    Path(f"evaluation/datasets/raw/{doc_id}/{doc_name}.pdf"),
                    Path(f"evaluation/datasets/raw/{doc_id}/{doc_name}.md"),
                ]
                for alt_path in possible_paths:
                    if alt_path.exists():
                        print(f"   💡 建议使用: {alt_path}")
                        break
        else:
            print(f"   ⚠️  文档路径未设置")
            issues.append(f"{doc_id}: 文档路径未设置")
        
        # 检查字段
        fields = doc.get("ground_truth_fields", [])
        print(f"   📊 字段数: {len(fields)}")
        
        required = sum(1 for f in fields if f.get("is_required", False))
        recommended = sum(1 for f in fields if f.get("is_recommended", False))
        print(f"   - 必需字段: {required}")
        print(f"   - 推荐字段: {recommended}")
        
        # 检查字段结构
        missing_fields = []
        for i, field in enumerate(fields[:10]):  # 检查前10个
            if "field_name" not in field:
                missing_fields.append(f"字段 {i}: 缺少 field_name")
            if "isa_sheet" not in field:
                missing_fields.append(f"字段 {i}: 缺少 isa_sheet")
        
        if missing_fields:
            print(f"   ⚠️  字段结构问题: {len(missing_fields)} 个")
            issues.extend([f"{doc_id}: {m}" for m in missing_fields[:3]])
    
    return issues


def check_runs_data():
    """检查运行数据的完整性"""
    print("\n" + "=" * 70)
    print("2. 运行数据完整性检查")
    print("=" * 70)
    
    # Try multiple possible paths
    possible_paths = [
        Path("evaluation/runs"),
        Path(__file__).parent.parent / "runs",
        Path(__file__).parent.parent.parent / "evaluation/runs",
    ]
    
    runs_dir = None
    for path in possible_paths:
        if path.exists():
            runs_dir = path
            break
    
    if not runs_dir or not runs_dir.exists():
        print(f"❌ Runs 目录不存在")
        for path in possible_paths:
            print(f"   尝试: {path} ({path.exists()})")
        return {}
    
    model_stats = defaultdict(lambda: {"complete": 0, "incomplete": 0, "missing_eval": 0})
    doc_stats = defaultdict(lambda: {"complete": 0, "incomplete": 0})
    
    for model_dir in runs_dir.iterdir():
        if not model_dir.is_dir() or model_dir.name in EXCLUDED_DIRECTORIES:
            continue
        
        model = model_dir.name
        if model in EXCLUDED_MODELS:
            continue
        
        for doc_dir in model_dir.iterdir():
            if not doc_dir.is_dir():
                continue
            
            doc_id = doc_dir.name
            if doc_id in EXCLUDED_DOCUMENTS:
                continue
            
            for run_dir in doc_dir.glob("run_*"):
                if not run_dir.is_dir():
                    continue
                
                has_metadata = (run_dir / "metadata_json.json").exists()
                has_eval = (run_dir / "eval_result.json").exists()
                
                if has_metadata and has_eval:
                    model_stats[model]["complete"] += 1
                    doc_stats[doc_id]["complete"] += 1
                elif has_metadata:
                    model_stats[model]["missing_eval"] += 1
                    doc_stats[doc_id]["incomplete"] += 1
                elif has_eval:
                    model_stats[model]["incomplete"] += 1
                    doc_stats[doc_id]["incomplete"] += 1
    
    print(f"\n📊 模型统计:")
    for model in sorted(model_stats.keys()):
        stats = model_stats[model]
        total = stats["complete"] + stats["incomplete"] + stats["missing_eval"]
        print(f"   {model}:")
        print(f"     ✅ 完整: {stats['complete']}")
        print(f"     ⚠️  缺少评估: {stats['missing_eval']}")
        print(f"     ⚠️  不完整: {stats['incomplete']}")
        print(f"     总计: {total}")
    
    print(f"\n📄 文档统计:")
    for doc_id in sorted(doc_stats.keys()):
        stats = doc_stats[doc_id]
        print(f"   {doc_id}: {stats['complete']} 完整, {stats['incomplete']} 不完整")
    
    return model_stats


def check_analysis_output():
    """检查分析输出"""
    print("\n" + "=" * 70)
    print("3. 分析输出检查")
    print("=" * 70)
    
    # Try multiple possible paths
    possible_paths = [
        Path("evaluation/analysis/output"),
        Path(__file__).parent.parent / "analysis/output",
        Path(__file__).parent.parent.parent / "evaluation/analysis/output",
    ]
    
    output_dir = None
    for path in possible_paths:
        if path.exists():
            output_dir = path
            break
    
    if not output_dir or not output_dir.exists():
        print(f"❌ 分析输出目录不存在")
        for path in possible_paths:
            print(f"   尝试: {path} ({path.exists()})")
        return
    
    # 检查摘要文件
    summary_files = list(output_dir.glob("analysis_summary*.json"))
    if summary_files:
        latest_summary = max(summary_files, key=lambda p: p.stat().st_mtime)
        print(f"\n📊 分析摘要: {latest_summary.name}")
        
        with open(latest_summary, 'r') as f:
            data = json.load(f)
        
        print(f"   运行数: {data.get('n_runs', 'N/A')}")
        print(f"   模型数: {data.get('n_models', 'N/A')}")
        print(f"   文档数: {data.get('n_documents', 'N/A')}")
        
        # 检查可靠性摘要
        reliability = data.get("reliability_summary", {})
        completion = reliability.get("completion_rate", {})
        print(f"\n   完成率:")
        for model, rate in completion.items():
            if rate == 0.0:
                print(f"     ❌ {model}: {rate}")
            elif rate < 1.0:
                print(f"     ⚠️  {model}: {rate}")
            else:
                print(f"     ✅ {model}: {rate}")
    else:
        print("❌ 未找到分析摘要文件")
    
    # 检查图表
    figures_dir = output_dir / "figures"
    if figures_dir.exists():
        figures = list(figures_dir.glob("*.png"))
        print(f"\n📈 图表文件: {len(figures)} 个")
        
        # 检查文件大小（空文件或损坏）
        small_files = [f for f in figures if f.stat().st_size < 1000]
        if small_files:
            print(f"   ⚠️  可能损坏的图表 ({len(small_files)} 个):")
            for f in small_files[:5]:
                print(f"      {f.name}: {f.stat().st_size} bytes")
    else:
        print("❌ 图表目录不存在")
    
    # 检查表格
    tables_dir = output_dir / "tables"
    if tables_dir.exists():
        tables = list(tables_dir.glob("*.csv"))
        print(f"\n📋 表格文件: {len(tables)} 个")
        
        # 检查空表格
        empty_tables = []
        for table in tables:
            try:
                with open(table, 'r') as f:
                    lines = f.readlines()
                    if len(lines) <= 1:  # 只有标题行
                        empty_tables.append(table)
            except:
                pass
        
        if empty_tables:
            print(f"   ⚠️  空表格 ({len(empty_tables)} 个):")
            for t in empty_tables[:5]:
                print(f"      {t.name}")
    else:
        print("❌ 表格目录不存在")


def check_evaluation_results():
    """检查评估结果文件的内容"""
    print("\n" + "=" * 70)
    print("4. 评估结果文件检查")
    print("=" * 70)
    
    runs_dir = Path("evaluation/runs")
    sample_results = []
    
    for eval_file in list(runs_dir.rglob("eval_result.json"))[:5]:
        try:
            with open(eval_file, 'r') as f:
                data = json.load(f)
            
            doc_id = data.get("document_id", "unknown")
            model = eval_file.parent.parent.parent.name
            run_id = eval_file.parent.name
            
            sample_results.append({
                "model": model,
                "doc": doc_id,
                "run": run_id,
                "has_completeness": "completeness" in data,
                "has_correctness": "correctness" in data,
                "has_llm_judge": "llm_judge" in data,
            })
        except Exception as e:
            print(f"   ⚠️  无法读取 {eval_file}: {e}")
    
    if sample_results:
        print(f"\n📋 样本评估结果 (前5个):")
        for result in sample_results:
            checks = []
            if result["has_completeness"]:
                checks.append("✅ completeness")
            else:
                checks.append("❌ completeness")
            if result["has_correctness"]:
                checks.append("✅ correctness")
            else:
                checks.append("❌ correctness")
            if result["has_llm_judge"]:
                checks.append("✅ llm_judge")
            else:
                checks.append("❌ llm_judge")
            
            print(f"   {result['model']}/{result['doc']}/{result['run']}: {', '.join(checks)}")


def main():
    """主函数"""
    print("\n" + "=" * 70)
    print("FAIRiAgent 评估诊断工具")
    print("=" * 70)
    
    # 检查各个部分
    gt_issues = check_ground_truth()
    model_stats = check_runs_data()
    check_analysis_output()
    check_evaluation_results()
    
    # 总结
    print("\n" + "=" * 70)
    print("诊断总结")
    print("=" * 70)
    
    if model_stats:
        total_complete = sum(s["complete"] for s in model_stats.values())
        total_expected = len(model_stats) * 2 * 10  # 8 models × 2 docs × 10 runs
        
        print(f"\n✅ 完整运行: {total_complete}/{total_expected}")
        if total_expected > 0:
            print(f"📊 数据完整性: {total_complete/total_expected*100:.1f}%")
        else:
            print(f"📊 数据完整性: N/A (无预期数据)")
    else:
        print("\n⚠️  未找到运行数据")
    
    if gt_issues:
        print(f"\n⚠️  Ground Truth 问题: {len(gt_issues)} 个")
        for issue in gt_issues[:5]:
            print(f"   - {issue}")
    
    print("\n💡 建议:")
    if total_complete < total_expected:
        missing = total_expected - total_complete
        print(f"   1. 有 {missing} 个运行不完整，需要补跑或重新评估")
    
    if gt_issues:
        print(f"   2. 修复 ground truth 中的文档路径问题")
    
    print(f"   3. 重新运行分析: python evaluation/analysis/run_analysis.py")


if __name__ == "__main__":
    main()
