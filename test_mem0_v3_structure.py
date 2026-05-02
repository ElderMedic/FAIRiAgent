from fairifier.services.mem0_service import get_mem0_service
from fairifier.config import config
import os

config.mem0_enabled = True
config.mem0_llm_provider = "ollama"
config.mem0_llm_model = "qwen3.6:9b"
config.mem0_embedding_model = "nomic-embed-text-v2-moe:latest"
config.mem0_qdrant_host = "localhost"

mem0 = get_mem0_service()
if mem0 and mem0.is_available():
    print("Mem0 is available")
    # Add a strong memory fact
    res = mem0.add([{"role": "user", "content": "My name is John and I live in Tokyo. I always use Qwen models."}], "test_ui_session", agent_id="TestAgent")
    print("Add result:", res)
    # List memories
    mems = mem0.list_memories("test_ui_session")
    print("Listed memories:", mems)
else:
    print("Mem0 not available")
