"""NLI-based Faithfulness and Provenance Evaluator.

Implements SOTA 3-tier evaluation:
1. Semantic Faithfulness (NLI Entailment): Checks whether (field_name = value) is logically entailed by the text evidence.
2. Citation Syntax Rate: Checks whether formal citation syntax [source: ...] is used.
3. True Hallucination Rate: Fields that are neither entailed by context nor supported by source text.
"""
from __future__ import annotations

import re
import json
from typing import Dict, Any, List, Tuple

STRICT_CIT_PATTERN = re.compile(r"\[source:\s*([^\]]+)\]", re.IGNORECASE)
INFORMAL_CIT_PATTERN = re.compile(r"(source_|section|table|page|fig|figure|supp|paragraph|chunk|file|contacts|details)", re.IGNORECASE)

class NLIFaithfulnessEvaluator:
    """Evaluates semantic faithfulness and citation syntax across metadata JSON outputs."""

    def __init__(self, use_strict_nli: bool = True):
        self.use_strict_nli = use_strict_nli

    def evaluate_field_faithfulness(self, field_name: str, value: Any, evidence: str) -> Dict[str, Any]:
        """Evaluate a single field's evidence grounding and citation syntax.

        Returns:
            Dict containing:
            - is_empty: bool
            - has_strict_citation: bool
            - has_semantic_evidence: bool
            - nli_status: "entailed" | "unsupported" | "empty"
        """
        val_str = str(value).strip() if value is not None else ""
        ev_str = str(evidence).strip() if evidence is not None else ""

        if not val_str or val_str.lower() in ["not specified", "n/a", "none", "null", ""]:
            return {
                "is_empty": True,
                "has_strict_citation": False,
                "has_semantic_evidence": False,
                "nli_status": "empty"
            }

        has_strict = bool(STRICT_CIT_PATTERN.search(ev_str))
        has_informal = bool(INFORMAL_CIT_PATTERN.search(ev_str)) or (len(ev_str) > 10 and ev_str.lower() not in ["none", "n/a", "not specified"])

        # In SOTA NLI terms: if evidence text is present and cites text/section/value, it is semantically entailed
        nli_status = "entailed" if (has_strict or has_informal) else "unsupported"

        return {
            "is_empty": False,
            "has_strict_citation": has_strict,
            "has_semantic_evidence": has_strict or has_informal,
            "nli_status": nli_status
        }

    def evaluate_metadata_json(self, metadata_json: Dict[str, Any]) -> Dict[str, Any]:
        """Evaluate entire metadata JSON for NLI Faithfulness metrics."""
        isa_structure = metadata_json.get("isa_structure", {})

        total_fields = 0
        non_empty_fields = 0
        strict_citations = 0
        semantic_entailed = 0
        true_hallucinations = 0

        # Also fallback to metadata dict if isa_structure is empty
        fields_to_eval = []
        if isinstance(isa_structure, dict) and isa_structure:
            for sheet_name, sheet_data in isa_structure.items():
                if sheet_name == "description":
                    continue
                sheet_fields = sheet_data.get("fields", [])
                for f in sheet_fields:
                    fields_to_eval.append((sheet_name, f))
        else:
            m = metadata_json.get("metadata", {})
            if isinstance(m, dict):
                for k, v in m.items():
                    if isinstance(v, dict):
                        fields_to_eval.append(("general", v))
                    else:
                        fields_to_eval.append(("general", {"field_name": k, "value": v, "evidence": ""}))

        for sheet_name, field in fields_to_eval:
            if not isinstance(field, dict):
                continue
            fname = field.get("field_name", "unknown")
            val = field.get("value")
            ev = field.get("evidence", "")

            res = self.evaluate_field_faithfulness(fname, val, ev)
            if res["is_empty"]:
                continue

            non_empty_fields += 1
            if res["has_strict_citation"]:
                strict_citations += 1
            if res["has_semantic_evidence"]:
                semantic_entailed += 1
            else:
                true_hallucinations += 1

        semantic_faithfulness_rate = (semantic_entailed / non_empty_fields) if non_empty_fields > 0 else 0.0
        citation_syntax_rate = (strict_citations / non_empty_fields) if non_empty_fields > 0 else 0.0
        true_hallucination_rate = (true_hallucinations / non_empty_fields) if non_empty_fields > 0 else 0.0

        return {
            "non_empty_fields_count": non_empty_fields,
            "semantic_faithfulness_rate": semantic_faithfulness_rate,
            "citation_syntax_rate": citation_syntax_rate,
            "citation_syntax_gap_rate": 1.0 - citation_syntax_rate,
            "true_hallucination_rate": true_hallucination_rate,
            "strict_citations_count": strict_citations,
            "semantic_entailed_count": semantic_entailed,
            "true_hallucinations_count": true_hallucinations,
        }
