#!/usr/bin/env python3
"""检查失败的运行并统计需要补跑的数量（排除 JSON 解析错误）"""

import json
from pathlib import Path
from collections import defaultdict

# 配置
RUNS_DIR = Path(__file__).parent.parent / "runs"
EXPECTED_REPEATS = 10  # 每个模型每个文档应该跑10次
DOCS = ["earthworm", "biosensor"]  # biorem 暂时移除

# 是否排除 JSON 解析错误（这些是 LLM 输出问题，不是 workflow 未完成）
EXCLUDE_JSON_PARSING_ERRORS = True

def check_run_failure(run_dir: Path) -> tuple[bool, str]:
    """检查运行是否成功，返回 (is_success, error_type)"""
    metadata_file = run_dir / "metadata_json.json"
    eval_result_file = run_dir / "eval_result.json"
    
    # 如果有 metadata_json.json，说明成功
    if metadata_file.exists():
        return True, ""
    
    # 检查失败原因
    if eval_result_file.exists():
        try:
            with open(eval_result_file, 'r') as f:
                result = json.load(f)
                error = result.get('error', '')
                
                if 'timed out' in error.lower():
                    return False, 'timeout'
                elif 'not found after workflow' in error.lower():
                    return False, 'metadata_not_found'
                elif 'json parsing' in error.lower():
                    return False, 'json_parsing_error'
                else:
                    return False, 'other_error'
        except:
            return False, 'eval_result_parse_error'
    
    return False, 'no_eval_result'

def main():
    results = defaultdict(lambda: defaultdict(lambda: {
        'total': 0,
        'success': 0,
        'failed': 0,
        'timeout': 0,
        'metadata_not_found': 0,
        'json_parsing_error': 0,
        'other_error': 0,
        'no_eval_result': 0,
        'eval_result_parse_error': 0
    }))
    
    # 遍历所有运行目录
    for run_batch_dir in RUNS_DIR.iterdir():
        if not run_batch_dir.is_dir() or run_batch_dir.name == 'archive':
            continue
        
        # 遍历模型目录
        for model_dir in run_batch_dir.iterdir():
            if not model_dir.is_dir():
                continue
            
            outputs_dir = model_dir / "outputs"
            if not outputs_dir.exists():
                continue
            
            # 遍历模型输出子目录
            for output_subdir in outputs_dir.iterdir():
                if not output_subdir.is_dir():
                    continue
                
                model_name = output_subdir.name
                
                # 遍历文档
                for doc in DOCS:
                    doc_dir = output_subdir / doc
                    if not doc_dir.exists():
                        continue
                    
                    # 检查所有 run_* 目录
                    run_dirs = sorted([d for d in doc_dir.iterdir() if d.is_dir() and d.name.startswith('run_')])
                    
                    for run_dir in run_dirs:
                        results[model_name][doc]['total'] += 1
                        
                        is_success, error_type = check_run_failure(run_dir)
                        
                        if is_success:
                            results[model_name][doc]['success'] += 1
                        else:
                            # 如果排除 JSON 解析错误，跳过这类错误
                            if EXCLUDE_JSON_PARSING_ERRORS and error_type == 'json_parsing_error':
                                # 视为"不需要重跑"，但仍记录为失败
                                results[model_name][doc]['failed'] += 1
                                results[model_name][doc][error_type] += 1
                            else:
                                results[model_name][doc]['failed'] += 1
                                if error_type:
                                    results[model_name][doc][error_type] += 1
    
    # 打印结果
    print("\n" + "="*80)
    print("失败运行统计与补跑需求")
    if EXCLUDE_JSON_PARSING_ERRORS:
        print("（已排除 JSON 解析错误 - 这些是 LLM 输出问题，不需要重跑）")
    print("="*80 + "\n")
    
    total_to_rerun = 0
    rerun_details = []
    
    for model_name in sorted(results.keys()):
        print(f"\n### {model_name.upper()}")
        print("-" * 80)
        
        for doc in DOCS:
            if doc not in results[model_name]:
                continue
            
            stats = results[model_name][doc]
            success = stats['success']
            failed = stats['failed']
            
            # 计算需要补跑的次数（排除 JSON 解析错误）
            if EXCLUDE_JSON_PARSING_ERRORS:
                # 不算 JSON 解析错误，这些不需要重跑
                json_errors = stats['json_parsing_error']
                # 实际需要补的 = 期望次数 - 成功次数
                # 但不包括 JSON 解析错误（这些算作"成功"运行，只是 LLM 输出问题）
                needed = max(0, EXPECTED_REPEATS - (success + json_errors))
            else:
                needed = max(0, EXPECTED_REPEATS - success)
            
            print(f"\n  {doc}:")
            print(f"    ✅ 成功: {success}/{EXPECTED_REPEATS}")
            print(f"    ❌ 失败: {failed}")
            
            if failed > 0:
                print(f"    失败原因:")
                if stats['timeout'] > 0:
                    print(f"      - Timeout: {stats['timeout']}")
                if stats['metadata_not_found'] > 0:
                    print(f"      - Metadata未找到: {stats['metadata_not_found']}")
                if stats['json_parsing_error'] > 0:
                    print(f"      - JSON解析错误: {stats['json_parsing_error']}")
                if stats['other_error'] > 0:
                    print(f"      - 其他错误: {stats['other_error']}")
            
            if needed > 0:
                print(f"    🔄 需要补跑: {needed} 次")
                total_to_rerun += needed
                rerun_details.append({
                    'model': model_name,
                    'doc': doc,
                    'needed': needed,
                    'success': success,
                    'failed': failed
                })
    
    # 总结
    print("\n" + "="*80)
    print("补跑总结")
    print("="*80 + "\n")
    
    if total_to_rerun > 0:
        print(f"**总计需要补跑: {total_to_rerun} 次**\n")
        
        # 按模型分组
        model_summary = defaultdict(int)
        for item in rerun_details:
            model_summary[item['model']] += item['needed']
        
        print("按模型分组:")
        for model_name, count in sorted(model_summary.items()):
            print(f"  - {model_name}: {count} 次")
        
        print("\n详细列表:")
        for item in rerun_details:
            print(f"  - {item['model']} / {item['doc']}: 补跑 {item['needed']} 次 (已有 {item['success']} 次成功)")
    else:
        print("✅ 所有运行都已完成！")

if __name__ == "__main__":
    main()

