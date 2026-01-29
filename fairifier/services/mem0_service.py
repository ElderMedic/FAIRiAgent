"""
Mem0 Memory Service for FAIRiAgent multi-agent system.

Provides persistent semantic memory for context compression and retrieval
across the workflow session. Uses Ollama for embeddings and Qdrant for
vector storage.

This is an opt-in feature that complements (not replaces) the SQLite
checkpointer for workflow state persistence.
"""

from typing import List, Dict, Any, Optional
import logging

# LangSmith tracing (optional)
try:
    from langsmith import traceable
except ImportError:
    # Define a no-op decorator if langsmith is not available
    def traceable(*args, **kwargs):
        def decorator(func):
            return func
        return decorator

logger = logging.getLogger(__name__)

# Custom fact-extraction prompt for FAIR workflow: extract REUSABLE, HIGH-VALUE facts for context
# compression and retrieval. Focuses on domain patterns, field mappings, and quality insights rather
# than ephemeral execution details. Includes few-shot examples and explicit negative cases.
FAIR_FACT_EXTRACTION_PROMPT = """You extract REUSABLE, HIGH-VALUE facts from FAIR metadata workflow outputs for FUTURE runs.

EXTRACTION PRINCIPLES:
1. Extract PATTERNS and KNOWLEDGE that apply to multiple documents/runs
2. Include domain-specific associations, package preferences, and ontology mappings
3. Capture workflow decisions and their rationale (why certain choices were made)
4. Keep each fact concise (<120 chars) and self-contained
5. Be generous with valuable information - if in doubt, extract it

EXTRACT (high-value, reusable):
- Domain-package associations: "alpine ecology studies commonly use soil + GSC MIUVIGS packages"
- Package combinations: "nanotoxicology RNA-seq requires soil + Illumina + Genome packages"
- Field mappings: "elevation_m maps to 'geographic location (elevation)' in Sample sheet"
- Ontology preferences: "earthworm studies use ENVO for habitats, OBI for assays"
- Study design patterns: "time-series transcriptomics studies span multiple ISA levels"
- Method associations: "RNA-seq nanomaterial exposure commonly uses differential expression analysis"
- Quality patterns: "high-confidence metadata generation (>70%) indicates comprehensive source data"

DO NOT EXTRACT (low-value, ephemeral):
- Execution status: "DocumentParser ran successfully"
- Exact counts alone: "retrieved 106 fields" (meaningless without context)
- Agent names alone: "Parsed by DocumentParser" (adds no value)
- Temporary state: "retry count is 2"

EXAMPLES:

Input: "DocumentParser extracted: ecotoxicogenomics research, organisms: Eisenia fetida, Eisenia andrei, methods: RNA-seq, differential expression"
Output: {"facts": ["earthworm toxicology studies commonly use Eisenia fetida and Eisenia andrei as model species", "ecotoxicogenomics RNA-seq studies focus on differential expression analysis"]}

Input: "KnowledgeRetriever selected packages: soil, Illumina, Genome for nanotoxicology study. Relevant ontologies: ENVO, OBI, EDAM, NPO. Complex metadata spanning 4 ISA levels"
Output: {"facts": ["nanotoxicology soil studies use packages: soil + Illumina + Genome", "nanotoxicology metadata commonly requires ENVO, OBI, EDAM, NPO ontologies", "complex experimental designs span 4+ ISA levels"]}

Input: "JSONGenerator: 89/156 high-confidence fields. Key mappings: exposure_concentration → OBI, time_point → EDAM, nanomaterial_type → NPO"
Output: {"facts": ["exposure_concentration fields map to OBI ontology", "time_point metadata uses EDAM terms", "nanomaterial characterization uses NPO ontology"]}

Input: "Quality score: 0.72. Strengths: comprehensive coverage of experimental variables"
Output: {"facts": ["comprehensive experimental variable extraction achieves quality scores >0.7"]}

Now extract from the following assistant message:
{assistant_message}

Return JSON format: {"facts": [...]}
"""

