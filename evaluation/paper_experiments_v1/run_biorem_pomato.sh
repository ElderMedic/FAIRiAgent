#!/usr/bin/env bash
# Run biorem + pomato for all 5 Full pipeline models
set -eu
SD="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LD="$SD/runs/logs"
mkdir -p "$LD"
TS=$(date +%Y%m%d_%H%M%S)
LOG="$LD/biorem_pomato_${TS}.log"
_log() { echo "[$(date '+%H:%M:%S')] $*" >> "$LOG"; echo "[$(date '+%H:%M:%S')] $*"; }

MODELS=("qwen3.6-27b" "qwen3.6-35b" "gemma4-31b" "gpt-oss-20b" "deepseek-v4-pro")
DOCS=("biorem" "pomato")
FULL="$SD/run_full_pipeline.py"
TOTAL=$(( ${#MODELS[@]} * ${#DOCS[@]} ))
DONE=0

_log "Starting $TOTAL cells (biorem + pomato x5 models)"

for model in "${MODELS[@]}"; do
    for doc in "${DOCS[@]}"; do
        DONE=$((DONE + 1))
        _log "[$DONE/$TOTAL] Running $model / $doc"
        t0=$(date +%s)
        if mamba run -n FAIRiAgent python "$FULL" --doc "$doc" --model "$model" --repeats 1 >> "$LD/cell_${model}_${doc}.log" 2>&1; then
            dt=$(($(date +%s) - t0))
            _log "[$DONE/$TOTAL] OK   $model / $doc — ${dt}s"
        else
            dt=$(($(date +%s) - t0))
            _log "[$DONE/$TOTAL] FAIL $model / $doc — ${dt}s"
        fi
    done
done

_log "ALL DONE"
