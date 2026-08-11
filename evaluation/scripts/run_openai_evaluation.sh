#!/bin/bash
# Run evaluation for OpenAI models in parallel
# Usage: ./run_openai_evaluation.sh [repeats] [workers] [approval-id]

BASE_DIR="/Users/changlinke/Documents/Main/SSB/PhD/Research/FAIRiAgent"
cd "$BASE_DIR"

TIMESTAMP=$(date +%Y%m%d_%H%M%S)
OUTPUT_DIR="evaluation/runs/openai_parallel_${TIMESTAMP}"
PYTHON="/Users/changlinke/miniforge3/envs/FAIRiAgent/bin/python3"

# Default values
REPEATS=${1:-3}
WORKERS=${2:-3}
APPROVAL_ID=${3:-${FAIRIAGENT_APPROVAL_ID:-}}

if [ -z "$APPROVAL_ID" ]; then
  echo "Refusing model execution: provide approval-id as argument 3 or FAIRIAGENT_APPROVAL_ID."
  exit 2
fi

# Create output directory
mkdir -p "$OUTPUT_DIR"

echo "🚀 Starting OpenAI models parallel evaluation"
echo "Output directory: $OUTPUT_DIR"
echo "Repeats: $REPEATS per document"
echo "Workers: $WORKERS parallel runs"
echo ""

# Start GPT-5 evaluation
# echo "📊 Starting GPT-5 evaluation..."
# nohup $PYTHON evaluation/scripts/run_batch_evaluation.py \
#   --env-file evaluation/config/env.evaluation \
#   --model-configs evaluation/config/model_configs/openai_gpt5.env \
#   --ground-truth evaluation/datasets/annotated/ground_truth_v2.json \
#   --output-dir "${OUTPUT_DIR}/gpt5" \
#   --repeats $REPEATS \
#   --workers $WORKERS \
#   > "${OUTPUT_DIR}/gpt5.log" 2>&1 &
# GPT5_PID=$!
# echo "  GPT-5 PID: $GPT5_PID"

# Start GPT-4.1 evaluation
echo "📊 Starting GPT-4.1 evaluation..."
nohup $PYTHON evaluation/scripts/run_batch_evaluation.py \
  --env-file evaluation/config/env.evaluation \
  --model-configs evaluation/config/model_configs/openai_gpt4.1.env \
  --ground-truth evaluation/datasets/annotated/ground_truth_v2.json \
  --output-dir "${OUTPUT_DIR}/gpt4.1" \
  --repeats $REPEATS \
  --workers $WORKERS \
  --approval-id "$APPROVAL_ID" \
  > "${OUTPUT_DIR}/gpt4.1.log" 2>&1 &
GPT4_1_PID=$!
echo "  GPT-4.1 PID: $GPT4_1_PID"

# Start GPT-4o evaluation
# echo "📊 Starting GPT-4o evaluation..."
# nohup $PYTHON evaluation/scripts/run_batch_evaluation.py \
#   --env-file evaluation/config/env.evaluation \
#   --model-configs evaluation/config/model_configs/openai_gpt4o.env \
#   --ground-truth evaluation/datasets/annotated/ground_truth_v2.json \
#   --output-dir "${OUTPUT_DIR}/gpt4o" \
#   --repeats $REPEATS \
#   --workers $WORKERS \
#   > "${OUTPUT_DIR}/gpt4o.log" 2>&1 &
# GPT4O_PID=$!
# echo "  GPT-4o PID: $GPT4O_PID"

# Start O3 evaluation
echo "📊 Starting O3 evaluation..."
nohup $PYTHON evaluation/scripts/run_batch_evaluation.py \
  --env-file evaluation/config/env.evaluation \
  --model-configs evaluation/config/model_configs/openai_o3.env \
  --ground-truth evaluation/datasets/annotated/ground_truth_v2.json \
  --output-dir "${OUTPUT_DIR}/o3" \
  --repeats $REPEATS \
  --workers $WORKERS \
  --approval-id "$APPROVAL_ID" \
  > "${OUTPUT_DIR}/o3.log" 2>&1 &
O3_PID=$!
echo "  O3 PID: $O3_PID"

echo ""
echo "✅ All evaluations started!"
echo ""
echo "📊 Monitor progress:"
echo "  tail -f ${OUTPUT_DIR}/*.log"
echo ""
echo "📋 Check status:"
echo "  ps aux | grep run_batch_evaluation"
echo ""
echo "🛑 To stop all evaluations:"
echo "  pkill -f run_batch_evaluation"
echo ""
echo "📁 Results will be in: $OUTPUT_DIR"
echo ""
echo "📊 After all runs complete, run analysis:"
echo "  $PYTHON evaluation/analysis/run_analysis.py --runs-dir $OUTPUT_DIR"