# Global singleton instance
_mem0_service: Optional["Mem0Service"] = None


class Mem0Service:
    """Centralized memory service for FAIRiAgent multi-agent system.
    
    Provides semantic memory storage and retrieval using mem0 with:
    - Ollama for LLM (fact extraction) and embeddings
    - Qdrant for vector storage
    - Session/agent scoping for organized memory management
    
    All operations are designed to fail gracefully - if mem0 or Qdrant
    is unavailable, methods return empty results instead of raising exceptions.
    """
    
    def __init__(self, config: dict):
        """Initialize mem0 with provided configuration.
        
        Args:
            config: mem0 configuration dictionary with llm, embedder, and vector_store settings
        """
        self._init_error: Optional[Exception] = None  # Stored for strict-mode re-raise
        try:
            from mem0 import Memory
            self.memory = Memory.from_config(config)
            self.enabled = True
            self._config = config
            logger.info("Mem0 service initialized successfully")
        except Exception as e:
            self._init_error = e
            self.memory = None
            self.enabled = False
            self._config = config
            # Optional feature: log as WARNING with clear one-liner; full detail at DEBUG
            short_msg = str(e).split("\n")[0].strip() if str(e) else repr(e)
            logger.warning(
                "Mem0 optional feature disabled (workflow continues without memory layer): %s",
                short_msg[:200] + ("..." if len(short_msg) > 200 else ""),
            )
            logger.debug("Mem0 init full error: %s", e, exc_info=True)
    
    def is_available(self) -> bool:
        """Check if mem0 service is available and enabled."""
        return self.enabled and self.memory is not None
    
    @traceable(name="mem0_search", tags=["memory", "retrieval"])
    def search(
        self, 
        query: str, 
        session_id: str, 
        agent_id: str = None, 
        limit: int = 5
    ) -> List[Dict[str, Any]]:
        """Search for relevant memories.
        
        Args:
            query: Natural language query for semantic search
            session_id: Session identifier (bound to workflow thread_id)
            agent_id: Optional agent identifier for scoped search
            limit: Maximum number of results to return
            
        Returns:
            List of memory dictionaries with 'memory', 'id', and metadata fields.
            Returns empty list on error.
        """
        if not self.is_available():
            return []
        
        try:
            # mem0 uses user_id for scoping
            results = self.memory.search(
                query=query,
                user_id=session_id,
                agent_id=agent_id,
                limit=limit
            )
            memories = results.get("results", [])
            logger.debug(f"Memory search returned {len(memories)} results for session={session_id}, agent={agent_id}")
            return memories
        except Exception as e:
            logger.warning(f"Memory search failed: {e}")
            return []
    
    @traceable(name="mem0_add", tags=["memory", "storage"])
    def add(
        self, 
        messages: List[Dict[str, str]], 
        session_id: str, 
        agent_id: str = None,
        metadata: Dict[str, Any] = None
    ) -> Dict[str, Any]:
        """Add memories from conversation messages.
        
        Args:
            messages: List of message dicts with 'role' and 'content' keys
            session_id: Session identifier (bound to workflow thread_id)
            agent_id: Optional agent identifier for scoped storage
            metadata: Optional metadata to attach to memories
            
        Returns:
            Result dictionary with 'results' containing added memory IDs.
            Returns empty dict on error.
        """
        if not self.is_available():
            return {}
        
        try:
            result = self.memory.add(
                messages=messages,
                user_id=session_id,
                agent_id=agent_id,
                metadata=metadata or {}
            )
            added_count = len(result.get("results", []))
            logger.debug(f"Added {added_count} memories for session={session_id}, agent={agent_id}")
            return result
        except Exception as e:
            logger.warning(f"Memory add failed: {e}")
            return {}
    
    def list_memories(
        self, 
        session_id: str, 
        agent_id: str = None
    ) -> List[Dict[str, Any]]:
        """List all memories for a session (for debugging/monitoring).
        
        Args:
            session_id: Session identifier to list memories for
            agent_id: Optional agent identifier to filter by
            
        Returns:
            List of all memory dictionaries for the session.
            Returns empty list on error.
        """
        if not self.is_available():
            return []
        
        try:
            results = self.memory.get_all(user_id=session_id, agent_id=agent_id)
            memories = results.get("results", [])
            logger.debug(f"Listed {len(memories)} memories for session={session_id}, agent={agent_id}")
            return memories
        except Exception as e:
            logger.warning(f"Memory list failed: {e}")
            return []
    
    def delete_session_memories(self, session_id: str) -> int:
        """Delete all memories for a session (for re-run with fresh context).
        
        Args:
            session_id: Session identifier to delete memories for
            
        Returns:
            Number of memories deleted. Returns 0 on error.
        """
        if not self.is_available():
            return 0
        
        try:
            memories = self.list_memories(session_id)
            count = 0
            for m in memories:
                memory_id = m.get("id")
                if memory_id:
                    self.memory.delete(memory_id)
                    count += 1
            logger.info(f"Deleted {count} memories for session {session_id}")
            return count
        except Exception as e:
            logger.warning(f"Memory deletion failed: {e}")
            return 0
    
    def delete_memory(self, memory_id: str) -> bool:
        """Delete a specific memory by ID.
        
        Args:
            memory_id: ID of the memory to delete
            
        Returns:
            True if deleted successfully, False otherwise.
        """
        if not self.is_available():
            return False
        
        try:
            self.memory.delete(memory_id)
            logger.debug(f"Deleted memory {memory_id}")
            return True
        except Exception as e:
            logger.warning(f"Failed to delete memory {memory_id}: {e}")
            return False
    
    def filter_by_relevance(
        self, 
        memories: List[Dict[str, Any]], 
        threshold: float = 0.5
    ) -> List[Dict[str, Any]]:
        """
        Filter memories by relevance score (cosine similarity from semantic search).
        
        Useful when cross-agent search returns many memories - filter to keep only
        highly relevant ones based on embedding similarity.
        
        Args:
            memories: List of memory dicts from search() (includes 'score' field)
            threshold: Minimum relevance score (0-1). Default 0.5 = moderate relevance
            
        Returns:
            Filtered list of high-relevance memories, sorted by score descending
        """
        if not memories:
            return []
        
        # Filter and sort by score
        filtered = []
        for m in memories:
            # mem0 search results include 'score' field (cosine similarity, higher = more relevant)
            score = m.get("score", 1.0)  # Default to 1.0 if not present (assume relevant)
            if score >= threshold:
                filtered.append(m)
        
        # Sort by score descending (most relevant first)
        filtered.sort(key=lambda x: x.get("score", 0.0), reverse=True)
        
        logger.debug(f"Filtered {len(memories)} memories to {len(filtered)} above threshold {threshold}")
        return filtered
    
    @traceable(name="mem0_overview", tags=["memory", "analysis"])
    def generate_memory_overview(
        self,
        session_id: str,
        use_llm: bool = True
    ) -> Dict[str, Any]:
        """
        Generate an overview/summary of memories for a session.
        
        Similar to ChatGPT's memory overview feature, provides:
        - Total memory count
        - Key topics and themes
        - Agent activity summary
        - LLM-generated natural language summary (optional)
        
        Args:
            session_id: Session identifier to analyze
            use_llm: Whether to use LLM for generating natural language summary
            
        Returns:
            Dictionary containing:
            - session_id: str
            - total_memories: int
            - agents: Dict[str, int] (agent_name -> memory_count)
            - memory_texts: List[str] (actual memory content)
            - summary: str (LLM-generated overview, if use_llm=True)
            - themes: List[str] (extracted key themes/topics)
        """
        if not self.is_available():
            return {
                "session_id": session_id,
                "error": "Mem0 service not available"
            }
        
        try:
            # Get all memories for this session
            memories = self.list_memories(session_id)
            
            if not memories:
                return {
                    "session_id": session_id,
                    "total_memories": 0,
                    "agents": {},
                    "memory_texts": [],
                    "summary": "No memories found for this session.",
                    "themes": []
                }
            
            # Extract memory texts and agent info
            memory_texts = []
            agent_counts = {}
            
            for m in memories:
                # Get memory text
                text = m.get("memory", "")
                if isinstance(text, str) and text.strip():
                    memory_texts.append(text.strip())
                
                # Count by agent
                metadata = m.get("metadata", {})
                agent = metadata.get("agent_id", "unknown")
                agent_counts[agent] = agent_counts.get(agent, 0) + 1
            
            # Basic statistics
            result = {
                "session_id": session_id,
                "total_memories": len(memories),
                "agents": agent_counts,
                "memory_texts": memory_texts
            }
            
            # Extract themes (simple keyword extraction from memories)
            themes = self._extract_themes(memory_texts)
            result["themes"] = themes
            
            # Generate LLM summary if requested
            if use_llm and memory_texts:
                try:
                    summary = self._generate_llm_summary(session_id, memory_texts, agent_counts, themes)
                    result["summary"] = summary
                except Exception as e:
                    logger.warning(f"Failed to generate LLM summary: {e}")
                    result["summary"] = self._generate_simple_summary(memory_texts, agent_counts, themes)
            else:
                result["summary"] = self._generate_simple_summary(memory_texts, agent_counts, themes)
            
            logger.info(f"Generated memory overview for session {session_id}: {len(memories)} memories")
            return result
            
        except Exception as e:
            logger.error(f"Failed to generate memory overview: {e}")
            return {
                "session_id": session_id,
                "error": str(e)
            }
    
    def _extract_themes(self, memory_texts: List[str], max_themes: int = 5) -> List[str]:
        """Extract key themes from memory texts using simple keyword analysis."""
        if not memory_texts:
            return []
        
        # Combine all memory texts
        combined_text = " ".join(memory_texts).lower()
        
        # Common domain-related keywords to look for
        domain_keywords = [
            "alpine", "grassland", "soil", "metagenomics", "microbiome",
            "ecology", "biodiversity", "sequencing", "elevation", "climate",
            "bacteria", "archaea", "fungi", "species", "community",
            "metadata", "ontology", "package", "field", "FAIR"
        ]
        
        # Count occurrences
        theme_counts = {}
        for keyword in domain_keywords:
            count = combined_text.count(keyword)
            if count > 0:
                theme_counts[keyword] = count
        
        # Get top themes
        sorted_themes = sorted(theme_counts.items(), key=lambda x: x[1], reverse=True)
        themes = [theme for theme, count in sorted_themes[:max_themes]]
        
        return themes
    
    def _generate_simple_summary(
        self, 
        memory_texts: List[str], 
        agent_counts: Dict[str, int],
        themes: List[str]
    ) -> str:
        """Generate a simple text summary without LLM."""
        parts = []
        
        # Overall count
        parts.append(f"This session has {len(memory_texts)} stored memories")
        
        # Agent breakdown
        if agent_counts:
            agent_list = [f"{agent} ({count})" for agent, count in sorted(agent_counts.items())]
            parts.append(f"from agents: {', '.join(agent_list)}")
        
        # Themes
        if themes:
            parts.append(f"Key themes: {', '.join(themes)}")
        
        # Sample memories
        if memory_texts:
            parts.append("\nRecent memories:")
            for i, mem in enumerate(memory_texts[:3], 1):
                # Truncate long memories
                display_mem = mem if len(mem) <= 100 else mem[:97] + "..."
                parts.append(f"  {i}. {display_mem}")
        
        return ". ".join(parts[:2]) + ".\n" + "\n".join(parts[2:])
    
    def _generate_llm_summary(
        self,
        session_id: str,
        memory_texts: List[str],
        agent_counts: Dict[str, int],
        themes: List[str]
    ) -> str:
        """Generate a natural language summary using LLM."""
        from langchain_core.messages import HumanMessage, SystemMessage
        
        # Import LLM helper to get the configured LLM
        try:
            from ..utils.llm_helper import get_llm_helper
            llm_helper = get_llm_helper()
            llm = llm_helper.llm
        except Exception as e:
            logger.warning(f"Failed to get LLM for summary: {e}")
            return self._generate_simple_summary(memory_texts, agent_counts, themes)
        
        # Prepare prompt
        system_prompt = """You are a helpful assistant that summarizes workflow memories.
        
Your task: Create a concise, natural language overview of the memories stored for this FAIR metadata workflow session.

Style: Write like ChatGPT's memory overview - friendly, informative, and highlighting what the system has learned.

Focus on:
- Key research domains and topics identified
- Notable patterns or associations learned
- Important metadata mappings discovered
- Any user preferences or workflow patterns

Keep it concise (2-3 paragraphs max) and conversational."""
        
        # Build context
        context_parts = [
            f"Session ID: {session_id}",
            f"Total memories: {len(memory_texts)}",
            f"Agents involved: {', '.join(f'{agent} ({count} memories)' for agent, count in agent_counts.items())}",
            f"Key themes: {', '.join(themes) if themes else 'none identified'}",
            "\nMemory contents:",
        ]
        
        # Add memories (limit to avoid token overflow)
        max_memories = 15
        for i, mem in enumerate(memory_texts[:max_memories], 1):
            context_parts.append(f"{i}. {mem}")
        
        if len(memory_texts) > max_memories:
            context_parts.append(f"... and {len(memory_texts) - max_memories} more memories")
        
        user_prompt = "\n".join(context_parts)
        
        # Call LLM
        try:
            messages = [
                SystemMessage(content=system_prompt),
                HumanMessage(content=user_prompt)
            ]
            
            response = llm.invoke(messages)
            summary = response.content.strip()
            
            logger.debug(f"Generated LLM summary ({len(summary)} chars)")
            return summary
            
        except Exception as e:
            logger.warning(f"LLM summary generation failed: {e}")
            return self._generate_simple_summary(memory_texts, agent_counts, themes)


