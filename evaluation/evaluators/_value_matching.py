"""
Shared value-matching primitives for FAIRiAgent evaluation.

This module is the single source of truth for how two metadata *values*
(one predicted, one ground truth) are compared. It is used by:

- ``evaluation/evaluators/value_accuracy_evaluator.py`` (Layer 2 evaluator)
- ``evaluation/evaluators/structural_evaluator.py`` (Layer 3, for row alignment)
- ``evaluation/evaluators/novel_field_evaluator.py`` (Layer 4, evidence grounding)
- ``evaluation/scripts/compare_values_against_gt.py`` (thin CLI wrapper)

Extracted (2026 evaluation-metrics redesign) so all call sites share one
implementation instead of four independent copies.

Match-type-aware scoring
------------------------
A single generic semantic-similarity/token-F1 function is not reliable across
every value type FAIRiAgent extracts (identifiers vs. numeric measurements vs.
controlled-vocabulary terms vs. free text). ``match_value()`` dispatches to a
per-type scorer based on ``match_type``:

- ``exact``            — normalized identifier equality, including DOI wrappers.
- ``identifier``       — the same equality scorer; similarity is not identity.
- ``numeric_tolerance`` — measurements: 1.0 within tolerance, graded decay when
                          close, 0.0 when far off (not strictly binary).
- ``categorical``       — controlled-vocabulary terms. Binary after normalization.
- ``semantic`` (default) — free text. ``max(semantic_sim, token_f1)`` with partial
                           credit, excluding directly negated identical content.
"""

from __future__ import annotations

import json
import os
import re
import string
import urllib.request
from collections import Counter
from functools import lru_cache
from math import isfinite
from typing import List, Optional, Tuple

import numpy as np

# ---------------------------------------------------------------------------
# Thresholds (shared across all evaluators / the CLI script)
# ---------------------------------------------------------------------------
MATCH_THRESHOLD = 0.75    # score >= this -> status "match"
PARTIAL_THRESHOLD = 0.35  # score >= this -> status "partial" (graded credit below)

# ---------------------------------------------------------------------------
# sentence-transformers semantic similarity (lazy-loaded, optional)
# ---------------------------------------------------------------------------

_ST_MODEL = None
_ST_AVAILABLE = False
_ST_DISABLED = False


def disable_semantic_similarity(disabled: bool = True) -> None:
    """Force token-F1-only mode (used by --no-semantic CLI flag / fast tests)."""
    global _ST_DISABLED, _ST_AVAILABLE
    _ST_DISABLED = disabled
    if disabled:
        _ST_AVAILABLE = False


# Embeddings come from the forwarded Ollama service by default. The local
# all-MiniLM-L6-v2 model runs only when FAIRIFIER_EVAL_SEMANTIC_BACKEND=local.
_BACKEND = os.getenv("FAIRIFIER_EVAL_SEMANTIC_BACKEND", "ollama").strip().lower()
_OLLAMA_URL = os.getenv("FAIRIFIER_EVAL_EMBEDDING_BASE_URL", "http://localhost:11434").rstrip("/")
_OLLAMA_MODEL = os.getenv("FAIRIFIER_EVAL_EMBEDDING_MODEL", "nomic-embed-text-v2-moe")


def semantic_similarity_available() -> bool:
    if _ST_DISABLED or _BACKEND == "none":
        return False
    if _BACKEND == "ollama":
        return _ollama_embedding("ping") is not None
    return _get_st_model() is not None


def _get_st_model():
    global _ST_MODEL, _ST_AVAILABLE
    if _ST_DISABLED or _BACKEND != "local":
        _ST_AVAILABLE = False
        return None
    if _ST_MODEL is not None:
        return _ST_MODEL
    try:
        from sentence_transformers import SentenceTransformer

        _ST_MODEL = SentenceTransformer("all-MiniLM-L6-v2")
        _ST_AVAILABLE = True
    except Exception:
        _ST_AVAILABLE = False
    return _ST_MODEL


@lru_cache(maxsize=50000)
def _ollama_embedding(text: str) -> Optional[Tuple[float, ...]]:
    """Unit-normalised embedding from the Ollama service, or None on failure."""
    body = json.dumps({"model": _OLLAMA_MODEL, "input": [text]}).encode()
    request = urllib.request.Request(f"{_OLLAMA_URL}/api/embed", data=body,
                                     headers={"Content-Type": "application/json"})
    for _ in range(3):
        try:
            with urllib.request.urlopen(request, timeout=60) as response:
                vector = np.asarray(json.loads(response.read())["embeddings"][0], dtype=float)
            norm = float(np.linalg.norm(vector))
            return tuple(vector / norm) if norm else None
        except Exception:
            continue
    return None


