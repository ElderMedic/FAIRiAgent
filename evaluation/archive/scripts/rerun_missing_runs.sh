#!/bin/bash
#
# 补跑缺失的评估运行，补齐每个模型每个文档到 10 次
# 使用已有的 MinerU markdown 输出作为输入，跳过 MinerU 转换步骤
#

set -e  # Exit on error

# 配置
TIMESTAMP=$(date +%Y%m%d_%H%M%S)
BASE_OUTPUT_DIR="evaluation/runs/rerun_${TIMESTAMP}"
WORKERS=5  # 并发工作进程数
GROUND_TRUTH="evaluation/datasets/annotated/ground_truth_filtered.json"  # 使用过滤后的 ground truth（排除 biorem）
EVAL_ENV="evaluation/config/env.evaluation"  # 评估环境配置

# 检查文件是否存在
if [ ! -f "$GROUND_TRUTH" ]; then
    echo "❌ Error: ground truth file not found: $GROUND_TRUTH"
    exit 1
fi

if [ ! -f "$EVAL_ENV" ]; then
    echo "❌ Error: evaluation env file not found: $EVAL_ENV"
    exit 1
fi

echo "========================================================================"
echo "🔄 开始补跑缺失的评估运行"
echo "========================================================================"
echo "时间戳: $TIMESTAMP"
echo "输出目录: $BASE_OUTPUT_DIR"
echo "并发工作进程: $WORKERS"
echo "目标：补齐每个模型每个文档到 10 次运行"
echo "========================================================================"

# 创建输出目录
mkdir -p "$BASE_OUTPUT_DIR"

# 补跑函数 - 支持指定文档和运行次数
run_evaluation() {
    local MODEL_NAME=$1
    local MODEL_CONFIG=$2
    local DOCUMENT=$3
    local REPEAT_COUNT=$4
    
    echo ""
    echo "=== 补跑 $MODEL_NAME/$DOCUMENT ($REPEAT_COUNT 次) ==="
    
    # 创建临时 ground truth，只包含指定的文档
    TEMP_GT=$(mktemp /tmp/ground_truth_${MODEL_NAME}_${DOCUMENT}_XXXXXX.json)
    python3 << PYTHON_EOF
import json
from pathlib import Path

gt_path = Path("$GROUND_TRUTH")
with open(gt_path, 'r') as f:
    gt_data = json.load(f)

# Filter to only include the specified document
filtered_docs = [
    doc for doc in gt_data.get('documents', [])
    if doc.get('document_id') == '$DOCUMENT'
]

gt_data['documents'] = filtered_docs

with open('$TEMP_GT', 'w') as f:
    json.dump(gt_data, f, indent=2)

print(f"Created temporary ground truth with {len(filtered_docs)} document(s)")
PYTHON_EOF
    
    python evaluation/scripts/run_batch_evaluation.py \
        --env-file "$EVAL_ENV" \
        --ground-truth "$TEMP_GT" \
        --model-configs "$MODEL_CONFIG" \
        --output-dir "$BASE_OUTPUT_DIR/${MODEL_NAME}_${DOCUMENT}" \
        --workers "$WORKERS" \
        --repeats "$REPEAT_COUNT"
    
    local STATUS=$?
    rm -f "$TEMP_GT"
    
    if [ $STATUS -eq 0 ]; then
        echo "✅ $MODEL_NAME/$DOCUMENT 补跑完成"
    else
        echo "❌ $MODEL_NAME/$DOCUMENT 补跑失败"
        return 1
    fi
}

# 根据统计结果，需要补跑的情况：
# 1. GPT-5/biosensor: 7 次 (缺失: 1, 3, 5, 7, 8, 9, 10)
# 2. O3/biosensor: 7 次 (缺失: 4, 5, 6, 7, 8, 9, 10)
# 3. Sonnet/biosensor: 4 次 (缺失: 1, 2, 3, 4)
# 4. Qwen Flash/biosensor: 1 次 (缺失: 4)
# 5. Qwen Flash/earthworm: 1 次 (缺失: 10)
# 6. Haiku/biosensor: 1 次 (缺失: 7)

