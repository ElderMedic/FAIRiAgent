from fairifier.apps.api.routers.v1 import memory_cloud
from fairifier.config import config
import asyncio

class MockApp:
    state = type('obj', (object,), {'store': type('obj', (object,), {'get_project': lambda self, pid: {'session_id': 'test_ui_session'}})()})

class MockRequest:
    app = MockApp()

async def main():
    res = await memory_cloud("eval_ollama_qwen3.6-35b_v1.4.0_cb_mt_sorted_bam_run1", MockRequest())
    if res.scope_words:
        print("Sample scope word:", res.scope_words[0].model_dump())

if __name__ == "__main__":
    # Ensure mem0 is enabled
    config.mem0_enabled = True
    config.mem0_llm_provider = "ollama"
    config.mem0_llm_model = "qwen3.6:35b"
    config.mem0_embedding_model = "nomic-embed-text-v2-moe:latest"
    config.mem0_qdrant_host = "localhost"
    asyncio.run(main())
