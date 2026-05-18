#!/bin/bash
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"
export PYTHONPATH="$SCRIPT_DIR"
DOC_PATH="evaluation/datasets/raw/aetherobacter_fasciculatus_genome/study_narrative.md"
ENV_FILE="evaluation/config/model_configs/deepseek_v4-pro_v1.4.0.env"
OUT_BASE="evaluation/ablation_quick_run"
mkdir -p $OUT_BASE

echo "Running Full System..."
FAIRIFIER_DISABLE_CRITIC=0 FAIRIFIER_DISABLE_CROSS_LAYER_ROLLBACK=0 python -m fairifier.cli process $DOC_PATH --output-dir $OUT_BASE/full_system --env-file $ENV_FILE --project-id ablation_full > $OUT_BASE/full.log 2>&1
echo "Full System Done."

echo "Running No Critic..."
FAIRIFIER_DISABLE_CRITIC=1 FAIRIFIER_DISABLE_CROSS_LAYER_ROLLBACK=0 python -m fairifier.cli process $DOC_PATH --output-dir $OUT_BASE/no_critic --env-file $ENV_FILE --project-id ablation_nocritic > $OUT_BASE/no_critic.log 2>&1
echo "No Critic Done."

echo "Running No Rollback..."
FAIRIFIER_DISABLE_CRITIC=0 FAIRIFIER_DISABLE_CROSS_LAYER_ROLLBACK=1 python -m fairifier.cli process $DOC_PATH --output-dir $OUT_BASE/no_rollback --env-file $ENV_FILE --project-id ablation_norollback > $OUT_BASE/no_rollback.log 2>&1
echo "No Rollback Done."
