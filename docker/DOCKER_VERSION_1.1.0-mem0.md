# Docker Image: fairiagent:1.1.0-mem0

**Built**: 2026-01-29  
**Image ID**: `fa9e1b7561a4`  
**Size**: 3.7GB  
**Branch**: `feature/mem0-context-management`  
**Base Version**: 1.1.0.20260129  

## What's New in This Release

### 🎯 Major Features

#### 1. **mem0 Integration** (Persistent Memory Layer)
- Added `mem0_service.py` with context compression & retrieval
- Support for SQLite + Ollama embeddings (nomic-embed-text)
- Session-level memory for multi-agent workflow
- New CLI command: `memory` (add, search, clear)

#### 2. **Critical Bug Fixes**
- **JSON Parsing Bug**: Fixed `_extract_json_from_markdown` using `find()` instead of `rfind()`
  - Resolves issue where multiple code blocks caused wrong JSON extraction
- **document_info Mapping**: Enhanced to handle adaptive field names
  - Supports nested metadata structures
  - Improved author normalization (preserves dict structure)
  - Intelligent title extraction from summary

#### 3. **Prompt Engineering Overhaul**
- Redefined role: "METADATA EXTRACTION TOOL" (not "expert")
- Added explicit FORBIDDEN list (prevents paper-writing hallucination)
- Anti-pattern examples showing incorrect outputs
- Multiple STOP signals to prevent over-generation
- Maintained flexibility for adaptive field extraction
- Output length constraints (20K-50K chars per agent)

#### 4. **Model Testing & Validation**
- Tested with Ollama qwen3:30b: FAILED (0% success, ignores constraints)
- Tested with Qwen-max (DashScope): SUCCESS (84% confidence, 65 fields, 10x faster)
- Recommendation: Use Qwen-max or similar capable models for production

### 📦 New Dependencies

```txt
mem0ai>=0.1.0
qdrant-client>=1.7.0
```

### 🔧 Configuration Changes

New environment variables:
```bash
# mem0 Configuration (optional)
MEM0_ENABLED=false                          # Enable mem0 memory layer
MEM0_OLLAMA_BASE_URL=http://localhost:11434 # Ollama server for embeddings
MEM0_EMBEDDING_MODEL=nomic-embed-text       # Embedding model name
MEM0_QDRANT_HOST=localhost                  # Qdrant server host
MEM0_QDRANT_PORT=6333                       # Qdrant server port
MEM0_COLLECTION_NAME=fairifier_memories     # Qdrant collection name
MEM0_HISTORY_LIMIT=10                       # Max conversation history
```

### 🐛 Bug Fixes

1. **JSON Parsing Logic Error**
   - Before: Used `rfind("```")` to find last code block
   - After: Uses `find("```", start)` to find first code block
   - Impact: Eliminates selection of hallucinated small JSON blocks

2. **document_info Extraction**
   - Handles nested `metadata` key structures
   - Extracts title from summary's first sentence
   - Preserves author dict objects (ORCID, affiliations)
   - Parses dict-structured research domains

3. **Prompt Hallucination Prevention**
   - Prevents model from generating research papers
   - Blocks APA-formatted references and meta-commentary
   - Reduces output from 192KB to within 20KB constraints

### 🚀 Performance Improvements

| Metric | Before | After |
|--------|--------|-------|
| Qwen-max Success Rate | N/A | 100% |
| Qwen-max Confidence | N/A | 84% |
| Qwen-max Speed | N/A | 2.7 min/doc |
| Ollama qwen3:30b Success Rate | N/A | 0% (not recommended) |

### 📝 CLI Updates

New commands:
- `run_fairifier.py memory add` - Add memory to a session
- `run_fairifier.py memory search` - Search memories
- `run_fairifier.py memory clear` - Clear session memories
- `run_fairifier.py config-info` - Show configuration (now includes mem0 status)

### 🔍 Testing

All improvements tested with:
- ✅ Qwen-max (DashScope) - Recommended for production
- ❌ Ollama qwen3:30b - Not recommended (fails constraints)

