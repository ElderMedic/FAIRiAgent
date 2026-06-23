#!/usr/bin/env bash
# =============================================================================
# Phase-0 Broad N=1 Runner — FAIRiAgent paper experiments
# =============================================================================
# Runs every (condition × model × doc) cell of the Phase-0 matrix ONCE,
# STRICTLY ONE RUN AT A TIME (no background jobs / no parallelism).
#
# Total target: 8 docs × 5 models × 4 conditions = 160 runs
#
# Cells that already contain a metadata.json are silently skipped.
#
# Usage:
#   cd /home/WUR/ke003/Projects/FAIRiAgent
#   bash evaluation/paper_experiments_v1/phase0_broad_n1.sh [OPTIONS]
#
# Options:
#   --dry-run        Print what would run without executing anything
#   --condition C    Run only condition(s): full | b1 | b2 | b3 (repeatable)
#   --model M        Run only model key(s): qwen3.5-9b | qwen3.6-27b | … (repeatable)
#   --doc D          Run only document(s) (repeatable)
#   --help           Show this message
#
# Examples:
#   # Full dry-run to see the plan:
#   bash phase0_broad_n1.sh --dry-run
#
#   # Run only B1 baseline for all models and docs:
#   bash phase0_broad_n1.sh --condition b1
#
#   # Run all conditions but only for qwen3.6-27b:
#   bash phase0_broad_n1.sh --model qwen3.6-27b
#
#   # Resume an interrupted run (already-done cells are skipped automatically):
#   bash phase0_broad_n1.sh
# =============================================================================

set -euo pipefail

# ---------------------------------------------------------------------------
# Locate project root (two levels up from this script)
# ---------------------------------------------------------------------------
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
PAPER_ROOT="$PROJECT_ROOT/evaluation/paper_experiments_v1"

# ---------------------------------------------------------------------------
# Experiment matrix
# ---------------------------------------------------------------------------
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

# Models: key → config-stem (used to build the run-directory path)
declare -A MODEL_CFG_STEM=(
    ["qwen3.5-9b"]="ollama_qwen3.5-9b_v1.4.0"
    ["qwen3.6-27b"]="ollama_qwen3.6-27b_v1.4.0"
    ["qwen3.6-35b"]="ollama_qwen3.6-35b_v1.4.0"
    ["gemma4-31b"]="ollama_gemma4-31b_v1.4.0"
    ["gpt-oss-20b"]="ollama_gpt-oss-20b_v1.5.0"
)
MODEL_KEYS=("qwen3.5-9b" "qwen3.6-27b" "qwen3.6-35b" "gemma4-31b" "gpt-oss-20b")

# Condition → sub-directory name used in runs/
declare -A COND_DIR=(
    ["full"]="full_pipeline"
    ["b1"]="baseline_b1"
    ["b2"]="baseline_b2"
    ["b3"]="baseline_b3"
)
CONDITIONS=("full" "b1" "b2" "b3")

# ---------------------------------------------------------------------------
# Defaults
# ---------------------------------------------------------------------------
DRY_RUN=false
LOG_FILE="$PAPER_ROOT/logs/phase0_run_$(date +%Y%m%d_%H%M%S).log"
PYTHON="mamba run -n FAIRiAgent python3"

# Filters (empty = run all)
FILTER_CONDITIONS=()
FILTER_MODELS=()
FILTER_DOCS=()

# ---------------------------------------------------------------------------
# Parse arguments
# ---------------------------------------------------------------------------
while [[ $# -gt 0 ]]; do
    case "$1" in
        --dry-run)    DRY_RUN=true; shift ;;
        --condition)  FILTER_CONDITIONS+=("$2"); shift 2 ;;
        --model)      FILTER_MODELS+=("$2"); shift 2 ;;
        --doc)        FILTER_DOCS+=("$2"); shift 2 ;;
        --help|-h)
            sed -n '2,40p' "${BASH_SOURCE[0]}" | sed 's/^# \?//'
            exit 0
            ;;
        *)  echo "Unknown option: $1" >&2; exit 1 ;;
    esac
done

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
contains() {
    local needle="$1"; shift
    local item
    for item in "$@"; do [[ "$item" == "$needle" ]] && return 0; done
    return 1
}

