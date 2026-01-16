#!/usr/bin/env python3
"""
为所有运行添加评估指标到 eval_result.json

这个脚本会：
1. 遍历所有运行目录
2. 为每个运行计算 completeness, correctness, llm_judge 等指标
3. 更新 eval_result.json 文件
"""

import json
import sys
from pathlib import Path
from typing import Dict, Any, Optional
from dotenv import load_dotenv
import os

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from evaluation.evaluators import (
    CompletenessEvaluator,
    CorrectnessEvaluator,
    LLMJudgeEvaluator,
    InternalMetricsEvaluator,
)
from evaluation.analysis.config import (
    EXCLUDED_MODELS,
    EXCLUDED_DOCUMENTS,
    EXCLUDED_DIRECTORIES,
)


def load_ground_truth(gt_path: Path) -> Dict[str, Dict[str, Any]]:
    """加载 ground truth 数据"""
    with open(gt_path, 'r', encoding='utf-8') as f:
        data = json.load(f)
    
    return {
        doc['document_id']: doc
        for doc in data.get('documents', [])
    }


def evaluate_single_run(
    run_dir: Path,
    ground_truth_docs: Dict[str, Dict[str, Any]],
    env_file: Optional[Path] = None
) -> Dict[str, Any]:
    """为单个运行计算评估指标"""
    
    # Load existing eval_result.json
    eval_result_file = run_dir / 'eval_result.json'
    if not eval_result_file.exists():
        return None
    
    with open(eval_result_file, 'r', encoding='utf-8') as f:
        eval_result = json.load(f)
    
    # Skip if already has NEW confidence-aware correctness metrics
    correctness = eval_result.get('correctness', {})
    has_adjusted_metrics = 'adjusted_f1' in correctness and correctness.get('adjusted_f1', 0.0) > 0
    
    if has_adjusted_metrics:
        return eval_result
    
    # Get document ID
    doc_id = eval_result.get('document_id', '')
    if not doc_id or doc_id not in ground_truth_docs:
        return None
    
    ground_truth_doc = ground_truth_docs[doc_id]
    
    # Load metadata_json.json
    metadata_file = run_dir / 'metadata_json.json'
    if not metadata_file.exists():
        return None
    
    with open(metadata_file, 'r', encoding='utf-8') as f:
        fairifier_output = json.load(f)
    
    # Initialize evaluators
    completeness_eval = CompletenessEvaluator()
    # Correctness evaluator for field presence (no LLM judge needed)
    correctness_eval = CorrectnessEvaluator(judge_config={})
    
    # Load LLM judge config if env_file provided
    llm_judge_config = None
    if env_file and env_file.exists():
        load_dotenv(env_file)
        judge_provider = os.getenv('EVAL_JUDGE_PROVIDER', 'anthropic')
        llm_judge_config = {
            'provider': judge_provider,
            'model': os.getenv('EVAL_JUDGE_MODEL', 'claude-sonnet-4'),
            'api_key': os.getenv('EVAL_JUDGE_API_KEY') or os.getenv('LLM_API_KEY'),
            'temperature': float(os.getenv('EVAL_JUDGE_TEMPERATURE', '0.0'))
        }
        if judge_provider == 'qwen':
            llm_judge_config['base_url'] = os.getenv('QWEN_API_BASE_URL') or 'https://dashscope-intl.aliyuncs.com/compatible-mode/v1'
    
    llm_judge_eval = None
    if llm_judge_config and llm_judge_config.get('api_key'):
        try:
            llm_judge_eval = LLMJudgeEvaluator(judge_config=llm_judge_config)
        except Exception as e:
            print(f"  ⚠️  LLM Judge 初始化失败: {e}")
    
    internal_metrics_eval = InternalMetricsEvaluator()
    
    # Compute metrics
    metrics = {}
    
    # 1. Completeness
    try:
        completeness_result = completeness_eval.evaluate(fairifier_output, ground_truth_doc)
        overall_metrics = completeness_result.get('overall_metrics', {})
        metrics['completeness'] = {
            'overall_completeness': overall_metrics.get('overall_completeness', 0.0),
            'required_completeness': overall_metrics.get('required_completeness', 0.0),
            'recommended_completeness': overall_metrics.get('recommended_completeness', 0.0),
            'total_ground_truth_fields': overall_metrics.get('total_ground_truth_fields', 0),
            'total_extracted_fields': overall_metrics.get('total_extracted_fields', 0),
            'covered_fields': overall_metrics.get('covered_fields', 0),
        }
    except Exception as e:
        print(f"  ⚠️  Completeness 计算失败: {e}")
        import traceback
        traceback.print_exc()
        metrics['completeness'] = {}
    
    # 2. Correctness (field presence) with confidence-aware metrics
    try:
        correctness_result = correctness_eval.evaluate(
            fairifier_output, 
            ground_truth_doc
        )
        # Extract summary metrics
        summary = correctness_result.get('summary_metrics', {})
        metrics['correctness'] = {
            # Original metrics
            'f1_score': summary.get('f1_score', 0.0),
            'precision': summary.get('precision', 0.0),
            'recall': summary.get('recall', 0.0),
            'field_presence_rate': summary.get('field_presence_rate', 0.0),
            # NEW: Confidence-aware metrics
            'high_conf_excess': summary.get('high_conf_excess', 0),
            'low_conf_excess': summary.get('low_conf_excess', 0),
            'adjusted_precision': summary.get('adjusted_precision', 0.0),
            'adjusted_f1': summary.get('adjusted_f1', 0.0),
            'discovery_bonus': summary.get('discovery_bonus', 0.0),
        }
    except Exception as e:
        print(f"  ⚠️  Correctness 计算失败: {e}")
        import traceback
        traceback.print_exc()
        metrics['correctness'] = {}
    
    # 3. LLM Judge (optional, requires API key)
    if llm_judge_eval:
        try:
            llm_judge_result = llm_judge_eval.evaluate(fairifier_output, ground_truth_doc)
            metrics['llm_judge'] = {
                'overall_score': llm_judge_result.get('overall_score', 0.0),
                'evidence_quality': llm_judge_result.get('evidence_quality', 0.0),
                'appropriateness': llm_judge_result.get('appropriateness', 0.0),
                'completeness': llm_judge_result.get('completeness', 0.0),
                'accuracy': llm_judge_result.get('accuracy', 0.0),
            }
        except Exception as e:
            print(f"  ⚠️  LLM Judge 计算失败: {e}")
            metrics['llm_judge'] = {}
    else:
        metrics['llm_judge'] = {}
    
    # 4. Internal metrics (from workflow_report.json quality_metrics)
    try:
        workflow_report_file = run_dir / 'workflow_report.json'
        if workflow_report_file.exists():
            with open(workflow_report_file, 'r') as f:
                workflow_data = json.load(f)
            
            # 正确的位置是 quality_metrics，不是 confidence_scores
            quality_metrics = workflow_data.get('quality_metrics', {})
            metrics['internal_metrics'] = {
                'overall_confidence': quality_metrics.get('overall_confidence', 0.0),
                'critic_confidence': quality_metrics.get('critic_confidence', 0.0),
                'structural_confidence': quality_metrics.get('structural_confidence', 0.0),
                'validation_confidence': quality_metrics.get('validation_confidence', 0.0),
            }
            
            # 从 workflow_report.json 提取 agent 执行详情
            exec_summary = workflow_data.get('execution_summary', {})
            agents_executed = exec_summary.get('agents_executed', {})
            retry_analysis = workflow_data.get('retry_analysis', {})
            timeline = workflow_data.get('timeline', [])
            
            # 计算 agent 统计
            total_attempts = sum(a.get('total_attempts', 0) for a in agents_executed.values())
            total_retries = retry_analysis.get('global_retries_used', 0)
            
            metrics['internal_metrics']['total_agent_attempts'] = total_attempts
            metrics['internal_metrics']['total_retries'] = total_retries
            metrics['internal_metrics']['agents_with_retries'] = retry_analysis.get('agents_with_retries', [])
            
            # Agent-level details
            agent_details = {}
            for agent_name, agent_data in agents_executed.items():
                agent_details[agent_name] = {
                    'total_attempts': agent_data.get('total_attempts', 0),
                    'successful': agent_data.get('successful', 0),
                    'failed': agent_data.get('failed', 0),
                }
            metrics['internal_metrics']['agent_details'] = agent_details
            
            # 同时尝试从 llm_responses.json 提取 critic scores（如果有的话）
            llm_responses_file = run_dir / 'llm_responses.json'
            if llm_responses_file.exists():
                with open(llm_responses_file, 'r') as f:
                    llm_responses = json.load(f)
                
                critic_trajectory = []
                for resp in llm_responses:
                    op = resp.get('operation', '')
                    if 'critic' in op.lower():
                        response_text = resp.get('response', '')
                        import re
                        json_match = re.search(r'\{[\s\S]*\}', response_text)
                        if json_match:
                            try:
                                critic_data = json.loads(json_match.group())
                                critic_trajectory.append({
                                    'agent': op,
                                    'timestamp': resp.get('timestamp', ''),
                                    'confidence_score': critic_data.get('confidence_score', critic_data.get('score')),
                                    'decision': critic_data.get('decision', ''),
                                })
                            except json.JSONDecodeError:
                                pass
                
                if critic_trajectory:
                    metrics['internal_metrics']['critic_trajectory'] = critic_trajectory
        else:
            # Fallback: try metadata_json.json confidence scores
            if fairifier_output:
                metrics['internal_metrics'] = {
                    'overall_confidence': fairifier_output.get('overall_confidence', 0.0),
                    'critic_confidence': 0.0,
                    'structural_confidence': 0.0,
                    'validation_confidence': 0.0,
                }
            else:
                metrics['internal_metrics'] = {
                    'overall_confidence': 0.0,
                    'critic_confidence': 0.0,
                    'structural_confidence': 0.0,
                    'validation_confidence': 0.0,
                }
    except Exception as e:
        print(f"  ⚠️  Internal metrics 计算失败: {e}")
        metrics['internal_metrics'] = {}
    
    # Update eval_result.json
    eval_result.update(metrics)
    
    # Save updated result
    with open(eval_result_file, 'w', encoding='utf-8') as f:
        json.dump(eval_result, f, indent=2, ensure_ascii=False)
    
    return eval_result


