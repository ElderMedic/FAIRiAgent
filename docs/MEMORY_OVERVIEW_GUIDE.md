# Memory Overview Feature Guide

**Version**: 1.2.0.20260129  
**Feature**: Memory Overview - Session Memory Analysis and Summary

---

## 🎯 Overview

The Memory Overview feature provides a ChatGPT-style summary of what the FAIRiAgent workflow has learned and remembered during a session. It analyzes all memories stored in the vector database (Qdrant) and generates a natural language overview of key patterns, themes, and insights.

---

## 🚀 Quick Start

### Basic Usage

```bash
# Generate full overview with LLM summary
fairifier memory overview my_project_20260129

# Fast overview without LLM (simple statistics)
fairifier memory overview my_project_20260129 --simple

# Get raw JSON data
fairifier memory overview my_project_20260129 --json
```

### Example Output

```
🔍 Analyzing memories for session: fairifier_20260129_150755
   (Using LLM to generate natural language summary...)

======================================================================
📚 Memory Overview: fairifier_20260129_150755
======================================================================

📊 Statistics:
   Total Memories: 2

🤖 Agent Activity:
   • DocumentParser: 1 memories
   • KnowledgeRetriever: 1 memories

🏷️  Key Themes:
   • alpine
   • grassland
   • metagenomics
   • elevation
   • soil

📝 Summary:
   This workflow session focused on analyzing an alpine ecology research study.
   The system learned that alpine grassland soils research commonly involves
   metagenomics and microbial diversity studies, with particular attention to
   elevation gradients and their impact on soil microbiome variation.

   The workflow identified key patterns for this domain: soil + GSC MIUVIGS +
   Illumina packages are frequently used together for alpine grassland
   metagenomics research involving shotgun sequencing.

💡 Recent Memories (showing 2/2):
   1. alpine grassland soils → metagenomics + microbial diversity + elevation...
   2. elevation gradient studies in alpine ecology commonly link to soil micr...

======================================================================
💡 Tip: Use 'fairifier memory list <session_id>' to see all memories
```

---

## 📚 How It Works

### Architecture

```
┌─────────────────────────────────────────────────┐
│ User: fairifier memory overview <session_id>    │
└─────────────────┬───────────────────────────────┘
                  │
                  v
┌─────────────────────────────────────────────────┐
│ Mem0Service.generate_memory_overview()          │
│                                                  │
│ 1. Fetch all memories from Qdrant               │
│    - Filter by session_id (user_id in mem0)     │
│    - Retrieve memory texts and metadata         │
│                                                  │
│ 2. Extract statistics                           │
│    - Count by agent                             │
│    - Identify key themes (keyword analysis)     │
│    - Collect memory texts                       │
│                                                  │
│ 3. Generate summary                             │
│    - Option A: LLM-generated (natural language) │
│    - Option B: Simple template-based            │
│                                                  │
│ 4. Format and return overview                   │
└─────────────────────────────────────────────────┘
```

### Components

#### 1. `generate_memory_overview()` Method

Main method in `fairifier/services/mem0_service.py`:

```python
overview = mem0_service.generate_memory_overview(
    session_id="my_project_20260129",
    use_llm=True  # Set False for faster, simple summary
)
```

**Returns**:
```python
{
    "session_id": str,
    "total_memories": int,
    "agents": Dict[str, int],  # agent_name -> count
    "memory_texts": List[str],
    "themes": List[str],
    "summary": str
}
```

#### 2. Theme Extraction

Analyzes memory texts for domain-specific keywords:

- **Scientific domains**: alpine, ecology, biodiversity, etc.
- **Research methods**: metagenomics, sequencing, etc.
- **Biological targets**: bacteria, archaea, fungi, etc.
- **FAIR metadata**: ontology, package, field, etc.

#### 3. LLM Summary Generation

When `use_llm=True`:
1. Combines all memory texts
2. Sends to configured LLM with specialized prompt
3. Receives natural language summary (2-3 paragraphs)
4. Fallback to simple summary if LLM fails

**Prompt Design**:
- Style: ChatGPT-like (friendly, informative)
- Focus: What the system learned, key patterns, associations
- Length: Concise (2-3 paragraphs max)

---

## 🎨 Use Cases

### 1. Session Review

**Scenario**: After completing a workflow, review what the system learned.

```bash
fairifier memory overview my_biorem_study
```

**Use**: Understand workflow insights before starting next document.

### 2. Debugging

**Scenario**: Workflow behaving unexpectedly, check if memories are influencing it.

```bash
fairifier memory overview my_project --json > memories.json
# Inspect memories.json to see stored facts
```

### 3. Quality Assessment

**Scenario**: Verify that high-quality facts are being stored (not low-value noise).

```bash
fairifier memory overview my_project
# Read summary - should show domain patterns, not execution status
```

### 4. Knowledge Transfer

**Scenario**: Share workflow learnings with team members.

```bash
fairifier memory overview shared_project > project_memory.txt
# Send project_memory.txt to team
```

### 5. Cross-Session Analysis

**Scenario**: Compare what was learned across multiple sessions.

```bash
fairifier memory overview session1 > s1.txt
fairifier memory overview session2 > s2.txt
diff s1.txt s2.txt
```

---

## ⚙️ Options and Flags

### `--simple` / `-s`

Use simple summary without LLM.

**When to use**:
- Fast overview needed
- LLM not available or slow
- Just want statistics

**Example**:
```bash
fairifier memory overview my_project -s
```

**Output**: Statistics + template-based summary (no LLM inference)

### `--json`

Output raw JSON data instead of pretty format.

**When to use**:
- Programmatic access
- Integration with other tools
- Data analysis scripts

