"""Shared JSON parsing helpers for LLM responses."""

from __future__ import annotations

import json
from typing import Any, Dict, Optional

from fairifier.utils.llm_helper import normalize_llm_response_content


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
        parsed = json.loads(snippet)
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
                            parsed = json.loads(snippet[start : i + 1])
                            return parsed if isinstance(parsed, dict) else None
                        except json.JSONDecodeError:
                            pass
                        break

    return None


# Backward-compatible alias used across agents/tests.
safe_json_parse = parse_llm_json
