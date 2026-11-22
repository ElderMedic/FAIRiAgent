"""Centralized accessor for document text (P1 §5 of architecture refactor).

Document text used to be carried in ``state["document_content"]`` (hundreds of
KB) through the entire pipeline, even though only the parser, planner, and
JSON generator actually need it. This module centralizes reads and prefers the
on-disk reference (``state["document_text_path"]``), falling back to in-memory
``document_content`` only for legacy/test paths.

See ARCHITECTURE_REFACTOR_PLAN.md §5.
"""

from __future__ import annotations

import re
import unicodedata
from pathlib import Path
from typing import Any, Dict, Optional


_SUPERSCRIPTS = {"⁻": "-", "¹": "1", "²": "2", "³": "3", "⁰": "0", "⁴": "4",
                 "⁵": "5", "⁶": "6", "⁷": "7", "⁸": "8", "⁹": "9"}
_MATH_SYMBOLS = {r"\pm": "±", r"\times": "×", r"\%": "%", r"\cdot": "·", r"\approx": "≈", r"\sim": "~",
                 r"\leq": "≤", r"\geq": "≥", r"\le": "≤", r"\ge": "≥"}
_PLAIN_MATH_RE = re.compile(r"(?:[\d\s.,+\-±×%·≈~≤≥<>=()/]|°[CFK]?)+")


def _plain_math(match: "re.Match[str]") -> str:
    body = match[1]
    for command in sorted(_MATH_SYMBOLS, key=len, reverse=True):
        body = body.replace(command, _MATH_SYMBOLS[command])
    return " ".join(body.split()) if _PLAIN_MATH_RE.fullmatch(body) else match[0]


def normalize_source_evidence_text(value: Any) -> str:
    """Normalize display typography, preserving scientific identifiers and signs."""
    text = unicodedata.normalize("NFC", "" if value is None else str(value)).translate(
        str.maketrans({"\u2212": "-", "\u00b5": "\u03bc", "\u2018": "'", "\u2019": "'", "\u201c": '"', "\u201d": '"'})
    )
    # A unit exponent ("L⁻¹", "cm²") reads as its plain spelling; a power of
    # ten ("10³") is left alone so it never reads as another number.
    text = re.sub(r"(?<=[A-Za-z])[" + "".join(_SUPERSCRIPTS) + r"]+",
                  lambda match: match[0].translate(str.maketrans(_SUPERSCRIPTS)), text)
    # An escaped Markdown underscore has the same displayed identifier.
    text = text.replace(r"\_", "_")
    # Join PDF-wrapped prose, but preserve inline hyphens and identifier fragments.
    text = re.sub(r"(?<!\w)([a-z]{2,})-[ \t]*\r?\n[ \t]*(?=[a-z]{2,})", r"\1", text)
    # Decode only a numeric micro prefix, retaining magnitude and unit case.
    text = re.sub(r"(?<=\d)([ \t]*)\$\s*\\mu\s*\$[ \t]*(?=[A-Za-z])", r"\1μ", text)
    # Equivalent temperature typography; keep signs, decimals and unit letters.
    text = re.sub(r"\^\{\s*\\circ\s*\}", "°", text)
    text = re.sub(r"\$([+-]?(?:\d+(?:\.\d*)?|\.\d+)°)\$", r"\1", text)
    text = re.sub(r"(?<=\d)[ \t]*°[ \t]*(?=[CFK](?![A-Za-z]))", "°", text)
    # Inline math that only holds numbers and symbols ("$42.6 \pm 2.9\%$",
    # "g L $^{-1}$") reads the same as its plain spelling ("42.6 ± 2.9%",
    # "g L-1" or "g L⁻¹"). Math with names or other commands is kept.
    text = re.sub(r"(?<=[A-Za-z])[ \t]*\$\s*\^\s*\{?\s*([-+]?\d+)\s*\}?\s*\$", r"\1", text)
    text = re.sub(r"\$([^$\n]{1,80})\$", _plain_math, text)
    # PDF-to-Markdown spacing inside brackets and before commas is not content.
    text = re.sub(r"\([ \t]+", "(", text)
    text = re.sub(r"[ \t]+([,;)])", r"\1", text)
    # Preserve the subscript marker and label: mg_protein is not plain mg.
    text = re.sub(
        r"([A-Za-z][A-Za-z0-9]*)[ \t]*\$\s*_\{([A-Za-z0-9]+)\}\s*\$([ \t]*/[ \t]*)?",
        lambda match: f"{match[1]}_{match[2]}" + ("/" if match[3] else ""),
        text,
    )
    return " ".join(text.split())


def read_document_text(
    state: Dict[str, Any],
    *,
    max_chars: Optional[int] = None,
) -> str:
    """Return document text, preferring on-disk reference over in-memory copy.

    Lookup order:
    1. ``state["document_text_path"]`` (read from file)
    2. ``state["document_content"]`` (legacy in-memory fallback)
    3. ``""`` (empty)

    Args:
        state: FAIRifierState (or any dict-like with the two keys).
        max_chars: If provided, truncate the returned text to this length.
            ``0`` returns an empty string. ``None`` (default) returns full text.

    Returns:
        The document text (possibly truncated). Never raises on missing /
        unreadable files — falls back through the chain.
    """
    if max_chars is not None and max_chars <= 0:
        return ""

    text = ""
    text_path = state.get("document_text_path")
    if text_path:
        try:
            path = Path(text_path)
            if path.is_file():
                text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            text = ""

    if not text:
        text = state.get("document_content") or ""

    if max_chars is not None and len(text) > max_chars:
        text = text[:max_chars]
    return text


_REFERENCE_HEADING_RE = re.compile(
    r"^#{1,6}\s*(?:\d+\.?\s*)?(?:references?(?: and notes)?|bibliography|literature cited|works cited)\s*$",
    re.IGNORECASE | re.MULTILINE,
)
_SECTION_START_RE = re.compile(r"^(?:#{1,6}\s|\[Native text from |\[Derived table rows)", re.MULTILINE)


def without_reference_list(text: str) -> str:
    """Drop the cited-literature list: it describes other papers, never this one.

    Removes each references/bibliography section up to the next heading, the
    next appended native-text block or the derived table rows.
    """
    for _ in range(3):
        heading = _REFERENCE_HEADING_RE.search(text or "")
        if not heading:
            break
        following = _SECTION_START_RE.search(text, heading.end())
        end = following.start() if following else len(text)
        text = text[:heading.start()] + text[end:]
    return text
