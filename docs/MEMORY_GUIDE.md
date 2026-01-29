# Memory Management Guide

**Version**: 1.2.2  
**Last Updated**: 2026-01-29

---

## Overview

FAIRiAgent includes an intelligent memory system that learns from each document processing run to improve future performance.

### Key Features
- 🧠 **Semantic Memory**: Stores workflow insights and patterns
- 🔍 **Cross-Agent Learning**: Agents share knowledge across sessions
- 📊 **Memory Overview**: ChatGPT-style natural language summaries
- ♻️ **Smart Retrieval**: Context-aware memory search

---

## Usage

### List Memories
```bash
python run_fairifier.py memory list <session_id>
```

**Example Output**:
```
🆔 Memory 1
🤖 Agent: KnowledgeRetriever
💭 nanotoxicology research requires FAIR-DS packages: soil, Illumina, Genome

🆔 Memory 2  
🤖 Agent: Planner
💭 time-series RNA-seq is standard for transcriptomic toxicant responses

Total: 8 memories
```

### Memory Overview
```bash
python run_fairifier.py memory overview <session_id>
```

**Example Output**:
```
📚 Memory Overview: your_session

📊 Statistics:
   Total Memories: 8
   
🤖 Agent Activity:
   • KnowledgeRetriever: 3 memories
   • Planner: 3 memories
   • JSONGenerator: 2 memories

🏷️ Key Themes:
   • FAIR-DS packages
   • Ontology mappings
   • Metadata complexity

📝 Summary:
This session processed ecotoxicogenomics research, requiring 
specialized metadata packages including soil and Illumina...
```

### Clear Memories
```bash
python run_fairifier.py memory clear <session_id>
```

---

## What Gets Remembered

### 1. Workflow Decisions
- **Package Selections**: Which FAIR-DS packages were used for what type of research
- **Ontology Mappings**: Which ontologies map to which field types
- **Metadata Complexity**: How many terms were needed for different study types

Example:
```
"nanotoxicology studies require soil + Illumina + Genome packages"
"FAIR-DS ontologies mapped: ENVO, OBI, EDAM, NPO"
```

### 2. Document Patterns
- **Study Designs**: Common experimental designs by domain
- **Research Domains**: Domain classification patterns
- **Model Organisms**: Frequently used species by field

Example:
```
"ecotoxicogenomics studies commonly use earthworms as model organisms"
"time-series RNA-seq is standard for transcriptomic responses"
```

### 3. Quality Insights
- **Success Patterns**: What leads to high-quality metadata
- **Common Issues**: Frequently encountered problems
- **Repair Rules**: Successful fix strategies

Example:
```
"Repair: Added missing author affiliations improved score from 0.6 to 0.95"
"Quality: Comprehensive experimental variables achieve scores >0.8"
```

---

## Memory System Design

### Retrieve Before Execute
Before each agent runs, the system retrieves relevant memories from past sessions to inform its decisions.

### Write Selectively
After execution, only high-value insights are stored (not every output). This prevents memory bloat.

**Gating Rules**:
- ✅ High quality (score > 0.75)
- ✅ Learned repairs
- ✅ Novel failures
- ✅ Workflow decisions

---

## Configuration

### Environment Variables
```bash
# Memory collection name
export MEM0_COLLECTION_NAME=fairifier_memories_production

# Enable/disable memory
export ENABLE_MEM0=true
```

### In config.py
```python
memory_config = MemoryConfig(
    collection_name="fairifier_memories",
    embedding_model="nomic-embed-text",
    llm_provider="qwen"
)
```

---

## Best Practices

### 1. Use Meaningful Session IDs
```bash
# Good
--project-id ecotox_study_2026

# Bad  
--project-id test123
```

### 2. Review Memory Overviews
Periodically check memory overviews to understand what the system has learned:
```bash
python run_fairifier.py memory overview <session_id>
```

### 3. Clear When Starting Fresh
If starting a completely different project domain:
```bash
python run_fairifier.py memory clear <old_session>
```

---

## Troubleshooting

### No Memories Found
**Check**:
1. Verify session_id matches the one used during processing
2. Check Mem0 service is enabled: `grep "Mem0 service" your_log.log`
3. Verify Qdrant is running: `docker ps | grep qdrant`

### Too Many Memories
The system automatically gates memory writes. If you see too many:
- This is unusual - gating should keep count reasonable
- Check if quality threshold was lowered in config

### Memory Not Helping
If retrieved memories don't seem relevant:
- The system learns over time
- First few runs may have limited memories
- Check memory overview to see what's stored

---

## Technical Details

For developers and advanced users:

**Architecture**: Mem0 + Qdrant + Nomic embeddings  
**Storage**: Vector database with semantic search  
**Retrieval**: Task-specific queries with cross-agent sharing  
**Gating**: Multi-rule quality filtering

For complete technical documentation, see `.memory/development/` (local only).

---

**Version**: 1.2.2  
**Status**: Production Ready  
**Support**: See [README.md](README.md) for main documentation