def main():
    """主函数"""
    import argparse
    
    parser = argparse.ArgumentParser(description='为所有运行添加评估指标')
    parser.add_argument(
        '--runs-dir',
        type=Path,
        default=Path('evaluation/runs'),
        help='Runs 目录路径'
    )
    parser.add_argument(
        '--ground-truth',
        type=Path,
        default=Path('evaluation/datasets/annotated/ground_truth_filtered.json'),
        help='Ground truth 文件路径'
    )
    parser.add_argument(
        '--env-file',
        type=Path,
        default=None,
        help='环境配置文件（用于 LLM Judge）'
    )
    parser.add_argument(
        '--dry-run',
        action='store_true',
        help='只检查，不实际更新文件'
    )
    
    args = parser.parse_args()
    
    # Load ground truth
    print("📊 加载 ground truth...")
    ground_truth_docs = load_ground_truth(args.ground_truth)
    print(f"✅ 加载了 {len(ground_truth_docs)} 个文档的 ground truth")
    
    # Find all runs
    runs_dir = args.runs_dir
    if not runs_dir.exists():
        print(f"❌ Runs 目录不存在: {runs_dir}")
        return
    
    all_runs = []
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
            
            for run_dir in doc_dir.glob('run_*'):
                if run_dir.is_dir():
                    all_runs.append((model, doc_id, run_dir))
    
    print(f"\n🔍 找到 {len(all_runs)} 个运行需要评估")
    
    # Process runs
    updated = 0
    skipped = 0
    failed = 0
    
    for i, (model, doc_id, run_dir) in enumerate(all_runs, 1):
        print(f"\n[{i}/{len(all_runs)}] {model}/{doc_id}/{run_dir.name}")
        
        if args.dry_run:
            eval_file = run_dir / 'eval_result.json'
            if eval_file.exists():
                with open(eval_file, 'r') as f:
                    data = json.load(f)
                if 'completeness' in data:
                    print(f"  ✅ 已有评估指标")
                    skipped += 1
                else:
                    print(f"  ⚠️  缺少评估指标")
            continue
        
        try:
            result = evaluate_single_run(
                run_dir,
                ground_truth_docs,
                args.env_file
            )
            
            if result:
                if 'completeness' in result:
                    print(f"  ✅ 评估指标已添加")
                    updated += 1
                else:
                    print(f"  ⚠️  部分指标计算失败")
                    failed += 1
            else:
                print(f"  ⏭️  跳过（缺少必要文件）")
                skipped += 1
        except Exception as e:
            print(f"  ❌ 错误: {e}")
            failed += 1
    
    print("\n" + "=" * 70)
    print("总结")
    print("=" * 70)
    print(f"✅ 已更新: {updated}")
    print(f"⏭️  跳过: {skipped}")
    print(f"❌ 失败: {failed}")
    print(f"📊 总计: {len(all_runs)}")


if __name__ == "__main__":
    main()
