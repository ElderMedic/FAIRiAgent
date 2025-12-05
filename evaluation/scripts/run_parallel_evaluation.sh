#!/bin/bash
# Run evaluation for all 3 models in parallel

BASE_DIR="/Users/changlinke/Documents/Main/SSB/PhD/Research/FAIRiAgent"
cd "$BASE_DIR"

TIMESTAMP=$(date +%Y%m%d_%H%M%S)
OUTPUT_DIR="evaluation/runs/run_${TIMESTAMP}"
PYTHON="/Users/changlinke/miniforge3/envs/FAIRiAgent/bin/python3"

# Create output directory
mkdir -p "$OUTPUT_DIR"

echo "🚀 Starting parallel evaluation runs"
echo "Output directory: $OUTPUT_DIR"
echo ""

# Start Qwen Max evaluation
echo "📊 Starting Qwen Max evaluation..."
nohup $PYTHON evaluation/scripts/run_batch_evaluation.py \
  --env-file evaluation/config/env.evaluation \
  --model-configs evaluation/config/model_configs/qwen_max.env \
  --ground-truth evaluation/datasets/annotated/ground_truth_v1.json \
  --output-dir "${OUTPUT_DIR}/qwen_max" \
  --repeats 3 \
  --workers 3 \
  > "${OUTPUT_DIR}/qwen_max.log" 2>&1 &
QWEN_MAX_PID=$!
echo "  Qwen Max PID: $QWEN_MAX_PID"

# Start Qwen Plus evaluation
echo "📊 Starting Qwen Plus evaluation..."
nohup $PYTHON evaluation/scripts/run_batch_evaluation.py \
  --env-file evaluation/config/env.evaluation \
  --model-configs evaluation/config/model_configs/qwen_plus.env \
  --ground-truth evaluation/datasets/annotated/ground_truth_v1.json \
  --output-dir "${OUTPUT_DIR}/qwen_plus" \
  --repeats 3 \
  --workers 3 \
  > "${OUTPUT_DIR}/qwen_plus.log" 2>&1 &
QWEN_PLUS_PID=$!
echo "  Qwen Plus PID: $QWEN_PLUS_PID"

# Start Qwen Flash evaluation
echo "📊 Starting Qwen Flash evaluation..."
nohup $PYTHON evaluation/scripts/run_batch_evaluation.py \
  --env-file evaluation/config/env.evaluation \
  --model-configs evaluation/config/model_configs/qwen_flash.env \
  --ground-truth evaluation/datasets/annotated/ground_truth_v1.json \
  --output-dir "${OUTPUT_DIR}/qwen_flash" \
  --repeats 3 \
  --workers 3 \
  > "${OUTPUT_DIR}/qwen_flash.log" 2>&1 &
QWEN_FLASH_PID=$!
echo "  Qwen Flash PID: $QWEN_FLASH_PID"

echo ""
echo "✅ All 3 Qwen evaluations started in parallel!"
echo ""
echo "📝 Monitor progress:"
echo "  tail -f ${OUTPUT_DIR}/qwen_max.log"
echo "  tail -f ${OUTPUT_DIR}/qwen_plus.log"
echo "  tail -f ${OUTPUT_DIR}/qwen_flash.log"
echo ""
echo "🔍 Check processes:"
echo "  ps aux | grep run_batch_evaluation"
echo ""
echo "📊 PIDs:"
echo "  Qwen Max: $QWEN_MAX_PID"
echo "  Qwen Plus: $QWEN_PLUS_PID"
echo "  Qwen Flash: $QWEN_FLASH_PID"
echo ""
echo "Output directory: $OUTPUT_DIR"