def semantic_sim(a: str, b: str) -> float:
    """Cosine similarity in [0,1]; fallback 0.0. Backend: FAIRIFIER_EVAL_SEMANTIC_BACKEND."""
    if _ST_DISABLED or _BACKEND == "none" or not a.strip() or not b.strip():
        return 0.0
    if _BACKEND == "ollama":
        ea, eb = _ollama_embedding(a), _ollama_embedding(b)
        if ea is None or eb is None:
            return 0.0
        return float(np.clip(float(np.dot(ea, eb)), 0.0, 1.0))
    model = _get_st_model()
    if model is None:
        return 0.0
    try:
        embs = model.encode([a, b], convert_to_numpy=True, normalize_embeddings=True)
        return float(np.clip(float(embs[0] @ embs[1]), 0.0, 1.0))
    except Exception:
        return 0.0


# ---------------------------------------------------------------------------
# token-F1 (SQuAD-style)
# ---------------------------------------------------------------------------

_STOPWORDS = frozenset({
    "the", "a", "an", "is", "are", "was", "were", "be", "been",
    "and", "or", "of", "in", "to", "for", "with", "on", "at",
    "by", "from", "as", "n/a", "na", "unknown",
})


def normalize_tokens(text: str) -> List[str]:
    text = text.lower()
    text = text.translate(str.maketrans("", "", string.punctuation))
    return [t for t in text.split() if t]


def token_f1(pred: str, gt: str) -> Tuple[float, float, float]:
    """Token-level precision, recall, F1."""
    p_toks = [t for t in normalize_tokens(pred) if t not in _STOPWORDS]
    g_toks = [t for t in normalize_tokens(gt) if t not in _STOPWORDS]
    if not g_toks:
        return (1.0, 1.0, 1.0) if not p_toks else (0.0, 1.0, 0.0)
    if not p_toks:
        return (0.0, 0.0, 0.0)
    common = Counter(p_toks) & Counter(g_toks)
    if not common:
        return (0.0, 0.0, 0.0)
    overlap = sum(common.values())
    prec = overlap / len(p_toks)
    rec = overlap / len(g_toks)
    f1 = 2 * prec * rec / (prec + rec)
    return (prec, rec, f1)


def _direct_negation_conflict(pred: str, gt: str) -> bool:
    """Detect otherwise identical content with a single added ``not`` or ``no``.

    This is deliberately narrower than comparing whether either text contains
    negation. Paraphrases such as ``absent`` and ``not detected``, and phrases
    such as ``not only``, still require the normal semantic scorer.
    """
    negators = {"not", "no"}

    def content_tokens(text: str) -> List[str]:
        # ``No. 1`` denotes a number; punctuation removal must not negate it.
        text = re.sub(r"\bno\.\s*(?=\d)", "number ", text, flags=re.IGNORECASE)
        return [t for t in normalize_tokens(text) if t not in _STOPWORDS]

    pred_tokens = content_tokens(pred)
    gt_tokens = content_tokens(gt)
    counts = (
        sum(t in negators for t in pred_tokens),
        sum(t in negators for t in gt_tokens),
    )
    if counts not in {(1, 0), (0, 1)}:
        return False
    pred_content = [t for t in pred_tokens if t not in negators]
    gt_content = [t for t in gt_tokens if t not in negators]
    return bool(pred_content) and pred_content == gt_content


def combined_score(pred: str, gt: str) -> float:
    """
    Best-of semantic similarity and token-F1 (the "semantic" match type).

    Takes the maximum of both signals so short paraphrases (e.g.
    ``LCC`` vs ``leaf-branch compost cutinase (LCC) wild-type``) are not
    forced through token-F1 alone. A direct negation of otherwise identical
    content cannot be overridden by embedding similarity.
    """
    if pred.strip() == gt.strip():
        return 1.0
    if _direct_negation_conflict(pred, gt):
        return 0.0
    _, _, tf1 = token_f1(pred, gt)
    if not pred.strip() or not gt.strip():
        return tf1
    sim = semantic_sim(pred, gt)
    return max(sim, tf1)


# ---------------------------------------------------------------------------
# Type-aware matchers (ExtractBench-style: one metric per value type)
# ---------------------------------------------------------------------------

_NUMBER_RE = re.compile(r"[-+]?\d*\.?\d+(?:[eE][-+]?\d+)?")


def _normalize_categorical(text: str) -> str:
    text = text.strip().lower()
    text = re.sub(r"[\s_\-]+", " ", text)
    text = text.translate(str.maketrans("", "", string.punctuation.replace(" ", "")))
    return text.strip()


def _normalize_identifier(text: str) -> str:
    text = text.strip().lower()
    text = re.sub(r"^doi:\s*", "", text)
    text = re.sub(r"^https?://(dx\.)?doi\.org/", "", text)
    text = re.sub(r"\s+", "", text)
    return text


