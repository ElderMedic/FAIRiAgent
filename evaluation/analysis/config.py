"""
Analysis configuration.

Defines configuration for evaluation analysis including model mappings,
document normalization, and exclusion lists.
"""

from typing import Dict, List, Optional
from pathlib import Path
import json


# ============================================================================
# Exclusion Lists
# ============================================================================

# Models to EXCLUDE from analysis (e.g., known issues, deprecated)
EXCLUDED_MODELS: List[str] = [
    'opus',
    'anthropic_opus'
]

# Documents to EXCLUDE from analysis (e.g., known conversion issues)
EXCLUDED_DOCUMENTS: List[str] = [
    'biorem'  # Consistently fails due to MinerU conversion issues
]

# Directories to EXCLUDE from discovery (e.g., archives, backups, reruns)
# Rerun directories are excluded because they contain duplicate data that was merged into original runs
EXCLUDED_DIRECTORIES: List[str] = [
    'archive',
    'output_test1',  # Backup directories
]


# ============================================================================
# Model Configuration
# ============================================================================

# Model name normalization: maps variant names to canonical names
# Used to merge runs from same model (e.g., reruns)
MODEL_MERGE_MAP: Dict[str, str] = {
    'openai_gpt5': 'gpt5',
    'openai_o3': 'o3',
    'anthropic_sonnet': 'sonnet',
    'anthropic_haiku': 'haiku',
}

# Model display names for visualizations
MODEL_DISPLAY_NAMES: Dict[str, str] = {
    'gpt4.1': 'GPT-4.1',
    'gpt5': 'GPT-5',
    'o3': 'O3',
    'sonnet': 'Claude Sonnet 4.5',
    'haiku': 'Claude Haiku 4.5',
    'qwen_max': 'Qwen Max',
    'qwen_plus': 'Qwen Plus',
    'qwen_flash': 'Qwen Flash',
    'baseline_openai_gpt4o': 'Baseline (GPT-4o)',
}

# Model family colors for visualizations
MODEL_COLORS: Dict[str, str] = {
    # OpenAI family - Green shades
    'gpt4.1': '#2ecc71',
    'gpt5': '#27ae60',
    'openai_gpt5': '#1abc9c',
    'o3': '#16a085',
    'openai_o3': '#1dd1a1',
    # Anthropic family - Orange/Red shades
    'sonnet': '#e74c3c',
    'anthropic_sonnet': '#c0392b',
    'haiku': '#e67e22',
    'anthropic_haiku': '#d35400',
    # Qwen family - Blue/Purple shades
    'qwen_max': '#3498db',
    'qwen_plus': '#9b59b6',
    'qwen_flash': '#8e44ad',
    # Baseline - Gray
    'baseline_openai_gpt4o': '#95a5a6',
    'Baseline (GPT-4o)': '#95a5a6',
}


# ============================================================================
# Document Configuration
# ============================================================================

# Document ID normalization: maps alternative IDs to canonical IDs
# Used when baseline and agentic use different document IDs
DOC_ID_MAP: Dict[str, str] = {
    'aec8570': 'biosensor',  # Baseline uses different ID
}


# ============================================================================
# Workflow Configuration
# ============================================================================

# Actual agents in the workflow
# (no Validator - that doesn't exist in our implementation)
ACTUAL_AGENTS: List[str] = [
    'DocumentParser',
    'KnowledgeRetriever',
    'JSONGenerator'
]

# Field categories for analysis
FIELD_CATEGORIES: List[str] = [
    'investigation',
    'study',
    'assay',
    'sample',
    'observationunit'
]

# Quality metric mapping
# Map from workflow_report.json keys to analysis keys
QUALITY_METRICS_MAPPING: Dict[str, str] = {
    'overall_confidence': 'overall_confidence',
    'critic_confidence': 'llm_judge_score',  # This IS our LLM judge score
    'structural_confidence': 'structural_confidence',
    'validation_confidence': 'validation_confidence'  # This is JSON validation, not schema
}

# Note: We don't have schema compliance checking yet
# validation_confidence refers to JSON structure validation, not schema compliance


# ============================================================================
# Helper Functions
# ============================================================================

def normalize_model_name(model_name: str) -> str:
    """
    Normalize model name to canonical form.
    
    Args:
        model_name: Raw model name from run directory
        
    Returns:
        Canonical model name (merged variants)
    """
    return MODEL_MERGE_MAP.get(model_name, model_name)


def get_model_display_name(model_name: str) -> str:
    """
    Get display name for a model.
    
    Args:
        model_name: Canonical model name
        
    Returns:
        Human-readable display name
    """
    return MODEL_DISPLAY_NAMES.get(model_name, model_name)


def get_model_color(model_name: str) -> str:
    """
    Get color for a model in visualizations.
    
    Args:
        model_name: Canonical model name
        
    Returns:
        Hex color code
    """
    return MODEL_COLORS.get(model_name, '#7f8c8d')  # Default gray


def normalize_document_id(doc_id: str) -> str:
    """
    Normalize document ID to canonical form.
    
    Args:
        doc_id: Raw document ID
        
    Returns:
        Canonical document ID
    """
    return DOC_ID_MAP.get(doc_id, doc_id)


def is_baseline_run(run_dir: Path) -> bool:
    """
    Check if a run directory is a baseline run.
    
    Args:
        run_dir: Path to run directory
        
    Returns:
        True if baseline run, False otherwise
    """
    return run_dir.name.startswith('baseline_')


def discover_models(runs_dir: Path) -> List[str]:
    """
    Automatically discover all models from runs directory.
    
    Args:
        runs_dir: Path to evaluation/runs directory
        
    Returns:
        List of discovered model names (normalized)
    """
    models = set()
    runs_dir = Path(runs_dir)
    
    for run_dir in runs_dir.iterdir():
        if not run_dir.is_dir():
            continue
        if run_dir.name in EXCLUDED_DIRECTORIES:
            continue
        if is_baseline_run(run_dir):
            continue
        
        # Look for model directories
        for model_dir in run_dir.iterdir():
            if not model_dir.is_dir():
                continue
            model_name = normalize_model_name(model_dir.name)
            if model_name not in EXCLUDED_MODELS:
                models.add(model_name)
    
    return sorted(models)


def discover_documents(runs_dir: Path) -> List[str]:
    """
    Automatically discover all documents from runs directory.
    
    Args:
        runs_dir: Path to evaluation/runs directory
        
    Returns:
        List of discovered document IDs (normalized)
    """
    documents = set()
    runs_dir = Path(runs_dir)
    
    for eval_file in runs_dir.rglob("eval_result.json"):
        try:
            with open(eval_file, 'r') as f:
                data = json.load(f)
            doc_id = data.get('document_id', 'unknown')
            doc_id = normalize_document_id(doc_id)
            if doc_id not in EXCLUDED_DOCUMENTS:
                documents.add(doc_id)
        except Exception:
            continue
    
    return sorted(documents)
