#!/bin/bash
# Run evaluation for Anthropic models in parallel
# Usage: ./run_anthropic_evaluation.sh [repeats] [workers] [approval-id]

BASE_DIR="/Users/changlinke/Documents/Main/SSB/PhD/Research/FAIRiAgent"
cd "$BASE_DIR"

TIMESTAMP=$(date +%Y%m%d_%H%M%S)
OUTPUT_DIR="evaluation/runs/anthropic_parallel_${TIMESTAMP}"
PYTHON="/Users/changlinke/miniforge3/envs/FAIRiAgent/bin/python3"

# Default values: 10 repeats, 5 workers
REPEATS=${1:-10}
WORKERS=${2:-5}
APPROVAL_ID=${3:-${FAIRIAGENT_APPROVAL_ID:-}}

if [ -z "$APPROVAL_ID" ]; then
  echo "Refusing model execution: provide approval-id as argument 3 or FAIRIAGENT_APPROVAL_ID."
  exit 2
fi

# Create output directory
mkdir -p "$OUTPUT_DIR"

echo "🚀 Starting Anthropic models parallel evaluation"
echo "Output directory: $OUTPUT_DIR"
echo "Repeats: $REPEATS per document"
echo "Workers: $WORKERS parallel runs"
echo "Excluding: biorem"
echo ""

# Start Claude Sonnet 4.5 evaluation
echo "📊 Starting Claude Sonnet 4.5 evaluation..."
nohup $PYTHON evaluation/scripts/run_batch_evaluation.py \
  --env-file evaluation/config/env.evaluation \
  --model-configs evaluation/config/model_configs/anthropic_sonnet.env \
  --ground-truth evaluation/datasets/annotated/ground_truth_v2.json \
  --output-dir "${OUTPUT_DIR}/sonnet" \
  --repeats $REPEATS \
  --workers $WORKERS \
  --exclude-documents biorem \
  --approval-id "$APPROVAL_ID" \
  > "${OUTPUT_DIR}/sonnet.log" 2>&1 &
SONNET_PID=$!
echo "  Claude Sonnet 4.5 PID: $SONNET_PID"

# Start Claude Haiku 4.5 evaluation
echo "📊 Starting Claude Haiku 4.5 evaluation..."
nohup $PYTHON evaluation/scripts/run_batch_evaluation.py \
  --env-file evaluation/config/env.evaluation \
  --model-configs evaluation/config/model_configs/anthropic_haiku.env \
  --ground-truth evaluation/datasets/annotated/ground_truth_v2.json \
  --output-dir "${OUTPUT_DIR}/haiku" \
  --repeats $REPEATS \
  --workers $WORKERS \
  --exclude-documents biorem \
  --approval-id "$APPROVAL_ID" \
  > "${OUTPUT_DIR}/haiku.log" 2>&1 &
HAIKU_PID=$!
echo "  Claude Haiku 4.5 PID: $HAIKU_PID"

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
