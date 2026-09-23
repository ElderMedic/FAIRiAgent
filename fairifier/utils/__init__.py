"""Utility modules for FAIRifier.

The LLM helper is intentionally imported lazily.  Importing it from the
package initializer freezes the global configuration singleton, which breaks
per-run model configuration loading in evaluation runners.
"""

from .json_logger import JSONLogger, get_logger, set_logger

__all__ = [
    "JSONLogger", "get_logger", "set_logger",
    "LLMHelper", "get_llm_helper", "save_llm_responses"
]


def __getattr__(name):
    if name in {"LLMHelper", "get_llm_helper", "save_llm_responses"}:
        from .llm_helper import LLMHelper, get_llm_helper, save_llm_responses

        return {
            "LLMHelper": LLMHelper,
            "get_llm_helper": get_llm_helper,
            "save_llm_responses": save_llm_responses,
        }[name]
    raise AttributeError(name)
