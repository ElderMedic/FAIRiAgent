"""Shared JSON parsing helpers for LLM responses."""

from __future__ import annotations

import json
import logging
from typing import Any, Dict, Optional

from fairifier.utils.llm_helper import normalize_llm_response_content

logger = logging.getLogger(__name__)


def _loads_preserving_literal_backslashes(snippet: str) -> Any:
    r"""Escape only literal backslashes rejected by the JSON string decoder.

    Source math such as ``\mu`` must survive as text, not be deleted. Valid
    escapes, Unicode escapes, values and object structure are never repaired.
    The original provider response remains in the call log.
    """
    repairs = 0
    while True:
        try:
            parsed = json.loads(snippet)
        except json.JSONDecodeError as exc:
            if exc.msg != "Invalid \\escape" or repairs >= 32:
                raise
            # The decoder locates an invalid escape *inside* a JSON string.
            # Doubling that backslash preserves the intended literal character.
            if snippet[exc.pos:exc.pos + 1] != "\\":
                raise
            snippet = snippet[:exc.pos] + "\\" + snippet[exc.pos:]
            repairs += 1
        else:
            if repairs:
                logger.warning("Preserved %d unescaped literal backslash(es) in JSON strings", repairs)
            return parsed


def parse_llm_json(raw: Any) -> Optional[Dict[str, Any]]:
    """Parse JSON content with support for fenced code blocks and trailing text."""
    if not raw:
        return None

    snippet = normalize_llm_response_content(raw).strip()

    if "```json" in snippet:
        snippet = snippet.split("```json", 1)[1].split("```", 1)[0].strip()
    elif "```" in snippet:
        parts = snippet.split("```")
        if len(parts) >= 3:
            snippet = parts[1].strip()
        elif snippet.startswith("```") and snippet.endswith("```"):
            snippet = snippet[3:-3].strip()

    try:
        parsed = _loads_preserving_literal_backslashes(snippet)
        return parsed if isinstance(parsed, dict) else None
    except json.JSONDecodeError:
        pass

    start = snippet.find("{")
    if start != -1:
        brace_count = 0
        in_string = False
        escape_next = False

        for i in range(start, len(snippet)):
            char = snippet[i]

            if escape_next:
                escape_next = False
                continue

            if char == "\\":
                escape_next = True
                continue

            if char == '"' and not escape_next:
                in_string = not in_string
                continue

            if not in_string:
                if char == "{":
                    brace_count += 1
                elif char == "}":
                    brace_count -= 1
                    if brace_count == 0:
                        try:
                            parsed = _loads_preserving_literal_backslashes(snippet[start : i + 1])
                            return parsed if isinstance(parsed, dict) else None
                        except json.JSONDecodeError:
                            pass
                        break

    return None


# Backward-compatible alias used across agents/tests.
safe_json_parse = parse_llm_json


def salvage_truncated_json(raw: Any) -> Optional[Dict[str, Any]]:
    """Recover the complete prefix of a JSON object whose end was cut off.

    The element being written when the text stopped is dropped whole: the
    cut is made after the last complete element of the outermost still-open
    array, and open brackets are closed. Nothing is invented and no half-
    written element is kept. Returns None when no safe cut exists.
    """
    text = str(raw or "")
    start = text.find("{")
    if start < 0:
        return None
    body = text[start:]
    stack: list = []  # (bracket, position)
    in_string = escaped = False
    commas: list = []  # (position, depth, bracket at that depth)
    for index, char in enumerate(body):
        if in_string:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                in_string = False
            continue
        if char == '"':
            in_string = True
        elif char in "{[":
            stack.append((char, index))
        elif char in "}]":
            if stack:
                stack.pop()
            if not stack:
                try:
                    parsed = json.loads(body[: index + 1])
                except ValueError:
                    return None
                return parsed if isinstance(parsed, dict) else None
        elif char == "," and stack:
            commas.append((index, len(stack)))
    # Outermost open array: drop its incomplete last element.
    array_depth = next(
        (depth + 1 for depth, (bracket, _) in enumerate(stack) if bracket == "["), None
    )
    if array_depth is None:
        return None
    array_pos = stack[array_depth - 1][1]
    cut = max(
        (pos for pos, depth in commas if depth == array_depth and pos > array_pos),
        default=None,
    )
    prefix = body[:cut] if cut is not None else body[: array_pos + 1]
    closing = "".join(
        "}" if bracket == "{" else "]" for bracket, _ in reversed(stack[:array_depth])
    )
    try:
        parsed = json.loads(prefix + closing)
    except ValueError:
        return None
    return parsed if isinstance(parsed, dict) else None
