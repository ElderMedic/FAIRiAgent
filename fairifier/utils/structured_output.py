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
    attempts: Optional[int] = None,
) -> Any:
    """Call a prompt-JSON provider without leaking transient transport errors.

    Provider clients normally retry failures that happen before a response is
    opened, but streamed local responses can still end with an incomplete body.
    A structured-output audit is not allowed to crash the whole workflow for
    that reason. Retry the identical bounded request with a short increasing
    backoff, then return ``None`` so the owning agent can fail its deterministic
    validation or use its own stage-level retry policy. The transport budget
    follows the configured step retry budget instead of racing a reconnect with
    one immediate retry.
    """
    attempt_budget = (
        max(1, int(attempts))
        if attempts is not None
        else max(2, int(config.max_step_retries) + 1)
    )
    retry_delays = (5.0, 15.0, 30.0)
    last_error: Optional[Exception] = None
    for attempt in range(1, attempt_budget + 1):
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
                attempt_budget,
                exc,
            )
            if attempt < attempt_budget:
                delay = retry_delays[min(attempt - 1, len(retry_delays) - 1)]
                logger.info(
                    "Waiting %.1fs before retrying %s after transport failure",
                    delay,
                    operation_name,
                )
                await asyncio.sleep(delay)
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
    if normalized == "ollama" and getattr(config, "ollama_constrained_json", True):
        # Ollama ``format="json"`` constrains decoding to complete JSON.
        return StructuredOutputMode.JSON_OBJECT
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
    schema = model.model_json_schema()
    schema_text = json.dumps(schema, ensure_ascii=False)
    property_names = list(schema.get("properties", {}).keys())

    json_hint = ""
    if require_json_word and "json" not in prompt.lower():
        json_hint = "Respond with valid JSON only.\n\n"

    return (
        f"{prompt}\n\n"
        f"{json_hint}"
        "OUTPUT FORMAT — JSON OBJECT (required keys only, no markdown fences):\n"
        f"{example_text}\n\n"
        f"JSON properties: {property_names}\n"
        "The schema below defines required properties, nested records, allowed "
        "values and nullability. Empty arrays above illustrate the outer shape; "
        "populate source-supported records using their complete item schema.\n"
        f"JSON Schema:\n{schema_text}\n"
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


_SCHEMA_ERROR_MESSAGES = {
    "missing": "Required field is missing.",
    "extra_forbidden": "Unexpected property is not permitted.",
    "string_type": "Input should be a valid string.",
    "list_type": "Input should be a valid list.",
    "dict_type": "Input should be a valid dictionary.",
    "int_type": "Input should be a valid integer.",
    "int_parsing": "Input should be a valid integer.",
    "float_type": "Input should be a valid number.",
    "float_parsing": "Input should be a valid number.",
    "bool_type": "Input should be a valid boolean.",
    "bool_parsing": "Input should be a valid boolean.",
    "none_required": "Input should be null.",
    "literal_error": "Input must match an allowed literal in the schema.",
    "enum": "Input must match an allowed enum value in the schema.",
    "model_type": "Input should match the required object schema.",
    "value_error": "Custom validation failed; check the field against the schema.",
    "assertion_error": "Custom validation failed; check the field against the schema.",
}
_SCHEMA_NUMERIC_LIMITS = {
    "greater_than_equal": ("ge", "Input should be greater than or equal to"),
    "greater_than": ("gt", "Input should be greater than"),
    "less_than_equal": ("le", "Input should be less than or equal to"),
    "less_than": ("lt", "Input should be less than"),
    "multiple_of": ("multiple_of", "Input should be a multiple of"),
}


def _schema_property_names(model: Type[BaseModel]) -> set[str]:
    """Collect trusted property names, including nested schema definitions."""
    names: set[str] = set()
    pending: List[Any] = [model.model_json_schema()]
    while pending:
        node = pending.pop()
        if isinstance(node, dict):
            properties = node.get("properties")
            if isinstance(properties, dict):
                names.update(properties)
            pending.extend(node.values())
        elif isinstance(node, list):
            pending.extend(node)
    return names


def _record_schema_failure(
    error: Optional[Exception],
    model: Type[BaseModel],
    validation_errors: Optional[List[str]],
) -> None:
    """Report bounded schema diagnostics without copying the rejected payload."""
    validation_error = error
    seen: set[int] = set()
    for _ in range(5):
        if isinstance(validation_error, ValidationError) or validation_error is None:
            break
        if id(validation_error) in seen:
            break
        seen.add(id(validation_error))
        validation_error = validation_error.__cause__ or validation_error.__context__

    if isinstance(validation_error, ValidationError):
        details = validation_error.errors(
            include_url=False, include_context=True, include_input=False
        )
        property_names = _schema_property_names(model)
        messages = []
        for detail in details[:20]:
            path = ".".join(
                str(part) if type(part) is int or part in property_names else "<key>"
                for part in detail.get("loc", ())
            ) or "root"
            error_type = str(detail.get("type") or "validation_error")
            message = _SCHEMA_ERROR_MESSAGES.get(error_type)
            if error_type in _SCHEMA_NUMERIC_LIMITS:
                context_key, prefix = _SCHEMA_NUMERIC_LIMITS[error_type]
                limit = (detail.get("ctx") or {}).get(context_key)
                message = (
                    f"{prefix} {limit}." if type(limit) in {int, float}
                    else "Input must satisfy the numeric constraint in the schema."
                )
            if message is None:
                error_type = "validation_error"
                message = "Input does not satisfy the field schema."
            # Even detail['msg'] and dynamic loc keys can contain rejected input
            # from custom validators. Render trusted labels and numeric limits
            # instead of copying provider/custom exception text or context.
            messages.append(f"{path} [{error_type}]: {message}"[:220])
        if len(details) > 20:
            messages.append(
                f"{len(details) - 20} further schema errors omitted; fix the same patterns."
            )
    elif error is None:
        messages = ["root [json_object]: Response did not contain a parseable JSON object."]
    else:
        # Provider parser exceptions can embed the entire response in str(exc).
        # Only Pydantic's structured diagnostics are safe to send back verbatim.
        messages = [
            f"root [validation_error]: Response does not satisfy {model.__name__}."
        ]

    logger.warning(
        "Structured output failed %s validation: %s", model.__name__, "; ".join(messages)
    )
    if validation_errors is not None:
        validation_errors.extend(
            message for message in messages if message not in validation_errors
        )


def _coerce_to_dict(
    parsed: Any,
    model: Type[BaseModel],
    *,
    validation_errors: Optional[List[str]] = None,
) -> Optional[Dict[str, Any]]:
    """Validate provider output and return canonical schema field names.

    Prompt-JSON and JSON-object providers return ordinary dictionaries. Passing
    them through unchanged makes validation aliases provider-dependent: an
    accepted alias such as ``dimension`` never becomes the canonical
    ``dimension_name`` expected downstream. Keep one schema boundary for every
    provider instead.
    """
    if parsed is None:
        if validation_errors is not None:
            _record_schema_failure(None, model, validation_errors)
        return None
    try:
        validated = parsed if isinstance(parsed, model) else model.model_validate(parsed)
    except (ValidationError, TypeError, ValueError) as exc:
        _record_schema_failure(exc, model, validation_errors)
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
    validation_errors: Optional[List[str]] = None,
    allow_truncated: bool = False,
) -> Optional[Dict[str, Any]]:
    """
    Invoke an LLM and parse a structured Pydantic-shaped JSON response.

    ``allow_truncated`` recovers the complete prefix of an answer whose JSON
    was cut off (the caller must validate the result as a partial answer).

    Strategy by provider:
    - deepseek: ``response_format={'type': 'json_object'}`` (DeepSeek JSON Output)
    - openai: LangChain ``with_structured_output`` (JSON Schema), then fallbacks
    - others: prompt-guided JSON parsing

    The optional caller-owned ``validation_errors`` list receives bounded
    path/type/message diagnostics. Schema failures still return None; the
    owning stage retains its existing retry budget.
    """
    from .llm_helper import call_output_budget

    max_tokens = call_output_budget(max_tokens)
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
                parsing_error = None
                if isinstance(result, dict) and "raw" in result:
                    raw_result = result.get("raw")
                    parsed_result = result.get("parsed")
                    parsing_error = result.get("parsing_error")
                if raw_result is not None and hasattr(llm_helper, "_log_llm_response"):
                    llm_helper._log_llm_response(raw_result, messages, operation_name)
                if parsed_result is None and isinstance(parsing_error, Exception):
                    _record_schema_failure(parsing_error, schema_model, validation_errors)
                    return None
                return _coerce_to_dict(
                    parsed_result, schema_model, validation_errors=validation_errors
                )

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
            parsed_json = parse_llm_json(content)
            if parsed_json is None:
                _log_unparseable_response(response, content, schema_model, operation_name)
                parsed_json = _salvage(content, allow_truncated, operation_name, validation_errors)
            return _coerce_to_dict(
                parsed_json, schema_model, validation_errors=validation_errors
            )
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
    parsed_json = parse_llm_json(content)
    if parsed_json is None:
        _log_unparseable_response(response, content, schema_model, operation_name)
        parsed_json = _salvage(content, allow_truncated, operation_name, validation_errors)
    return _coerce_to_dict(
        parsed_json, schema_model, validation_errors=validation_errors
    )