### 📚 Documentation

New documentation files:
- `docs/MEM0_INTEGRATION_SUMMARY.md` - mem0 integration guide
- `docs/MEM0_QUICKSTART.md` - Quick start guide
- `docs/MODEL_COMPARISON_FINAL_20260129.md` - Model comparison results
- `docs/PROMPTS_AUDIT_REPORT.md` - Prompt audit findings
- `docs/PROMPT_IMPROVEMENTS_20260129.md` - Prompt engineering details
- `docs/BUGFIX_document_info_mapping.md` - Bugfix documentation
- `docs/EXECUTIVE_SUMMARY_CN.md` - Executive summary (Chinese)
- `docs/en/development/PROMPT_ENGINEERING_GUIDE.md` - Prompt design guide

## Docker Usage

### Basic Usage

```bash
# Pull the image (if published)
docker pull fairiagent:1.1.0-mem0

# Run API mode
docker run -p 8000:8000 fairiagent:1.1.0-mem0

# Run CLI mode
docker run -v $(pwd)/output:/app/output \
  fairiagent:1.1.0-mem0 python run_fairifier.py process document.pdf
```

### With mem0 Enabled

```bash
# Start with Qdrant for mem0
docker-compose -f docker/compose.yaml up -d

# Or run standalone with external Qdrant
docker run -p 8000:8000 \
  -e MEM0_ENABLED=true \
  -e MEM0_QDRANT_HOST=host.docker.internal \
  -e MEM0_QDRANT_PORT=6333 \
  fairiagent:1.1.0-mem0
```

### Environment Variables

```bash
# LLM Configuration
LLM_PROVIDER=qwen                              # ollama, openai, qwen, anthropic
FAIRIFIER_LLM_MODEL=qwen-max                   # Model name
LLM_API_KEY=your-api-key                       # API key (if needed)
LLM_BASE_URL=https://dashscope-intl.aliyuncs.com/compatible-mode/v1

# FAIR-DS API
FAIR_DS_API_URL=http://host.docker.internal:8083

# LangSmith (optional)
LANGSMITH_API_KEY=your-langsmith-key
LANGSMITH_PROJECT=fairifier
```

## Git Commits Included

```
e6eb8da docs: add comprehensive prompt improvement documentation
8bb5ce6 refactor: enhance DocumentParser prompts to prevent model hallucination
043532a fix: enhance document_info mapping to handle adaptive field names
2664ec7 feat: integrate mem0 + critical bug fixes + prompt optimization
```

## Backward Compatibility

✅ **Fully backward compatible** - All existing functionality preserved

- mem0 is **opt-in** (disabled by default)
- Existing API endpoints unchanged
- CLI commands work as before
- Configuration variables have sensible defaults

## Known Issues

1. **Ollama qwen3:30b**: Does not respect output constraints
   - Workaround: Use Qwen-max or other capable models
   
2. **document_info extraction**: Some edge cases may still need refinement
   - Affected: Uncommon document structures
   - Impact: Minimal - core functionality works

## Upgrade Notes

### From Previous Version

1. Update your `.env` file with new mem0 variables (optional)
2. If using mem0, ensure Qdrant is running
3. Review `LLM_MAX_TOKENS` setting (recommended: 10000, not 100000)

### Configuration Validation

Check your configuration:
```bash
docker run --rm fairiagent:1.1.0-mem0 python run_fairifier.py config-info
```

## Support

For issues or questions:
- Check documentation in `docs/` folder
- Review `docs/PROMPT_IMPROVEMENTS_20260129.md` for prompt details
- See `docs/MEM0_QUICKSTART.md` for mem0 setup

## Next Steps

Recommended improvements (not included in this release):
1. Lower `LLM_MAX_TOKENS` to 10000 (currently 100000 in config)
2. Add response size validation before JSON parsing
3. Consider JSON schema validation for stricter format checking
4. Further refine `document_info` mapping for edge cases
