#!/bin/bash
# Monitor parallel evaluation runs

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

echo "📊 Parallel Evaluation Progress"
echo "==============================="
echo "Run directory: $RUN_DIR"
echo ""

# Check if processes are running
QWEN_MAX_RUNNING=$(pgrep -f "qwen_max.env" > /dev/null && echo "✅" || echo "❌")
QWEN_PLUS_RUNNING=$(pgrep -f "qwen_plus.env" > /dev/null && echo "✅" || echo "❌")
QWEN_FLASH_RUNNING=$(pgrep -f "qwen_flash.env" > /dev/null && echo "✅" || echo "❌")

echo "Process Status:"
echo "  Qwen Max:   $QWEN_MAX_RUNNING"
echo "  Qwen Plus:  $QWEN_PLUS_RUNNING"
echo "  Qwen Flash: $QWEN_FLASH_RUNNING"
echo ""

# Count completed runs per model
echo "Completed Runs (out of 9 per model):"
for model in qwen_max qwen_plus qwen_flash; do
    COUNT=$(find "$RUN_DIR/$model/outputs" -name "metadata_json.json" 2>/dev/null | wc -l | tr -d ' ')
    echo "  $model: $COUNT / 9"
done

echo ""
echo "Total Progress: $(( $(find "$RUN_DIR" -name "metadata_json.json" 2>/dev/null | wc -l | tr -d ' ') )) / 27 runs"
echo ""

# Show latest activity from each log
echo "📝 Latest Activity:"
echo "-------------------"
for model in qwen_max qwen_plus qwen_flash; do
    if [ -f "$RUN_DIR/$model.log" ]; then
        LAST_LINE=$(tail -1 "$RUN_DIR/$model.log" 2>/dev/null | sed 's/^[[:space:]]*//' | cut -c1-80)
        if [ -n "$LAST_LINE" ]; then
            echo "  $model: ${LAST_LINE}..."
        fi
    fi
done

echo ""
echo "🔍 Check MinerU usage:"
grep -h "MinerU\|PyMuPDF" "$RUN_DIR"/*.log 2>/dev/null | tail -3 | head -3

