#!/bin/bash
# Run FAIRiAgent CLI in Docker on test inputs
# Usage: ./test-cli.sh [filename.pdf]
#
# Configuration:
#   1. Copy .env.example to .env
#   2. Edit .env with your settings
#   3. Run this script

set -e

# Set variables
# IMAGE_NAME="fairiagent:latest"
IMAGE_NAME="ghcr.io/eldermedic/fairiagent:latest"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
INPUT_DIR="${PROJECT_ROOT}/examples/inputs"
OUTPUT_DIR="${PROJECT_ROOT}/docker-test-output"

# Load .env file if it exists (check docker/.env first, then root .env)
if [ -f "${SCRIPT_DIR}/.env" ]; then
    echo "📋 Loading configuration from docker/.env file..."
    export $(grep -v '^#' "${SCRIPT_DIR}/.env" | xargs)
    echo ""
elif [ -f "${PROJECT_ROOT}/.env" ]; then
    echo "📋 Loading configuration from root .env file..."
    export $(grep -v '^#' "${PROJECT_ROOT}/.env" | xargs)
    echo ""
fi

# Default test file
DEFAULT_TEST_FILE="earthworm_4n_paper_bioRxiv.pdf"

# Use provided filename or default
if [ $# -gt 0 ]; then
    TEST_FILE="$1"
else
    TEST_FILE="${DEFAULT_TEST_FILE}"
fi

echo "==================================="
echo "FAIRiAgent Docker CLI Test"
echo "==================================="
echo ""

# Check if Docker is running
if ! docker info > /dev/null 2>&1; then
    echo "❌ Error: Docker is not running"
    echo "Please start Docker and try again"
    exit 1
fi

# Check if test file exists
if [ ! -f "${INPUT_DIR}/${TEST_FILE}" ]; then
    echo "❌ Error: File not found: ${INPUT_DIR}/${TEST_FILE}"
    echo ""
    echo "Available test files:"
    ls -1 "${INPUT_DIR}"/*.pdf 2>/dev/null || echo "  No PDF files found"
    echo ""
    echo "Usage: $0 [filename.pdf]"
    echo "Example: $0 BIOREM_appendix2.pdf"
    exit 1
fi

# Create output directory
mkdir -p "${OUTPUT_DIR}"

# Check if image exists, if not build it
if ! docker image inspect ${IMAGE_NAME} > /dev/null 2>&1; then
    echo "🔨 Building Docker image..."
    cd "${PROJECT_ROOT}"
    docker build -t ${IMAGE_NAME} .
    echo "✅ Image built successfully"
    echo ""
fi

echo "📄 Processing: ${TEST_FILE}"
echo "📂 Input directory: ${INPUT_DIR}"
echo "📁 Output directory: ${OUTPUT_DIR}"
echo "🤖 LLM Provider: ${LLM_PROVIDER:-ollama}"
echo "🧠 Model: ${FAIRIFIER_LLM_MODEL:-qwen3:30b-a3b}"
echo ""

# Determine Docker extra hosts for Linux compatibility
# On Linux, host.docker.internal may not work, so we add it explicitly
if [ "$(uname)" = "Linux" ]; then
    # Use --add-host to make host.docker.internal work on Linux
    DOCKER_EXTRA_HOSTS="--add-host=host.docker.internal:host-gateway"
    
    # On Linux, replace localhost with host.docker.internal for Docker container access
    if [ -n "${FAIRIFIER_LLM_BASE_URL}" ] && echo "${FAIRIFIER_LLM_BASE_URL}" | grep -q "localhost"; then
        FAIRIFIER_LLM_BASE_URL=$(echo "${FAIRIFIER_LLM_BASE_URL}" | sed 's/localhost/host.docker.internal/g')
    fi
    if [ -n "${FAIR_DS_API_URL}" ] && echo "${FAIR_DS_API_URL}" | grep -q "localhost"; then
        FAIR_DS_API_URL=$(echo "${FAIR_DS_API_URL}" | sed 's/localhost/host.docker.internal/g')
    fi
else
    # macOS/Windows Docker Desktop supports host.docker.internal natively
    DOCKER_EXTRA_HOSTS=""
fi

# Set default URLs if not provided
if [ -z "${FAIRIFIER_LLM_BASE_URL}" ]; then
    FAIRIFIER_LLM_BASE_URL="http://host.docker.internal:11434"
fi
if [ -z "${FAIR_DS_API_URL}" ]; then
    FAIR_DS_API_URL="http://host.docker.internal:8083"
fi

# Display final configuration
echo "🔌 Ollama URL: ${FAIRIFIER_LLM_BASE_URL}"
echo "🔌 FAIR-DS API: ${FAIR_DS_API_URL}"
echo ""
echo "⏳ Processing document..."
echo ""

# Run Docker CLI
docker run --rm \
    ${DOCKER_EXTRA_HOSTS} \
    -v "${INPUT_DIR}:/app/test-inputs:ro" \
    -v "${OUTPUT_DIR}:/app/output" \
    -e LLM_PROVIDER="${LLM_PROVIDER:-ollama}" \
    -e FAIRIFIER_LLM_MODEL="${FAIRIFIER_LLM_MODEL:-qwen3:30b-a3b}" \
    -e FAIRIFIER_LLM_BASE_URL="${FAIRIFIER_LLM_BASE_URL}" \
    -e LLM_API_KEY="${LLM_API_KEY:-}" \
    -e LANGSMITH_API_KEY="${LANGSMITH_API_KEY:-}" \
    -e FAIR_DS_API_URL="${FAIR_DS_API_URL}" \
    ${IMAGE_NAME} \
    python run_fairifier.py process "/app/test-inputs/${TEST_FILE}"

echo ""
echo "==================================="
echo "✅ Processing complete!"
echo "==================================="
echo ""
echo "📊 Results saved to: ${OUTPUT_DIR}"
echo ""
echo "To process another file, run:"
echo "  ./test-cli.sh BIOREM_appendix2.pdf"
echo ""