def identifier_match(pred: str, gt: str) -> float:
    """
    Compare complete identifiers after whitespace, case, and DOI normalization.

    DOI URLs and ``doi:`` wrappers are equivalent to the bare DOI. Containment,
    token overlap, and embeddings cannot establish identifier identity.
    Document-local ISA identifiers are aligned separately by the evaluators.
    """
    return float(_normalize_identifier(pred) == _normalize_identifier(gt))


def exact_match(pred: str, gt: str) -> float:
    """Strict normalized identifier equality, allowing equivalent DOI wrappers."""
    return identifier_match(pred, gt)


def categorical_match(pred: str, gt: str) -> float:
    """Binary match after normalization; no partial credit for near-miss vocab terms."""
    p = _normalize_categorical(pred)
    g = _normalize_categorical(gt)
    if not g:
        return 1.0 if not p else 0.0
    return 1.0 if p == g else 0.0


def _extract_number(text: str) -> Optional[float]:
    match = _NUMBER_RE.search(text.replace(",", ""))
    if not match:
        return None
    try:
        return float(match.group())
    except ValueError:
        return None


# A deliberately small unit vocabulary. Unknown symbols compare only when
# identical; unsupported expressions never fall back to comparing one number.
_UNIT_BASES = {
    "g": ({"mass": 1}, 1.0), "m": ({"length": 1}, 1.0),
    "L": ({"volume": 1}, 1.0), "l": ({"volume": 1}, 1.0),
    "mol": ({"amount": 1}, 1.0), "M": ({"amount": 1, "volume": -1}, 1.0),
    "s": ({"time": 1}, 1.0), "min": ({"time": 1}, 60.0),
    "h": ({"time": 1}, 3600.0), "d": ({"time": 1}, 86400.0),
    "U": ({"activity": 1}, 1.0), "%": ({"fraction": 1}, 0.01),
    "K": ({"kelvin": 1}, 1.0), "°C": ({"celsius": 1}, 1.0),
}
_UNIT_PREFIXES = {"p": 1e-12, "n": 1e-9, "u": 1e-6, "m": 1e-3,
                  "c": 1e-2, "d": 1e-1, "k": 1e3, "M": 1e6, "G": 1e9}
_PREFIXABLE_UNITS = {"g", "m", "L", "l", "mol", "M", "s", "U"}
_UNIT_TOKEN_RE = re.compile(r"([A-Za-z°%]+)(?:\^?([-+]?\d+))?")


def _unit_signature(text: str) -> Optional[Tuple[dict, float]]:
    text = text.replace("µ", "u").replace("μ", "u").replace("−", "-")
    text = text.translate(str.maketrans("⁰¹²³⁴⁵⁶⁷⁸⁹⁻", "0123456789-"))
    text = text.replace("·", " ").replace("*", " ").strip()
    if not text:
        return {}, 1.0
    dims, scale, unknown = Counter(), 1.0, False
    for index, part in enumerate(text.split("/")):
        tokens = part.split()
        if not tokens:
            return None
        for token in tokens:
            match = _UNIT_TOKEN_RE.fullmatch(token)
            if not match:
                return None
            symbol, exponent = match.groups()
            power = int(exponent or 1) * (1 if index == 0 else -1)
            base = _UNIT_BASES.get(symbol)
            if base is None and len(symbol) > 1 and symbol[0] in _UNIT_PREFIXES:
                remainder = symbol[1:]
                if remainder in _PREFIXABLE_UNITS:
                    dimensions, factor = _UNIT_BASES[remainder]
                    base = dimensions, factor * _UNIT_PREFIXES[symbol[0]]
            dimensions, factor = base or ({"unknown:" + symbol: 1}, 1.0)
            unknown = unknown or base is None
            for dimension, exponent in dimensions.items():
                dims[dimension] += exponent * power
            try:
                scale *= factor ** power
            except OverflowError:
                return None
            if not isfinite(scale) or scale == 0:
                return None
    if unknown:
        return {"unknown:" + " ".join(text.split()): 1}, 1.0
    return {key: value for key, value in dims.items() if value}, scale


def _quantity(text: str) -> Optional[Tuple[float, dict]]:
    text = text.strip().replace("−", "-")
    match = _NUMBER_RE.match(text)
    if not match:
        return None
    signature = _unit_signature(text[match.end():].strip())
    if signature is None:
        return None
    dimensions, factor = signature
    number = float(match.group())
    value = number * factor
    if not isfinite(value) or (value == 0 and number != 0):
        return None
    if number == 0 and re.search(r"[1-9]", re.split(r"[eE]", match.group())[0]):
        return None
    return value, dimensions


