#!/usr/bin/env bash
# ============================================================
# Retry all 20 remaining failed/missing cells
# ============================================================
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LOG_DIR="$SCRIPT_DIR/runs/logs"
mkdir -p "$LOG_DIR"

TS=$(date +%Y%m%d_%H%M%S)
MAIN_LOG="$LOG_DIR/remaining_gaps_${TS}.log"

log() { echo "[$(date '+%H:%M:%S')] $*" | tee -a "$MAIN_LOG"; }

# ============================================================
# Phase A: gpt-oss baseline retries (5 cells, fast)
# ============================================================
log "====== Phase A: gpt-oss baseline retries ======"

GPT_BASELINE_FAILS=(
    "baseline_b2:aetherobacter_fasciculatus_genome"
    "baseline_b2:pea_cold_stress"
    "baseline_b2:pseudomonas_recombinase_screen"
    "baseline_b3:pea_cold_stress"
    "baseline_b3:sea_cucumber_gut_metagenome"
)

for item in "${GPT_BASELINE_FAILS[@]}"; do
    btype="${item%%:*}"
    doc="${item##*:}"
    eval_file="$SCRIPT_DIR/runs/$btype/ollama_gpt-oss-20b_v1.5.0/$doc/run_1/eval_result.json"

    # Remove failed run
    rm -rf "$(dirname "$eval_file")"

    script="$SCRIPT_DIR/run_${btype}.py"
    log "  RUN  gpt-oss $btype / $doc"
    start_t=$(date +%s)

    if mamba run -n FAIRiAgent python "$script" --doc "$doc" --model gpt-oss-20b --repeats 1 \
        >> "$LOG_DIR/gap_${btype}_gptoss_${doc}.log" 2>&1; then
        elapsed=$(($(date +%s) - start_t))
        log "  OK   gpt-oss $btype / $doc — ${elapsed}s"
    else
        elapsed=$(($(date +%s) - start_t))
        log "  FAIL gpt-oss $btype / $doc — ${elapsed}s"
    fi
done

log "Phase A complete."

# ============================================================
# Phase B: Full pipeline retries (5 cells)
# ============================================================
log "====== Phase B: Full pipeline retries ======"

FULL_FAILS=(
    "deepseek_v4-pro_v1.4.0:pea_cold_stress"
    "ollama_gemma4-31b_v1.4.0:arabidopsis_vacuolar_srna"
    "ollama_gemma4-31b_v1.4.0:biosensor"
    "ollama_gpt-oss-20b_v1.5.0:biosensor"
    "ollama_gpt-oss-20b_v1.5.0:pseudomonas_recombinase_screen"
)

FULL_SCRIPT="$SCRIPT_DIR/run_full_pipeline.py"

for item in "${FULL_FAILS[@]}"; do
    model_name="${item%%:*}"
    doc="${item##*:}"
    eval_file="$SCRIPT_DIR/runs/full_pipeline/$model_name/$doc/run_1/eval_result.json"

    rm -rf "$(dirname "$eval_file")"

    log "  RUN  Full $model_name / $doc"
    start_t=$(date +%s)

    # Map directory name to --model arg
    case "$model_name" in
        deepseek*) model_arg="deepseek-v4-pro" ;;
        ollama_gemma4*) model_arg="gemma4-31b" ;;
        ollama_gpt-oss*) model_arg="gpt-oss-20b" ;;
        ollama_qwen3.6-27b*) model_arg="qwen3.6-27b" ;;
        ollama_qwen3.6-35b*) model_arg="qwen3.6-35b" ;;
        *) model_arg="$model_name" ;;
    esac

    if mamba run -n FAIRiAgent python "$FULL_SCRIPT" --doc "$doc" --model "$model_arg" --repeats 1 \
        >> "$LOG_DIR/gap_full_${model_name}_${doc}.log" 2>&1; then
        elapsed=$(($(date +%s) - start_t))
        log "  OK   Full $model_name / $doc — ${elapsed}s"
    else
        elapsed=$(($(date +%s) - start_t))
        log "  FAIL Full $model_name / $doc — ${elapsed}s"
    fi
done

log "Phase B complete."

# ============================================================
# Phase C: Full pipeline missing docs (10 cells)
# ============================================================
log "====== Phase C: Full pipeline biorem + pomato ======"

FULL_MODELS=(
    "ollama_qwen3.6-27b_v1.4.0:qwen3.6-27b"
    "ollama_qwen3.6-35b_v1.4.0:qwen3.6-35b"
    "ollama_gemma4-31b_v1.4.0:gemma4-31b"
    "ollama_gpt-oss-20b_v1.5.0:gpt-oss-20b"
    "deepseek_v4-pro_v1.4.0:deepseek-v4-pro"
)

MISSING_DOCS=("biorem" "pomato")

for model_pair in "${FULL_MODELS[@]}"; do
    dir_name="${model_pair%%:*}"
    model_arg="${model_pair##*:}"

    for doc in "${MISSING_DOCS[@]}"; do
        eval_file="$SCRIPT_DIR/runs/full_pipeline/$dir_name/$doc/run_1/eval_result.json"

        if [ -f "$eval_file" ]; then
            s=$(jq -r '.success' "$eval_file" 2>/dev/null || echo "false")
            if [ "$s" = "true" ]; then
                log "  SKIP Full $dir_name / $doc — already OK"
                continue
            fi
            rm -rf "$(dirname "$eval_file")"
        fi

        log "  RUN  Full $dir_name / $doc"
        start_t=$(date +%s)

        if mamba run -n FAIRiAgent python "$FULL_SCRIPT" --doc "$doc" --model "$model_arg" --repeats 1 \
            >> "$LOG_DIR/gap_full_${dir_name}_${doc}.log" 2>&1; then
            elapsed=$(($(date +%s) - start_t))
            log "  OK   Full $dir_name / $doc — ${elapsed}s"
        else
            elapsed=$(($(date +%s) - start_t))
            log "  FAIL Full $dir_name / $doc — ${elapsed}s"
        fi
    done
done

log "Phase C complete."
log "====== ALL DONE ======"
