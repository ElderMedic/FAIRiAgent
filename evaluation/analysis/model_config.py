"""
Model Configuration and Metadata

Centralized configuration for model classification, colors, and display names.
Distinguishes between API (closed-source) and local (open-source via Ollama) models.
"""

from typing import Dict, Any


# Model metadata: family, type, colors, display names
MODEL_METADATA: Dict[str, Dict[str, Any]] = {
    # ============================================================================
    # OpenAI (API - Closed Source)
    # ============================================================================
    'openai_gpt4.1': {
        'family': 'OpenAI',
        'display_name': 'GPT-4.1',
        'type': 'api',
        'license': 'Proprietary',
        'color': '#27ae60',
        'marker': 'o',  # circle
        'order': 1
    },
    'openai_o3': {
        'family': 'OpenAI',
        'display_name': 'O3',
        'type': 'api',
        'license': 'Proprietary',
        'color': '#16a085',
        'marker': 'o',
        'order': 2
    },
    'gpt-5.1': {
        'family': 'OpenAI',
        'display_name': 'GPT-5.1',
        'type': 'api',
        'license': 'Proprietary',
        'color': '#2ecc71',
        'marker': 'o',
        'order': 3
    },
    
    # ============================================================================
    # Anthropic (API - Closed Source)
    # ============================================================================
    'anthropic_sonnet': {
        'family': 'Anthropic',
        'display_name': 'Claude Sonnet 4.5',
        'type': 'api',
        'license': 'Proprietary',
        'color': '#e74c3c',
        'marker': 'o',
        'order': 4
    },
    'anthropic_haiku': {
        'family': 'Anthropic',
        'display_name': 'Claude Haiku 4.5',
        'type': 'api',
        'license': 'Proprietary',
        'color': '#e67e22',
        'marker': 'o',
        'order': 5
    },
    'claude-haiku-4-5': {
        'family': 'Anthropic',
        'display_name': 'Claude Haiku 4.5 (Baseline)',
        'type': 'api',
        'license': 'Proprietary',
        'color': '#d35400',
        'marker': 'o',
        'order': 6
    },
    
    # ============================================================================
    # Qwen/Alibaba (API - Closed Source)
    # ============================================================================
    'qwen_max': {
        'family': 'Qwen',
        'display_name': 'Qwen-Max',
        'type': 'api',
        'license': 'Proprietary',
        'color': '#3498db',
        'marker': 'o',
        'order': 7
    },
    'qwen_plus': {
        'family': 'Qwen',
        'display_name': 'Qwen-Plus',
        'type': 'api',
        'license': 'Proprietary',
        'color': '#5dade2',
        'marker': 'o',
        'order': 8
    },
    'qwen_flash': {
        'family': 'Qwen',
        'display_name': 'Qwen-Flash',
        'type': 'api',
        'license': 'Proprietary',
        'color': '#85c1e9',
        'marker': 'o',
        'order': 9
    },
    
    # ============================================================================
    # Ollama Local (Open Source)
    # ============================================================================
    'ollama_deepseek-r1-70b': {
        'family': 'Ollama-DeepSeek',
        'display_name': 'DeepSeek-R1 70B',
        'type': 'local',
        'license': 'MIT',
        'color': '#8e44ad',
        'marker': '^',  # triangle
        'order': 10
    },
    'ollama_gpt-oss': {
        'family': 'Ollama-GPT',
        'display_name': 'GPT-OSS 20B',
        'type': 'local',
        'license': 'Apache-2.0',
        'color': '#9b59b6',
        'marker': '^',
        'order': 11
    },
    'ollama_qwen3-30b': {
        'family': 'Ollama-Qwen',
        'display_name': 'Qwen3 30B',
        'type': 'local',
        'license': 'Apache-2.0',
        'color': '#af7ac5',
        'marker': '^',
        'order': 12
    },
    'ollama_llama4': {
        'family': 'Ollama-Llama',
        'display_name': 'Llama 4',
        'type': 'local',
        'license': 'Llama',
        'color': '#c39bd3',
        'marker': '^',
        'order': 13
    },
    'ollama_granite4': {
        'family': 'Ollama-Granite',
        'display_name': 'Granite 4',
        'type': 'local',
        'license': 'Apache-2.0',
        'color': '#d7bde2',
        'marker': '^',
        'order': 14
    },
    'ollama_phi4': {
        'family': 'Ollama-Phi',
        'display_name': 'Phi-4',
        'type': 'local',
        'license': 'MIT',
        'color': '#ebdef0',
        'marker': '^',
        'order': 15
    },
    'ollama_gemma3-27b': {
        'family': 'Ollama-Gemma',
        'display_name': 'Gemma3 27B',
        'type': 'local',
        'license': 'Gemma',
        'color': '#bb8fce',
        'marker': '^',
        'order': 16
    },
    'ollama_qwen3-next-80b': {
        'family': 'Ollama-Qwen',
        'display_name': 'Qwen3-Next 80B',
        'type': 'local',
        'license': 'Apache-2.0',
        'color': '#a569bd',
        'marker': '^',
        'order': 17
    }
}


