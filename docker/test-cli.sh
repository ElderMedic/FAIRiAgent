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

# Load .env file if it exists (check docker/.env first, then root .env, fallback to env.example)
if [ -f "${SCRIPT_DIR}/.env" ]; then
    echo "📋 Loading configuration from docker/.env file..."
    export $(grep -v '^#' "${SCRIPT_DIR}/.env" | xargs)
    echo ""
elif [ -f "${PROJECT_ROOT}/.env" ]; then
    echo "📋 Loading configuration from root .env file..."
    export $(grep -v '^#' "${PROJECT_ROOT}/.env" | xargs)
    echo ""
elif [ -f "${PROJECT_ROOT}/env.example" ]; then
    echo "⚠️  No .env file found, using env.example as fallback..."
    echo "💡 Tip: Copy env.example to .env and customize it: cp env.example .env"
    export $(grep -v '^#' "${PROJECT_ROOT}/env.example" | xargs)
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

LLM_PROVIDER="${LLM_PROVIDER:-qwen}"
FAIRIFIER_LLM_MODEL="${FAIRIFIER_LLM_MODEL:-qwen-flash}"
QWEN_API_BASE_URL="${QWEN_API_BASE_URL:-https://dashscope-intl.aliyuncs.com/compatible-mode/v1}"

echo "📄 Processing: ${TEST_FILE}"
echo "📂 Input directory: ${INPUT_DIR}"
echo "📁 Output directory: ${OUTPUT_DIR}"
echo "🤖 LLM Provider: ${LLM_PROVIDER}"
echo "🧠 Model: ${FAIRIFIER_LLM_MODEL}"
echo ""

# Determine Docker network configuration for Linux compatibility
# On Linux, use --network host for better compatibility with local services
if [ "$(uname)" = "Linux" ]; then
    # Use host network mode on Linux for direct access to localhost services
    # This allows containers to access services on the host directly
    DOCKER_NETWORK="--network host"
    DOCKER_EXTRA_HOSTS=""

    if [ -n "${FAIR_DS_API_URL}" ] && echo "${FAIR_DS_API_URL}" | grep -q "host.docker.internal"; then
        FAIR_DS_API_URL=$(echo "${FAIR_DS_API_URL}" | sed 's/host.docker.internal/localhost/g')
    fi
    if [ -n "${FAIR_DS_API_URL}" ] && echo "${FAIR_DS_API_URL}" | grep -q "localhost"; then
        # Keep localhost for host network mode
        :
    fi
else
    # macOS/Windows Docker Desktop supports host.docker.internal natively
    DOCKER_NETWORK=""
    DOCKER_EXTRA_HOSTS=""
fi

# Set default URLs if not provided
if [ -z "${FAIR_DS_API_URL}" ]; then
    if [ "$(uname)" = "Linux" ]; then
        FAIR_DS_API_URL="http://localhost:8083"
    else
        FAIR_DS_API_URL="http://host.docker.internal:8083"
    fi
fi

# Display final configuration
if [ "${LLM_PROVIDER}" = "qwen" ]; then
    echo "🔌 Qwen API: ${QWEN_API_BASE_URL}"
else
    echo "🔌 LLM base URL: ${FAIRIFIER_LLM_BASE_URL}"
fi
echo "🔌 FAIR-DS API: ${FAIR_DS_API_URL}"
echo ""
echo "⏳ Processing document..."
echo ""

# Run Docker CLI
docker run --rm \
    ${DOCKER_NETWORK} \
    ${DOCKER_EXTRA_HOSTS} \
    -v "${INPUT_DIR}:/app/test-inputs:ro" \
    -v "${OUTPUT_DIR}:/app/output" \
    -e LLM_PROVIDER="${LLM_PROVIDER}" \
    -e FAIRIFIER_LLM_MODEL="${FAIRIFIER_LLM_MODEL}" \
    -e FAIRIFIER_LLM_BASE_URL="${FAIRIFIER_LLM_BASE_URL:-}" \
    -e QWEN_API_BASE_URL="${QWEN_API_BASE_URL}" \
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
