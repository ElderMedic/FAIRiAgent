"""
Provider-aware structured LLM output.

DeepSeek supports ``response_format={'type': 'json_object'}`` only (not JSON Schema).
See: https://api-docs.deepseek.com/guides/json_mode

OpenAI supports LangChain ``with_structured_output`` (JSON Schema) and ``json_object``.
Other providers fall back to prompt-guided JSON parsing.
"""

from __future__ import annotations

import json
import logging
from enum import Enum
from typing import Any, Dict, List, Optional, Type, Union, get_args, get_origin

from langchain_core.messages import BaseMessage, HumanMessage
from pydantic import BaseModel

from fairifier.config import config
from fairifier.utils.json_parse import parse_llm_json

logger = logging.getLogger(__name__)


class StructuredOutputMode(str, Enum):
    JSON_SCHEMA = "json_schema"
    JSON_OBJECT = "json_object"
    PROMPT_JSON = "prompt_json"


def resolve_structured_output_mode(provider: Optional[str] = None) -> StructuredOutputMode:
    """Pick the best structured-output strategy for the active LLM provider."""
    normalized = (provider or config.llm_provider or "").lower()
    if normalized == "google":
        normalized = "gemini"
    if normalized == "claude":
        normalized = "anthropic"

    if normalized == "deepseek":
        return StructuredOutputMode.JSON_OBJECT
    if normalized == "openai":
        return StructuredOutputMode.JSON_SCHEMA
    return StructuredOutputMode.PROMPT_JSON


def pydantic_json_example(model: Type[BaseModel]) -> Dict[str, Any]:
    """Build a small example object from a Pydantic model (for prompt guidance)."""
    example: Dict[str, Any] = {}
    for name, field in model.model_fields.items():
        annotation = field.annotation
        origin = get_origin(annotation)
        if origin is Union:
            args = [a for a in get_args(annotation) if a is not type(None)]
            annotation = args[0] if args else str

        if annotation is float:
            example[name] = 0.85
        elif annotation is int:
            example[name] = 1
        elif annotation is bool:
            example[name] = True
        elif origin is list or annotation is list:
            inner = get_args(annotation)[0] if get_args(annotation) else str
            example[name] = [] if inner is str else []
        elif annotation is dict:
            example[name] = {}
        else:
            example[name] = f"example {name.replace('_', ' ')}"
    return example


def append_json_schema_instructions(
    prompt: str,
    model: Type[BaseModel],
    *,
    require_json_word: bool = True,
) -> str:
    """
    Extend a prompt with JSON output instructions.

    DeepSeek requires the word ``json`` in the prompt when using JSON Output mode.
    """
    example = pydantic_json_example(model)
    example_text = json.dumps(example, indent=2, ensure_ascii=False)
    property_names = list(model.model_json_schema().get("properties", {}).keys())

    json_hint = ""
    if require_json_word and "json" not in prompt.lower():
        json_hint = "Respond with valid JSON only.\n\n"

    return (
        f"{prompt}\n\n"
        f"{json_hint}"
        "OUTPUT FORMAT — JSON OBJECT (required keys only, no markdown fences):\n"
        f"{example_text}\n\n"
        f"Required JSON keys: {property_names}\n"
        "Return a single JSON object. No preamble or explanation outside JSON."
    )


def _enhance_messages_for_json_object(
    messages: List[BaseMessage],
    model: Type[BaseModel],
) -> List[BaseMessage]:
    """Append schema hints to the last human message for json_object providers."""
    if not messages:
        return messages

    enhanced: List[BaseMessage] = list(messages)
    last = enhanced[-1]
    if isinstance(last, HumanMessage):
        content = append_json_schema_instructions(str(last.content or ""), model)
        enhanced[-1] = HumanMessage(content=content)
    else:
        enhanced.append(
            HumanMessage(content=append_json_schema_instructions("", model))
        )
    return enhanced


def _coerce_to_dict(parsed: Any, model: Type[BaseModel]) -> Optional[Dict[str, Any]]:
    if parsed is None:
        return None
    if isinstance(parsed, BaseModel):
        return parsed.model_dump()
    if isinstance(parsed, dict):
        return parsed
    return None


async def invoke_structured_output(
    llm_helper,
    messages: List[BaseMessage],
    schema_model: Type[BaseModel],
    *,
    operation_name: str = "StructuredOutput",
    max_tokens: Optional[int] = None,
    provider: Optional[str] = None,
) -> Optional[Dict[str, Any]]:
    """
    Invoke an LLM and parse a structured Pydantic-shaped JSON response.

    Strategy by provider:
    - deepseek: ``response_format={'type': 'json_object'}`` (DeepSeek JSON Output)
    - openai: LangChain ``with_structured_output`` (JSON Schema), then fallbacks
    - others: prompt-guided JSON parsing
    """
    mode = resolve_structured_output_mode(provider or llm_helper.provider)

    if mode == StructuredOutputMode.JSON_SCHEMA:
        try:
            llm = llm_helper.get_llm()
            if max_tokens is not None:
                if hasattr(llm, "max_tokens"):
                    llm.max_tokens = max_tokens
                if hasattr(llm, "num_predict"):
                    llm.num_predict = max_tokens
            structured_llm = llm.with_structured_output(schema_model)
            result = await structured_llm.ainvoke(messages)
            return _coerce_to_dict(result, schema_model)
        except Exception as exc:
            logger.debug(
                "JSON Schema structured output unavailable (%s); trying json_object fallback",
                exc,
            )
            mode = StructuredOutputMode.JSON_OBJECT

    if mode == StructuredOutputMode.JSON_OBJECT:
        try:
            enhanced = _enhance_messages_for_json_object(messages, schema_model)
            response = await llm_helper._call_llm(
                enhanced,
                operation_name=operation_name,
                json_mode=True,
                max_tokens=max_tokens,
            )
            content = getattr(response, "content", "") if response else ""
            return parse_llm_json(content)
        except Exception as exc:
            logger.warning(
                "JSON Object mode failed (%s); falling back to prompt JSON",
                exc,
            )
            mode = StructuredOutputMode.PROMPT_JSON

    prompt_messages = _enhance_messages_for_json_object(messages, schema_model)
    response = await llm_helper._call_llm(
        prompt_messages,
        operation_name=operation_name,
        max_tokens=max_tokens,
    )
    content = getattr(response, "content", "") if response else ""
    return parse_llm_json(content)


def supports_api_json_object(provider: Optional[str] = None) -> bool:
    """Return True when the provider exposes OpenAI-style json_object response_format."""
    normalized = (provider or config.llm_provider or "").lower()
    return normalized in {"deepseek", "openai", "qwen"}
