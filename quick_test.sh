#!/bin/bash
# Quick Test Script for FAIRiAgent with LangSmith

set -e  # Exit on error

echo "🧪 FAIRiAgent Quick Test"
echo "======================="
echo ""

# Check if in correct directory
if [ ! -f "fairifier/config.py" ]; then
    echo "❌ Error: Please run this script from the FAIRiAgent project root"
    exit 1
fi

# Activate conda environment
echo "📦 Activating FAIRiAgent environment..."
eval "$(conda shell.bash hook)"
mamba activate FAIRiAgent 2>/dev/null || conda activate FAIRiAgent 2>/dev/null || { echo "❌ Failed to activate 'FAIRiAgent' environment"; exit 1; }

# Check if .env exists
if [ ! -f ".env" ]; then
    echo "⚠️  No .env file found, using environment variables"
    echo "💡 Tip: Copy env.example to .env and configure it"
else
    echo "✅ Found .env file"
    # Load .env (strip full-line and inline comments so export does not get invalid identifiers)
    set -a
    while IFS= read -r line; do
        [[ -z "$line" || "$line" =~ ^[[:space:]]*# ]] && continue
        line=$(printf '%s' "$line" | sed 's/[[:space:]]*#.*$//' | sed 's/[[:space:]]*$//')
        [[ -n "$line" ]] && export "$line"
    done < .env
    set +a
fi

# Set LangSmith tracing
export LANGCHAIN_TRACING_V2=true
export LANGCHAIN_PROJECT=${LANGSMITH_PROJECT:-"fairifier-quicktest"}

echo ""
echo "📋 Configuration:"
echo "  • LLM Model: ${LLM_MODEL:-qwen3:32b}"
echo "  • FAIR-DS API: ${FAIR_DS_API_URL:-http://localhost:8083}"
echo "  • LangSmith Project: $LANGCHAIN_PROJECT"
echo "  • LangSmith Tracing: ✅ Enabled"
echo ""

# Check dependencies
echo "🔍 Checking dependencies..."

# Check Ollama
if ! curl -s http://localhost:11434/api/tags > /dev/null 2>&1; then
    echo "⚠️  Warning: Ollama may not be running at localhost:11434"
    echo "   Please start Ollama: ollama serve"
else
    echo "  ✅ Ollama is running"
fi

# Check FAIR-DS API
if ! curl -s ${FAIR_DS_API_URL:-http://localhost:8083}/api/package > /dev/null 2>&1; then
    echo "  ⚠️  Warning: FAIR-DS API not responding at ${FAIR_DS_API_URL:-http://localhost:8083}"
    echo "   Please start FAIR-DS API"
else
    echo "  ✅ FAIR-DS API is accessible"
fi

echo ""

TEST_DOC="examples/inputs/earthworm_4n_paper_bioRxiv.pdf"
if [ ! -f "$TEST_DOC" ]; then
    echo "❌ Bundled sample not found: $TEST_DOC"
    exit 1
fi

# Create output directory
OUTPUT_DIR="output_test_$(date +%Y%m%d_%H%M%S)"
mkdir -p "$OUTPUT_DIR"

echo ""
echo "🚀 Running FAIRiAgent..."
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""

# Run the CLI
python -m fairifier.cli process "$TEST_DOC" \
    --output-dir "$OUTPUT_DIR" \
    --project-id "test_$(date +%H%M%S)" \
    --verbose

EXIT_CODE=$?

echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""

if [ $EXIT_CODE -eq 0 ]; then
    echo "✅ Test completed successfully!"
    echo ""
    echo "📁 Output files:"
    ls -lh "$OUTPUT_DIR"
    echo ""
    echo "📊 View results:"
    echo "  • Metadata JSON: cat $OUTPUT_DIR/metadata.json | jq '.'"
    echo "  • Processing Log: cat $OUTPUT_DIR/processing_log.jsonl | jq '.'"
    echo "  • LLM Responses: cat $OUTPUT_DIR/llm_responses.json | jq '.'"
    echo ""
    echo "🔍 View in LangSmith:"
    echo "  https://smith.langchain.com/projects/$LANGCHAIN_PROJECT"
else
    echo "❌ Test failed with exit code $EXIT_CODE"
    echo ""
    echo "🐛 Debug tips:"
    echo "  1. Check the output above for error messages"
    echo "  2. Verify Ollama is running: curl http://localhost:11434/api/tags"
    echo "  3. Verify FAIR-DS API: curl http://localhost:8083/api/package"
    echo "  4. Check logs in: $OUTPUT_DIR/processing_log.jsonl"
fi

echo ""
