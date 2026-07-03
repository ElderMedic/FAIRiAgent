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

- ``exact``            — strict identifiers after normalization; falls back to
                          ``identifier_match`` (DOI/URL containment, token overlap)
                          with capped partial credit when formats differ.
- ``identifier``       — same flexible identifier scorer (explicit GT override).
- ``numeric_tolerance`` — measurements: 1.0 within tolerance, graded decay when
                          close, 0.0 when far off (not strictly binary).
- ``categorical``       — controlled-vocabulary terms. Binary after normalization.
- ``semantic`` (default) — free text. ``max(semantic_sim, token_f1)`` with partial
                           credit via continuous score (not only match/wrong bins).
"""

from __future__ import annotations

import re
import string
from typing import List, Optional, Tuple

import numpy as np

# ---------------------------------------------------------------------------
# Thresholds (shared across all evaluators / the CLI script)
# ---------------------------------------------------------------------------
MATCH_THRESHOLD = 0.75    # score >= this -> status "match"
PARTIAL_THRESHOLD = 0.35  # score >= this -> status "partial" (graded credit below)

# Cap semantic fallback when scoring identifier-like fields (format mismatch).
_IDENTIFIER_SEMANTIC_CAP = 0.75

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


def semantic_similarity_available() -> bool:
    if _ST_DISABLED:
        return False
    return _get_st_model() is not None


def _get_st_model():
    global _ST_MODEL, _ST_AVAILABLE
    if _ST_DISABLED:
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


def semantic_sim(a: str, b: str) -> float:
    """Cosine similarity in [0,1] using all-MiniLM-L6-v2; fallback 0.0."""
    model = _get_st_model()
    if model is None or not a.strip() or not b.strip():
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
    "by", "from", "as", "not", "no", "n/a", "na", "unknown",
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
    common = set(p_toks) & set(g_toks)
    if not common:
        return (0.0, 0.0, 0.0)
    prec = len(common) / len(p_toks)
    rec = len(common) / len(g_toks)
    f1 = 2 * prec * rec / (prec + rec)
    return (prec, rec, f1)


def combined_score(pred: str, gt: str) -> float:
    """
    Best-of semantic similarity and token-F1 (the "semantic" match type).

    Always takes the maximum of both signals so short paraphrases (e.g.
    ``LCC`` vs ``leaf-branch compost cutinase (LCC) wild-type``) are not
    forced through token-F1 alone.
    """
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


_DOI_RE = re.compile(r"10\.\d{4,9}/[-._;()/:\w]+", re.I)


def _normalize_identifier(text: str) -> str:
    text = text.strip().lower()
    text = re.sub(r"^https?://(dx\.)?doi\.org/", "", text)
    text = re.sub(r"^doi:\s*", "", text)
    text = re.sub(r"\s+", "", text)
    return text


def _extract_doi(text: str) -> Optional[str]:
    match = _DOI_RE.search(text)
    return match.group(0).lower().rstrip(".,;") if match else None


def identifier_match(pred: str, gt: str) -> float:
    """
    Flexible identifier / code matching with graded partial credit.

    Handles common FAIRiAgent mismatches: DOI vs ``INV_*`` id, URL vs bare DOI,
    enzyme shorthand (``LCC_wt``) vs canonical codes, etc.
    """
    p_norm = _normalize_identifier(pred)
    g_norm = _normalize_identifier(gt)
    if not g_norm:
        return 1.0 if not p_norm else 0.0
    if p_norm == g_norm:
        return 1.0

    p_doi, g_doi = _extract_doi(pred), _extract_doi(gt)
    if p_doi and g_doi and p_doi == g_doi:
        return 0.95
    if p_doi and g_doi and (p_doi in g_doi or g_doi in p_doi):
        return 0.9

    if g_norm in p_norm or p_norm in g_norm:
        return 0.88

    p_toks = set(re.findall(r"[a-z0-9]+", p_norm))
    g_toks = set(re.findall(r"[a-z0-9]+", g_norm))
    if g_toks:
        overlap = len(p_toks & g_toks) / len(g_toks)
        if overlap >= 0.6:
            return 0.75 + 0.2 * overlap
        if overlap >= 0.3:
            return 0.45 + 0.5 * overlap

    sem = combined_score(pred, gt)
    return min(sem, _IDENTIFIER_SEMANTIC_CAP)


def exact_match(pred: str, gt: str) -> float:
    """Strict normalized equality; near-miss identifiers get partial credit."""
    p = re.sub(r"\s+", "", pred.strip().lower())
    g = re.sub(r"\s+", "", gt.strip().lower())
    if not g:
        return 1.0 if not p else 0.0
    if p == g:
        return 1.0
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


def numeric_tolerance_match(pred: str, gt: str, rel_tol: float = 0.02) -> float:
    """
    Graded numeric match: 1.0 within tolerance, partial credit when close.

    Falls back to ``identifier_match`` when no parseable number exists.
    """
    p_num = _extract_number(pred)
    g_num = _extract_number(gt)
    if p_num is None or g_num is None:
        return identifier_match(pred, gt)
    if g_num == 0:
        return 1.0 if abs(p_num) < 1e-9 else 0.0
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
