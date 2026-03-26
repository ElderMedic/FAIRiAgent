# Mem0 Memory Layer Quick Start

## Overview

FAIRiAgent v1.1+ includes optional mem0 integration for persistent semantic memory across workflow sessions. This feature provides:

- 🧠 **Context compression** - Store key insights from each agent execution
- 🔍 **Smart retrieval** - Retrieve relevant memories before agent execution
- 📊 **Session tracking** - Memories scoped by session/thread ID
- 🔄 **Resume support** - Memories persist across workflow interruptions

## Installation

### 1. Install Dependencies

```bash
# Install mem0 and Qdrant client
pip install mem0ai qdrant-client
```

### 2. Start Qdrant

```bash
# Using Docker (recommended)
docker run -d -p 6333:6333 -p 6334:6334 \
  -v $(pwd)/qdrant_storage:/qdrant/storage \
  qdrant/qdrant

# Or install locally
# See: https://qdrant.tech/documentation/quick-start/
```

### 3. Configure Environment

Add to your `.env` file:

```bash
# Enable mem0
MEM0_ENABLED=true

# Qdrant connection
MEM0_QDRANT_URL=http://localhost:6333

# Optional: customize settings
MEM0_EMBEDDING_MODEL=nomic-embed-text
MEM0_COLLECTION_NAME=fairifier_memories
```

### 4. Verify Installation

```bash
# Check mem0 service status
fairifier memory status

# Should output:
# ✅ Status:     Available
# ✅ Qdrant connection OK
```

## Usage

### Basic Workflow

When mem0 is enabled, it automatically:

1. **Before agent execution**: Retrieves relevant memories based on:
   - Document info (title, domain, keywords)
   - Agent name (DocumentParser, KnowledgeRetriever, etc.)
   - Custom query hints (if agent implements `get_memory_query_hint()`)

2. **After successful execution**: Stores key insights:
   - Agent output summary
   - Quality score from Critic
   - Important findings and decisions

3. **During retry**: Memories from previous attempts inform the agent

### Memory Management

```bash
# Check memory status
fairifier memory status

# List all memories for a session
fairifier memory list fairifier_20260129_120000

# Filter by agent
fairifier memory list fairifier_20260129_120000 -a DocumentParser

# Clear memories for re-run with fresh context
fairifier memory clear fairifier_20260129_120000

# Clear without confirmation
fairifier memory clear fairifier_20260129_120000 -f
```

### Example Workflow

```bash
# 1. Process a document (mem0 enabled)
fairifier process document.pdf --project-id my_project

# Memories are automatically stored during processing

# 2. View stored memories
fairifier memory list my_project

# Output:
# 🆔 abc123def456...
# 🤖 Agent: DocumentParser
# 📊 Score: 0.85
# ⏰ Time:  2026-01-29 12:34:56
# 💭 [DocumentParser] Parsed document: 'RNA-seq Analysis in Arabidopsis'...

# 3. Resume workflow (uses memories automatically)
fairifier resume my_project

# 4. Clear memories before re-processing
fairifier memory clear my_project
fairifier process document.pdf --project-id my_project
```

## Advanced Configuration

### Custom Memory Queries

Agents can provide custom memory query hints by overriding `get_memory_query_hint()`:

```python
class MyCustomAgent(BaseAgent):
    def get_memory_query_hint(self, state: FAIRifierState) -> Optional[str]:
        # Return custom query for memory retrieval
        domain = state.get("document_info", {}).get("research_domain", "")
        return f"Context for {self.name} processing {domain} research data"
```

### Environment Variables

Full list of mem0 configuration options:

```bash
# Core settings
MEM0_ENABLED=true                          # Enable/disable mem0
MEM0_QDRANT_URL=http://localhost:6333      # Qdrant server URL
MEM0_COLLECTION_NAME=fairifier_memories    # Collection name

# LLM settings (defaults to main LLM config)
MEM0_OLLAMA_BASE_URL=http://localhost:11434
MEM0_LLM_MODEL=qwen3:30b                   # For fact extraction
MEM0_EMBEDDING_MODEL=nomic-embed-text      # For vector embeddings

# Alternative: separate host/port
MEM0_QDRANT_HOST=localhost
MEM0_QDRANT_PORT=6333
```

### LangSmith Tracing

Mem0 operations are automatically traced in LangSmith (if enabled):

- `mem0_search` - Memory retrieval operations
- `mem0_add` - Memory storage operations

Enable LangSmith tracing:

```bash
LANGSMITH_API_KEY=your_api_key
LANGCHAIN_TRACING_V2=true
```

## Troubleshooting

### Mem0 Not Available

```bash
# Check status
fairifier memory status

# Common issues:
# 1. Qdrant not running
docker ps | grep qdrant

# 2. Wrong URL
# Check MEM0_QDRANT_URL in .env

# 3. Dependencies not installed
pip install mem0ai qdrant-client
```

### Graceful Degradation

If mem0 is unavailable, FAIRiAgent automatically:
- Disables memory features
- Continues with normal operation
- Logs a warning

No code changes or special handling required.

### Memory Cleanup

```bash
# Clear specific session
fairifier memory clear <session_id>

# Clear all memories (via Qdrant)
curl -X DELETE http://localhost:6333/collections/fairifier_memories
```

## Architecture

### Data Flow

```
┌─────────────────────────────────────────────┐
│ LangGraph Workflow                          │
│                                             │
│  ┌────────────────────────────────────┐    │
│  │ Agent Execution Node               │    │
│  │                                    │    │
│  │  1. Retrieve memories (search)    │───┐│
│  │  2. Execute agent                 │   ││
│  │  3. Critic evaluation             │   ││
│  │  4. Store insights (if ACCEPT)    │───┤│
│  └────────────────────────────────────┘   ││
│                                            ││
└────────────────────────────────────────────┘│
                                              │
              ┌───────────────────────────────┘
              │
              v
     ┌─────────────────┐       ┌──────────────┐
     │  Mem0 Service   │◄─────►│   Qdrant     │
     │                 │       │  (Vector DB) │
     └─────────────────┘       └──────────────┘
              │
              │ (Optional: LangSmith Tracing)
              v
     ┌─────────────────┐
     │  LangSmith      │
     └─────────────────┘
```

### Session Binding

- `session_id` in FAIRifierState = `thread_id` in checkpointer
- Ensures memories align with workflow state on resume
- Memories persist independently from checkpointer

### Complementary with SQLite Checkpointer

| Feature | SQLite Checkpointer | Mem0 Memory Layer |
|---------|--------------------|--------------------|
| Purpose | Workflow state | Semantic insights |
| Scope | Full state dict | Key facts/findings |
| Resume | Exact state restore | Context enrichment |
| Storage | SQLite DB | Qdrant vectors |
| Query | Thread ID lookup | Semantic search |

Both work together seamlessly - no conflicts.

## Performance

### Storage

- ~100-200 bytes per memory entry
- Vector embeddings: 768 dimensions (nomic-embed-text)
- Typical session: 5-20 memories

### Latency

- Memory search: 10-50ms (local Qdrant)
- Memory add: 50-200ms (includes embedding + storage)
- Negligible impact on total workflow time (<1%)

## Next Steps

- [Configuration Reference](../env.example)
- [API Documentation](../fairifier/services/mem0_service.py)
