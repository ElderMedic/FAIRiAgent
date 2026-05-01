"""
Mem0 Memory Service for FAIRiAgent multi-agent system.

Provides persistent semantic memory for context compression and retrieval
across the workflow session. The service performs runtime health checks and
can auto-configure embedding/model backends when local dependencies are absent.
"""

from typing import List, Dict, Any, Optional
import logging
import hashlib
import json
import subprocess
import time
from urllib.request import urlopen
from urllib.error import HTTPError, URLError

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
            self._seen_message_fingerprints: set[str] = set()
            logger.info("Mem0 service initialized successfully")
        except Exception as e:
            self._init_error = e
            self.memory = None
            self.enabled = False
            self._config = config
            self._seen_message_fingerprints = set()
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
            normalized_messages = [
                {
                    "role": str(msg.get("role", "")).strip(),
                    "content": str(msg.get("content", "")).strip(),
                }
                for msg in messages
                if isinstance(msg, dict) and str(msg.get("content", "")).strip()
            ]
            if not normalized_messages:
                logger.debug("Skipping mem0 add with empty/blank messages for session=%s agent=%s", session_id, agent_id)
                return {"results": [], "skipped": "empty_messages"}

            fingerprint = self._fingerprint_messages(normalized_messages, session_id, agent_id)
            if fingerprint in self._seen_message_fingerprints:
                logger.debug("Skipping duplicate mem0 add for session=%s agent=%s", session_id, agent_id)
                return {"results": [], "skipped": "duplicate_messages"}

            result = self.memory.add(
                messages=normalized_messages,
                user_id=session_id,
                agent_id=agent_id,
                metadata=metadata or {}
            )
            self._seen_message_fingerprints.add(fingerprint)
            added_count = len(result.get("results", []))
            logger.debug(f"Added {added_count} memories for session={session_id}, agent={agent_id}")
            return result
        except Exception as e:
            logger.warning(f"Memory add failed: {e}")
            return {}

    def _fingerprint_messages(
        self,
        messages: List[Dict[str, str]],
        session_id: str,
        agent_id: Optional[str],
    ) -> str:
        """Create a stable fingerprint for duplicate write suppression."""
        payload = {
            "session_id": session_id,
            "agent_id": agent_id or "",
            "messages": messages,
        }
        return hashlib.sha256(
            json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8")
        ).hexdigest()
    
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
    embedding_provider: str = "ollama",
    embedding_model: str = "nomic-embed-text",
    embedding_base_url: str = None,
    embedding_api_key: Optional[str] = None,
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
        embedding_provider: Embedder provider (ollama, openai, azure_openai, etc.)
        embedding_model: Embedding model name
        embedding_base_url: Base URL for embedding API (defaults to llm_base_url)
        embedding_api_key: API key for openai-compatible embedding APIs
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

    if embedding_provider == "openai":
        embedder_config = {
            "model": embedding_model,
            "embedding_dims": embedding_model_dims,
            "openai_base_url": embedding_base_url,
        }
        if embedding_api_key:
            embedder_config["api_key"] = embedding_api_key
    else:
        embedder_config = {
            "model": embedding_model,
            "ollama_base_url": embedding_base_url,
        }

    return {
        "llm": {
            "provider": llm_provider,
            "config": llm_config,
        },
        "embedder": {
            "provider": embedding_provider,
            "config": embedder_config,
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


_LOCAL_HOST_ALIASES = {"localhost", "127.0.0.1", "0.0.0.0", "::1"}


def _sanitize_collection_token(
    value: Optional[str],
    fallback: str,
    max_length: int = 18,
) -> str:
    raw = (value or "").strip().lower()
    token = "".join(
        ch if ch.isalnum() else "-"
        for ch in raw
    ).strip("-")
    while "--" in token:
        token = token.replace("--", "-")
    token = token[:max_length].strip("-")
    return token or fallback


def resolve_mem0_collection_name(
    base_name: str,
    *,
    embedding_provider: str,
    embedding_model: str,
    embedding_dims: int,
    embedding_base_url: Optional[str] = None,
) -> str:
    """Derive a stable Qdrant collection name for the effective embedding profile.

    This prevents accidental reuse of the same collection across incompatible
    embedding dimensions or providers.
    """
    base = (base_name or "fairifier_memories").strip()
    fingerprint_source = json.dumps(
        {
            "provider": embedding_provider,
            "model": embedding_model,
            "dims": int(embedding_dims),
            "base_url": embedding_base_url or "",
        },
        sort_keys=True,
        ensure_ascii=False,
    )
    fingerprint = hashlib.sha1(
        fingerprint_source.encode("utf-8")
    ).hexdigest()[:10]
    provider_token = _sanitize_collection_token(
        embedding_provider, "embed"
    )
    return (
        f"{base}__{provider_token}_{int(embedding_dims)}d_{fingerprint}"
    )


def _is_local_host(host: str) -> bool:
    return (host or "").strip().lower() in _LOCAL_HOST_ALIASES


def _http_get_json(url: str, timeout_seconds: int = 2) -> Optional[Dict[str, Any]]:
    req = url if "://" in url else f"http://{url}"
    try:
        with urlopen(req, timeout=max(timeout_seconds, 1)) as response:
            payload = response.read().decode("utf-8", errors="replace")
            return json.loads(payload) if payload else {}
    except (HTTPError, URLError, TimeoutError, ValueError):
        return None


def _is_http_endpoint_reachable(url: str, timeout_seconds: int = 2) -> bool:
    req = url if "://" in url else f"http://{url}"
    try:
        with urlopen(req, timeout=max(timeout_seconds, 1)) as response:
            return 200 <= getattr(response, "status", 200) < 500
    except HTTPError as exc:
        # HTTP errors still indicate endpoint reachability.
        return 400 <= exc.code < 500
    except (URLError, TimeoutError):
        return False


def _is_qdrant_available(host: str, port: int, timeout_seconds: int = 2) -> bool:
    return _is_http_endpoint_reachable(
        f"http://{host}:{port}/collections",
        timeout_seconds=timeout_seconds,
    )


def _is_ollama_available(base_url: Optional[str], timeout_seconds: int = 2) -> bool:
    if not base_url:
        return False
    normalized = base_url.rstrip("/")
    return _is_http_endpoint_reachable(
        f"{normalized}/api/tags",
        timeout_seconds=timeout_seconds,
    )


def _ollama_has_model(base_url: Optional[str], model_name: str, timeout_seconds: int = 2) -> bool:
    if not base_url or not model_name:
        return False
    payload = _http_get_json(f"{base_url.rstrip('/')}/api/tags", timeout_seconds=timeout_seconds)
    if not payload:
        return False
    candidates = set()
    for item in payload.get("models", []):
        name = (item or {}).get("name")
        model = (item or {}).get("model")
        if name:
            candidates.add(str(name))
        if model:
            candidates.add(str(model))
    return any(
        c == model_name
        or c.startswith(f"{model_name}:")
        or model_name.startswith(f"{c}:")
        for c in candidates
    )


def _docker_available() -> bool:
    try:
        check = subprocess.run(
            ["docker", "version"],
            check=False,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            text=True,
            timeout=8,
        )
        return check.returncode == 0
    except Exception:
        return False


def _try_auto_start_qdrant(
    host: str,
    port: int,
    container_name: str,
    timeout_seconds: int = 20,
) -> bool:
    if not _is_local_host(host):
        logger.warning(
            "Qdrant host '%s' is not local; auto-start skipped for safety.",
            host,
        )
        return False

    if not _docker_available():
        logger.warning("Docker not available; cannot auto-start local Qdrant container.")
        return False

    resolved_name = container_name if port == 6333 else f"{container_name}-{port}"
    check_running = subprocess.run(
        ["docker", "ps", "--filter", f"name=^/{resolved_name}$", "--format", "{{.Names}}"],
        check=False,
        capture_output=True,
        text=True,
        timeout=10,
    )
    if resolved_name in check_running.stdout.splitlines():
        return True

    check_exists = subprocess.run(
        ["docker", "ps", "-a", "--filter", f"name=^/{resolved_name}$", "--format", "{{.Names}}"],
        check=False,
        capture_output=True,
        text=True,
        timeout=10,
    )

    if resolved_name in check_exists.stdout.splitlines():
        start_cmd = ["docker", "start", resolved_name]
    else:
        start_cmd = [
            "docker",
            "run",
            "-d",
            "--name",
            resolved_name,
            "--restart",
            "unless-stopped",
            "-p",
            f"{port}:6333",
            "qdrant/qdrant:latest",
        ]

    start = subprocess.run(
        start_cmd,
        check=False,
        capture_output=True,
        text=True,
        timeout=30,
    )
    if start.returncode != 0:
        logger.warning(
            "Failed to auto-start Qdrant via Docker (%s): %s",
            " ".join(start_cmd),
            (start.stderr or start.stdout or "unknown error").strip().splitlines()[0],
        )
        return False

    deadline = time.time() + max(timeout_seconds, 1)
    while time.time() < deadline:
        if _is_qdrant_available(host, port, timeout_seconds=2):
            logger.info("Auto-started local Qdrant container '%s' on port %s.", resolved_name, port)
            return True
        time.sleep(0.5)
    logger.warning("Qdrant container started but did not become healthy within %ss.", timeout_seconds)
    return False


def _infer_api_llm_profile(config: Any) -> Optional[Dict[str, Optional[str]]]:
    if config.llm_provider in {"qwen", "openai"} and config.llm_api_key:
        return {
            "provider": "openai",
            "model": config.llm_model,
            "base_url": config.llm_base_url,
            "api_key": config.llm_api_key,
        }
    if config.llm_provider == "anthropic" and config.llm_api_key:
        return {
            "provider": "anthropic",
            "model": config.llm_model,
            "base_url": None,
            "api_key": config.llm_api_key,
        }
    if config.mem0_llm_api_key:
        provider = config.mem0_llm_provider if config.mem0_llm_provider in {"openai", "anthropic"} else "openai"
        return {
            "provider": provider,
            "model": config.mem0_llm_model or config.llm_model,
            "base_url": config.mem0_llm_base_url or config.llm_base_url,
            "api_key": config.mem0_llm_api_key,
        }
    return None


def _infer_api_embedding_profile(
    config: Any,
    mem0_llm_provider: str,
    mem0_llm_base: Optional[str],
    mem0_llm_api_key: Optional[str],
) -> Optional[Dict[str, Any]]:
    if config.llm_provider == "qwen" and config.llm_api_key and config.llm_base_url:
        return {
            "provider": "openai",
            "model": "text-embedding-v4",
            "base_url": config.llm_base_url,
            "api_key": config.llm_api_key,
            "dims": 1024,
        }
    if config.llm_provider == "openai" and config.llm_api_key:
        return {
            "provider": "openai",
            "model": "text-embedding-3-small",
            "base_url": config.llm_base_url or "https://api.openai.com/v1",
            "api_key": config.llm_api_key,
            "dims": 1536,
        }
    if config.mem0_embedding_api_key and (config.mem0_embedding_base_url or mem0_llm_base):
        return {
            "provider": "openai",
            "model": config.mem0_embedding_model or "text-embedding-3-small",
            "base_url": config.mem0_embedding_base_url or mem0_llm_base,
            "api_key": config.mem0_embedding_api_key,
            "dims": config.mem0_embedding_dims or 1536,
        }
    if mem0_llm_provider == "openai" and mem0_llm_api_key and mem0_llm_base:
        return {
            "provider": "openai",
            "model": "text-embedding-3-small",
            "base_url": mem0_llm_base,
            "api_key": mem0_llm_api_key,
            "dims": 1536,
        }
    return None


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

        # mem0 supports ollama/openai/anthropic only.
        # For Qwen main workflow (OpenAI-compatible DashScope), route mem0 LLM via openai provider.
        if config.llm_provider == "qwen":
            mem0_llm_provider = "openai"
            mem0_llm_base = config.llm_base_url
            mem0_llm_api_key = config.llm_api_key
            mem0_llm_model = config.llm_model
            logger.debug(
                "Main LLM is Qwen (DashScope); mem0 LLM will use openai-compatible API (model=%s).",
                mem0_llm_model,
            )
        else:
            mem0_llm_provider = config.mem0_llm_provider
            mem0_llm_base = config.mem0_llm_base_url or config.mem0_ollama_base_url or config.llm_base_url
            mem0_llm_api_key = config.mem0_llm_api_key
            mem0_llm_model = config.mem0_llm_model or config.llm_model

        embedding_provider = config.mem0_embedding_provider
        embedding_model = config.mem0_embedding_model
        embedding_api_key = config.mem0_embedding_api_key or mem0_llm_api_key
        embedding_dims = config.mem0_embedding_dims

        # Ollama embeddings must use an Ollama base URL — never fall through to the main LLM URL
        # (e.g. DashScope when LLM_PROVIDER=qwen). OpenAI-compatible embedding APIs use explicit base URL.
        if embedding_provider == "ollama":
            embedding_base_url = (
                config.mem0_embedding_base_url
                or config.mem0_ollama_base_url
                or "http://localhost:11434"
            )
        else:
            embedding_base_url = (
                config.mem0_embedding_base_url
                or config.mem0_llm_base_url
                or config.llm_base_url
            )

        if config.mem0_auto_setup:
            timeout = max(int(config.mem0_healthcheck_timeout_seconds or 2), 1)

            # Health-check vector DB and try auto-start for local Qdrant.
            qdrant_ready = _is_qdrant_available(
                config.mem0_qdrant_host,
                config.mem0_qdrant_port,
                timeout_seconds=timeout,
            )
            if not qdrant_ready and config.mem0_auto_start_qdrant:
                qdrant_ready = _try_auto_start_qdrant(
                    host=config.mem0_qdrant_host,
                    port=config.mem0_qdrant_port,
                    container_name=config.mem0_qdrant_container_name,
                    timeout_seconds=max(timeout * 6, 8),
                )
            if not qdrant_ready:
                msg = (
                    "Mem0 preflight failed: Qdrant is unreachable at "
                    f"{config.mem0_qdrant_host}:{config.mem0_qdrant_port}."
                )
                if config.mem0_strict:
                    raise RuntimeError(msg)
                logger.warning("%s Memory layer will be skipped for this run.", msg)
                return None

            # If mem0 LLM points to local Ollama but service is down, auto-fallback to API profile.
            if mem0_llm_provider == "ollama":
                ollama_ok = _is_ollama_available(mem0_llm_base, timeout_seconds=timeout)
                if not ollama_ok:
                    llm_fallback = _infer_api_llm_profile(config)
                    if llm_fallback:
                        mem0_llm_provider = llm_fallback["provider"]  # type: ignore[index]
                        mem0_llm_model = llm_fallback["model"] or mem0_llm_model  # type: ignore[index]
                        mem0_llm_base = llm_fallback["base_url"] or mem0_llm_base  # type: ignore[index]
                        mem0_llm_api_key = llm_fallback["api_key"] or mem0_llm_api_key  # type: ignore[index]
                        logger.info(
                            "Mem0 LLM fallback activated: provider=%s, model=%s",
                            mem0_llm_provider,
                            mem0_llm_model,
                        )
                    else:
                        msg = (
                            "Mem0 preflight failed: Ollama is unreachable and no API-based mem0 LLM "
                            "credentials are available."
                        )
                        if config.mem0_strict:
                            raise RuntimeError(msg)
                        logger.warning("%s Memory layer will be skipped for this run.", msg)
                        return None

            # If embedder uses local Ollama but service/model is unavailable, switch to API embeddings.
            if embedding_provider == "ollama":
                ollama_ok = _is_ollama_available(embedding_base_url, timeout_seconds=timeout)
                model_ok = ollama_ok and _ollama_has_model(
                    embedding_base_url,
                    embedding_model,
                    timeout_seconds=timeout,
                )
                if not ollama_ok or not model_ok:
                    embedding_fallback = _infer_api_embedding_profile(
                        config,
                        mem0_llm_provider=mem0_llm_provider,
                        mem0_llm_base=mem0_llm_base,
                        mem0_llm_api_key=mem0_llm_api_key,
                    )
                    if embedding_fallback:
                        embedding_provider = embedding_fallback["provider"]
                        embedding_model = embedding_fallback["model"]
                        embedding_base_url = embedding_fallback["base_url"]
                        embedding_api_key = embedding_fallback["api_key"]
                        embedding_dims = int(embedding_fallback["dims"])
                        reason = "ollama_unreachable" if not ollama_ok else "embedding_model_missing"
                        logger.info(
                            "Mem0 embedding fallback activated (%s): provider=%s, model=%s, dims=%s",
                            reason,
                            embedding_provider,
                            embedding_model,
                            embedding_dims,
                        )
                    else:
                        msg = (
                            "Mem0 preflight failed: Ollama embedding backend unavailable and no "
                            "API embedding fallback credentials detected."
                        )
                        if config.mem0_strict:
                            raise RuntimeError(msg)
                        logger.warning("%s Memory layer will be skipped for this run.", msg)
                        return None

        mem0_config = build_mem0_config(
            collection_name=resolve_mem0_collection_name(
                config.mem0_collection_name,
                embedding_provider=embedding_provider,
                embedding_model=embedding_model,
                embedding_dims=int(embedding_dims),
                embedding_base_url=embedding_base_url,
            ),
            llm_provider=mem0_llm_provider,
            llm_model=mem0_llm_model,
            llm_base_url=mem0_llm_base,
            llm_api_key=mem0_llm_api_key,
            embedding_provider=embedding_provider,
            embedding_model=embedding_model,
            embedding_base_url=embedding_base_url,
            embedding_api_key=embedding_api_key,
            embedding_model_dims=embedding_dims,
            qdrant_host=config.mem0_qdrant_host,
            qdrant_port=config.mem0_qdrant_port,
        )

        _mem0_service = Mem0Service(mem0_config)
        if not _mem0_service.is_available():
            if config.mem0_strict:
                err = getattr(_mem0_service, "_init_error", None) or RuntimeError(
                    "Mem0 was enabled but failed to initialize."
                )
                _mem0_service = None
                raise err
            logger.info("Mem0 unavailable after setup. Workflow continues without memory layer.")
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
