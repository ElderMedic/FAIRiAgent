#!/bin/bash

######################################################################
# Quick test of baseline evaluation system
# Tests on a single document with 2 runs to verify everything works
######################################################################

set -e

# 激活环境
source /Users/changlinke/miniforge3/etc/profile.d/conda.sh
conda activate FAIRiAgent

echo "========================================================================"
echo "🧪 Testing Baseline Evaluation System"
echo "========================================================================"
echo ""

# 配置
TEST_OUTPUT="evaluation/runs/test_baseline_$(date +%Y%m%d_%H%M%S)"
CONFIG_FILE="evaluation/config/model_configs/openai_gpt4o.env"
CONFIG_NAME="test_baseline_gpt4o"
GROUND_TRUTH="evaluation/datasets/annotated/ground_truth_filtered.json"  # Excludes biorem

echo "📋 Config: $CONFIG_NAME (GPT-4o baseline)"
echo "📁 Output: $TEST_OUTPUT"
echo "📄 Ground truth: $GROUND_TRUTH (biosensor only)"
echo ""

# 创建测试目录
mkdir -p "$TEST_OUTPUT"

# 运行测试（只跑 2 次）
echo "Running baseline test (2 runs)..."
echo ""

python evaluation/scripts/run_baseline_batch.py \
    --config-file "$CONFIG_FILE" \
    --config-name "$CONFIG_NAME" \
    --ground-truth "$GROUND_TRUTH" \
    --output-dir "$TEST_OUTPUT/$CONFIG_NAME" \
    --workers 2 \
    --n-runs 2

if [ $? -eq 0 ]; then
    echo ""
    echo "========================================================================"
    echo "✅ Test successful!"
    echo "========================================================================"
    echo ""
    echo "📊 Check results:"
    echo "   ls -la $TEST_OUTPUT/$CONFIG_NAME/outputs/$CONFIG_NAME/biosensor/"
    echo ""
    echo "📄 View extracted metadata:"
    echo "   cat $TEST_OUTPUT/$CONFIG_NAME/outputs/$CONFIG_NAME/biosensor/run_1/metadata_json.json"
    echo ""
    echo "🔍 Compare with agentic workflow (if available):"
    echo "   # Agentic GPT-4o vs Baseline GPT-4o"
    echo "   diff $TEST_OUTPUT/$CONFIG_NAME/outputs/$CONFIG_NAME/biosensor/run_1/metadata_json.json \\"
    echo "        evaluation/runs/<agentic_run>/openai_gpt4o/outputs/openai_gpt4o/biosensor/run_1/metadata_json.json"
    echo "========================================================================"
else
    echo ""
    echo "========================================================================"
    echo "❌ Test failed!"
    echo "========================================================================"
    echo "Check logs in: $TEST_OUTPUT"
    exit 1
fi