**Example**:
```bash
fairifier memory overview my_project --json | jq '.summary'
```

**Output**: Raw JSON object (can pipe to `jq` for processing)

---

## 📊 Output Format

### Pretty Format (Default)

Sections:
1. **Statistics**: Total count
2. **Agent Activity**: Breakdown by agent
3. **Key Themes**: Extracted keywords
4. **Summary**: Natural language overview
5. **Recent Memories**: Sample of stored facts

### JSON Format (`--json`)

```json
{
  "session_id": "my_project_20260129",
  "total_memories": 5,
  "agents": {
    "DocumentParser": 2,
    "KnowledgeRetriever": 2,
    "JSONGenerator": 1
  },
  "memory_texts": [
    "alpine ecology study identified",
    "soil + GSC MIUVIGS packages",
    "..."
  ],
  "themes": ["alpine", "soil", "metagenomics"],
  "summary": "This workflow session focused on..."
}
```

---

## 🔧 Configuration

### Prerequisites

1. **Mem0 enabled**: `MEM0_ENABLED=true` in `.env`
2. **Qdrant running**: Vector database must be accessible
3. **LLM configured**: For natural language summaries (optional)

### Environment Variables

No additional configuration needed. Uses existing mem0 settings:

```bash
MEM0_ENABLED=true
MEM0_QDRANT_HOST=localhost
MEM0_QDRANT_PORT=6333
MEM0_COLLECTION_NAME=fairifier_memories
```

---

## 🧪 Testing

### Manual Testing

```bash
# 1. Run a workflow to generate memories
fairifier process examples/inputs/test_document.txt --project-id test_overview

# 2. Generate overview
fairifier memory overview test_overview

# 3. Verify output quality
# - Summary should mention domain (e.g., "alpine ecology")
# - Themes should include relevant keywords
# - No low-value facts like "DocumentParser ran successfully"
```

### Unit Tests

```bash
# Run mem0 overview tests
pytest tests/test_mem0_overview.py -v

# Expected: 7-10 tests, all passing
```

---

## 💡 Best Practices

### 1. Review After Each Session

```bash
# After workflow completes
fairifier memory overview <session_id>
```

**Why**: Understand what patterns the system learned for better next run.

### 2. Use Simple Mode for Quick Checks

```bash
fairifier memory overview <session_id> -s
```

**Why**: Faster, no LLM cost, good for quick status checks.

### 3. Clear Low-Quality Memories

If overview shows low-value facts:

```bash
fairifier memory clear <session_id>
```

**When**: After optimizing extraction prompt, clear old memories.

### 4. Export for Documentation

```bash
fairifier memory overview <session_id> > docs/session_learnings.md
```

**Why**: Document workflow insights for reproducibility.

---

## 🐛 Troubleshooting

### Issue: "Mem0 service not available"

**Cause**: Qdrant not running or mem0 disabled.

**Solution**:
```bash
# Check Qdrant
curl http://localhost:6333/collections

# Check config
grep MEM0_ENABLED .env

# Start Qdrant if needed
docker run -d -p 6333:6333 qdrant/qdrant
```

### Issue: "No memories found"

**Cause**: Session ID incorrect or no workflow run yet.

**Solution**:
```bash
# List all sessions with memories
fairifier memory status

# Check if workflow completed
fairifier status <session_id>
```

### Issue: LLM summary is generic/unhelpful

**Cause**: LLM struggling with memory content or too few memories.

**Solution**:
```bash
# Use simple summary instead
fairifier memory overview <session_id> -s

# Or inspect raw memories
fairifier memory list <session_id>
```

### Issue: Themes not capturing domain

**Cause**: Theme extraction relies on predefined keyword list.

**Solution**: Memories are correct but theme extraction is limited. Read full summary or raw memories for complete picture.

---

## 🚀 Future Enhancements

Potential improvements (v1.3.0+):

1. **Hierarchical Overview**: User-level + session-level
2. **Trend Analysis**: Compare memory evolution over time
3. **Visual Dashboard**: Web UI for memory exploration
4. **Export Formats**: PDF, Markdown, HTML
5. **Custom Themes**: User-defined keyword extraction
6. **Memory Search**: Search within overview results

---

## 📚 Related Commands

- `fairifier memory list <session_id>` - List all memories in detail
- `fairifier memory clear <session_id>` - Delete session memories
- `fairifier memory status` - Check mem0 service status
- `fairifier status <session_id>` - Check workflow run status

---

## 🔗 Related Documentation

- [MEM0_CONTEXT_ENGINEERING_INSIGHTS.md](MEM0_CONTEXT_ENGINEERING_INSIGHTS.md) - Context engineering principles
- [MEM0_QUICKSTART.md](MEM0_QUICKSTART.md) - Mem0 installation and setup
- [MEM0_INTEGRATION_SUMMARY.md](MEM0_INTEGRATION_SUMMARY.md) - Technical architecture

---

## 📝 Example Use Case: Research Project

### Scenario

You're processing multiple documents from an alpine ecology research project.

### Workflow

```bash
# Process first document
fairifier process alpine_study_1.pdf --project-id alpine_project

# Check what was learned
fairifier memory overview alpine_project

# Output shows: "alpine ecology + metagenomics + elevation gradients"

# Process second document (benefits from memories)
fairifier process alpine_study_2.pdf --project-id alpine_project

# Check updated learnings
fairifier memory overview alpine_project

# Output shows accumulated knowledge from both documents

# Export final overview
fairifier memory overview alpine_project > alpine_project_summary.md
```

### Result

Second document processes faster and more accurately because system reuses patterns learned from first document.

---

**Version**: 1.2.0.20260129  
**Status**: ✅ Production Ready  
**Last Updated**: 2026-01-29