# Family colors for grouping
FAMILY_COLORS = {
    'OpenAI': '#27ae60',      # Green
    'Anthropic': '#e74c3c',   # Red/Orange
    'Qwen': '#3498db',        # Blue
    'Ollama-DeepSeek': '#8e44ad',  # Purple
    'Ollama-GPT': '#9b59b6',
    'Ollama-Qwen': '#af7ac5',
    'Ollama-Llama': '#c39bd3',
    'Ollama-Granite': '#d7bde2',
    'Ollama-Phi': '#ebdef0',
    'Ollama-Gemma': '#bb8fce',
}


# Type colors
TYPE_COLORS = {
    'api': '#2c3e50',         # Dark blue-gray (closed)
    'local': '#7f8c8d'        # Gray (open)
}


# Type markers for scatter plots
TYPE_MARKERS = {
    'api': 'o',      # Circle
    'local': '^'     # Triangle (up)
}


def get_model_metadata(model_name: str) -> Dict[str, Any]:
    """
    Get metadata for a model.
    
    Args:
        model_name: Model identifier
        
    Returns:
        Dict with model metadata
    """
    # Check direct match
    if model_name in MODEL_METADATA:
        return MODEL_METADATA[model_name]
    
    # Fallback: guess based on name
    metadata = {
        'family': 'Unknown',
        'display_name': model_name,
        'type': 'unknown',
        'license': 'Unknown',
        'color': '#95a5a6',  # Gray
        'marker': 's',  # square
        'order': 999
    }
    
    # Try to infer type
    if 'ollama' in model_name.lower():
        metadata['type'] = 'local'
        metadata['marker'] = '^'
        metadata['family'] = f'Ollama-{model_name.split("_")[1] if "_" in model_name else "Unknown"}'
        metadata['color'] = '#8e44ad'
    elif any(api in model_name.lower() for api in ['gpt', 'claude', 'qwen', 'anthropic', 'openai']):
        metadata['type'] = 'api'
        metadata['marker'] = 'o'
    
    return metadata


def get_model_display_name(model_name: str) -> str:
    """Get display name for a model."""
    metadata = get_model_metadata(model_name)
    return metadata['display_name']


def get_model_color(model_name: str) -> str:
    """Get color for a model."""
    metadata = get_model_metadata(model_name)
    return metadata['color']


def get_model_type(model_name: str) -> str:
    """Get type for a model (api or local)."""
    metadata = get_model_metadata(model_name)
    return metadata['type']


def get_model_marker(model_name: str) -> str:
    """Get marker shape for a model in scatter plots."""
    metadata = get_model_metadata(model_name)
    return metadata['marker']


def get_model_order(model_name: str) -> int:
    """Get sort order for a model."""
    metadata = get_model_metadata(model_name)
    return metadata['order']


def sort_models_by_family_and_type(model_names: list) -> list:
    """
    Sort models by family and type for visualization.
    
    API models come first, then local models.
    Within each type, sort by family.
    
    Args:
        model_names: List of model identifiers
        
    Returns:
        Sorted list of model names
    """
    def sort_key(model_name):
        metadata = get_model_metadata(model_name)
        # First by type (api=0, local=1)
        type_order = 0 if metadata['type'] == 'api' else 1
        # Then by order within type
        return (type_order, metadata['order'])
    
    return sorted(model_names, key=sort_key)


def get_model_families(model_names: list) -> Dict[str, list]:
    """
    Group models by family.
    
    Args:
        model_names: List of model identifiers
        
    Returns:
        Dict mapping family name -> list of models
    """
    families = {}
    for model in model_names:
        metadata = get_model_metadata(model)
        family = metadata['family']
        if family not in families:
            families[family] = []
        families[family].append(model)
    
    return families


def get_api_vs_local_groups(model_names: list) -> Dict[str, list]:
    """
    Group models by type (API vs Local).
    
    Args:
        model_names: List of model identifiers
        
    Returns:
        Dict with 'api' and 'local' keys mapping to lists of models
    """
    groups = {'api': [], 'local': []}
    for model in model_names:
        model_type = get_model_type(model)
        if model_type in groups:
            groups[model_type].append(model)
    
    return groups
