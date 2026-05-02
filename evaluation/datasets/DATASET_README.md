# Ground Truth Dataset

## Summary

**Tracked multi-document ground truth**: `evaluation/datasets/annotated/ground_truth_filtered.json` — 4 documents (`earthworm`, `biosensor`, `pomato`, `biorem`).

## Papers Included

### 1. 📄 Earthworm
- **File**: `raw/earthworm/.../earthworm_4n_paper_bioRxiv.md`
- **Metadata**: `raw/earthworm/Diagonal_RNAseq_Earthworms.xlsx`
- **Fields**: 46 total

### 2. 📄 Biosensor
- **File**: `raw/biosensor/.../aec8570_CombinedPDF_v1.md`
- **Metadata**: `raw/biosensor/Whole-cell_biosensor_metadata.xlsx`
- **Fields**: 43 total

### 3. 📄 Pomato
- **Input**: Markdown under `raw/pomato/`
- **Fields**: 31 total

### 4. 📄 Biorem
- **Input**: `raw/biorem/BIOREM_study_narrative.md`
- **Metadata**: `raw/biorem/BIOREM_Metadata.xlsx`
- **Fields**: 57 total
- **Source**: Expert bioremediation template

## Next Steps for Evaluation

Run batch evaluation on all documents:
```bash
python3 evaluation/scripts/run_batch_evaluation.py \
  --env-file evaluation/config/env.evaluation \
  --model-configs evaluation/config/model_configs/*.env \
  --ground-truth evaluation/datasets/annotated/ground_truth_filtered.json \
  --output-dir evaluation/runs/run_all
```

### 5. 🧪 CompBioBench
- **Input**: Various bioinformatics files (BAM, FASTQ, H5AD, etc.)
- **Tasks**: 29 metadata recovery and reasoning tasks
- **Format**: Aligned to standard document/field structure