def numeric_tolerance_match(pred: str, gt: str, rel_tol: float = 0.02) -> float:
    """
    Graded numeric match: 1.0 within tolerance, partial credit when close.

    Compare complete scalar quantities, including units. Complex expressions
    (ranges, uncertainty, prose) require exact text until explicitly supported.
    """
    if pred.strip() == gt.strip():
        return 1.0
    p_quantity, g_quantity = _quantity(pred), _quantity(gt)
    if p_quantity is None or g_quantity is None:
        return 0.0
    p_num, p_units = p_quantity
    g_num, g_units = g_quantity
    if p_units != g_units:
        return 0.0
    if g_num == 0:
        return 1.0 if p_num == 0 else 0.0
    rel_err = abs(p_num - g_num) / abs(g_num)
    if rel_err <= rel_tol:
        return 1.0
    # Tight graded band: small measurement noise gets partial credit; large
    # deviations (wrong entity / wrong unit magnitude) score 0.
    if rel_err <= 0.05:
        return 0.7 + 0.3 * (0.05 - rel_err) / (0.05 - rel_tol)
    if rel_err <= 0.10:
        return 0.3 + 0.4 * (0.10 - rel_err) / 0.05
    return 0.0


# ---------------------------------------------------------------------------
# Match-type inference (heuristic, override-able per field in GT JSON)
# ---------------------------------------------------------------------------

_EXACT_KEYWORDS = (
    "accession", "orcid", "barcode", "isbn", "issn", "email", "file", "filename",
)
_IDENTIFIER_KEYWORDS = (
    "identifier", "id", "doi", "url", "contenturl", "reference",
)
_SEMANTIC_KEYWORDS = (
    "title", "description", "notes", "protocol", "subject", "name",
    "loading", "condition", "design", "facility", "type", "mutation",
)
_NUMERIC_KEYWORDS = (
    "temperature", "ph", "concentration", "volume", "quantity", "weight",
    "age", "depth", "altitude", "latitude", "longitude", "duration",
    "dilution", "activity", "conc_ng", "rqn", "length", "size", "%", "percent",
)
_CATEGORICAL_KEYWORDS = (
    "platform", "library source", "library selection", "library strategy",
    "biosafety level", "sex", "instrument model", "sequencing method",
    "environment biome", "status",
)


def classify_match_type(field_name: str) -> str:
    """
    Infer a match type from a field name using a small rule set.

    This is a heuristic default; callers may override per-field via a
    ``match_type`` key on the GT field definition (see
    ``value_accuracy_evaluator.ValueAccuracyEvaluator``).
    """
    name = field_name.lower()
    if normalise_field_name(name) == "measurement value":
        return "numeric_tolerance"
    if normalise_field_name(name) in {"unit", "units", "measurement unit"}:
        return "unit"
    if any(k in name for k in _SEMANTIC_KEYWORDS):
        return "semantic"
    if any(k in name for k in _IDENTIFIER_KEYWORDS):
        return "identifier"
    if any(k in name for k in _EXACT_KEYWORDS):
        return "exact"
    if any(k in name for k in _CATEGORICAL_KEYWORDS):
        return "categorical"
    if any(k in name for k in _NUMERIC_KEYWORDS):
        return "numeric_tolerance"
    return "semantic"


def match_value(
    pred: str,
    gt: str,
    match_type: Optional[str] = None,
    field_name: Optional[str] = None,
) -> float:
    """Score `pred` against `gt` in [0, 1] using the given (or inferred) match type."""
    if match_type is None:
        match_type = classify_match_type(field_name) if field_name else "semantic"

    if match_type == "exact":
        return exact_match(pred, gt)
    if match_type == "identifier":
        return identifier_match(pred, gt)
    if match_type == "numeric_tolerance":
        return numeric_tolerance_match(pred, gt)
    if match_type == "unit":
        return numeric_tolerance_match("1 " + pred, "1 " + gt, rel_tol=0.0)
    if match_type == "categorical":
        return categorical_match(pred, gt)
    return combined_score(pred, gt)  # "semantic" (default)


def classify_status(score: float, match_type: str = "semantic") -> str:
    """
    Classify a continuous match score into match / partial / wrong.

    All match types use the same score bands; ``categorical`` remains
    effectively binary (0 or 1). Headline Layer 2 quality should use the
    raw continuous score (``value_mean_score``), not these bins alone.
    """
    if match_type == "categorical":
        return "match" if score >= 1.0 else "wrong"
    if score >= MATCH_THRESHOLD:
        return "match"
    if score >= PARTIAL_THRESHOLD:
        return "partial"
    return "wrong"


def normalise_field_name(name: str) -> str:
    """Canonical field-name form used for matching predicted vs. GT field names."""
    return re.sub(r"[\s_\-]+", " ", name.lower().strip())
