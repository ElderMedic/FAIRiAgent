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
from pathlib import Path
from typing import Any, Dict, List, Optional

from .base import BaseAgent
from .critic import safe_json_parse
from .react_loop import ReactLoopMixin
from .response_models import ISAValueMappingResponse
from ..models import FAIRifierState
from ..services.fairds_api_parser import FAIRDSAPIParser
from ..config import config
from ..utils.isa_order import ISA_LEVEL_ORDER, MULTI_ROW_ISA_LEVELS
from ..tools.isa_structure_tools import create_isa_structure_tools
from ..skills import load_skill_files, skills_catalog_seed_files

logger = logging.getLogger(__name__)

# ── Constants ──────────────────────────────────────────────────────────

ISA_LEVELS = ISA_LEVEL_ORDER

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


class ISAValueMapperAgent(ReactLoopMixin, BaseAgent):
    """Produces ``isa_values`` — the columns×rows matrix for Excel prefill.

    This agent receives all metadata fields already extracted by
    ``JSONGeneratorAgent`` plus the full pipeline context and produces a
    per-ISA-level ``{columns, rows}`` structure where every row has the
    identical set of column keys (empty string for missing cells).
    """

    def __init__(self) -> None:
        super().__init__("ISAValueMapper")
        self.llm_helper = self._get_llm({})

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

        # ── Cardinality gate for deep agent ───────────────────────────
        # Deep agent tool loops scale poorly with entity count.
        # For high-cardinality docs, skip the agentic path and use the
        # deterministic heuristic directly — it handles N rows just as
        # well (entity_id grouping), without the risk of a 1 h+ hang.
        distinct_entity_ids: int = len({
            fd.get("entity_id", "")
            for fd in metadata_fields
            if fd.get("entity_id")
        })
        # Count fields with values — docs with many populated rows are
        # the ones that cause ISAValueMapper to generate huge grids.
        populated_sample_fields: int = sum(
            1 for fd in metadata_fields
            if fd.get("isa_sheet") in ("sample", "observationunit")
            and fd.get("value")
        )
        _CARDINALITY_CAP = 12   # entity groups; above this the deep agent rarely finishes

        matrix: Dict[str, Dict[str, Any]]
        tool_metrics: Dict[str, Any] = {}
        tool_issues: List[str] = []

        use_deep_mapping = (
            config.enable_deep_agents
            and distinct_entity_ids <= _CARDINALITY_CAP
            and populated_sample_fields < 60
        )
        if config.enable_deep_agents and not use_deep_mapping:
            self.logger.info(
                "⏭️  Skipping deep mapping agent (%d entity groups, %d populated sample/observationunit fields) — "
                "using deterministic heuristic to avoid agent-loop hang",
                distinct_entity_ids,
                populated_sample_fields,
            )
        if use_deep_mapping:
            inner_agent = self._build_ivm_inner_agent(
                source_workspace=source_ws,
                critic_feedback=critic_feedback,
                planner_instruction=planner_instruction,
                prior_memory_context=prior_memory_context or None,
            )
            task_desc = (
                "Build the ISA matrix by actively inspecting the source workspace with tools. "
                "Use grep, targeted reads, table search, and read-only shell commands when useful. "
                "Do not rely on unstated assumptions or hardcoded extraction rules. "
                "Respect ISA unfold order: investigation -> study -> observationunit -> sample -> assay. "
                "If supplementary inputs exist in the workspace, inspect them as first-class sources and merge them."
            )
            structured = await self._invoke_react_agent(
                inner_agent,
                task_message=self._compose_task_message(state, task_desc),
                seed_files=self._build_ivm_seed_files(
                    fields_by_level=fields_by_level,
                    knowledge_items=knowledge_items,
                    source_workspace=source_ws,
                    document_context=document_context,
                ),
                thread_id=f"{state.get('session_id', 'default')}-ivm-inner",
                state=state,
                scratchpad_name=self.name,
            )
            if structured:
                matrix = self._structured_matrix_to_dict(structured)
                tool_metrics = self._derive_tool_metrics(matrix, state)
                tool_issues.extend(getattr(structured, "quality_issues", []) or [])
                if self._is_empty_matrix(matrix):
                    self.logger.warning(
                        "ISAValueMapper inner loop returned an empty matrix; using deterministic field fallback"
                    )
                    matrix = self._build_matrix_heuristic(fields_by_level)
                    matrix = self._merge_source_workspace_entity_rows(matrix, source_ws)
            else:
                matrix = {}
        else:
            matrix = {}

        if not matrix:
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
                matrix = self._build_matrix_heuristic(fields_by_level)
                matrix = self._merge_source_workspace_entity_rows(matrix, source_ws)

        # ── Post-process: normalize, split entities, align columns ───
        matrix = self._split_entities_heuristic(matrix)
        matrix = self._normalize_row_columns(matrix)
        quality = self._compute_matrix_quality(matrix, tool_metrics, tool_issues)
        state["isa_value_quality"] = quality

        # ── Store in state ───────────────────────────────────────────
        if "artifacts" not in state:
            state["artifacts"] = {}
        state["artifacts"]["isa_values_json"] = json.dumps(
            matrix, indent=2, ensure_ascii=False
        )

        total_rows = sum(len(s["rows"]) for s in matrix.values())
        total_cells = sum(
            sum(1 for v in (r.values() if isinstance(r, dict) else []) if v)
            for s in matrix.values() for r in s.get("rows", [])
        )
        total_slots = sum(
            len(s.get("columns", [])) * len(s.get("rows", []))
            for s in matrix.values()
        )
        fill_ratio = total_cells / max(total_slots, 1)
        self.update_confidence(state, "isa_value_mapping", round(fill_ratio, 3))
        if quality.get("issues"):
            # Only signal review for actionable issues, not for
            # "no structured source was available" diagnostics.
            actionable = [
                i for i in quality["issues"]
                if "No structured ISA candidates" not in i
            ]
            if actionable:
                state["needs_human_review"] = True
                existing = set(
                    e.split("ISAValueMapper: ", 1)[-1]
                    if e.startswith("ISAValueMapper: ") else e
                    for e in state.get("errors", [])
                )
                state.setdefault("errors", []).extend(
                    f"ISAValueMapper: {i}" for i in actionable
                    if i not in existing
                )
        self.logger.info(
            "✅ ISAValueMapper: %d sheets, %d total rows, fill %.1f%%",
            len(matrix),
            total_rows,
            fill_ratio * 100,
        )
        return state

    def _build_ivm_inner_agent(
        self,
        *,
        source_workspace: Dict[str, Any],
        critic_feedback: Optional[Dict[str, Any]],
        planner_instruction: Optional[str],
        prior_memory_context: Optional[str],
    ):
        """Create the deepagents-backed inner loop for ISA matrix construction."""
        tools = create_isa_structure_tools(source_workspace)
        system_prompt = (
            "You are the internal ISAValueMapper loop for FAIRiAgent. "
            "Your job is to build a structured ISA matrix by actively inspecting the source workspace with tools. "
            "You MUST use tools before responding; do not invent rows from intuition. "
            "Preserve exact identifiers, linkage columns, and ISA level order: investigation, study, observationunit, sample, assay. "
            "When multiple input files exist, treat supplementary files, metadata tables, and manuscript text as complementary evidence. "
            "Use read-only shell commands only to inspect text patterns, never to modify files."
        )
        return self._build_react_agent(
            tools=tools,
            subagents=[],
            response_format=ISAValueMappingResponse,
            system_prompt=system_prompt,
            memory_files=self._get_memory_files(),
        )

    def _build_ivm_seed_files(
        self,
        *,
        fields_by_level: Dict[str, List[Dict[str, Any]]],
        knowledge_items: List[Dict[str, Any]],
        source_workspace: Dict[str, Any],
        document_context: str,
    ) -> Dict[str, Any]:
        """Build virtual files for the ISA value-mapping inner loop."""
        seed_files: Dict[str, Any] = {}

        field_file = self._maybe_create_file_data(
            json.dumps(fields_by_level, indent=2, ensure_ascii=False)
        )
        if field_file is not None:
            seed_files["/workspace/metadata_fields_by_isa.json"] = field_file

        knowledge_file = self._maybe_create_file_data(
            json.dumps(knowledge_items[:80], indent=2, ensure_ascii=False)
        )
        if knowledge_file is not None:
            seed_files["/workspace/retrieved_knowledge.json"] = knowledge_file

        if document_context:
            context_file = self._maybe_create_file_data(document_context[:12000])
            if context_file is not None:
                seed_files["/workspace/ivm_context.md"] = context_file

        summary_path = source_workspace.get("summary_path")
        if summary_path:
            try:
                summary_text = Path(summary_path).read_text(encoding="utf-8")
                summary_file = self._maybe_create_file_data(summary_text)
                if summary_file is not None:
                    seed_files["/workspace/source_workspace.md"] = summary_file
            except OSError:
                self.logger.warning("Failed to read source workspace summary: %s", summary_path)

        manifest_path = source_workspace.get("manifest_path")
        if manifest_path:
            try:
                manifest_text = Path(manifest_path).read_text(encoding="utf-8")
                manifest_file = self._maybe_create_file_data(manifest_text)
                if manifest_file is not None:
                    seed_files["/workspace/source_manifest.json"] = manifest_file
            except OSError:
                self.logger.warning("Failed to read source workspace manifest: %s", manifest_path)

        seed_files.update(load_skill_files(*config.skill_roots))
        seed_files.update(
            skills_catalog_seed_files(
                *config.skill_roots,
                create_file_data=self._maybe_create_file_data,
            )
        )
        return seed_files

    def _structured_matrix_to_dict(
        self,
        structured: ISAValueMappingResponse,
    ) -> Dict[str, Dict[str, Any]]:
        """Convert a structured ISAValueMappingResponse into the matrix dict."""
        result: Dict[str, Dict[str, Any]] = {}
        payload = structured.model_dump()
        for level in ISA_LEVELS:
            level_data = payload.get(level) or {}
            result[level] = {
                "columns": list(level_data.get("columns") or []),
                "rows": list(level_data.get("rows") or []),
            }
        return result

    def _derive_tool_metrics(
        self,
        matrix: Dict[str, Dict[str, Any]],
        state: FAIRifierState,
    ) -> Dict[str, Any]:
        """Summarize whether the inner loop used tools and produced multi-row structure."""
        scratchpad = (state.get("react_scratchpad") or {}).get(self.name, {})
        return {
            "tools_called": list(scratchpad.get("tools_called") or []),
            "tool_backed_rows": sum(len((sheet or {}).get("rows") or []) for sheet in matrix.values()),
            "has_tool_evidence": bool(scratchpad.get("tools_called")),
        }

    def _is_empty_matrix(self, matrix: Dict[str, Dict[str, Any]]) -> bool:
        """Return True when a matrix has no rows with values in any ISA sheet."""
        for sheet in matrix.values():
            rows = (sheet or {}).get("rows") or []
            for row in rows:
                if isinstance(row, dict) and any(str(v).strip() for v in row.values() if v is not None):
                    return False
        return True

    def _merge_tool_candidates(
        self,
        matrix: Dict[str, Dict[str, Any]],
        candidate_matrix: Dict[str, Dict[str, Any]],
    ) -> Dict[str, Dict[str, Any]]:
        """Merge tool-backed rows into an ISA matrix without overwriting richer rows."""
        result = {
            level: {
                "columns": list((matrix.get(level) or {}).get("columns") or []),
                "rows": list((matrix.get(level) or {}).get("rows") or []),
            }
            for level in ISA_LEVELS
        }
        id_fields = {
            "study": "study identifier",
            "observationunit": "observation unit identifier",
            "sample": "sample identifier",
            "assay": "assay identifier",
        }
        for level in ISA_LEVELS:
            candidate = candidate_matrix.get(level) or {}
            rows = candidate.get("rows") or []
            if not isinstance(rows, list):
                continue
            id_field = id_fields.get(level)
            existing_ids = {
                str(row.get(id_field)).strip().lower()
                for row in result[level]["rows"]
                if isinstance(row, dict) and id_field and row.get(id_field)
            }
            for row in rows:
                if not isinstance(row, dict):
                    continue
                normalized = {
                    str(key).strip().lower(): value
                    for key, value in row.items()
                    if str(key).strip()
                }
                row_id = str(normalized.get(id_field, "")).strip().lower() if id_field else ""
                if row_id and row_id in existing_ids:
                    continue
                if row_id:
                    existing_ids.add(row_id)
                if normalized and normalized not in result[level]["rows"]:
                    result[level]["rows"].append(normalized)
            cols = set(result[level]["columns"])
            for row in result[level]["rows"]:
                if isinstance(row, dict):
                    cols.update(row.keys())
            result[level]["columns"] = sorted(cols)
        return result

    def _merge_source_workspace_entity_rows(
        self,
        matrix: Dict[str, Dict[str, Any]],
        source_workspace: Dict[str, Any],
    ) -> Dict[str, Dict[str, Any]]:
        """Seed multi-entity rows from explicit table sheet headers in sources.

        This is a deterministic safety net for cases where the agentic mapper
        fails to return rows, but MinerU/table conversion already exposed
        source-level sheet names such as ``[Sheet: ZYMO_EVEN]``.
        """
        sheet_names = self._extract_workspace_sheet_names(source_workspace)
        if not sheet_names:
            return matrix

        self._collapse_single_row_levels(matrix)
        parent_study = self._first_value(matrix, "study", "study identifier")
        specs = {
            "observationunit": ("observation unit identifier", "observation unit name"),
            "sample": ("sample identifier", "sample name"),
            "assay": ("assay identifier", "assay name"),
        }
        for level, (id_col, name_col) in specs.items():
            target = matrix.setdefault(level, {"columns": [], "rows": []})
            rows = target.setdefault("rows", [])
            sheet_name_set = {name.strip().lower() for name in sheet_names}
            shared_rows = [
                row for row in rows
                if isinstance(row, dict)
                and str(row.get(id_col) or "").strip().lower() not in sheet_name_set
            ]
            rows[:] = [
                row for row in rows
                if isinstance(row, dict)
                and str(row.get(id_col) or "").strip().lower() in sheet_name_set
            ]
            existing = {
                str(row.get(id_col)).strip().lower()
                for row in rows
                if isinstance(row, dict) and row.get(id_col)
            }
            for sheet_name in sheet_names:
                key = sheet_name.strip()
                if not key or key.lower() in existing:
                    continue
                row = {id_col: key, name_col: key}
                if level == "observationunit" and parent_study:
                    row["study identifier"] = parent_study
                elif level == "sample":
                    row["observation unit identifier"] = key
                elif level == "assay":
                    row["sample identifier"] = key
                rows.append(row)
                existing.add(key.lower())
            if shared_rows and rows:
                for row in rows:
                    if not isinstance(row, dict):
                        continue
                    for shared in shared_rows:
                        for col, value in shared.items():
                            if col == id_col or not value:
                                continue
                            if not row.get(col):
                                row[col] = value
            cols = set(str(c).strip().lower() for c in target.get("columns", []) if str(c).strip())
            for row in rows:
                if isinstance(row, dict):
                    cols.update(str(c).strip().lower() for c in row.keys() if str(c).strip())
            target["columns"] = sorted(cols)
        return matrix

    def _collapse_single_row_levels(self, matrix: Dict[str, Dict[str, Any]]) -> None:
        for level in ("investigation", "study"):
            sheet = matrix.get(level) or {}
            rows = sheet.get("rows") or []
            if len(rows) <= 1:
                continue
            merged: Dict[str, Any] = {}
            for row in rows:
                if not isinstance(row, dict):
                    continue
                for col, value in row.items():
                    if value and not merged.get(col):
                        merged[col] = value
            sheet["rows"] = [merged] if merged else []
            cols = set(str(c).strip().lower() for c in sheet.get("columns", []) if str(c).strip())
            cols.update(str(c).strip().lower() for c in merged.keys() if str(c).strip())
            sheet["columns"] = sorted(cols)

    def _extract_workspace_sheet_names(self, source_workspace: Dict[str, Any]) -> List[str]:
        paths: List[str] = []
        summary_path = source_workspace.get("summary_path")
        if summary_path:
            paths.append(str(summary_path))
        for path in (source_workspace.get("source_paths") or {}).values():
            if path:
                paths.append(str(path))

        seen: set[str] = set()
        names: List[str] = []
        for path in paths:
            try:
                text = Path(path).read_text(encoding="utf-8", errors="ignore")
            except OSError:
                continue
            for match in re.finditer(r"^\[Sheet:\s*([^\]\n]+)\]\s*$", text, flags=re.MULTILINE):
                name = match.group(1).strip()
                if name and name.lower() not in seen:
                    names.append(name)
                    seen.add(name.lower())
        return names

    def _first_value(
        self,
        matrix: Dict[str, Dict[str, Any]],
        level: str,
        column: str,
    ) -> str:
        for row in (matrix.get(level) or {}).get("rows", []) or []:
            if isinstance(row, dict) and row.get(column):
                return str(row[column])
        return ""

    def _compute_matrix_quality(
        self,
        matrix: Dict[str, Dict[str, Any]],
        tool_metrics: Dict[str, Any],
        tool_issues: List[str],
    ) -> Dict[str, Any]:
        row_counts = {
            level: len((matrix.get(level) or {}).get("rows") or [])
            for level in ISA_LEVELS
        }
        link_fields = {
            "study": "investigation identifier",
            "observationunit": "study identifier",
            "sample": "observation unit identifier",
            "assay": "sample identifier",
        }
        missing_link_counts: Dict[str, int] = {}
        for level, field_name in link_fields.items():
            rows = (matrix.get(level) or {}).get("rows") or []
            missing_link_counts[level] = sum(
                1 for row in rows if isinstance(row, dict) and not row.get(field_name)
            )
        issues = list(dict.fromkeys(tool_issues))
        if tool_metrics.get("has_tool_evidence") and row_counts.get("assay", 0) <= 1:
            issues.append("Tool-backed structured evidence was present, but assay rows were not expanded.")
        if tool_metrics.get("has_tool_evidence") and row_counts.get("observationunit", 0) <= 1:
            issues.append("Tool-backed structured evidence was present, but observation-unit rows were not expanded.")
        for level, count in missing_link_counts.items():
            if row_counts.get(level, 0) > 0 and count == row_counts[level] and level != "study":
                issues.append(f"All {level} rows are missing their parent linkage field.")
        return {
            "row_counts": row_counts,
            "missing_link_counts": missing_link_counts,
            "tool_metrics": tool_metrics,
            "issues": issues,
            "submission_ready": not issues,
        }

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
            "**ISA levels:** investigation, study, observationunit, sample, assay.\n\n"
            "**Rules:**\n"
            "1. Columns = all unique field names for that ISA level.\n"
            "2. Rows = one per distinct entity. Investigation and study have 1 row.\n"
            "   Observationunit, sample, assay may have multiple rows if the document "
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
            "  nanomaterials, produce 3+ rows for observationunit/sample/assay levels.\n"
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
        # Use brace-balanced extraction (via safe_json_parse); naive regex
        # ``\{.*?\}`` stops at the first ``}`` and breaks nested ISA matrices.
        parsed = safe_json_parse(content)
        if not isinstance(parsed, dict):
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
        """Build a matrix from flat fields WITHOUT LLM (deterministic fallback).

        Fields emitted by JSONGenerator already carry ``entity_id`` when the
        model identifies separate samples, observation units, or assays. Use
        that as the authoritative row grouping before falling back to a single
        row per sheet.
        """
        result: Dict[str, Dict[str, Any]] = {}
        for lvl in ISA_LEVELS:
            fds = fields_by_level.get(lvl, [])
            if not fds:
                result[lvl] = {"columns": [], "rows": []}
                continue

            columns: List[str] = []
            rows_by_entity: Dict[str, Dict[str, Any]] = {}
            row_order: List[str] = []
            for f in fds:
                name = (f.get("field_name") or "").strip().lower()
                if not name:
                    continue
                columns.append(name)
                entity_id = str(f.get("entity_id") or lvl).strip() or lvl
                if entity_id not in rows_by_entity:
                    rows_by_entity[entity_id] = {}
                    row_order.append(entity_id)
                val = f.get("value")
                rows_by_entity[entity_id][name] = str(val) if val is not None else ""

            rows = [rows_by_entity[eid] for eid in row_order if rows_by_entity[eid]]
            result[lvl] = {
                "columns": sorted(set(columns)),
                "rows": rows,
            }
        return result

    # ── Entity splitting (heuristic) ───────────────────────────────────

    def _split_entities_heuristic(
        self,
        matrix: Dict[str, Dict[str, Any]],
    ) -> Dict[str, Dict[str, Any]]:
        """Split single-row sheets into multi-row when semicolons or patterns exist."""
        multi = MULTI_ROW_ISA_LEVELS

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