def build_mem0_config(
    llm_provider: str = "ollama",
    llm_model: str = "qwen3:30b",
    llm_base_url: str = "http://localhost:11434",
    llm_api_key: Optional[str] = None,
    embedding_model: str = "nomic-embed-text",
    embedding_base_url: str = None,
    embedding_model_dims: int = 768,
    qdrant_host: str = "localhost",
    qdrant_port: int = 6333,
    collection_name: str = "fairifier_memories"
) -> dict:
    """Build mem0 configuration dictionary.
    
    Uses only mem0-supported LLM providers (ollama, openai, anthropic). The
    provider and URLs/keys are set separately for mem0 (MEM0_LLM_PROVIDER,
    MEM0_LLM_BASE_URL, MEM0_LLM_API_KEY, MEM0_OLLAMA_BASE_URL) and are not
    derived from the main workflow LLM.
    
    embedding_model_dims must match the embedder output (e.g. nomic-embed-text
    is 768; OpenAI text-embedding-ada-002 is 1536) so the vector store creates
    collections with the correct dimension.
    
    Args:
        llm_provider: mem0 LLM provider (ollama, openai, anthropic)
        llm_model: LLM model name for fact extraction
        llm_base_url: Base URL for LLM API (used for ollama or openai base)
        llm_api_key: API key for openai/anthropic (optional for ollama)
        embedding_model: Embedding model name
        embedding_base_url: Base URL for embedding API (defaults to llm_base_url)
        embedding_model_dims: Vector dimension from embedder (default 768 for nomic-embed-text)
        qdrant_host: Qdrant server host
        qdrant_port: Qdrant server port
        collection_name: Qdrant collection name for memories
        
    Returns:
        Configuration dictionary for mem0.Memory.from_config()
    """
    if embedding_base_url is None:
        embedding_base_url = llm_base_url

    if llm_provider == "openai":
        llm_config = {
            "model": llm_model,
            "temperature": 0.1,
            "openai_base_url": llm_base_url,
        }
        if llm_api_key:
            llm_config["api_key"] = llm_api_key
    elif llm_provider == "anthropic":
        llm_config = {
            "model": llm_model,
            "temperature": 0.1,
        }
        if llm_api_key:
            llm_config["api_key"] = llm_api_key
    else:
        # ollama (default): mem0 expects ollama_base_url
        llm_config = {
            "model": llm_model,
            "temperature": 0.1,
            "ollama_base_url": llm_base_url,
        }

    return {
        "llm": {
            "provider": llm_provider,
            "config": llm_config,
        },
        "embedder": {
            "provider": "ollama",
            "config": {
                "model": embedding_model,
                "ollama_base_url": embedding_base_url,
            }
        },
        "vector_store": {
            "provider": "qdrant",
            "config": {
                "host": qdrant_host,
                "port": qdrant_port,
                "collection_name": collection_name,
                "embedding_model_dims": embedding_model_dims,
            }
        },
        "custom_fact_extraction_prompt": FAIR_FACT_EXTRACTION_PROMPT,
    }


