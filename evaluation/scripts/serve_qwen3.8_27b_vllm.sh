#!/usr/bin/env bash
# Serve Qwen/Qwen3.8-27B with vLLM using the official recipe flags.
# Default GPU 1 leaves MinerU on GPU 0. API: http://127.0.0.1:${PORT}/v1
set -euo pipefail

MODEL="${MODEL:-Qwen/Qwen3.8-27B}"
PORT="${PORT:-8001}"
GPU="${CUDA_VISIBLE_DEVICES:-1}"
MAX_MODEL_LEN="${MAX_MODEL_LEN:-65536}"
GPU_MEM_UTIL="${GPU_MEM_UTIL:-0.90}"
VENV="${VLLM_VENV:-/scratch/LLM/venvs/vllm}"
# Ignore login-shell HF_HOME (often a different cache). Override with VLLM_HF_HOME.
HF_HOME="${VLLM_HF_HOME:-/scratch/LLM/huggingface/ke003}"
LOG_DIR="${LOG_DIR:-/scratch/LLM/logs}"
PID_FILE="${PID_FILE:-${LOG_DIR}/vllm_qwen3.8-27b.pid}"
LOG_FILE="${LOG_FILE:-${LOG_DIR}/vllm_qwen3.8-27b.log}"
ENABLE_MTP="${ENABLE_MTP:-0}"

mkdir -p "$LOG_DIR" "$HF_HOME"

VLLM_BIN="${VENV}/bin/vllm"
PYTHON_BIN="${VENV}/bin/python"
if [[ ! -x "$VLLM_BIN" && ! -x "$PYTHON_BIN" ]]; then
    echo "vLLM venv not found at ${VENV}. Install with:"
    echo "  uv venv ${VENV} --python 3.12"
    echo "  uv pip install --python ${PYTHON_BIN} vllm --torch-backend=cu128"
    exit 1
fi

if [[ -f "$PID_FILE" ]] && kill -0 "$(cat "$PID_FILE")" 2>/dev/null; then
    echo "Already running (PID $(cat "$PID_FILE")). Stop it with: kill \$(cat $PID_FILE)"
    exit 0
fi

if ss -tln | awk '{print $4}' | grep -Eq "[:(]${PORT}$"; then
    echo "Port ${PORT} is already in use."
    exit 1
fi

export CUDA_VISIBLE_DEVICES="$GPU"
export HF_HOME
export HF_HUB_CACHE="${HF_HOME}/hub"
export HUGGINGFACE_HUB_CACHE="$HF_HUB_CACHE"
export TRANSFORMERS_CACHE="${HF_HOME}/hub"
export HF_HUB_OFFLINE="${HF_HUB_OFFLINE:-1}"
export TRANSFORMERS_OFFLINE="${TRANSFORMERS_OFFLINE:-1}"
export PYTHONUNBUFFERED=1
export VLLM_WORKER_MULTIPROC_METHOD="${VLLM_WORKER_MULTIPROC_METHOD:-spawn}"
# Keep compile caches off /home (only 26G free).
export VLLM_CACHE_ROOT="${VLLM_CACHE_ROOT:-/scratch/LLM/.cache/vllm}"
mkdir -p "$VLLM_CACHE_ROOT"
# torchcodec (VL video) pulls CUDA 13 NVRTC; text serving does not need it.
export VLLM_VIDEO_LOADER_BACKEND="${VLLM_VIDEO_LOADER_BACKEND:-opencv}"

ARGS=(
    serve "$MODEL"
    --host 0.0.0.0
    --port "$PORT"
    --tensor-parallel-size 1
    --max-model-len "$MAX_MODEL_LEN"
    --gpu-memory-utilization "$GPU_MEM_UTIL"
    --reasoning-parser qwen3
    --enable-auto-tool-choice
    --tool-call-parser qwen3_coder
    --mm-encoder-tp-mode data
    --default-chat-template-kwargs '{"enable_thinking": true, "preserve_thinking": true}'
)

if [[ "$ENABLE_MTP" == "1" ]]; then
    ARGS+=(--speculative-config '{"method":"mtp","num_speculative_tokens":3}')
fi

echo "Starting ${MODEL} on GPU ${GPU}, port ${PORT}, max_model_len=${MAX_MODEL_LEN}"
echo "Log: ${LOG_FILE}"

if [[ -x "$VLLM_BIN" ]]; then
    nohup "$VLLM_BIN" "${ARGS[@]}" >>"$LOG_FILE" 2>&1 &
else
    nohup "$PYTHON_BIN" -m vllm.entrypoints.cli.main "${ARGS[@]}" >>"$LOG_FILE" 2>&1 &
fi
echo $! >"$PID_FILE"
echo "PID=$(cat "$PID_FILE")"
echo "Health: curl -s http://127.0.0.1:${PORT}/v1/models"
echo "FAIRiAgent env: evaluation/config/model_configs/vllm_qwen3.8-27b.env"
