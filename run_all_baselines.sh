#!/bin/bash
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
export PYTHONPATH="$SCRIPT_DIR"
DOCS="arabidopsis_vacuolar_srna pea_cold_stress sea_cucumber_gut_metagenome human_gut_microbiome_temporal aetherobacter_fasciculatus_genome pseudomonas_recombinase_screen biosensor earthworm"

for doc in $DOCS; do
  for b in b1 b2 b3; do
    echo "python $SCRIPT_DIR/evaluation/paper_experiments_v1/run_baseline_${b}.py --doc $doc --model deepseek-v4-pro --repeats 1"
  done
done | xargs -I CMD -P 4 bash -c "CMD"
