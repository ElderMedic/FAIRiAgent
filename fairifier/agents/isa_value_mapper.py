"""ISA Value Mapper Agent — generates the columns×rows value matrix for Excel.

This agent bridges the gap between flat metadata extraction and the structured
ISA Excel workbook.  It takes the metadata fields produced by
:class:`JSONGeneratorAgent`, the original document, FAIR-DS knowledge, and
available context (critic feedback, memory, source workspace) and produces a
clean ``columns × rows`` matrix per ISA sheet.

Unlike the JSON generator which focuses on extracting individual field values,
this agent reasons about *entities* — which fields belong to the same sample,
assay, or observation unit — and ensures each entity row carries a complete,
aligned set of cells.

Design
------
- **Orchestrator-managed** — runs as a named agent node in the LangGraph
  workflow, downstream of ``JSONGeneratorAgent``.
- **Critic-aware** — receives critic feedback and retries.
- **Memory-backed** — pulls prior memories to improve entity resolution.
- **FAIR-DS tool access** — can query the FAIR-DS API for field-level
  definitions (requirement, data type, allowed values) via its
  ``KnowledgeRetriever`` reference.
"""

from __future__ import annotations

import json
import logging
import re
from typing import Any, Dict, List, Optional, Tuple

from .base import BaseAgent
from ..models import FAIRifierState, MetadataField
from ..services.fairds_api_parser import FAIRDSAPIParser
from ..config import config

logger = logging.getLogger(__name__)

# ── Constants ──────────────────────────────────────────────────────────

ISA_LEVELS = ("investigation", "study", "assay", "sample", "observationunit")

# Fields that are internal database keys (not extractable from documents).
# The agent should NOT fabricate values for these.
_SYNTHETIC_ID_FIELDS: set = {
    "observation unit identifier",
    "sample identifier",
    "assay identifier",
    "study identifier",
    "investigation identifier",
}


def _is_synthetic_id(field_name: str) -> bool:
    return field_name.strip().lower() in _SYNTHETIC_ID_FIELDS


# ── Agent ──────────────────────────────────────────────────────────────


