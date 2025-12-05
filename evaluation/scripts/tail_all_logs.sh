#!/bin/bash
# Tail all evaluation logs in real-time with prefixes

# Use provided directory or find latest
if [ -n "$1" ]; then
    RUN_DIR="$1"
else
    # Find latest run directory
    RUN_DIR=$(ls -td evaluation/runs/run_* 2>/dev/null | head -1)
    if [ -z "$RUN_DIR" ]; then
        echo "❌ No evaluation runs found in evaluation/runs/"
        exit 1
    fi
fi

echo "📊 Real-time Evaluation Logs (Ctrl+C to stop)"
echo "=============================================="
echo "Run directory: $RUN_DIR"
echo ""

# Function to tail with model prefix
tail_model() {
    local file=$1
    local model=$2
    local color=$3
    
    if [ -f "$file" ]; then
        tail -f "$file" 2>/dev/null | while IFS= read -r line; do
            echo -e "${color}[${model}]${NC} $line"
        done &
    fi
}

# Colors
GREEN='\033[0;32m'
BLUE='\033[0;34m'
MAGENTA='\033[0;35m'
NC='\033[0m' # No Color

# Start tailing all logs
tail_model "$RUN_DIR/qwen_max.log" "QWEN-MAX" "$GREEN" &
tail_model "$RUN_DIR/qwen_plus.log" "QWEN-PLUS" "$BLUE" &
tail_model "$RUN_DIR/qwen_flash.log" "QWEN-FLASH" "$MAGENTA" &

# Wait for all background jobs
wait

