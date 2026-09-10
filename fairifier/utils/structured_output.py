"""
Provider-aware structured LLM output.

DeepSeek supports ``response_format={'type': 'json_object'}`` only (not JSON Schema).
See: https://api-docs.deepseek.com/guides/json_mode

OpenAI supports LangChain ``with_structured_output`` (JSON Schema) and ``json_object``.
Other providers fall back to prompt-guided JSON parsing.
"""

from __future__ import annotations

import asyncio
import json
import logging
from enum import Enum
from typing import Any, Dict, List, Optional, Type, Union, get_args, get_origin

from langchain_core.messages import BaseMessage, HumanMessage
from pydantic import BaseModel, ValidationError

from fairifier.config import config
from fairifier.utils.json_parse import parse_llm_json

logger = logging.getLogger(__name__)


async def _invoke_prompt_json_with_transport_retry(
    llm_helper,
    messages: List[BaseMessage],
    *,
    operation_name: str,
    max_tokens: Optional[int],
    attempts: int = 2,
) -> Any:
    """Call a prompt-JSON provider without leaking transient transport errors.

    Provider clients normally retry failures that happen before a response is
    opened, but streamed local responses can still end with an incomplete body.
    A structured-output audit is not allowed to crash the whole workflow for
    that reason.  Retry the identical bounded request once, then return ``None``
    so the owning agent can fail its deterministic validation or use its own
    stage-level retry policy.
    """
    last_error: Optional[Exception] = None
    for attempt in range(1, max(1, attempts) + 1):
        try:
            return await llm_helper._call_llm(
                messages,
                operation_name=operation_name,
                max_tokens=max_tokens,
            )
        except Exception as exc:  # provider exception types vary by adapter
            last_error = exc
            logger.warning(
                "Prompt JSON transport failure for %s (attempt %d/%d): %s",
                operation_name,
                attempt,
                attempts,
                exc,
            )
            if attempt < attempts:
                await asyncio.sleep(1.0)
    logger.error(
        "Prompt JSON transport retries exhausted for %s: %s",
        operation_name,
        last_error,
    )
    return None


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
    """Validate provider output and return canonical schema field names.

    Prompt-JSON and JSON-object providers return ordinary dictionaries. Passing
    them through unchanged makes validation aliases provider-dependent: an
    accepted alias such as ``dimension`` never becomes the canonical
    ``dimension_name`` expected downstream. Keep one schema boundary for every
    provider instead.
    """
    if parsed is None:
        return None
    try:
        validated = parsed if isinstance(parsed, model) else model.model_validate(parsed)
    except (ValidationError, TypeError, ValueError) as exc:
        logger.warning(
            "Structured output failed %s validation: %s",
            model.__name__,
            exc,
        )
        return None
    return validated.model_dump()


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
            # Never mutate the shared ChatModel — Critic's low max_tokens must
            # not permanently starve later planner/JSON calls (esp. always-on
            # reasoning models like Kimi K3 that share budget with thinking).
            if max_tokens is not None:
                if hasattr(llm, "model_copy"):
                    fields = getattr(llm, "model_fields", None)
                    if not isinstance(fields, dict):
                        fields = getattr(llm, "__fields__", None)
                    if not isinstance(fields, dict):
                        fields = {}
                    update = {}
                    if "max_tokens" in fields or (
                        not fields and hasattr(llm, "max_tokens")
                    ):
                        update["max_tokens"] = max_tokens
                    if "num_predict" in fields:
                        update["num_predict"] = max_tokens
                    if update:
                        llm = llm.model_copy(update=update)
                    else:
                        llm = llm.bind(max_tokens=max_tokens)
                else:
                    llm = llm.bind(max_tokens=max_tokens)
            # Kimi K3 natively supports strict JSON Schema. Explicitly select
            # this path so LangChain does not silently downgrade to a looser
            # function-calling/prompt-only contract.
            model_name = str(getattr(llm_helper, "model", "") or "").lower()
            if "kimi-k3" in model_name.replace("_", "-"):
                structured_llm = llm.with_structured_output(
                    schema_model,
                    method="json_schema",
                    strict=True,
                    include_raw=True,
                )
            else:
                structured_llm = llm.with_structured_output(
                    schema_model,
                    include_raw=True,
                )
        except Exception as exc:
            logger.debug(
                "JSON Schema structured-output setup unavailable (%s); trying json_object fallback",
                exc,
            )
            mode = StructuredOutputMode.JSON_OBJECT
        else:
            try:
                run_config = (
                    llm_helper._build_run_config()
                    if hasattr(llm_helper, "_build_run_config")
                    else None
                )
                result = await structured_llm.ainvoke(messages, config=run_config)
            except Exception as exc:
                if hasattr(llm_helper, "_log_llm_error"):
                    llm_helper._log_llm_error(messages, operation_name, exc)
                logger.debug(
                    "JSON Schema structured-output invocation unavailable (%s); "
                    "trying json_object fallback",
                    exc,
                )
                mode = StructuredOutputMode.JSON_OBJECT
            else:
                # include_raw=True preserves the provider AIMessage, including
                # input/output/cache/reasoning usage metadata. The previous
                # direct Pydantic return path discarded that provenance.
                raw_result = result
                parsed_result = result
                if isinstance(result, dict) and "raw" in result:
                    raw_result = result.get("raw")
                    parsed_result = result.get("parsed")
                if raw_result is not None and hasattr(llm_helper, "_log_llm_response"):
                    llm_helper._log_llm_response(raw_result, messages, operation_name)
                return _coerce_to_dict(parsed_result, schema_model)

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
            return _coerce_to_dict(parse_llm_json(content), schema_model)
        except Exception as exc:
            logger.warning(
                "JSON Object mode failed (%s); falling back to prompt JSON",
                exc,
            )
            mode = StructuredOutputMode.PROMPT_JSON

    prompt_messages = _enhance_messages_for_json_object(messages, schema_model)
    response = await _invoke_prompt_json_with_transport_retry(
        llm_helper,
        prompt_messages,
        operation_name=operation_name,
        max_tokens=max_tokens,
    )
    content = getattr(response, "content", "") if response else ""
    return _coerce_to_dict(parse_llm_json(content), schema_model)


def supports_api_json_object(provider: Optional[str] = None) -> bool:
    """Return True when the provider exposes OpenAI-style json_object response_format."""
    normalized = (provider or config.llm_provider or "").lower()
    return normalized in {"deepseek", "openai", "qwen"}