echo ""
echo "════════════════════════════════════════════════════════════════════════"
echo "📋 补跑计划"
echo "════════════════════════════════════════════════════════════════════════"
echo "GPT-5/biosensor: 7 次"
echo "O3/biosensor: 7 次"
echo "Sonnet/biosensor: 4 次"
echo "Qwen Flash/biosensor: 1 次"
echo "Qwen Flash/earthworm: 1 次"
echo "Haiku/biosensor: 1 次"
echo "总计: 21 次运行"
echo "════════════════════════════════════════════════════════════════════════"
echo ""

# 并行运行可以同时进行的任务
PIDS=()
STATUSES=()

# OpenAI GPT-5 - biosensor: 7 次
echo "🚀 启动 GPT-5/biosensor (7 次)..."
run_evaluation "gpt5" \
    "evaluation/config/model_configs/openai_gpt5.env" \
    "biosensor" \
    7 &
PIDS+=($!)
STATUSES+=("GPT-5/biosensor")

# OpenAI O3 - biosensor: 7 次
echo "🚀 启动 O3/biosensor (7 次)..."
run_evaluation "o3" \
    "evaluation/config/model_configs/openai_o3.env" \
    "biosensor" \
    7 &
PIDS+=($!)
STATUSES+=("O3/biosensor")

# Anthropic Sonnet - biosensor: 4 次
echo "🚀 启动 Sonnet/biosensor (4 次)..."
run_evaluation "sonnet" \
    "evaluation/config/model_configs/anthropic_sonnet.env" \
    "biosensor" \
    4 &
PIDS+=($!)
STATUSES+=("Sonnet/biosensor")

# 等待第一批完成
echo ""
echo "⏳ 等待第一批任务完成..."
for i in "${!PIDS[@]}"; do
    wait ${PIDS[$i]}
    STATUS=$?
    if [ $STATUS -eq 0 ]; then
        echo "✅ ${STATUSES[$i]} 补跑成功"
    else
        echo "❌ ${STATUSES[$i]} 补跑失败 (退出码: $STATUS)"
    fi
done

# 清空数组
PIDS=()
STATUSES=()

# 第二批：较小的任务
# Qwen Flash - biosensor: 1 次
echo ""
echo "🚀 启动 Qwen Flash/biosensor (1 次)..."
run_evaluation "qwen_flash" \
    "evaluation/config/model_configs/qwen_flash.env" \
    "biosensor" \
    1 &
PIDS+=($!)
STATUSES+=("Qwen Flash/biosensor")

# Qwen Flash - earthworm: 1 次
echo "🚀 启动 Qwen Flash/earthworm (1 次)..."
run_evaluation "qwen_flash" \
    "evaluation/config/model_configs/qwen_flash.env" \
    "earthworm" \
    1 &
PIDS+=($!)
STATUSES+=("Qwen Flash/earthworm")

# Anthropic Haiku - biosensor: 1 次
echo "🚀 启动 Haiku/biosensor (1 次)..."
run_evaluation "haiku" \
    "evaluation/config/model_configs/anthropic_haiku.env" \
    "biosensor" \
    1 &
PIDS+=($!)
STATUSES+=("Haiku/biosensor")

# 等待第二批完成
echo ""
echo "⏳ 等待第二批任务完成..."
for i in "${!PIDS[@]}"; do
    wait ${PIDS[$i]}
    STATUS=$?
    if [ $STATUS -eq 0 ]; then
        echo "✅ ${STATUSES[$i]} 补跑成功"
    else
        echo "❌ ${STATUSES[$i]} 补跑失败 (退出码: $STATUS)"
    fi
done

echo ""
echo "========================================================================"
echo "✅ 所有补跑任务完成"
echo "========================================================================"
echo "输出目录: $BASE_OUTPUT_DIR"
echo ""
echo "📝 下一步："
echo "  1. 检查补跑结果："
echo "     ls -la $BASE_OUTPUT_DIR"
echo ""
echo "  2. 将补跑结果合并到主目录（需要手动处理 run_idx 映射）："
echo "     python evaluation/scripts/merge_rerun_results.py --rerun-dir $BASE_OUTPUT_DIR"
echo ""
echo "  3. 重新运行分析："
echo "     python evaluation/analysis/run_analysis.py"
echo "========================================================================"


