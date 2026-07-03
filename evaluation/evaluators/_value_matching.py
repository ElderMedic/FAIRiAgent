"""
Shared value-matching primitives for FAIRiAgent evaluation (Layer 2).

Every GT-vs-prediction value pair receives:
1. **semantic_score** — sentence-transformers cosine similarity (all-MiniLM-L6-v2)
2. **token_f1_score** — SQuAD-style token overlap
3. **rule_score** — type-aware deterministic matcher (identifier / numeric / categorical)
4. **score** — fused final in [0, 1], always consulting semantic judgment unless
   the field is strict controlled vocabulary (``categorical``).

Headline Layer 2 quality = mean ``score`` across GT-populated fields
(``value_mean_score`` / ``value_partial_credit_score``).
"""

from __future__ import annotations

import re
import string
from dataclasses import dataclass
from typing import List, Optional

import numpy as np

MATCH_THRESHOLD = 0.75
PARTIAL_THRESHOLD = 0.35
_IDENTIFIER_SEMANTIC_CAP = 0.75
_NUMERIC_SEMANTIC_BLEND = 0.55  # when numeric rule fails, semantic can partially rescue

_ST_MODEL = None
_ST_AVAILABLE = False
_ST_DISABLED = False


def disable_semantic_similarity(disabled: bool = True) -> None:
    global _ST_DISABLED, _ST_AVAILABLE
    _ST_DISABLED = disabled
    if disabled:
        _ST_AVAILABLE = False


def warmup_semantic_model():
    """Load sentence-transformers model if available (lazy, once per process)."""
    return _get_st_model()


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


def semantic_similarity_available() -> bool:
    if _ST_DISABLED:
        return False
    return _get_st_model() is not None


def semantic_sim(a: str, b: str) -> float:
    """Cosine similarity in [0, 1] using all-MiniLM-L6-v2; 0.0 if unavailable."""
    model = _get_st_model()
    if model is None or not a.strip() or not b.strip():
        return 0.0
    try:
        embs = model.encode([a, b], convert_to_numpy=True, normalize_embeddings=True)
        return float(np.clip(float(embs[0] @ embs[1]), 0.0, 1.0))
    except Exception:
        return 0.0


_STOPWORDS = frozenset({
    "the", "a", "an", "is", "are", "was", "were", "be", "been",
    "and", "or", "of", "in", "to", "for", "with", "on", "at",
    "by", "from", "as", "not", "no", "n/a", "na", "unknown",
})


def normalize_tokens(text: str) -> List[str]:
    text = text.lower()
    text = text.translate(str.maketrans("", "", string.punctuation))
    return [t for t in text.split() if t]


def token_f1(pred: str, gt: str) -> tuple[float, float, float]:
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


def combined_semantic_score(pred: str, gt: str) -> float:
    """
    Semantic judgment path: max(cosine similarity, token F1).

    Always considers both signals so short paraphrases and long descriptions
    are scored fairly.
    """
    _, _, tf1 = token_f1(pred, gt)
    if not pred.strip() or not gt.strip():
        return tf1
    return max(semantic_sim(pred, gt), tf1)


def combined_score(pred: str, gt: str) -> float:
    """Alias for ``combined_semantic_score`` (backward compatible)."""
    return combined_semantic_score(pred, gt)


_NUMBER_RE = re.compile(r"[-+]?\d*\.?\d+(?:[eE][-+]?\d+)?")
_DOI_RE = re.compile(r"10\.\d{4,9}/[-._;()/:\w]+", re.I)


def _normalize_categorical(text: str) -> str:
    text = text.strip().lower()
    text = re.sub(r"[\s_\-]+", " ", text)
    text = text.translate(str.maketrans("", "", string.punctuation.replace(" ", "")))
    return text.strip()


def _normalize_identifier(text: str) -> str:
    text = text.strip().lower()
    text = re.sub(r"^https?://(dx\.)?doi\.org/", "", text)
    text = re.sub(r"^doi:\s*", "", text)
    text = re.sub(r"\s+", "", text)
    return text


def _extract_doi(text: str) -> Optional[str]:
    match = _DOI_RE.search(text)
    return match.group(0).lower().rstrip(".,;") if match else None


def _extract_number(text: str) -> Optional[float]:
    match = _NUMBER_RE.search(text.replace(",", ""))
    if not match:
        return None
    try:
        return float(match.group())
    except ValueError:
        return None


def identifier_match(pred: str, gt: str) -> float:
    p_norm = _normalize_identifier(pred)
    g_norm = _normalize_identifier(gt)
    if not g_norm:
        return 1.0 if not p_norm else 0.0
    if p_norm == g_norm:
        return 1.0

    p_doi, g_doi = _extract_doi(pred), _extract_doi(gt)
    if p_doi and g_doi and p_doi == g_doi:
        return 0.95
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

    return min(combined_semantic_score(pred, gt), _IDENTIFIER_SEMANTIC_CAP)


