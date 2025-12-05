# Evaluation Analysis Framework

Comprehensive, reusable analysis framework for FAIRiAgent evaluation results.

## Architecture

The analysis framework is designed to be:
- **Generic**: Automatically discovers models and documents
- **Extensible**: Easy to add new metrics and visualizations
- **Maintainable**: Clear separation of concerns

### Directory Structure

```
evaluation/analysis/
├── __init__.py
├── config.py                    # Configuration (exclusions, mappings)
├── baseline_comparison.py        # Baseline data loading and processing
├── run_analysis.py              # Main entry point
├── data_loaders/
│   └── evaluation_loader.py    # Discovers and loads evaluation results
├── analyzers/
│   ├── model_performance.py     # Model performance metrics
│   ├── workflow_reliability.py  # Workflow reliability analysis
│   └── failure_patterns.py      # Failure pattern analysis
├── visualizations/
│   ├── model_comparison.py      # Model comparison charts
│   ├── workflow_reliability.py  # Reliability visualizations
│   ├── failure_analysis.py      # Failure analysis charts
│   └── baseline_comparison.py   # Baseline vs agentic comparisons
└── reports/
    └── report_generator.py      # Orchestrates all analysis
```

## Usage

### Basic Usage

```bash
# Run full analysis
python evaluation/analysis/run_analysis.py

# Custom output directory
python evaluation/analysis/run_analysis.py --output-dir results/

# Filter specific runs
python evaluation/analysis/run_analysis.py --pattern "qwen_*"
```

### Configuration

Edit `evaluation/analysis/config.py` to:
- Exclude specific models or documents
- Map model name variants to canonical names
- Configure display names and colors
- Normalize document IDs

### Adding New Models

The framework automatically discovers new models. Just:
1. Add new runs to `evaluation/runs/`
2. Run analysis - new models will be included automatically
3. Optionally add display name/color in `config.py`

### Adding New Documents

Similarly, new documents are auto-discovered:
1. Add new document runs
2. Run analysis - new documents will be included
3. Optionally normalize document IDs in `config.py` if needed

## Output Structure

```
evaluation/analysis/output/
├── figures/          # All visualization PNG files
├── tables/           # CSV and LaTeX tables
├── data/             # Processed data (CSV)
└── analysis_summary.json  # Summary statistics
```

## Key Features

### Automatic Discovery
- Discovers all models from run directories
- Discovers all documents from evaluation results
- Merges runs from same model (handles reruns automatically)

### Baseline Comparison
- Automatically detects baseline runs (directories starting with `baseline_`)
- Compares baseline vs agentic workflows
- Generates per-document and overall comparisons

### Model Name Normalization
- Merges variant names (e.g., `gpt5` + `openai_gpt5` → `GPT-5`)
- Configurable via `MODEL_MERGE_MAP` in `config.py`

### Document ID Normalization
- Handles different document IDs between baseline and agentic
- Configurable via `DOC_ID_MAP` in `config.py`

## Extending the Framework

### Adding New Metrics

1. Add metric calculation to appropriate analyzer in `analyzers/`
2. Update `ReportGenerator` to include new metric
3. Add visualization if needed in `visualizations/`

### Adding New Visualizations

1. Create new visualization class in `visualizations/`
2. Add to `ReportGenerator._generate_*_visualizations()`
3. Export from `visualizations/__init__.py`

## Configuration Reference

### Exclusion Lists

```python
EXCLUDED_MODELS = ['opus', 'anthropic_opus']  # Models to skip
EXCLUDED_DOCUMENTS = ['biorem']  # Documents to skip
EXCLUDED_DIRECTORIES = ['archive']  # Directories to skip
```

### Model Configuration

```python
MODEL_MERGE_MAP = {
    'openai_gpt5': 'gpt5',  # Merge variants
    'anthropic_sonnet': 'sonnet',
}

MODEL_DISPLAY_NAMES = {
    'gpt5': 'GPT-5',  # Human-readable names
}

MODEL_COLORS = {
    'gpt5': '#27ae60',  # Visualization colors
}
```

### Document Configuration

```python
DOC_ID_MAP = {
    'aec8570': 'biosensor',  # Normalize document IDs
}
```

## Notes

- The framework automatically handles reruns by merging data from same model
- Baseline runs are detected by directory name prefix (`baseline_*`)
- All exclusions and mappings are configurable in `config.py`
- The framework is designed to work with any number of models/documents
