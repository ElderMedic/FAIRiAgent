#!/bin/bash
# Show full logs with all details

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

echo "📊 Full Evaluation Logs"
echo "======================="
echo "Run directory: $RUN_DIR"
echo ""

for model in qwen_max qwen_plus qwen_flash; do
    LOG_FILE="$RUN_DIR/$model.log"
    
    if [ -f "$LOG_FILE" ]; then
        echo ""
        echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
        echo "📄 $model.log ($(wc -l < "$LOG_FILE" | tr -d ' ') lines)"
        echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
        echo ""
        cat "$LOG_FILE"
        echo ""
    else
        echo "⚠️  $model.log not found"
    fi
done

echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "✅ End of logs"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

