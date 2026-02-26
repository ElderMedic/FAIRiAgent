# Model Classification and Metadata

**Purpose**: Accurate classification of models for analysis and visualization

---

## Model Families and Types

### 1. OpenAI (API - Closed Source) 🔒

**Provider**: OpenAI  
**Access**: API  
**License**: Proprietary

| Model ID | Display Name | Context | Type |
|----------|--------------|---------|------|
| `openai_gpt4.1` | GPT-4.1 | 256k | Closed |
| `openai_o3` | O3 | 256k | Closed (Reasoning) |
| `gpt-5.1` | GPT-5.1 | 400k | Closed |

**Color Scheme**: Green shades (#27ae60, #2ecc71, #16a085)

---

### 2. Anthropic (API - Closed Source) 🔒

**Provider**: Anthropic  
**Access**: API  
**License**: Proprietary

| Model ID | Display Name | Context | Type |
|----------|--------------|---------|------|
| `anthropic_sonnet` | Claude Sonnet 4.5 | 200k | Closed |
| `anthropic_haiku` | Claude Haiku 4.5 | 200k | Closed |
| `claude-haiku-4-5` | Claude Haiku 4.5 (Baseline) | 200k | Closed |

**Color Scheme**: Orange/Red shades (#e74c3c, #e67e22, #d35400)

---

### 3. Qwen/Alibaba (API - Closed Source but from Chinese Provider) 🔒

**Provider**: Alibaba Cloud  
**Access**: API  
**License**: Proprietary (but available in China)

| Model ID | Display Name | Context | Type |
|----------|--------------|---------|------|
| `qwen_max` | Qwen-Max | 128k | Closed API |
| `qwen_plus` | Qwen-Plus | 128k | Closed API |
| `qwen_flash` | Qwen-Flash | 100k | Closed API |

**Color Scheme**: Blue/Purple shades (#3498db, #9b59b6, #5dade2)

---

### 4. Ollama Local (Open Source) 🔓

**Provider**: Various (run locally via Ollama)  
**Access**: Local  
**License**: Open Source

| Model ID | Display Name | Base Model | License |
|----------|--------------|------------|---------|
| `ollama_deepseek-r1-70b` | DeepSeek-R1 70B | DeepSeek | MIT |
| `ollama_gpt-oss` | GPT-OSS 20B | GPT-OSS | Apache-2.0 |
| `ollama_qwen3-30b` | Qwen3 30B | Qwen3 | Apache-2.0 |
| `ollama_llama4` | Llama 4 | Meta Llama | Llama License |
| `ollama_granite4` | Granite 4 | IBM Granite | Apache-2.0 |
| `ollama_phi4` | Phi-4 | Microsoft Phi | MIT |
| `ollama_gemma3-27b` | Gemma3 27B | Google Gemma | Gemma License |
| `ollama_qwen3-next-80b` | Qwen3-Next 80B | Qwen3-Next | Apache-2.0 |

**Color Scheme**: Purple/Magenta shades (#8e44ad, #9b59b6, #c39bd3, #af7ac5)

---

## Visualization Guidelines

### Color Coding by Type

```python
MODEL_TYPE_COLORS = {
    'openai_api': '#27ae60',      # Green
    'anthropic_api': '#e74c3c',   # Red/Orange
    'qwen_api': '#3498db',        # Blue
    'ollama_local': '#8e44ad'     # Purple
}
```

### Grouping Strategy

**For Bar Charts/Heatmaps**:
1. Group by family (OpenAI, Anthropic, Qwen, Ollama)
2. Within family, order by model size/capability
3. Separate API models from local models with visual divider

**For Scatter Plots**:
1. Use shape + color:
   - API models: Circles
   - Local models: Triangles
2. Color by family
3. Add legend clearly distinguishing API vs Local

---

## Model Metadata for Analysis

```python
MODEL_METADATA = {
    # OpenAI API
    'openai_gpt4.1': {
        'family': 'OpenAI',
        'display_name': 'GPT-4.1',
        'type': 'api',
        'license': 'proprietary',
        'color': '#27ae60',
        'order': 1
    },
    'openai_o3': {
        'family': 'OpenAI',
        'display_name': 'O3',
        'type': 'api',
        'license': 'proprietary',
        'color': '#16a085',
        'order': 2
    },
    'gpt-5.1': {
        'family': 'OpenAI',
        'display_name': 'GPT-5.1',
        'type': 'api',
        'license': 'proprietary',
        'color': '#2ecc71',
        'order': 3
    },
    
    # Anthropic API
    'anthropic_sonnet': {
        'family': 'Anthropic',
        'display_name': 'Claude Sonnet 4.5',
        'type': 'api',
        'license': 'proprietary',
        'color': '#e74c3c',
        'order': 4
    },
    'anthropic_haiku': {
        'family': 'Anthropic',
        'display_name': 'Claude Haiku 4.5',
        'type': 'api',
        'license': 'proprietary',
        'color': '#e67e22',
        'order': 5
    },
    'claude-haiku-4-5': {
        'family': 'Anthropic',
        'display_name': 'Claude Haiku 4.5 (Baseline)',
        'type': 'api',
        'license': 'proprietary',
        'color': '#d35400',
        'order': 6
    },
    
    # Qwen API
    'qwen_max': {
        'family': 'Qwen',
        'display_name': 'Qwen-Max',
        'type': 'api',
        'license': 'proprietary',
        'color': '#3498db',
        'order': 7
    },
    'qwen_plus': {
        'family': 'Qwen',
        'display_name': 'Qwen-Plus',
        'type': 'api',
        'license': 'proprietary',
        'color': '#5dade2',
        'order': 8
    },
    'qwen_flash': {
        'family': 'Qwen',
        'display_name': 'Qwen-Flash',
        'type': 'api',
        'license': 'proprietary',
        'color': '#85c1e9',
        'order': 9
    },
    
    # Ollama Local
    'ollama_deepseek-r1-70b': {
        'family': 'Ollama-DeepSeek',
        'display_name': 'DeepSeek-R1 70B (Local)',
        'type': 'local',
        'license': 'MIT',
        'color': '#8e44ad',
        'order': 10
    },
    'ollama_gpt-oss': {
        'family': 'Ollama-GPT',
        'display_name': 'GPT-OSS 20B (Local)',
        'type': 'local',
        'license': 'Apache-2.0',
        'color': '#9b59b6',
        'order': 11
    },
    'ollama_qwen3-30b': {
        'family': 'Ollama-Qwen',
        'display_name': 'Qwen3 30B (Local)',
        'type': 'local',
        'license': 'Apache-2.0',
        'color': '#af7ac5',
        'order': 12
    },
    'ollama_llama4': {
        'family': 'Ollama-Llama',
        'display_name': 'Llama 4 (Local)',
        'type': 'local',
        'license': 'Llama',
        'color': '#c39bd3',
        'order': 13
    },
    'ollama_granite4': {
        'family': 'Ollama-Granite',
        'display_name': 'Granite 4 (Local)',
        'type': 'local',
        'license': 'Apache-2.0',
        'color': '#d7bde2',
        'order': 14
    },
    'ollama_phi4': {
        'family': 'Ollama-Phi',
        'display_name': 'Phi-4 (Local)',
        'type': 'local',
        'license': 'MIT',
        'color': '#ebdef0',
        'order': 15
    },
    'ollama_gemma3-27b': {
        'family': 'Ollama-Gemma',
        'display_name': 'Gemma3 27B (Local)',
        'type': 'local',
        'license': 'Gemma',
        'color': '#bb8fce',
        'order': 16
    },
    'ollama_qwen3-next-80b': {
        'family': 'Ollama-Qwen',
        'display_name': 'Qwen3-Next 80B (Local)',
        'type': 'local',
        'license': 'Apache-2.0',
        'color': '#a569bd',
        'order': 17
    }
}
```

---

## Corrections from Previous Analysis

### ❌ Incorrect Classifications

**None identified** - All models correctly classified in completeness check

### ✅ Verified Correct

- OpenAI models (gpt4.1, o3, gpt-5.1): API ✓
- Anthropic models (sonnet, haiku): API ✓
- Qwen models (max, plus, flash): API ✓
- Ollama models: Local ✓

---

## Data Source Verification

### Agentic Runs (294 complete)

```
evaluation/runs/
├── qwen_max/ (20 runs) ✓
├── qwen_plus/ (20 runs) ✓
├── qwen_flash/ (19 runs) ✓
├── anthropic_haiku/ (20 runs) ✓
├── anthropic_sonnet/ (16 runs) ✓
├── openai_gpt4.1/ (10 runs) ⚠️
├── openai_o3/ (11 runs) ✓
├── ollama_20260129/
│   ├── ollama_deepseek-r1-70b/ (18 runs) ✓
│   ├── ollama_gpt-oss/ (2 runs) ✓
│   └── ... (other ollama models)
```

### Baseline Runs (30 complete)

```
evaluation/baselines/runs/
├── openai_gpt5.1_20260130/ (20 runs) ✓
└── claude-haiku-4-5_20260130/ (10 runs) ✓
```

---

## Analysis Status

### ✅ Analyzed (5 models)

1. **qwen_max** (API, Qwen, 20 runs): 80% success ✓
2. **gpt-5.1** (API, OpenAI, 20 runs): 0% success ✓
3. **claude-haiku-4-5** (API, Anthropic, 10 runs): 0% success ✓
4. **anthropic_haiku** (API, Anthropic, 20 runs): ✓
5. **ollama_deepseek-r1-70b** (Local, Ollama, 18 runs): 0% success ✓

### ⏳ Pending Analysis

- qwen_plus (API, Qwen, 20 runs)
- qwen_flash (API, Qwen, 19 runs)
- openai_o3 (API, OpenAI, 11 runs)
- anthropic_sonnet (API, Anthropic, 16 runs)
- Other ollama models (Local)

---

**Last Updated**: 2026-01-30  
**Status**: Ready for improved visualizations
