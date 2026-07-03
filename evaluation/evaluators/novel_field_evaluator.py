"""
Layer 4 - Novel Field Classification Evaluator for FAIRiAgent outputs.

Replaces the old confidence-based "adjusted precision" mitigation in
``correctness_evaluator.py`` (which exempted extra fields from the precision
penalty based on the *model's own self-reported confidence* -- not a
defensible signal, since an over-confident model would simply benefit).

For every extracted field that is not in the field-presence ground truth,
this evaluator classifies it into one of three buckets:

- ``beneficial_discovery`` (evidence-grounded + in FAIR-DS/ISA vocabulary
  scope) -- reported as ``discovery_rate``, **not** penalized.
- ``domain_insight`` (evidence-grounded but out of current vocabulary scope)
  -- reported separately as ``untracked_insight_rate``, neutral. Surfaces
  candidate fields for future schema/package extension -- this directly
  operationalizes "may inspire researchers".
- ``unsupported_fabrication`` (not evidence-grounded, regardless of
  vocabulary) -- the only bucket counted as a real false positive.

A field is "evidence-grounded" if its evidence string cites a source
location (cheap regex pre-filter,
``fairifier.utils.grounding.SOURCE_REF_PATTERN``) *or* its value text
demonstrably occurs (exactly or via fuzzy/token overlap) in the run's source
document text. Both checks are cheap (regex + a local sentence-transformer
model already used by Layer 2) -- no extra LLM calls, consistent with the
benchmark's existing runtime constraints.

Missing-artifact fallback: if a run has no source text available for
grounding (e.g. older runs, or BioMetadataAgent runs on BAM/VCF/FASTQ with no
paper text to ground against), affected non-GT fields are classified as
``ungroundable_no_evaluation_data`` and excluded from the fabrication-penalty
denominator, rather than defaulting to ``unsupported_fabrication``. Silently
penalizing runs for missing *evaluation* artifacts (not missing *model*
quality) would reintroduce exactly the kind of validity problem this
redesign is meant to remove.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Optional, Set

from fairifier.utils.grounding import SOURCE_REF_PATTERN

from ._value_matching import normalize_tokens, token_f1, semantic_sim, normalise_field_name

GROUNDING_TOKEN_F1_THRESHOLD = 0.4  # matches Layer 2's PARTIAL_THRESHOLD
GROUNDING_SEMANTIC_THRESHOLD = 0.55


class NovelFieldEvaluator:
    """Layer 4: evidence-grounded classification of non-GT (extra) fields."""

    def __init__(self, vocabulary_paths: Optional[List[Path]] = None):
        """
        Args:
            vocabulary_paths: JSON package/term-catalog files to build the
                in-vocabulary scope check from (each entry's ``label`` /
                ``field_name`` is treated as a known term). If omitted, or if
                none can be loaded (e.g. ``kb/`` not populated locally), the
                scope check is treated as *unknown*: grounded fields are
                conservatively classified as ``domain_insight`` rather than
                ``beneficial_discovery`` since in-vocabulary membership can't
                be confirmed.
        """
        self.vocab_terms: Set[str] = set()
        self.vocab_known = False
        for path in vocabulary_paths or self._default_vocabulary_paths():
            self._load_vocabulary(path)

    @staticmethod
    def _default_vocabulary_paths() -> List[Path]:
        repo_root = Path(__file__).resolve().parents[2]
        candidates = []
        pkg_dir = repo_root / "evaluation" / "config" / "packages"
        if pkg_dir.exists():
            candidates.extend(sorted(pkg_dir.glob("*.json")))
        kb_dir = repo_root / "kb"
        if kb_dir.exists():
            candidates.extend(sorted(kb_dir.rglob("*.json")))
        return candidates

    def _load_vocabulary(self, path: Path) -> None:
        try:
            with open(path, encoding="utf-8") as f:
                data = json.load(f)
        except Exception:
            return
        entries = data.get("metadata", data if isinstance(data, list) else [])
        for entry in entries:
            if not isinstance(entry, dict):
                continue
            label = entry.get("label") or entry.get("field_name") or entry.get("term", {}).get("label")
            if label:
                self.vocab_terms.add(normalise_field_name(str(label)))
                self.vocab_known = True

    def _in_vocabulary(self, field_name: str) -> Optional[bool]:
        if not self.vocab_known:
            return None  # unknown -- catalog not available
        return normalise_field_name(field_name) in self.vocab_terms

    # ------------------------------------------------------------------
    # Grounding
    # ------------------------------------------------------------------

    @staticmethod
    def _value_in_source(value: str, source_text: str) -> bool:
        """Cheap fuzzy check: does `value` demonstrably occur in `source_text`?"""
        value = value.strip()
        if not value or not source_text:
            return False
        lowered_source = source_text.lower()
        if value.lower() in lowered_source:
            return True

        value_tokens = normalize_tokens(value)
        if not value_tokens:
            return False

        # Short values (identifiers, numbers): require a stronger token match
        # since a single common word appearing anywhere in a long doc is
        # not meaningful evidence.
        if len(value_tokens) <= 3:
            return False  # already failed the exact substring check above

        # Longer text values: scan source line-by-line for the best overlap,
        # using a rare-token pre-filter to avoid scoring every line.
        rare_tokens = set(value_tokens)
        best_f1 = 0.0
        for line in source_text.splitlines():
            if not line.strip():
                continue
            line_tokens = set(normalize_tokens(line))
            if not (rare_tokens & line_tokens):
                continue
            _, _, f1 = token_f1(line, value)
            if f1 > best_f1:
                best_f1 = f1
            if best_f1 >= GROUNDING_TOKEN_F1_THRESHOLD:
                return True
        if best_f1 >= GROUNDING_TOKEN_F1_THRESHOLD:
            return True

        # Last resort: semantic similarity against the whole document is too
        # expensive per-line; skip unless doc is small.
        if len(source_text) < 20000:
            return semantic_sim(value, source_text[:5000]) >= GROUNDING_SEMANTIC_THRESHOLD
        return False

    def _is_grounded(self, field: Dict[str, Any], source_text: Optional[str]) -> bool:
        evidence = str(field.get("evidence", "") or "")
        if SOURCE_REF_PATTERN.search(evidence):
            return True
        if source_text is None:
            return False
        value = str(field.get("value", "") or "")
        return self._value_in_source(value, source_text)

    # ------------------------------------------------------------------
    # Extraction helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _extract_fields(fairifier_output: Dict[str, Any]) -> List[Dict[str, Any]]:
        fields = []
        isa_structure = fairifier_output.get("isa_structure", {})
        for sheet_name, sheet_data in isa_structure.items():
            if sheet_name == "description" or not isinstance(sheet_data, dict):
                continue
            for field in sheet_data.get("fields", []):
                fields.append({
                    "field_name": field.get("field_name", ""),
                    "value": field.get("value", ""),
                    "evidence": field.get("evidence", ""),
                    "confidence": field.get("confidence", 0.0),
                    "isa_sheet": sheet_name,
                })
        if not fields:
            for field in fairifier_output.get("metadata", []):
                fields.append({
                    "field_name": field.get("field_name", ""),
                    "value": field.get("value", ""),
                    "evidence": field.get("evidence", ""),
                    "confidence": field.get("confidence", 0.0),
                    "isa_sheet": field.get("isa_sheet", "unknown"),
                })
        return fields

    # ------------------------------------------------------------------
    # Main evaluation
    # ------------------------------------------------------------------

    def evaluate(
        self,
        fairifier_output: Dict[str, Any],
        gt_field_names: Set[str],
        source_text: Optional[str] = None,
        true_positives: Optional[int] = None,
    ) -> Dict[str, Any]:
        """
        Args:
            fairifier_output: parsed metadata.json
            gt_field_names: normalized GT field names (from field-presence GT)
            source_text: paper.md contents for this run, or None if unavailable
            true_positives: TP count from CorrectnessEvaluator (Layer 1), used
                to compute ``precision_excl_discoveries``. If omitted, falls
                back to the count of extracted fields that ARE in GT.
        """
        gt_norm = {normalise_field_name(n) for n in gt_field_names}
        extracted = self._extract_fields(fairifier_output)

        novel_fields = [f for f in extracted if normalise_field_name(f["field_name"]) not in gt_norm]
        tp = true_positives if true_positives is not None else (len(extracted) - len(novel_fields))

        classified: List[Dict[str, Any]] = []
        for field in novel_fields:
            if source_text is None:
                bucket = "ungroundable_no_evaluation_data"
                grounded = None
                in_vocab = self._in_vocabulary(field["field_name"])
            else:
                grounded = self._is_grounded(field, source_text)
                in_vocab = self._in_vocabulary(field["field_name"])
                if not grounded:
                    bucket = "unsupported_fabrication"
                elif in_vocab is True:
                    bucket = "beneficial_discovery"
                else:
                    # in_vocab is False or None (catalog unavailable) -> be
                    # conservative, treat as domain_insight rather than
                    # rewarding it as a confirmed in-scope discovery.
                    bucket = "domain_insight"

            classified.append({
                "field_name": field["field_name"],
                "isa_sheet": field.get("isa_sheet", "unknown"),
                "grounded": grounded,
                "in_vocabulary": in_vocab,
                "bucket": bucket,
            })

        n_beneficial = sum(1 for c in classified if c["bucket"] == "beneficial_discovery")
        n_insight = sum(1 for c in classified if c["bucket"] == "domain_insight")
        n_fabrication = sum(1 for c in classified if c["bucket"] == "unsupported_fabrication")
        n_ungroundable = sum(1 for c in classified if c["bucket"] == "ungroundable_no_evaluation_data")

        precision_denominator = tp + n_fabrication
        precision_excl_discoveries = tp / precision_denominator if precision_denominator else 0.0

        n_gt = len(gt_norm) or 1
        return {
            "classified_fields": classified,
            "summary_metrics": {
                "n_novel_fields": len(novel_fields),
                "beneficial_discovery_count": n_beneficial,
                "domain_insight_count": n_insight,
                "unsupported_fabrication_count": n_fabrication,
                "ungroundable_count": n_ungroundable,
                "discovery_rate": n_beneficial / n_gt,
                "untracked_insight_rate": n_insight / n_gt,
                "precision_excl_discoveries": precision_excl_discoveries,
                "had_source_text": source_text is not None,
            },
        }

    def evaluate_batch(
        self,
        fairifier_outputs: Dict[str, Dict[str, Any]],
        gt_field_names_by_doc: Dict[str, Set[str]],
        source_texts_by_doc: Optional[Dict[str, Optional[str]]] = None,
        true_positives_by_doc: Optional[Dict[str, int]] = None,
    ) -> Dict[str, Any]:
        source_texts_by_doc = source_texts_by_doc or {}
        true_positives_by_doc = true_positives_by_doc or {}

        per_document: Dict[str, Any] = {}
        for doc_id, gt_names in gt_field_names_by_doc.items():
            if doc_id not in fairifier_outputs:
                continue
            per_document[doc_id] = self.evaluate(
                fairifier_outputs[doc_id],
                gt_names,
                source_text=source_texts_by_doc.get(doc_id),
                true_positives=true_positives_by_doc.get(doc_id),
            )

        return {"per_document": per_document, "aggregated": self._aggregate(per_document)}

    @staticmethod
    def _aggregate(per_document: Dict[str, Any]) -> Dict[str, Any]:
        if not per_document:
            return {}
        keys = ["discovery_rate", "untracked_insight_rate", "precision_excl_discoveries"]
        agg = {f"mean_{k}": sum(r["summary_metrics"][k] for r in per_document.values()) / len(per_document) for k in keys}
        agg["total_unsupported_fabrication"] = sum(
            r["summary_metrics"]["unsupported_fabrication_count"] for r in per_document.values()
        )
        agg["total_ungroundable"] = sum(
            r["summary_metrics"]["ungroundable_count"] for r in per_document.values()
        )
        agg["n_documents"] = len(per_document)
        return agg


def find_source_text(run_dir: Path) -> Optional[str]:
    """
    Locate and read this run's converted source document text, for grounding.

    Looks for ``mineru_paper/**/paper.md`` under the run directory (confirmed
    present per successful run in the standard pipeline output layout).
    Returns None (triggering the missing-artifact fallback) if not found.
    """
    candidates = list(run_dir.glob("mineru_paper/**/paper.md"))
    if not candidates:
        return None
    try:
        return candidates[0].read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return None