TRUNCATED_ANSWER_MARKER = "root [truncated]: the answer was cut off; only its complete prefix was recovered."


def _salvage(
    content: Any, allowed: bool, operation_name: str,
    validation_errors: Optional[List[str]] = None,
) -> Optional[Dict[str, Any]]:
    if not allowed:
        return None
    from .json_parse import salvage_truncated_json

    salvaged = salvage_truncated_json(content)
    if salvaged is not None:
        logger.warning("Recovered the complete prefix of a truncated answer for %s", operation_name)
        if validation_errors is not None:
            # A recovered prefix is partial by definition; tell the caller.
            validation_errors.append(TRUNCATED_ANSWER_MARKER)
    return salvaged


def _log_unparseable_response(response: Any, content: Any, schema_model: Any, operation_name: str) -> None:
    """Say whether an unparseable answer was truncated, empty or malformed."""
    metadata = getattr(response, "response_metadata", {}) or {}
    reason = (
        metadata.get("done_reason") or metadata.get("finish_reason")
        or metadata.get("stop_reason") or "unknown"
    )
    text = str(content or "")
    logger.warning(
        "Unparseable %s answer for %s: %d chars, stop=%s, tail=%r",
        getattr(schema_model, "__name__", "schema"), operation_name, len(text), reason,
        text[-160:],
    )


def supports_api_json_object(provider: Optional[str] = None) -> bool:
    """Return True when the provider exposes OpenAI-style json_object response_format."""
    normalized = (provider or config.llm_provider or "").lower()
    return normalized in {"deepseek", "openai", "qwen"}
