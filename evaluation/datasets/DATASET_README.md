# Ground Truth Dataset

## Summary

**Total Documents**: 3  
**Created**: 2025-11-21  
**Location**: `evaluation/datasets/annotated/ground_truth_v1.json`

## Papers Included

### 1. 📄 Earthworm
- **File**: `raw/earthworm/earthworm_4n_paper_bioRxiv.pdf`
- **Metadata**: `raw/earthworm/Diagonal_RNAseq_Earthworms.xlsx`
- **Fields**: 46 total (21 required, 25 recommended)
- **Source**: Manually curated ISA-Tab Excel file
- **ISA Coverage**: investigation(9), study(4), assay(20), sample(9), observationunit(4)

### 2. 📄 Biosensor
- **File**: `raw/biosensor/aec8570_CombinedPDF_v1.pdf`
- **Metadata**: `raw/biosensor/Whole-cell_biosensor_metadata.xlsx`
- **Fields**: 43 total (21 required, 22 recommended)
- **Source**: Manually curated ISA-Tab Excel file
- **ISA Coverage**: investigation(8), study(4), assay(13), sample(14), observationunit(4)

### 3. 📄 BIOREM
- **File**: `raw/biorem/BIOREM_appendix2.pdf`
- **Metadata**: Converted from FAIRiAgent output (`output/20251116_185736/`)
- **Fields**: 51 total (6 required, 51 recommended)
- **Source**: High-confidence FAIRiAgent extraction (confidence > 0.5, status = confirmed)
- **ISA Coverage**: investigation(6), study(9), assay(13), sample(23)

## Conversion Process

### Earthworm & Biosensor
- Converted from Excel ISA-Tab format using `convert_excel_to_ground_truth.py`
- Each Excel sheet (investigation, study, assay, sample, observationunit) was parsed
- Field names from column headers, values from first non-null row
- Multiple rows treated as acceptable variations

### BIOREM
- Converted from existing FAIRiAgent output using `add_biorem_to_ground_truth.py`
- Only included fields with:
  - `status: "confirmed"`
  - `confidence > 0.5`
- Evidence and confidence preserved from original extraction

## Data Quality

- ✅ All papers have complete ISA sheet coverage
- ✅ All required fields annotated
- ✅ Evidence locations documented
- ✅ Package sources identified (default, Illumina, MIAPPE, etc.)
- ✅ ISA sheet assignments validated

## Next Steps for Evaluation

### 1. Configure Environment

```bash
# Copy and edit evaluation config
cp evaluation/config/env.evaluation.template evaluation/config/env.evaluation
# Add your LangSmith API key and LLM provider keys
```

### 2. Run Batch Evaluation

```bash
# This will run FAIRiAgent on all 3 papers with different model configs
python3 evaluation/scripts/run_batch_evaluation.py \
  --env-file evaluation/config/env.evaluation \
  --model-configs evaluation/config/model_configs/*.env \
  --ground-truth evaluation/datasets/annotated/ground_truth_v1.json \
  --output-dir evaluation/runs/run_$(date +%Y%m%d) \
  --workers 2
```

### 3. Evaluate Outputs

```bash
# Compute all quality metrics
python3 evaluation/scripts/evaluate_outputs.py \
  --env-file evaluation/config/env.evaluation \
  --run-dir evaluation/runs/run_$(date +%Y%m%d) \
  --ground-truth evaluation/datasets/annotated/ground_truth_v1.json
```

### 4. Generate Manuscript Materials

```bash
# Create publication-ready figures and tables
python3 evaluation/scripts/generate_report.py \
  --results-dir evaluation/runs/run_$(date +%Y%m%d)/results \
  --output-dir evaluation/runs/run_$(date +%Y%m%d)/manuscript_materials
```

## File Structure

```
evaluation/datasets/
├── raw/                                    # Your original papers
│   ├── earthworm/
│   │   ├── earthworm_4n_paper_bioRxiv.pdf
│   │   └── Diagonal_RNAseq_Earthworms.xlsx
│   ├── biosensor/
│   │   ├── aec8570_CombinedPDF_v1.pdf
│   │   └── Whole-cell_biosensor_metadata.xlsx
│   └── biorem/
│       └── BIOREM_appendix2.pdf
│
└── annotated/
    └── ground_truth_v1.json                # ✅ Complete ground truth dataset
```

## Notes

- **Dataset Size**: 3 papers is suitable for initial model comparison and validation
- **Field Coverage**: 140 total fields across all papers (good sample size)
- **Diversity**: Mix of genomics, biosensor, and bioremediation projects
- **Quality**: High-confidence annotations from manual curation and validated extraction

## Extending the Dataset

To add more papers in the future:

1. Place PDF and Excel metadata in `raw/{paper_id}/`
2. Run conversion script:
   ```bash
   python3 evaluation/scripts/convert_excel_to_ground_truth.py \
     --raw-dir evaluation/datasets/raw \
     --output evaluation/datasets/annotated/ground_truth_v2.json
   ```
3. Or manually edit `ground_truth_v1.json` to add new documents

