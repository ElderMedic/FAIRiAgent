# FAIRiAgent Evaluation Analysis Framework

Comprehensive data analysis and visualization framework for evaluation results. Designed to easily incorporate new evaluation runs.

## Directory Structure

```
evaluation/analysis/
├── data_loaders/          # Data loading and aggregation
│   ├── __init__.py
│   └── evaluation_loader.py
├── analyzers/             # Data analysis modules
│   ├── __init__.py
│   ├── model_performance.py
│   ├── workflow_reliability.py
│   └── failure_patterns.py
├── visualizations/        # Visualization generators
│   ├── __init__.py
│   ├── model_comparison.py
│   ├── workflow_reliability.py
│   └── failure_analysis.py
├── reports/               # Report generation
│   ├── __init__.py
│   └── report_generator.py
├── run_analysis.py        # Main analysis script
├── README.md              # This file
└── output/                # Generated outputs (created automatically)
    ├── figures/           # Publication-ready figures (PNG + PDF)
    ├── tables/             # LaTeX and CSV tables
    └── data/               # Processed data (CSV)
```

## Quick Start

### Run Complete Analysis

```bash
# Analyze all evaluation runs
python evaluation/analysis/run_analysis.py

# Analyze specific runs (e.g., only Qwen models)
python evaluation/analysis/run_analysis.py --pattern "qwen_*"

# Custom output directory
python evaluation/analysis/run_analysis.py --output-dir evaluation/analysis/my_report
```

### Output Files

After running analysis, you'll find:

**Figures** (`output/figures/`):
- `model_comparison_heatmap.pdf` - Model performance across metrics
- `model_rankings.pdf` - Model rankings by aggregate score
- `model_rankings_completeness.pdf` - Rankings by completeness
- `model_rankings_correctness.pdf` - Rankings by correctness
- `metric_correlation.pdf` - Correlation matrix between metrics
- `document_performance.pdf` - Performance breakdown by document
- `retry_rates.pdf` - Workflow retry rates by model
- `agent_retry_patterns.pdf` - Retry patterns by agent
- `completion_rates.pdf` - Workflow completion rates
- `failure_by_agent.pdf` - Failure counts by agent
- `failure_by_document.pdf` - Failure rates by document
- `failure_by_model.pdf` - Failure patterns by model

**Tables** (`output/tables/`):
- `model_rankings.csv/.tex` - Model performance rankings
- `reliability_summary.csv/.tex` - Workflow reliability summary
- `agent_reliability.csv/.tex` - Agent-level reliability metrics
- `failure_by_agent.csv/.tex` - Failure statistics by agent

**Data** (`output/data/`):
- `model_performance.csv` - Model-level performance data
- `document_performance.csv` - Document-level performance data
- `workflow_reliability.csv` - Workflow reliability data

**Summary** (`output/`):
- `analysis_summary.json` - Complete analysis summary

## Adding New Runs

The framework automatically discovers all `evaluation_results.json` files in the `evaluation/runs/` directory. To add new runs:

1. **Run evaluation** on new models/documents
2. **Re-run analysis** - the framework will automatically include new results:

```bash
python evaluation/analysis/run_analysis.py
```

No manual configuration needed - all runs are automatically discovered and included!

## Custom Analysis

### Using Individual Components

```python
from pathlib import Path
from evaluation.analysis import (
    EvaluationDataLoader,
    ModelPerformanceAnalyzer,
    ModelComparisonVisualizer
)

# Load data
loader = EvaluationDataLoader(Path('evaluation/runs'))
loader.load_all()

# Get dataframes
model_df = loader.get_model_dataframe()
doc_df = loader.get_document_level_dataframe()

# Analyze
analyzer = ModelPerformanceAnalyzer(model_df)
rankings = analyzer.get_model_rankings()
correlations = analyzer.get_metric_correlations()

# Visualize
viz = ModelComparisonVisualizer(Path('output/figures'))
viz.plot_model_comparison_heatmap(model_df)
```

## Analysis Features

### 1. Model Performance Analysis
- Model rankings across multiple metrics
- Statistical comparisons between models
- Metric correlations
- Document-level performance breakdown

### 2. Workflow Reliability Analysis
- Completion rates by model
- Retry patterns and frequencies
- Agent-level reliability metrics
- Human review requirements

### 3. Failure Pattern Analysis
- Failure counts by agent
- Failure rates by document
- Failure patterns by model
- Error type distribution

## Publication-Ready Outputs

All figures are generated in both PNG (for quick viewing) and PDF (for publication) formats:
- High resolution (300 DPI)
- Publication-quality styling
- Clear labels and legends
- Consistent color schemes

All tables are generated in both CSV (for data analysis) and LaTeX (for manuscript inclusion) formats.

## Dependencies

```bash
pip install pandas matplotlib seaborn scipy numpy
```

(Already included in FAIRiAgent environment)








