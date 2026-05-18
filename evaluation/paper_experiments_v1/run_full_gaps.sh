#!/usr/bin/env bash
set -eu
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LOG_DIR="$SCRIPT_DIR/runs/logs"
mkdir -p "$LOG_DIR"
TS=$(date +%Y%m%d_%H%M%S)
MAIN_LOG="$LOG_DIR/full_gaps_${TS}.log"
log() { echo "[$(date '+%H:%M:%S')] $*" >> "$MAIN_LOG"; echo "[$(date '+%H:%M:%S')] $*"; }

FULL_SCRIPT="$SCRIPT_DIR/run_full_pipeline.py"

# Phase 1: Retry original 5 failed Full cells
log "====== Phase 1: Full pipeline retries (5 cells) ======"

RETRIES=(
    "deepseek-v4-pro:pea_cold_stress"
    "gemma4-31b:arabidopsis_vacuolar_srna"
    "gemma4-31b:biosensor"
    "gpt-oss-20b:biosensor"
    "gpt-oss-20b:pseudomonas_recombinase_screen"
)

for item in "${RETRIES[@]}"; do
    model="${item%%:*}"
    doc="${item##*:}"
    log "  RUN  Full $model / $doc"
    start_t=$(date +%s)
    if mamba run -n FAIRiAgent python "$FULL_SCRIPT" --doc "$doc" --model "$model" --repeats 1 \
        >> "$LOG_DIR/fullgap_${model}_${doc}.log" 2>&1; then
        elapsed=$(($(date +%s) - start_t))
        log "  OK   Full $model / $doc — ${elapsed}s"
    else
        elapsed=$(($(date +%s) - start_t))
        log "  FAIL Full $model / $doc — ${elapsed}s"
    fi
done

log "Phase 1 complete."

# Phase 2: biorem + pomato for all 5 models
log "====== Phase 2: biorem + pomato (10 cells) ======"

MODELS=("qwen3.6-27b" "qwen3.6-35b" "gemma4-31b" "gpt-oss-20b" "deepseek-v4-pro")
DOCS=("biorem" "pomato")

for model in "${MODELS[@]}"; do
    for doc in "${DOCS[@]}"; do
        log "  RUN  Full $model / $doc"
        start_t=$(date +%s)
        if mamba run -n FAIRiAgent python "$FULL_SCRIPT" --doc "$doc" --model "$model" --repeats 1 \
            >> "$LOG_DIR/fullgap_${model}_${doc}.log" 2>&1; then
            elapsed=$(($(date +%s) - start_t))
            log "  OK   Full $model / $doc — ${elapsed}s"
        else
            elapsed=$(($(date +%s) - start_t))
            log "  FAIL Full $model / $doc — ${elapsed}s"
        fi
    done
done

log "Phase 2 complete."
log "====== ALL DONE ======"
