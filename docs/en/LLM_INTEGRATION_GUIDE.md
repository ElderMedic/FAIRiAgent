# LLM Integration Guide

## Overview

The FAIRiAgent project integrates Large Language Model (LLM) support, enabling the use of OpenAI GPT models or Anthropic Claude models to enhance the intelligent processing capabilities of each agent.

## Configuration

### 1. Environment Variables

Before use, set the corresponding API keys in your environment or `.env` file:

```bash
# Use OpenAI (Recommended)
export OPENAI_API_KEY="your-openai-api-key"
export LLM_PROVIDER="openai"
export FAIRIFIER_LLM_MODEL="gpt-4o-mini"  # or "gpt-4", "gpt-3.5-turbo"

# Use Claude
export ANTHROPIC_API_KEY="your-anthropic-api-key"
export LLM_PROVIDER="anthropic"
export FAIRIFIER_LLM_MODEL="claude-3-haiku-20240307"  # or other Claude models

# Use Ollama (Local)
export LLM_PROVIDER="ollama"
export FAIRIFIER_LLM_BASE_URL="http://localhost:11434"
export FAIRIFIER_LLM_MODEL="llama3"
```

### 2. Configuration File

You can also modify the `fairifier/config.py` file directly:

```python
# LLM Configuration
llm_provider: str = "openai"  # "openai", "anthropic", or "ollama"
llm_model: str = "gpt-4o-mini"  # Model name
llm_api_key: Optional[str] = "your-api-key"
```

## LLM Enhanced Features

### 1. DocumentParserAgent
- **Enhancement**: Uses LLM to intelligently parse scientific documents and extract structured information.
- **Improvements**: 
  - More accurate extraction of title, abstract, and authors.
  - Intelligent identification of research domains and methodologies.
  - Automatic identification of datasets, instruments, and variables.

### 2. KnowledgeRetrieverAgent
- **Enhancement**: Uses LLM for intelligent knowledge retrieval and matching.
- **Improvements**:
  - Intelligent selection of appropriate MIxS packages.
  - Selection of relevant optional fields based on document content.
  - Identification of relevant ontology terms.

### 3. JSONGeneratorAgent
- **Enhancement**: Uses LLM to generate smarter, more accurate metadata templates and values.
- **Improvements**:
  - Generates realistic example values based on research content.
  - Intelligently infers data types and necessity of fields.
  - Suggests additional FAIR data-related fields.

## Usage

### 1. Install Dependencies

```bash
pip install -r requirements.txt
```

### 2. Set API Keys

```bash
export OPENAI_API_KEY="your-openai-api-key"
```

### 3. Run System

```bash
python run_fairifier.py process examples/inputs/test_document.txt
```

## Model Selection Recommendations

### OpenAI Models
- **gpt-4o-mini**: Recommended. High cost-performance ratio, fast processing speed.
- **gpt-4**: Highest quality, but higher cost.
- **gpt-3.5-turbo**: Lowest cost, but slightly lower quality.

### Claude Models
- **claude-3-haiku**: Fast and economical.
- **claude-3-sonnet**: Balanced performance and cost.
- **claude-3-opus**: Highest quality.

## Error Handling

The system has robust error handling mechanisms:

1. **LLM Call Failure**: Automatically falls back to rule-based processing methods (if available) or retries.
2. **JSON Parsing Failure**: Uses regex as a fallback solution to extract JSON from LLM responses.
3. **API Limits**: Automatic retry and rate limit handling.

## Performance Optimization

1. **Batching**: Multiple fields are batched and sent to LLM for processing.
2. **Text Truncation**: Long documents are intelligently truncated to avoid token limits while preserving key sections.
3. **Caching**: Results for the same inputs are cached.

## Cost Control

1. **Use gpt-4o-mini**: Recommended for production environments.
2. **Set max_tokens limit**: Control response length.
3. **Text Preprocessing**: Remove irrelevant content to reduce token usage.

## Example Output

With LLM integration, the system generates more accurate metadata:

```json
{
  "project_name": "Marine Microbiome Diversity Study",
  "investigation_type": "metagenome",
  "env_biome": "marine biome [ENVO:00000447]",
  "sample_collect_device": "CTD rosette",
  "depth": "150",
  "temp": "4.2",
  "collection_date": "2023-08-15"
}
```

## Troubleshooting

### Common Issues

1. **API Key Error**: Check environment variable settings.
2. **Model Not Found**: Confirm the model name is correct.
3. **Network Connection Issues**: Check network connection and firewall settings.
4. **Token Limits**: Reduce input text length or increase `max_tokens`.

### Viewing Logs

The system records detailed log information. Use the `--json-log` flag for structured logging.

```bash
# View processing logs
tail -f processing_log.jsonl
```

## Next Steps

1. Consider integrating more model providers (e.g., Azure OpenAI).
2. Add model performance monitoring and evaluation.
3. Implement finer-grained prompt engineering optimizations.