def exact_match(pred: str, gt: str) -> float:
    p = re.sub(r"\s+", "", pred.strip().lower())
    g = re.sub(r"\s+", "", gt.strip().lower())
    if not g:
        return 1.0 if not p else 0.0
    if p == g:
        return 1.0
    return identifier_match(pred, gt)


def categorical_match(pred: str, gt: str) -> float:
    p = _normalize_categorical(pred)
    g = _normalize_categorical(gt)
    if not g:
        return 1.0 if not p else 0.0
    return 1.0 if p == g else 0.0


def numeric_tolerance_match(pred: str, gt: str, rel_tol: float = 0.02) -> float:
    p_num = _extract_number(pred)
    g_num = _extract_number(gt)
    if p_num is None or g_num is None:
        return identifier_match(pred, gt)

    if g_num == 0:
        return 1.0 if abs(p_num) < 1e-9 else 0.0

    rel_err = abs(p_num - g_num) / abs(g_num)
    if rel_err <= rel_tol:
        return 1.0
    if rel_err <= 0.05:
        return 0.7 + 0.3 * (0.05 - rel_err) / (0.05 - rel_tol)
    if rel_err <= 0.10:
        return 0.3 + 0.4 * (0.10 - rel_err) / 0.05
    return 0.0


_EXACT_KEYWORDS = (
    "accession", "orcid", "barcode", "isbn", "issn", "email", "file", "filename",
)
_IDENTIFIER_KEYWORDS = (
    "identifier", " doi", "url", "contenturl", "reference",
)
_SEMANTIC_KEYWORDS = (
    "title", "description", "notes", "protocol", "subject", "name",
    "loading", "condition", "design", "facility", "mutation", "type",
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


def rule_match_score(pred: str, gt: str, match_type: str) -> float:
    if match_type == "exact":
        return exact_match(pred, gt)
    if match_type == "identifier":
        return identifier_match(pred, gt)
    if match_type == "numeric_tolerance":
        return numeric_tolerance_match(pred, gt)
    if match_type == "categorical":
        return categorical_match(pred, gt)
    return combined_semantic_score(pred, gt)


def fuse_rule_and_semantic(rule_score: float, semantic_score: float, match_type: str) -> float:
    """
    Combine deterministic rule score with semantic judgment.

    ``semantic`` fields use semantic path directly. Other types take the max
    of rule and semantic so paraphrases are not zeroed when formatting differs.
    ``categorical`` stays strict (no semantic rescue).
    """
    if match_type == "semantic":
        return semantic_score
    if match_type == "categorical":
        return rule_score
    if match_type == "numeric_tolerance":
        if rule_score >= PARTIAL_THRESHOLD:
            return rule_score
        return max(rule_score, semantic_score * _NUMERIC_SEMANTIC_BLEND)
    return max(rule_score, semantic_score)


@dataclass
class ValueMatchResult:
    score: float
    semantic_score: float
    token_f1_score: float
    semantic_judgment_score: float
    rule_score: float
    match_type: str
    semantic_available: bool


def score_value_pair(
    pred: str,
    gt: str,
    match_type: Optional[str] = None,
    field_name: Optional[str] = None,
) -> ValueMatchResult:
    """Score one prediction against GT with explicit semantic breakdown."""
    mt = match_type or (classify_match_type(field_name) if field_name else "semantic")
    _, _, tf1 = token_f1(pred, gt)
    sem = semantic_sim(pred, gt)
    semantic_judgment = combined_semantic_score(pred, gt)
    rule = rule_match_score(pred, gt, mt) if pred.strip() and gt.strip() else 0.0
    final = fuse_rule_and_semantic(rule, semantic_judgment, mt) if pred.strip() else 0.0

    return ValueMatchResult(
        score=final,
        semantic_score=round(sem, 4),
        token_f1_score=round(tf1, 4),
        semantic_judgment_score=round(semantic_judgment, 4),
        rule_score=round(rule, 4),
        match_type=mt,
        semantic_available=semantic_similarity_available(),
    )


def match_value(
    pred: str,
    gt: str,
    match_type: Optional[str] = None,
    field_name: Optional[str] = None,
) -> float:
    return score_value_pair(pred, gt, match_type=match_type, field_name=field_name).score


def classify_status(score: float, match_type: str = "semantic") -> str:
    if match_type == "categorical":
        return "match" if score >= 1.0 else "wrong"
    if score >= MATCH_THRESHOLD:
        return "match"
    if score >= PARTIAL_THRESHOLD:
        return "partial"
    return "wrong"


def normalise_field_name(name: str) -> str:
    return re.sub(r"[\s_\-]+", " ", name.lower().strip())