def get_mem0_service() -> Optional[Mem0Service]:
    """Get the global Mem0Service instance.
    
    Returns the singleton instance if mem0 is enabled in config,
    otherwise returns None.
    
    Returns:
        Mem0Service instance or None if disabled/unavailable.
    """
    global _mem0_service
    
    if _mem0_service is not None:
        return _mem0_service
    
    # Import config here to avoid circular imports
    try:
        from ..config import config
        
        if not config.mem0_enabled:
            logger.debug("Mem0 is disabled in configuration")
            return None
        
        # When main workflow uses Qwen (DashScope), mem0 has no "qwen" provider; use openai
        # provider with OpenAI-compatible API (same base URL, API key, and model as main workflow).
        if config.llm_provider == "qwen":
            mem0_llm_provider = "openai"
            mem0_llm_base = config.llm_base_url
            mem0_llm_api_key = config.llm_api_key
            mem0_llm_model = config.llm_model  # Use main workflow model (e.g. qwen-plus-latest); DashScope has no "qwen3:32b"
            logger.debug(
                "Main LLM is Qwen (DashScope); mem0 will use openai provider with OpenAI-compatible API (model=%s)",
                mem0_llm_model,
            )
        else:
            mem0_llm_provider = config.mem0_llm_provider
            mem0_llm_base = config.mem0_llm_base_url or config.mem0_ollama_base_url or config.llm_base_url
            mem0_llm_api_key = config.mem0_llm_api_key
            mem0_llm_model = config.mem0_llm_model or config.llm_model
        
        mem0_config = build_mem0_config(
            llm_provider=mem0_llm_provider,
            llm_model=mem0_llm_model,
            llm_base_url=mem0_llm_base,
            llm_api_key=mem0_llm_api_key,
            embedding_model=config.mem0_embedding_model,
            embedding_base_url=config.mem0_ollama_base_url or config.llm_base_url,
            embedding_model_dims=config.mem0_embedding_dims,
            qdrant_host=config.mem0_qdrant_host,
            qdrant_port=config.mem0_qdrant_port,
            collection_name=config.mem0_collection_name,
        )
        
        _mem0_service = Mem0Service(mem0_config)
        
        if not _mem0_service.is_available():
            if config.mem0_strict:
                err = getattr(_mem0_service, "_init_error", None) or RuntimeError(
                    "Mem0 was enabled (MEM0_ENABLED=true) but failed to initialize."
                )
                _mem0_service = None
                raise err
            logger.info(
                "Mem0 not available (optional). Workflow continues without memory layer."
            )
            _mem0_service = None
            return None
        
        return _mem0_service
        
    except ImportError as e:
        logger.warning("mem0 optional: mem0ai package not installed: %s", e)
        return None
    except Exception as e:
        if getattr(config, "mem0_strict", False) and getattr(config, "mem0_enabled", False):
            raise
        logger.warning("Mem0 optional: init failed, continuing without memory layer: %s", e)
        return None


def reset_mem0_service():
    """Reset the global Mem0Service instance.
    
    Useful for testing or when configuration changes.
    """
    global _mem0_service
    _mem0_service = None
    logger.debug("Mem0 service instance reset")
