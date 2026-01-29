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
        try:
            from mem0 import Memory
            self.memory = Memory.from_config(config)
            self.enabled = True
            self._config = config
            logger.info("Mem0 service initialized successfully")
        except Exception as e:
            logger.error(f"Failed to initialize mem0: {e}")
            self.memory = None
            self.enabled = False
            self._config = config
    
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


def build_mem0_config(
    llm_provider: str = "ollama",
    llm_model: str = "qwen3:30b",
    llm_base_url: str = "http://localhost:11434",
    embedding_model: str = "nomic-embed-text",
    embedding_base_url: str = None,
    qdrant_host: str = "localhost",
    qdrant_port: int = 6333,
    collection_name: str = "fairifier_memories"
) -> dict:
    """Build mem0 configuration dictionary.
    
    Args:
        llm_provider: LLM provider name (default: ollama)
        llm_model: LLM model name for fact extraction
        llm_base_url: Base URL for LLM API
        embedding_model: Embedding model name
        embedding_base_url: Base URL for embedding API (defaults to llm_base_url)
        qdrant_host: Qdrant server host
        qdrant_port: Qdrant server port
        collection_name: Qdrant collection name for memories
        
    Returns:
        Configuration dictionary for mem0.Memory.from_config()
    """
    if embedding_base_url is None:
        embedding_base_url = llm_base_url
    
    return {
        "llm": {
            "provider": llm_provider,
            "config": {
                "model": llm_model,
                "ollama_base_url": llm_base_url,
                "temperature": 0.1,  # Low temperature for consistent fact extraction
            }
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
            }
        }
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
        
        mem0_config = build_mem0_config(
            llm_provider=config.llm_provider,
            llm_model=config.mem0_llm_model or config.llm_model,
            llm_base_url=config.mem0_ollama_base_url or config.llm_base_url,
            embedding_model=config.mem0_embedding_model,
            embedding_base_url=config.mem0_ollama_base_url or config.llm_base_url,
            qdrant_host=config.mem0_qdrant_host,
            qdrant_port=config.mem0_qdrant_port,
            collection_name=config.mem0_collection_name,
        )
        
        _mem0_service = Mem0Service(mem0_config)
        
        if not _mem0_service.is_available():
            logger.warning("Mem0 service initialized but not available")
            _mem0_service = None
            return None
        
        return _mem0_service
        
    except ImportError as e:
        logger.warning(f"mem0ai package not installed: {e}")
        return None
    except Exception as e:
        logger.warning(f"Failed to initialize mem0 service: {e}")
        return None


def reset_mem0_service():
    """Reset the global Mem0Service instance.
    
    Useful for testing or when configuration changes.
    """
    global _mem0_service
    _mem0_service = None
    logger.debug("Mem0 service instance reset")