class ISAValueMapperAgent(BaseAgent):
    """Produces ``isa_values`` — the columns×rows matrix for Excel prefill.

    This agent receives all metadata fields already extracted by
    ``JSONGeneratorAgent`` plus the full pipeline context and produces a
    per-ISA-level ``{columns, rows}`` structure where every row has the
    identical set of column keys (empty string for missing cells).
    """

    def __init__(self) -> None:
        super().__init__("ISAValueMapper")

    # ── Main execution ───────────────────────────────────────────────

    async def execute(self, state: FAIRifierState) -> FAIRifierState:
        self.logger.info("📊 ISAValueMapper: building columns×rows value matrix")

        metadata_fields: List[Dict[str, Any]] = state.get("metadata_fields", [])
        if not metadata_fields:
            self.logger.warning("No metadata_fields in state — skipping value mapper")
            return state

        # ── Build context the same way JSONGenerator does ────────────
        from ..services.evidence_packets import build_evidence_context
        from .json_generator import JSONGeneratorAgent

        evidence_packets = state.get("evidence_packets", []) or []
        source_ws = state.get("source_workspace", {}) or {}

        # Share JSONGenerator's context builders (avoid code duplication).
        # We need a temporary instance just to call the helper methods.
        _ctx_agent = JSONGeneratorAgent()

        evidence_ctx = build_evidence_context(evidence_packets, max_packets=20, max_chars=3200)
        workspace_ctx = _ctx_agent._build_source_workspace_context(source_ws)
        field_evidence_ctx, _ = _ctx_agent._build_field_source_evidence_context(
            source_ws,
            state.get("retrieved_knowledge", []),
        )

        context_parts = [
            p for p in (evidence_ctx, workspace_ctx, field_evidence_ctx) if p
        ]
        document_context = "\n\n".join(context_parts)

        knowledge_items: List[Dict[str, Any]] = state.get(
            "retrieved_knowledge", []
        )

        # ── Context & feedback ───────────────────────────────────────
        feedback = self.get_context_feedback(state)
        critic_feedback = feedback.get("critic_feedback")
        planner_instruction = feedback.get("planner_instruction")
        prior_memory_context = self.format_retrieved_memories_for_prompt(
            feedback.get("retrieved_memories") or []
        )

        if critic_feedback:
            self.logger.info("🔄 Retrying value mapping with Critic feedback")
            for suggestion in critic_feedback.get("suggestions", [])[:3]:
                self.logger.info("   🔧 %s", suggestion)

        # ── Group fields by ISA level ─────────────────────────────────
        fields_by_level: Dict[str, List[Dict[str, Any]]] = {
            lvl: [] for lvl in ISA_LEVELS
        }
        for fd in metadata_fields:
            sheet = FAIRDSAPIParser.normalize_isa_sheet(fd.get("isa_sheet"))
            if sheet in fields_by_level:
                fields_by_level[sheet].append(fd)

        # ── Invoke LLM with rich context (NOT raw document text) ──────
        try:
            matrix = await self._build_matrix_with_llm(
                fields_by_level=fields_by_level,
                knowledge_items=knowledge_items,
                document_context=document_context,
                critic_feedback=critic_feedback,
                planner_instruction=planner_instruction,
                prior_memory_context=prior_memory_context,
                state=state,
            )
        except Exception as exc:
            self.logger.error("ISA value mapping failed: %s", exc)
            # Fall back to heuristic matrix from flat fields.
            matrix = self._build_matrix_heuristic(fields_by_level)

        # ── Post-process: normalize, split entities, align columns ───
        matrix = self._split_entities_heuristic(matrix)
        matrix = self._normalize_row_columns(matrix)

        # ── Store in state ───────────────────────────────────────────
        if "artifacts" not in state:
            state["artifacts"] = {}
        state["artifacts"]["isa_values_json"] = json.dumps(
            matrix, indent=2, ensure_ascii=False
        )

        self._apply_isa_matrix_to_metadata_json(state, matrix)

        total_rows = sum(len(s["rows"]) for s in matrix.values())
        self.logger.info(
            "✅ ISAValueMapper: %d sheets, %d total rows",
            len(matrix),
            total_rows,
        )
        return state

    def _apply_isa_matrix_to_metadata_json(
        self,
        state: FAIRifierState,
        matrix: Dict[str, Dict[str, Any]],
    ) -> None:
        """Write the mapper matrix into ``artifacts.metadata_json`` as ``isa_values``."""
        artifacts = state.get("artifacts") or {}
        raw = artifacts.get("metadata_json")
        if not raw or not matrix:
            return
        try:
            parsed = json.loads(raw) if isinstance(raw, str) else raw
        except json.JSONDecodeError as exc:
            self.logger.warning(
                "ISAValueMapper: cannot merge isa_values (metadata_json parse error): %s",
                exc,
            )
            return
        if not isinstance(parsed, dict):
            return
        parsed["isa_values"] = {
            sheet: {
                "columns": list(matrix.get(sheet, {}).get("columns") or []),
                "rows": [
                    dict(r) if isinstance(r, dict) else r
                    for r in (matrix.get(sheet, {}) or {}).get("rows") or []
                ],
            }
            for sheet in ISA_LEVELS
        }
        state.setdefault("artifacts", {})
        state["artifacts"]["metadata_json"] = json.dumps(
            parsed, indent=2, ensure_ascii=False
        )

    # ── LLM-based matrix construction ─────────────────────────────────

    async def _build_matrix_with_llm(
        self,
        fields_by_level: Dict[str, List[Dict[str, Any]]],
        knowledge_items: List[Dict[str, Any]],
        document_context: str,
        critic_feedback: Optional[Dict[str, Any]],
        planner_instruction: Optional[str],
        prior_memory_context: Optional[str],
        state: FAIRifierState,
    ) -> Dict[str, Dict[str, Any]]:
        """Use the LLM to produce a structured columns×rows matrix."""

        from ..utils.llm_helper import LLMHelper

        llm = self._get_llm(state)

        # ── Build system prompt ─────────────────────────────────────
        system = (
            "You are a metadata structuring expert. Your task is to organise "
            "extracted metadata fields into a clean table (columns × rows) "
            "for each ISA level.\n\n"
            "**ISA levels:** investigation, study, assay, sample, observationunit.\n\n"
            "**Rules:**\n"
            "1. Columns = all unique field names for that ISA level.\n"
            "2. Rows = one per distinct entity. Investigation and study have 1 row.\n"
            "   Assay, sample, observationunit may have multiple rows if the document "
            "   describes multiple experiments, sample groups, or sequencing runs.\n"
            "3. Every row MUST have exactly the same column keys. "
            "   Use empty string '' for missing values — NEVER omit a column.\n"
            "4. Do NOT invent synthetic identifiers (no auto-generated IDs). "
            "   Use values from the document or leave empty.\n"
            "5. Shared fields (same value across all entities) go in every row; "
            "   entity-specific fields use the value for that entity.\n\n"
            "**Detecting entities from the document:**\n"
            "- Look for distinct experiments, treatment groups, time points, "
            "  sample types, or sequencing runs described in the document.\n"
            "- If the document explicitly describes 3 experiments with different "
            "  nanomaterials, produce 3+ rows for sample/assay levels.\n"
            "- If the document only describes one study, use 1 row per level.\n\n"
            "**Output format (JSON):**\n"
            "Wrap in ```json ... ```. Return a dict with one key per ISA level:\n"
            '{"investigation": {"columns": [...], "rows": [{...}]}, ...}'
        )

        # ── Build user prompt ───────────────────────────────────────
        user_parts = []

        # Extracted fields summary
        field_summary = {}
        for lvl in ISA_LEVELS:
            fds = fields_by_level.get(lvl, [])
            field_summary[lvl] = {
                "count": len(fds),
                "fields": [
                    {
                        "field_name": f.get("field_name", ""),
                        "value": str(f.get("value", ""))[:200] if f.get("value") else "",
                        "confidence": f.get("confidence", 0),
                        "required": f.get("required", False),
                    }
                    for f in fds
                ],
            }
        user_parts.append(
            "Extracted metadata fields:\n"
            + json.dumps(field_summary, indent=2, ensure_ascii=False)
        )

        # Knowledge items summary (field definitions from FAIR-DS)
        if knowledge_items:
            ki_summary = []
            for ki in knowledge_items[:50]:
                meta = ki.get("metadata", {}) if isinstance(ki, dict) else {}
                ki_summary.append({
                    "term": ki.get("term", "") if isinstance(ki, dict) else "",
                    "isa_sheet": FAIRDSAPIParser.normalize_isa_sheet(
                        meta.get("isa_sheet") or meta.get("sheet")
                    ),
                    "required": meta.get("required", False),
                })
            user_parts.append(
                "FAIR-DS field definitions:\n"
                + json.dumps(ki_summary, indent=2, ensure_ascii=False)
            )

        # Structured document context (source workspace + evidence + field candidates)
        if document_context:
            user_parts.append(
                "Structured source context (evidence packets, workspace, field candidates):\n"
                + document_context[:8000]
            )

        # Critic / planner
        if critic_feedback:
            user_parts.append(
                "Critic feedback to address:\n"
                + json.dumps(critic_feedback, indent=2, ensure_ascii=False)
            )
        if planner_instruction:
            user_parts.append(f"Planner instruction: {planner_instruction}")

        user_prompt = "\n\n".join(user_parts)

        # ── Construct prior context (memory) ────────────────────────
        messages = []
        if prior_memory_context:
            from langchain_core.messages import HumanMessage
            messages.append(HumanMessage(content=prior_memory_context))
        from langchain_core.messages import SystemMessage, HumanMessage as HM

        messages.extend([
            SystemMessage(content=system),
            HM(content=user_prompt),
        ])

        # ── Call LLM ────────────────────────────────────────────────
        try:
            response = await llm._call_llm(
                messages, operation_name="ISA Value Mapping"
            )
            content = response.content if hasattr(response, "content") else str(response)
        except Exception:
            self.logger.warning("LLM call failed for ISA value mapping; using heuristic")
            return self._build_matrix_heuristic(fields_by_level)

        # ── Parse response ──────────────────────────────────────────
        try:
            # Extract JSON from markdown
            json_match = re.search(
                r"```(?:json)?\s*(\{.*?\})\s*```", content, re.DOTALL
            )
            if json_match:
                parsed = json.loads(json_match.group(1))
            else:
                parsed = json.loads(content)
        except (json.JSONDecodeError, AttributeError):
            self.logger.warning("Failed to parse LLM JSON; falling back to heuristic")
            return self._build_matrix_heuristic(fields_by_level)

        # ── Validate & merge ────────────────────────────────────────
        result: Dict[str, Dict[str, Any]] = {}
        for lvl in ISA_LEVELS:
            lvl_data = parsed.get(lvl, {})
            result[lvl] = {
                "columns": lvl_data.get("columns", []),
                "rows": lvl_data.get("rows", []),
            }

        return result

    # ── Heuristic fallback ────────────────────────────────────────────

    def _build_matrix_heuristic(
        self,
        fields_by_level: Dict[str, List[Dict[str, Any]]],
    ) -> Dict[str, Dict[str, Any]]:
        """Build a matrix from flat fields WITHOUT LLM (deterministic fallback)."""
        result: Dict[str, Dict[str, Any]] = {}
        for lvl in ISA_LEVELS:
            fds = fields_by_level.get(lvl, [])
            if not fds:
                result[lvl] = {"columns": [], "rows": []}
                continue

            # Single row: one field per column
            row: Dict[str, Any] = {}
            columns: List[str] = []
            for f in fds:
                name = (f.get("field_name") or "").strip().lower()
                if not name:
                    continue
                columns.append(name)
                val = f.get("value")
                row[name] = str(val) if val is not None else ""
            result[lvl] = {
                "columns": sorted(set(columns)),
                "rows": [row] if row else [],
            }
        return result

    # ── Entity splitting (heuristic) ───────────────────────────────────

    def _split_entities_heuristic(
        self,
        matrix: Dict[str, Dict[str, Any]],
    ) -> Dict[str, Dict[str, Any]]:
        """Split single-row sheets into multi-row when semicolons or patterns exist."""
        multi = {"sample", "assay", "observationunit"}

        for lvl in multi:
            sheet = matrix.get(lvl)
            if not sheet:
                continue
            rows = sheet.get("rows", [])
            if len(rows) != 1:
                continue

            row = rows[0]
            best_count = 1
            best_field = ""
            best_parts: List[str] = []

            for key, val in row.items():
                text = str(val) if val else ""
                if "not specified" in text.lower():
                    continue
                # Semicolons
                if ";" in text:
                    parts = [p.strip() for p in text.split(";") if p.strip()]
                    meaningful = [p for p in parts if len(p) > 10]
                    if len(meaningful) >= 2:
                        avg = sum(len(p) for p in meaningful) / len(meaningful)
                        if all(avg * 0.3 < len(p) < avg * 3.0 for p in meaningful):
                            if len(meaningful) > best_count:
                                best_count = len(meaningful)
                                best_field = key
                                best_parts = meaningful
                # "Experiment N" repeats
                exp = re.split(r"(?=(?:Experiment|Group|Treatment)\s+\d+)", text)
                if len(exp) >= 2:
                    parts = [p.strip() for p in exp if len(p.strip()) > 10]
                    if len(parts) > best_count:
                        best_count = len(parts)
                        best_field = key
                        best_parts = parts

            if best_count < 2:
                continue

            new_rows: List[Dict[str, Any]] = []
            for i in range(best_count):
                erow: Dict[str, Any] = {}
                for key, val in row.items():
                    text = str(val) if val else ""
                    if ";" in text:
                        parts = [p.strip() for p in text.split(";")]
                        erow[key] = parts[i] if i < len(parts) else parts[-1]
                    elif key == best_field:
                        erow[key] = best_parts[i] if i < len(best_parts) else best_parts[-1]
                    else:
                        erow[key] = val
                new_rows.append(erow)

            sheet["rows"] = new_rows
            self.logger.debug(
                "Entity split: '%s' 1→%d rows (field='%s')", lvl, len(new_rows), best_field
            )

        return matrix

    # ── Matrix normalization ──────────────────────────────────────────

    def _normalize_row_columns(
        self,
        matrix: Dict[str, Dict[str, Any]],
    ) -> Dict[str, Dict[str, Any]]:
        """Ensure every row in a sheet has the same column keys."""
        for _lvl, sheet in matrix.items():
            rows = sheet.get("rows", [])
            if not rows:
                continue

            all_cols: set = set()
            for row in rows:
                all_cols.update(row.keys())
            for c in sheet.get("columns", []):
                all_cols.add(str(c).strip().lower())

            sorted_cols = sorted(all_cols)
            sheet["columns"] = sorted_cols

            for row in rows:
                for col in sorted_cols:
                    if col not in row:
                        row[col] = ""

        return matrix

    # ── Helpers ───────────────────────────────────────────────────────

    def _get_llm(self, state: FAIRifierState):
        """Get or create an LLMHelper instance configured from config."""
        from ..utils.llm_helper import get_llm_helper

        return get_llm_helper()

    def format_retrieved_memories_for_prompt(
        self, memories: List[Any]
    ) -> Optional[str]:
        """Format memory items into a prompt string."""
        if not memories:
            return None
        parts = ["Prior session memories:"]
        for m in memories[:5]:
            if isinstance(m, dict):
                parts.append(
                    f"- {m.get('memory', str(m))}"
                )
            else:
                parts.append(f"- {str(m)}")
        return "\n".join(parts)


__all__ = ["ISAValueMapperAgent"]