should_run_condition() { [[ ${#FILTER_CONDITIONS[@]} -eq 0 ]] || contains "$1" "${FILTER_CONDITIONS[@]}"; }
should_run_model()     { [[ ${#FILTER_MODELS[@]}     -eq 0 ]] || contains "$1" "${FILTER_MODELS[@]}"; }
should_run_doc()       { [[ ${#FILTER_DOCS[@]}       -eq 0 ]] || contains "$1" "${FILTER_DOCS[@]}"; }

log() { echo "$*" | tee -a "$LOG_FILE"; }

# ---------------------------------------------------------------------------
# Setup
# ---------------------------------------------------------------------------
mkdir -p "$PAPER_ROOT/logs"
$DRY_RUN || touch "$LOG_FILE"

log "============================================================"
log "Phase-0 Broad N=1 Runner  $(date)"
log "Project root : $PROJECT_ROOT"
log "Dry-run      : $DRY_RUN"
log "============================================================"

TOTAL=0; SKIPPED=0; DONE_OK=0; DONE_FAIL=0

# ---------------------------------------------------------------------------
# Main loop — strictly serial
# ---------------------------------------------------------------------------
for COND in "${CONDITIONS[@]}"; do
    should_run_condition "$COND" || continue
    COND_SUBDIR="${COND_DIR[$COND]}"

    for MODEL in "${MODEL_KEYS[@]}"; do
        should_run_model "$MODEL" || continue
        CFG_STEM="${MODEL_CFG_STEM[$MODEL]}"

        for DOC in "${MAIN_DOCS[@]}"; do
            should_run_doc "$DOC" || continue

            TOTAL=$((TOTAL + 1))
            RUN_DIR="$PAPER_ROOT/runs/$COND_SUBDIR/$CFG_STEM/$DOC/run_1"
            META="$RUN_DIR/metadata.json"

            # --- Skip if already completed ---
            if [[ -f "$META" ]]; then
                SKIPPED=$((SKIPPED + 1))
                log "SKIP  [$COND|$MODEL|$DOC] — metadata.json exists"
                continue
            fi

            log ""
            log "RUN   [$COND|$MODEL|$DOC]  →  $RUN_DIR"

            if $DRY_RUN; then
                log "  (dry-run, not executing)"
                continue
            fi

            # --- Build the command for this condition ---
            case "$COND" in
                full)
                    CMD=(
                        $PYTHON
                        "$PAPER_ROOT/run_full_pipeline.py"
                        --doc "$DOC"
                        --model "$MODEL"
                        --output-dir "$PAPER_ROOT/runs/full_pipeline"
                        --repeats 1
                    )
                    ;;
                b1)
                    CMD=(
                        $PYTHON
                        "$PAPER_ROOT/run_baseline_b1.py"
                        --doc "$DOC"
                        --model "$MODEL"
                        --repeats 1
                    )
                    ;;
                b2)
                    CMD=(
                        $PYTHON
                        "$PAPER_ROOT/run_baseline_b2.py"
                        --doc "$DOC"
                        --model "$MODEL"
                        --repeats 1
                    )
                    ;;
                b3)
                    CMD=(
                        $PYTHON
                        "$PAPER_ROOT/run_baseline_b3.py"
                        --doc "$DOC"
                        --model "$MODEL"
                        --repeats 1
                    )
                    ;;
            esac

            log "  CMD: ${CMD[*]}"
            START_TS=$(date +%s)

            # Run, capturing stdout+stderr; exit code is captured separately
            set +e
            "${CMD[@]}" 2>&1 | tee -a "$LOG_FILE"
            RC=${PIPESTATUS[0]}
            set -e

            END_TS=$(date +%s)
            ELAPSED=$((END_TS - START_TS))

            if [[ -f "$META" ]]; then
                DONE_OK=$((DONE_OK + 1))
                log "  OK  [$COND|$MODEL|$DOC]  rc=$RC  elapsed=${ELAPSED}s"
            else
                DONE_FAIL=$((DONE_FAIL + 1))
                log "  FAIL[$COND|$MODEL|$DOC]  rc=$RC  elapsed=${ELAPSED}s  (no metadata.json)"
            fi

        done  # doc
    done  # model
done  # condition

# ---------------------------------------------------------------------------
# Summary
# ---------------------------------------------------------------------------
log ""
log "============================================================"
log "Phase-0 summary  $(date)"
log "  Total cells in matrix : $TOTAL"
log "  Skipped (already done): $SKIPPED"
log "  Completed OK          : $DONE_OK"
log "  Failed                : $DONE_FAIL"
log "  Remaining             : $(( TOTAL - SKIPPED - DONE_OK - DONE_FAIL ))"
log "============================================================"

if [[ $DONE_FAIL -gt 0 ]]; then
    log "WARNING: $DONE_FAIL cells failed. Re-run the script to retry them."
    exit 1
fi
