#!/usr/bin/env bash
# ============================================================
# Batch Baseline Runner — Run ALL missing baseline cells
# ============================================================
# - DeepSeek B1/B2/B3 on 8 main docs (doesn't use local GPU)
# - Missing Ollama B1/B2/B3 cells (5 models × 10 docs each)
# - Skip-if-done: checks for eval_result.json before running
# - Serial execution: one at a time for safety
# ============================================================
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
LOG_DIR="$SCRIPT_DIR/runs/logs"
mkdir -p "$LOG_DIR"

TIMESTAMP=$(date +%Y%m%d_%H%M%S)
MAIN_LOG="$LOG_DIR/baselines_batch_${TIMESTAMP}.log"

log() {
    echo "[$(date '+%H:%M:%S')] $*" | tee -a "$MAIN_LOG"
}

run_cell() {
    local script="$1"
    local doc="$2"
    local model="$3"
    local label="$4"
    local output_dir="$SCRIPT_DIR/runs/${5}"

    local config_name
    config_name=$(python3 -c "
import sys; sys.path.insert(0, '$PROJECT_ROOT')
from pathlib import Path
env_files = {
    'qwen3.5-9b': 'ollama_qwen3.5-9b_v1.4.0.env',
    'qwen3.6-27b': 'ollama_qwen3.6-27b_v1.4.0.env',
    'qwen3.6-35b': 'ollama_qwen3.6-35b_v1.4.0.env',
    'gemma4-31b': 'ollama_gemma4-31b_v1.4.0.env',
    'gpt-oss-20b': 'ollama_gpt-oss-20b_v1.5.0.env',
    'deepseek-v4-pro': 'deepseek_v4-pro_v1.4.0.env',
}
env_name = env_files.get('$model', '')
print(Path(env_name).stem if env_name else '')
")

    local eval_file="$output_dir/$config_name/$doc/run_1/eval_result.json"

    if [ -f "$eval_file" ]; then
        local success
        success=$(python3 -c "import json; d=json.load(open('$eval_file')); print('OK' if d.get('success') else 'FAIL')" 2>/dev/null || echo "UNKNOWN")
        if [ "$success" = "OK" ]; then
            log "  SKIP [$label] $model / $doc — already OK"
            return 0
        else
            log "  RETRY [$label] $model / $doc — exists but success=$success, removing..."
            rm -rf "$(dirname "$eval_file")"
        fi
    fi

    log "  RUN  [$label] $model / $doc"
    local start_t=$(date +%s)

    if mamba run -n FAIRiAgent python "$script" \
        --doc "$doc" \
        --model "$model" \
        --repeats 1 \
        >> "$LOG_DIR/${label}_${model}_${doc}.log" 2>&1; then
        local elapsed=$(($(date +%s) - start_t))
        log "  OK   [$label] $model / $doc — ${elapsed}s"
    else
        local elapsed=$(($(date +%s) - start_t))
        log "  FAIL [$label] $model / $doc — ${elapsed}s (see $LOG_DIR/${label}_${model}_${doc}.log)"
    fi
}

# ============================================================
# Phase 1: DeepSeek baselines (API — no GPU needed)
# ============================================================
log "======== Phase 1: DeepSeek Baselines ========"

DEEPSEEK_MODEL="deepseek-v4-pro"
B1_SCRIPT="$SCRIPT_DIR/run_baseline_b1.py"
B2_SCRIPT="$SCRIPT_DIR/run_baseline_b2.py"
B3_SCRIPT="$SCRIPT_DIR/run_baseline_b3.py"

MAIN_DOCS=(
    "aetherobacter_fasciculatus_genome"
    "arabidopsis_vacuolar_srna"
    "biosensor"
    "earthworm"
    "human_gut_microbiome_temporal"
    "pea_cold_stress"
    "pseudomonas_recombinase_screen"
    "sea_cucumber_gut_metagenome"
)

for doc in "${MAIN_DOCS[@]}"; do
    run_cell "$B1_SCRIPT" "$doc" "$DEEPSEEK_MODEL" "DS-B1" "baseline_b1"
    run_cell "$B2_SCRIPT" "$doc" "$DEEPSEEK_MODEL" "DS-B2" "baseline_b2"
    run_cell "$B3_SCRIPT" "$doc" "$DEEPSEEK_MODEL" "DS-B3" "baseline_b3"
done

log "Phase 1 (DeepSeek) complete."

# ============================================================
# Phase 2: Missing Ollama baselines
# ============================================================
log "======== Phase 2: Ollama Baselines ========"

OLLAMA_MODELS=(
    "qwen3.5-9b"
    "qwen3.6-27b"
    "qwen3.6-35b"
    "gemma4-31b"
    "gpt-oss-20b"
)

ALL_DOCS=(
    "aetherobacter_fasciculatus_genome"
    "arabidopsis_vacuolar_srna"
    "biorem"
    "biosensor"
    "earthworm"
    "human_gut_microbiome_temporal"
    "pea_cold_stress"
    "pomato"
    "pseudomonas_recombinase_screen"
    "sea_cucumber_gut_metagenome"
)

for model in "${OLLAMA_MODELS[@]}"; do
    for doc in "${ALL_DOCS[@]}"; do
        run_cell "$B1_SCRIPT" "$doc" "$model" "OL-B1" "baseline_b1"
        run_cell "$B2_SCRIPT" "$doc" "$model" "OL-B2" "baseline_b2"
        run_cell "$B3_SCRIPT" "$doc" "$model" "OL-B3" "baseline_b3"
    done
done

log "======== ALL DONE ========"
log "Total runtime: $(date)"
