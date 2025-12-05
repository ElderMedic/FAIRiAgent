#!/bin/bash
#
# 补跑失败的评估运行
# 使用已有的 MinerU markdown 输出作为输入，跳过 MinerU 转换步骤
#

set -e  # Exit on error

# 配置
TIMESTAMP=$(date +%Y%m%d_%H%M%S)
BASE_OUTPUT_DIR="evaluation/runs/rerun_${TIMESTAMP}"
WORKERS=5  # 并发工作进程数
GROUND_TRUTH="evaluation/datasets/annotated/ground_truth_rerun.json"  # 使用指向 markdown 的 ground truth
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
echo "🔄 开始补跑失败的评估运行"
echo "========================================================================"
echo "时间戳: $TIMESTAMP"
echo "输出目录: $BASE_OUTPUT_DIR"
echo "并发工作进程: $WORKERS"
echo "========================================================================"

# 创建输出目录
mkdir -p "$BASE_OUTPUT_DIR"

# 补跑函数
run_evaluation() {
    local MODEL_NAME=$1
    local MODEL_CONFIG=$2
    local REPEAT_COUNT=$3
    
    echo ""
    echo "=== 补跑 $MODEL_NAME ($REPEAT_COUNT 次) ==="
    
    python evaluation/scripts/run_batch_evaluation.py \
        --env-file "$EVAL_ENV" \
        --ground-truth "$GROUND_TRUTH" \
        --model-configs "$MODEL_CONFIG" \
        --output-dir "$BASE_OUTPUT_DIR/$MODEL_NAME" \
        --workers "$WORKERS" \
        --repeats "$REPEAT_COUNT"
    
    if [ $? -eq 0 ]; then
        echo "✅ $MODEL_NAME 补跑完成"
    else
        echo "❌ $MODEL_NAME 补跑失败"
        return 1
    fi
}

# 注意：Anthropic 模型已在 rerun_20251205_131942 中完成，此处只运行 OpenAI 模型

# OpenAI GPT-5 - biosensor: 7 次
echo ""
echo "════════════════════════════════════════════════════════════════════════"
echo "📋 OpenAI GPT-5 (并行运行)"
echo "════════════════════════════════════════════════════════════════════════"
run_evaluation "openai_gpt5" \
    "evaluation/config/model_configs/openai_gpt5.env" \
    7 &
GPT5_PID=$!

# OpenAI O3 - biosensor: 7 次
echo ""
echo "════════════════════════════════════════════════════════════════════════"
echo "📋 OpenAI O3 (并行运行)"
echo "════════════════════════════════════════════════════════════════════════"
run_evaluation "openai_o3" \
    "evaluation/config/model_configs/openai_o3.env" \
    7 &
O3_PID=$!

# 等待两个任务完成
echo ""
echo "⏳ 等待 GPT-5 (PID: $GPT5_PID) 和 O3 (PID: $O3_PID) 完成..."
wait $GPT5_PID
GPT5_STATUS=$?
wait $O3_PID
O3_STATUS=$?

echo ""
if [ $GPT5_STATUS -eq 0 ]; then
    echo "✅ GPT-5 补跑成功"
else
    echo "❌ GPT-5 补跑失败 (退出码: $GPT5_STATUS)"
fi

if [ $O3_STATUS -eq 0 ]; then
    echo "✅ O3 补跑成功"
else
    echo "❌ O3 补跑失败 (退出码: $O3_STATUS)"
fi

echo ""
echo "========================================================================"
echo "✅ 所有补跑任务完成"
echo "========================================================================"
echo "输出目录: $BASE_OUTPUT_DIR"
echo ""
echo "运行以下命令查看结果："
echo "  python evaluation/analysis/run_analysis.py"
echo "========================================================================"

