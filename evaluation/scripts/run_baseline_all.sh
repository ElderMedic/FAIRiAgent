#!/bin/bash

######################################################################
# Run baseline single-prompt evaluations on all documents
# This serves as a comparison against the multi-agent workflow
######################################################################

set -e

# 激活环境
source /Users/changlinke/miniforge3/etc/profile.d/conda.sh
conda activate FAIRiAgent

# 配置
TIMESTAMP=$(date +%Y%m%d_%H%M%S)
BASE_OUTPUT_DIR="evaluation/runs/baseline_${TIMESTAMP}"
GROUND_TRUTH="evaluation/datasets/annotated/ground_truth_filtered.json"  # Excludes biorem
N_RUNS=10  # 每个文档运行 10 次
WORKERS=3  # 并发数（比 agentic 低，因为单次调用更快）

echo "========================================================================"
echo "🔬 Baseline Single-Prompt Evaluation"
echo "========================================================================"
echo "Output directory: $BASE_OUTPUT_DIR"
echo "Ground truth: $GROUND_TRUTH"
echo "Runs per document: $N_RUNS"
echo "Workers: $WORKERS"
echo "========================================================================"
echo ""

# 创建输出目录
mkdir -p "$BASE_OUTPUT_DIR"

# 定义要测试的模型配置
# 使用 GPT-4o 作为 baseline：广泛使用，无 agent/thinking 功能
declare -a CONFIGS=(
    "openai_gpt4o:evaluation/config/model_configs/openai_gpt4o.env"
)

# 如果需要额外对比，可以添加：
# "anthropic_sonnet:evaluation/config/model_configs/anthropic_sonnet.env"

# 运行每个配置
for config_pair in "${CONFIGS[@]}"; do
    IFS=':' read -r config_name config_file <<< "$config_pair"
    
    echo ""
    echo "════════════════════════════════════════════════════════════════════════"
    echo "📋 Running baseline: $config_name"
    echo "════════════════════════════════════════════════════════════════════════"
    
    python evaluation/scripts/run_baseline_batch.py \
        --config-file "$config_file" \
        --config-name "baseline_${config_name}" \
        --ground-truth "$GROUND_TRUTH" \
        --output-dir "$BASE_OUTPUT_DIR/baseline_${config_name}" \
        --workers "$WORKERS" \
        --n-runs "$N_RUNS"
    
    if [ $? -eq 0 ]; then
        echo "✅ baseline_${config_name} completed"
    else
        echo "❌ baseline_${config_name} failed"
    fi
done

echo ""
echo "========================================================================"
echo "✅ All baseline evaluations complete!"
echo "========================================================================"
echo "Output directory: $BASE_OUTPUT_DIR"
echo ""
echo "Next steps:"
echo "1. Run evaluators on baseline outputs:"
echo "   python evaluation/scripts/evaluate_outputs.py \\"
echo "     --run-dir $BASE_OUTPUT_DIR/baseline_openai_gpt4o \\"
echo "     --ground-truth $GROUND_TRUTH \\"
echo "     --output-dir $BASE_OUTPUT_DIR/baseline_openai_gpt4o/evaluation_results"
echo ""
echo "2. Compare with agentic workflow results using analysis tools"
echo "========================================================================"

