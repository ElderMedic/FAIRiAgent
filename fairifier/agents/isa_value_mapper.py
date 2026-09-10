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
from typing import Any, Dict, List, Mapping, Optional

from .base import BaseAgent
from ..utils.json_parse import safe_json_parse
from ..utils.document_text import read_document_text
from .react_loop import ReactLoopMixin
from .response_models import ISAValueMappingResponse
from ..models import FAIRifierState
from ..services.fairds_api_parser import FAIRDSAPIParser
from ..config import config
from ..utils.isa_order import ISA_LEVEL_ORDER, MULTI_ROW_ISA_LEVELS
from ..utils.isa_matrix_projection import sync_compiled_matrix_to_state
from ..utils.entity_plan import (
    _entity_description,
    normalize_source_measurement_value,
    project_matrix_onto_entity_plan,
    render_entity_plan_for_prompt,
    validate_entity_matrix_against_plan,
)
from ..utils.fairds_value_contracts import (
    build_contract_index,
    canonicalize_value,
    contract_for,
    is_field_selector_contract,
)
from ..tools.isa_structure_tools import create_isa_structure_tools
from ..skills import load_skill_files, skills_catalog_seed_files

# Maximum evidence candidates to surface per field in the seed file.
_MAX_EVIDENCE_CANDIDATES_PER_FIELD = 5

logger = logging.getLogger(__name__)

# ── Constants ──────────────────────────────────────────────────────────

ISA_LEVELS = ISA_LEVEL_ORDER
_FAIRDS_IDENTIFIER_RE = re.compile(r"^[A-Za-z0-9_.-]{5,50}$")

# Core FAIR-DS columns follow the same order as the curated FAIR-DS workbooks.
# Package-specific extensions retain their upstream order after this core.
_FAIRDS_CORE_COLUMN_ORDER: Dict[str, List[str]] = {
    "investigation": [
        "investigation identifier",
        "investigation title",
        "investigation description",
        "firstname",
        "lastname",
        "email address",
        "orcid",
        "organization",
        "department",
    ],
    "study": [
        "study identifier",
        "study description",
        "study title",
        "investigation identifier",
    ],
    "observationunit": [
        "observation unit identifier",
        "observation unit name",
        "observation unit description",
        "study identifier",
    ],
    "sample": [
        "sample identifier",
        "sample description",
        "sample name",
        "ncbi taxonomy id",
        "scientific name",
        "biosafety level",
        "observation unit identifier",
        "collection date",
    ],
    "assay": [
        "assay identifier",
        "assay description",
        "protocol",
        "facility",
        "assay date",
        "sample identifier",
    ],
}

# ISA-Tab-style wrappers the LLM sometimes adds around canonical FAIR-DS
# term names (e.g. "characteristic[organism]" for "organism").
_ISA_TAB_WRAPPER_RE = re.compile(
    r"^(?:characteristic|comment|factor\s+value|parameter\s+value)\[(.+)\]$",
    re.IGNORECASE,
)

# Cell values that carry no information and therefore cannot be used to
# attribute a renamed column back to its upstream field.
_PLACEHOLDER_CELL_VALUES = frozenset({
    "", "not specified", "n/a", "na", "none", "unknown", "null", "-", "tbd",
})
_MISSING_VALUE_RE = re.compile(
    r"\b(?:not specified|not reported|not provided|not available|"
    r"unspecified|unknown)\b",
    re.IGNORECASE,
)

# Fields that are internal database keys (not extractable from documents).
# The agent should NOT fabricate values for these.
_SYNTHETIC_ID_FIELDS: set = {
    "observation unit identifier",
    "sample identifier",
    "assay identifier",
    "study identifier",
    "investigation identifier",
}

_IDENTIFIER_FIELDS = {
    "investigation": "investigation identifier",
    "study": "study identifier",
    "observationunit": "observation unit identifier",
    "sample": "sample identifier",
    "assay": "assay identifier",
}
_PARENT_IDENTIFIER_FIELDS = {
    "study": "investigation identifier",
    "observationunit": "study identifier",
    "sample": "observation unit identifier",
    "assay": "sample identifier",
}
_ENTITY_DESCRIPTION_FIELDS = {
    "investigation": "investigation description",
    "study": "study description",
    "observationunit": "observation unit description",
    "sample": "sample description",
    "assay": "assay description",
}


def _is_synthetic_id(field_name: str) -> bool:
    return field_name.strip().lower() in _SYNTHETIC_ID_FIELDS


def _norm_cell(value: Any) -> str:
    return " ".join(str(value or "").strip().lower().split())


def _is_missing_cell(value: Any) -> bool:
    text = _norm_cell(value)
    return text in _PLACEHOLDER_CELL_VALUES or bool(_MISSING_VALUE_RE.search(text))


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
        entity_plan = state.get("entity_plan") or {}
        # Read once at the execution boundary so both agentic and deterministic
        # mapping paths use the same source when deciding whether an optional
        # value is genuinely evidenced.
        document_text = read_document_text(state)

        # §4.1 — Load EvidenceStore JSONL to surface section-level FieldCandidates
        # to ISAValueMapper (previously this layer was invisible to it).
        evidence_store_meta: Dict[str, Any] = state.get("evidence_store") or {}
        evidence_summary = self._build_evidence_store_summary(evidence_store_meta)
        if evidence_summary:
            self.logger.info(
                "📂 EvidenceStore: loaded %d field candidates from section-level extraction",
                evidence_summary.get("field_count", 0),
            )
        else:
            self.logger.debug("EvidenceStore JSONL not available — skipping field evidence backfill")

        # Share JSONGenerator's context builders (avoid code duplication).
        # We need a temporary instance just to call the helper methods.
        _ctx_agent = JSONGeneratorAgent()

        evidence_ctx = build_evidence_context(evidence_packets, max_packets=20, max_chars=3200)
        workspace_ctx = _ctx_agent._build_source_workspace_context(source_ws)
        field_evidence_ctx, _ = _ctx_agent._build_field_source_evidence_context(
            source_ws,
            state.get("retrieved_knowledge", []),
        )

        entity_plan_context = render_entity_plan_for_prompt(
            state.get("entity_plan") or {}
        )
        context_parts = [
            p
            for p in (
                entity_plan_context,
                evidence_ctx,
                workspace_ctx,
                field_evidence_ctx,
            )
            if p
        ]
        document_context = "\n\n".join(context_parts)

        knowledge_items: List[Dict[str, Any]] = state.get(
            "retrieved_knowledge", []
        )
        value_contracts = build_contract_index(knowledge_items)

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
                normalized = dict(fd)
                try:
                    confidence = float(normalized.get("confidence") or 0.0)
                except (TypeError, ValueError):
                    confidence = 0.0
                if (
                    ("confidence" in normalized and confidence <= 0.0)
                    or _is_missing_cell(normalized.get("value"))
                ):
                    normalized["value"] = ""
                fields_by_level[sheet].append(normalized)

        matrix: Dict[str, Dict[str, Any]]
        tool_metrics: Dict[str, Any] = {}
        tool_issues: List[str] = []

        # Tool-driven mapping is useful for real tables and multi-file bundles,
        # not for repeatedly rereading one abstract. Entity count is deliberately
        # not used as a cutoff: cardinality belongs to the structure plan.
        use_deep_mapping = config.enable_deep_agents and (
            not entity_plan or self._needs_tool_mapping(source_ws)
        )
        if config.enable_deep_agents and not use_deep_mapping:
            self.logger.info(
                "⏭️  Source workspace has no tables or supplementary sources; "
                "using one structured mapping call plus deterministic plan compilation",
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
                "The entity plan in /workspace/ivm_context.md is authoritative: fill its rows and links; "
                "do not merge rows or replace internal row IDs with series-level identifiers. "
                "Column keys must be the exact field_name strings from the metadata fields; "
                "renaming, reformatting, or wrapping terms is not allowed. "
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
                    evidence_summary=evidence_summary,
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
                    matrix = self._build_matrix_heuristic(fields_by_level, evidence_summary)
                    matrix = self._merge_source_workspace_entity_rows(matrix, source_ws)
                else:
                    matrix = self._enforce_field_name_passthrough(
                        matrix, fields_by_level, drop_untraceable=False
                    )
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
                matrix = self._enforce_field_name_passthrough(
                    matrix, fields_by_level, drop_untraceable=True
                )
            except Exception as exc:
                self.logger.error("ISA value mapping failed: %s", exc)
                matrix = self._build_matrix_heuristic(fields_by_level, evidence_summary)
                matrix = self._merge_source_workspace_entity_rows(matrix, source_ws)

        # ── Post-process: normalize, project entities, align columns ───
        matrix = self._seed_missing_planned_levels(matrix, entity_plan)
        matrix = self._restore_high_confidence_shared_values(
            matrix,
            fields_by_level,
            value_contracts,
            entity_plan,
        )
        # The structure planner is authoritative when present.  Delimiter-based
        # splitting is only a legacy fallback; applying it before projection can
        # turn list-valued attributes into spurious ISA entities.
        if not entity_plan:
            matrix = self._split_entities_heuristic(matrix)
        matrix = self._normalize_row_columns(matrix)
        matrix = self._ensure_core_linkage_fields(matrix, state)
        if entity_plan:
            matrix = project_matrix_onto_entity_plan(matrix, entity_plan)
            matrix = self._normalize_row_columns(matrix)
            matrix, scope_clears = self._clear_values_outside_plan_field_scope(
                matrix, entity_plan
            )
            if scope_clears:
                self.logger.info(
                    "🧭 Cleared %d values outside plan-declared field scope: %s",
                    sum(scope_clears.values()),
                    scope_clears,
                )
            matrix, group_scope_issues = (
                self._clear_values_outside_group_evidence_scope(
                    matrix,
                    fields_by_level,
                    entity_plan,
                )
            )
            tool_issues.extend(group_scope_issues)
        matrix = self._normalize_source_measurement_units(matrix, document_text)
        matrix, provisional_issues = self._clear_unverified_provisional_values(
            matrix,
            fields_by_level,
            entity_plan,
            document_text,
        )
        tool_issues.extend(provisional_issues)
        matrix = self._ensure_selected_field_columns(matrix, fields_by_level)
        matrix, identifier_issues = self._canonicalize_structural_identifiers(
            matrix,
            entity_plan,
            value_contracts,
        )
        tool_issues.extend(identifier_issues)
        matrix, mapping_issues = self._demote_invalid_plan_attribute_mappings(
            matrix,
            entity_plan,
            value_contracts,
        )
        tool_issues.extend(mapping_issues)
        matrix, contract_issues = self._enforce_fairds_value_contracts(
            matrix,
            value_contracts,
        )
        tool_issues.extend(contract_issues)
        matrix, datatype_issues = self._sanitize_typed_matrix_values(
            matrix,
            fields_by_level,
        )
        tool_issues.extend(datatype_issues)
        matrix, pruned_columns = self._prune_uninformative_optional_columns(
            matrix,
            fields_by_level,
            entity_plan,
            source_text=document_text,
        )
        if pruned_columns:
            self.logger.info(
                "🧹 Removed %d uninformative optional/recommended columns: %s",
                sum(len(items) for items in pruned_columns.values()),
                pruned_columns,
            )
        # Single projection: compile once, write sidecar + metadata.json together.
        projected = sync_compiled_matrix_to_state(
            state,
            matrix,
            recompile=True,
            compiler_tag="isa_value_mapper",
        )
        matrix = projected["matrix"]
        quality = self._compute_matrix_quality(matrix, tool_metrics, tool_issues)
        if entity_plan:
            structure_validation = validate_entity_matrix_against_plan(
                matrix,
                entity_plan,
                expected_authors=(state.get("document_info") or {}).get("authors") or [],
            )
        else:
            structure_validation = {
                "passed": False,
                "submission_ready": False,
                "errors": ["No authoritative entity structure plan was available."],
                "warnings": [],
                "row_counts": quality.get("row_counts", {}),
                "investigation_contact_count": 0,
            }
        state["entity_matrix_validation"] = structure_validation
        self.logger.info(
            "Entity-matrix validation: passed=%s rows=%s errors=%s warnings=%s",
            structure_validation.get("passed", False),
            structure_validation.get("row_counts", {}),
            list(structure_validation.get("errors") or [])[:8],
            list(structure_validation.get("warnings") or [])[:8],
        )
        quality["entity_plan_validation"] = structure_validation
        quality["semantic_metrics"] = structure_validation.get("semantic_metrics", {})
        quality["pruned_uninformative_columns"] = pruned_columns
        quality["issues"] = list(
            dict.fromkeys(
                list(quality.get("issues") or [])
                + list(structure_validation.get("errors") or [])
                + list(structure_validation.get("warnings") or [])
            )
        )
        quality["submission_ready"] = bool(
            quality.get("submission_ready")
            and structure_validation.get("submission_ready")
        )
        state["isa_value_quality"] = quality

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

    @staticmethod
    def _needs_tool_mapping(source_workspace: Dict[str, Any]) -> bool:
        """Use the ReAct mapper only when tool inspection adds real evidence."""
        if source_workspace.get("table_paths"):
            return True
        manifest = source_workspace.get("manifest") or {}
        sources = [
            item
            for item in manifest.get("sources") or []
            if isinstance(item, dict)
        ]
        if len(sources) > 1:
            return True
        return any(
            item.get("tables")
            or str(item.get("content_type") or "").lower() == "table"
            or str(item.get("source_role") or "").lower()
            in {"supplement", "table", "metadata_table", "protocol"}
            for item in sources
        )

    @staticmethod
    def _ensure_selected_field_columns(
        matrix: Dict[str, Dict[str, Any]],
        fields_by_level: Dict[str, List[Dict[str, Any]]],
    ) -> Dict[str, Dict[str, Any]]:
        """Keep every selected FAIR-DS term as a matrix column on every row."""
        for level in ISA_LEVELS:
            block = matrix.setdefault(level, {"columns": [], "rows": []})
            columns = [str(column).strip().lower() for column in block.get("columns") or []]
            for field in fields_by_level.get(level) or []:
                field_name = str(field.get("field_name") or "").strip().lower()
                if field_name and field_name not in columns:
                    columns.append(field_name)
            block["columns"] = columns
            block["rows"] = [
                {column: row.get(column, "") for column in columns}
                for row in (block.get("rows") or [])
                if isinstance(row, dict)
            ]
        return matrix

    @staticmethod
    def _seed_missing_planned_levels(
        matrix: Dict[str, Dict[str, Any]],
        entity_plan: Dict[str, Any],
    ) -> Dict[str, Dict[str, Any]]:
        """Create a neutral seed row when a mapper omits a planned ISA level.

        Cardinality belongs to ``EntityStructurePlanner``.  A value-mapping LLM
        is allowed to leave cells blank, but returning zero rows for a level must
        not erase source-backed level-wide fields before deterministic plan
        projection.  One empty row is sufficient: the provenance-aware restore
        step can attach only confirmed shared values, and projection then creates
        the exact planned rows and links.
        """
        planned_levels = {
            str(item.get("level") or "")
            for item in (entity_plan or {}).get("levels") or []
            if isinstance(item, dict) and (item.get("entities") or [])
        }
        for level in planned_levels:
            if level not in ISA_LEVELS:
                continue
            block = matrix.setdefault(level, {"columns": [], "rows": []})
            rows = [row for row in block.get("rows") or [] if isinstance(row, dict)]
            if not rows:
                block["rows"] = [{}]
        return matrix

    @staticmethod
    def _restore_high_confidence_shared_values(
        matrix: Dict[str, Dict[str, Any]],
        fields_by_level: Dict[str, List[Dict[str, Any]]],
        value_contracts: Dict[tuple[str, str], Dict[str, Any]] | None = None,
        entity_plan: Dict[str, Any] | None = None,
    ) -> Dict[str, Dict[str, Any]]:
        """Restore source-backed values that the row mapper dropped or paraphrased.

        JSONGenerator has already extracted field values with provenance.  The
        mapper may reorganize rows, but it must not degrade a confirmed global
        value. At root levels a unique confirmed value is authoritative. At
        multi-entity levels, a unique value is *not* sufficient evidence of
        universality: the extractor must explicitly mark it as level-wide, and
        the structure plan must not assign that field to only a subset of rows.
        Entity/group values remain owned by the mapper and locked plan.
        """
        protected_multi = {
            "observation unit identifier",
            "observation unit name",
            "observation unit description",
            "study identifier",
            "sample identifier",
            "sample name",
            "sample description",
            "observation unit identifier",
            "assay identifier",
            "assay name",
            "assay description",
            "sample identifier",
        }
        for level, fields in fields_by_level.items():
            block = matrix.get(level)
            if not isinstance(block, dict):
                continue
            rows = [row for row in block.get("rows") or [] if isinstance(row, dict)]
            if not rows:
                continue
            candidates: Dict[str, List[tuple[str, str]]] = {}
            level_field_names = [
                str(field.get("field_name") or "").strip()
                for field in fields
                if isinstance(field, dict)
            ]
            for field in fields:
                if not isinstance(field, dict):
                    continue
                name = str(field.get("field_name") or "").strip().lower()
                value = str(field.get("value") or "").strip()
                status = str(field.get("status") or "").strip().lower()
                evidence = str(field.get("evidence") or "").strip()
                value_scope = str(field.get("value_scope") or "").strip().lower()
                try:
                    confidence = float(field.get("confidence") or 0.0)
                except (TypeError, ValueError):
                    confidence = 0.0
                if (
                    not name
                    or _is_missing_cell(value)
                    or confidence < 0.75
                    or status != "confirmed"
                    or not evidence
                ):
                    continue
                contract = contract_for(value_contracts or {}, level, name)
                if contract and canonicalize_value(value, contract) is None:
                    # A source phrase is not automatically a valid FAIR-DS cell.
                    # Preserve a mapper-produced canonical value, if present,
                    # instead of broadcasting the invalid upstream phrase.
                    continue
                if (
                    level not in {"investigation", "study"}
                    and contract
                    and is_field_selector_contract(contract, level_field_names)
                ):
                    # Selector values are group/entity-scoped. A single valid
                    # selector record must not be broadcast to sibling groups.
                    continue
                if level not in {"investigation", "study"}:
                    if value_scope != "level":
                        # Unknown, entity, and group scope are never safe to
                        # broadcast across a multi-row ISA level.  A conflicting
                        # synthetic entity_id does not overrule an explicit
                        # level-wide scope: the locked plan below is the
                        # authoritative check for whether broadcast is valid.
                        continue
                    if not ISAValueMapperAgent._plan_allows_level_broadcast(
                        entity_plan or {},
                        level,
                        name,
                        value,
                        allow_unmapped_entities=(
                            str(field.get("requirement") or "").strip().upper()
                            == "MANDATORY"
                        ),
                    ):
                        continue
                candidates.setdefault(name, []).append((value, evidence))

            is_root = level in {"investigation", "study"}
            for name, values in candidates.items():
                unique = {" ".join(value.lower().split()) for value, _ in values}
                if len(unique) != 1:
                    continue
                if not is_root and name in protected_multi:
                    continue
                value = values[0][0]
                if name not in block.setdefault("columns", []):
                    block["columns"].append(name)
                for row in rows:
                    if is_root or _is_missing_cell(row.get(name)):
                        row[name] = value
                if not is_root:
                    shared = block.setdefault("_shared_columns", [])
                    if name not in shared:
                        shared.append(name)
        return matrix

    @staticmethod
    def _plan_allows_level_broadcast(
        entity_plan: Dict[str, Any],
        level: str,
        field_name: str,
        value: str,
        *,
        allow_unmapped_entities: bool = False,
    ) -> bool:
        """Reject a level-wide claim contradicted by plan attribute scope.

        When the planner maps a field on only some entities, or maps different
        values across entities, that field is a design dimension rather than a
        sheet-wide constant. No domain- or field-specific pattern is used.
        """
        level_plan = next(
            (
                item
                for item in (entity_plan or {}).get("levels") or []
                if isinstance(item, dict) and item.get("level") == level
            ),
            None,
        )
        if not level_plan:
            return True
        entities = [
            entity
            for entity in level_plan.get("entities") or []
            if isinstance(entity, dict)
        ]
        mapped_values: List[str | None] = []
        field_is_mapped = False
        normalized_field = str(field_name or "").strip().lower()
        for entity in entities:
            entity_values = [
                str(attribute.get("value") or "").strip()
                for attribute in entity.get("attributes") or []
                if isinstance(attribute, dict)
                and str(attribute.get("field_name") or "").strip().lower()
                == normalized_field
            ]
            if entity_values:
                field_is_mapped = True
                mapped_values.append(entity_values[0])
            else:
                mapped_values.append(None)
        if not field_is_mapped:
            return True
        normalized = {
            " ".join(item.lower().split())
            for item in mapped_values
            if item is not None and item.strip()
        }
        candidate = " ".join(str(value or "").lower().split())
        if not entities or normalized != {candidate}:
            return False
        return allow_unmapped_entities or all(
            item is not None and item.strip() for item in mapped_values
        )

    @staticmethod
    def _canonicalize_structural_identifiers(
        matrix: Dict[str, Dict[str, Any]],
        entity_plan: Dict[str, Any],
        value_contracts: Dict[tuple[str, str], Dict[str, Any]],
    ) -> tuple[Dict[str, Dict[str, Any]], List[str]]:
        """Keep plan primary/foreign keys valid without discarding source labels.

        Source tables sometimes use short but meaningful labels (for example a
        four-character sample name) that do not satisfy a FAIR-DS identifier
        regex.  Clearing those cells destroys graph identity.  The matrix
        therefore keeps the source value in the entity name and substitutes a
        deterministic plan row ID only for the constrained key, then rewrites
        every child link from the same plan graph.
        """
        if not entity_plan:
            return matrix, []
        levels = {
            str(item.get("level") or "").strip().lower(): item
            for item in entity_plan.get("levels") or []
            if isinstance(item, dict)
        }
        resolved: Dict[str, Dict[str, str]] = {}
        replacement_counts: Dict[str, int] = {}
        issues: List[str] = []

        for level in ISA_LEVELS:
            block = matrix.get(level) or {}
            rows = [row for row in block.get("rows") or [] if isinstance(row, dict)]
            entities = [
                entity
                for entity in (levels.get(level) or {}).get("entities") or []
                if isinstance(entity, dict)
            ]
            if not rows or not entities:
                continue
            id_field = _IDENTIFIER_FIELDS[level]
            contract = contract_for(value_contracts, level, id_field)
            level_ids: Dict[str, str] = {}
            for row_index, row in enumerate(rows):
                entity_index = 0 if level == "investigation" else row_index
                if entity_index >= len(entities):
                    continue
                entity = entities[entity_index]
                row_id = str(entity.get("row_id") or "").strip()
                current = str(row.get(id_field) or "").strip()
                canonical = (
                    canonicalize_value(current, contract)
                    if contract
                    else current
                )
                if canonical is None or not canonical:
                    fallback = row_id
                    canonical = (
                        canonicalize_value(fallback, contract)
                        if contract
                        else fallback
                    )
                    if canonical is None:
                        issues.append(
                            f"Unable to create a FAIR-DS-compliant {level} identifier "
                            f"for planned row {row_id}."
                        )
                        continue
                    replacement_counts[level] = replacement_counts.get(level, 0) + 1
                row[id_field] = canonical
                entity["external_identifier"] = canonical
                level_ids[row_id] = canonical

                parent_field = _PARENT_IDENTIFIER_FIELDS.get(level)
                if parent_field:
                    parent_level = ISA_LEVELS[ISA_LEVELS.index(level) - 1]
                    parent_row_id = str(entity.get("parent_row_id") or "").strip()
                    parent_identifier = resolved.get(parent_level, {}).get(parent_row_id)
                    if parent_identifier:
                        row[parent_field] = parent_identifier
                    else:
                        issues.append(
                            f"Unable to resolve {level} parent {parent_row_id} "
                            f"while canonicalizing structural identifiers."
                        )

                if level == "assay" and parent_field and row.get(parent_field):
                    description_field = "assay description"
                    if description_field in block.get("columns", []) or description_field in row:
                        parent_entity = next(
                            (
                                item
                                for item in (levels.get("sample") or {}).get("entities") or []
                                if isinstance(item, dict)
                                and str(item.get("row_id") or "").strip()
                                == str(entity.get("parent_row_id") or "").strip()
                            ),
                            None,
                        )
                        row[description_field] = _entity_description(
                            entity,
                            level,
                            parent=parent_entity,
                            parent_identifier=str(row[parent_field]),
                        )
            resolved[level] = level_ids

        for level, count in sorted(replacement_counts.items()):
            issues.append(
                f"Used deterministic plan identifiers for {count} {level} row(s) "
                "whose source labels did not satisfy the selected FAIR-DS identifier contract; "
                "source labels remain in name/description fields."
            )
        return matrix, issues

    @staticmethod
    def _enforce_fairds_value_contracts(
        matrix: Dict[str, Dict[str, Any]],
        value_contracts: Dict[tuple[str, str], Dict[str, Any]],
    ) -> tuple[Dict[str, Dict[str, Any]], List[str]]:
        """Validate every populated cell governed by a FAIR-DS term pattern.

        The generation agents receive the same contracts and should normally
        emit canonical values.  This boundary is fail-closed: a value that does
        not full-match its field contract is cleared and surfaced for review,
        rather than allowing a plausible source phrase to masquerade as a
        controlled value.
        """
        issues: List[str] = []
        seen: set[tuple[str, str, str]] = set()
        for level, block in matrix.items():
            if not isinstance(block, dict):
                continue
            rows = [row for row in block.get("rows") or [] if isinstance(row, dict)]
            for row in rows:
                for field_name in list(row):
                    contract = contract_for(value_contracts, level, field_name)
                    if not contract or _is_missing_cell(row.get(field_name)):
                        continue
                    original = str(row.get(field_name) or "").strip()
                    canonical = canonicalize_value(original, contract)
                    if canonical is not None:
                        row[field_name] = canonical
                        continue
                    row[field_name] = ""
                    marker = (level, str(field_name).strip().lower(), original)
                    if marker in seen:
                        continue
                    seen.add(marker)
                    issues.append(
                        f"FAIR-DS value contract rejected {level}.{field_name}="
                        f"{original!r}; the unsupported value was cleared."
                    )
        return matrix, issues

    @staticmethod
    def _demote_invalid_plan_attribute_mappings(
        matrix: Dict[str, Dict[str, Any]],
        entity_plan: Dict[str, Any],
        value_contracts: Dict[tuple[str, str], Dict[str, Any]],
    ) -> tuple[Dict[str, Dict[str, Any]], List[str]]:
        """Keep explicit source factors without forcing them into invalid terms.

        A field mapping is only valid for an entity when the source value
        satisfies that selected FAIR-DS term's contract.  Invalid mappings are
        demoted back to an unmapped plan attribute and remain visible in the
        entity description; the controlled column stays blank.
        """
        if not entity_plan:
            return matrix, []
        levels = {
            str(item.get("level") or "").strip().lower(): item
            for item in entity_plan.get("levels") or []
            if isinstance(item, dict)
        }
        demoted: Dict[str, int] = {}
        for level in ISA_LEVELS:
            block = matrix.get(level) or {}
            rows = [row for row in block.get("rows") or [] if isinstance(row, dict)]
            entities = [
                entity
                for entity in (levels.get(level) or {}).get("entities") or []
                if isinstance(entity, dict)
            ]
            if not rows or not entities:
                continue
            for row_index, row in enumerate(rows):
                entity_index = 0 if level == "investigation" else row_index
                if entity_index >= len(entities):
                    continue
                entity = entities[entity_index]
                changed = False
                for attribute in entity.get("attributes") or []:
                    if not isinstance(attribute, dict):
                        continue
                    field_name = str(attribute.get("field_name") or "").strip().lower()
                    if not field_name:
                        continue
                    contract = contract_for(value_contracts, level, field_name)
                    if not contract:
                        continue
                    source_value = str(attribute.get("value") or "").strip()
                    canonical = canonicalize_value(source_value, contract)
                    if canonical is not None:
                        attribute["value"] = canonical
                        row[field_name] = canonical
                        continue
                    attribute["field_name"] = None
                    row[field_name] = ""
                    demoted[f"{level}.{field_name}"] = (
                        demoted.get(f"{level}.{field_name}", 0) + 1
                    )
                    changed = True
                if changed:
                    description_field = _ENTITY_DESCRIPTION_FIELDS[level]
                    if description_field in block.get("columns", []) or description_field in row:
                        parent_field = _PARENT_IDENTIFIER_FIELDS.get(level)
                        row[description_field] = _entity_description(
                            entity,
                            level,
                            parent=None,
                            parent_identifier=str(row.get(parent_field) or ""),
                        )
        issues = [
            f"Demoted {count} plan mapping(s) for {field}: source values did not "
            "satisfy the selected FAIR-DS value contract and remain in descriptions."
            for field, count in sorted(demoted.items())
        ]
        return matrix, issues

    @staticmethod
    def _clear_unverified_provisional_values(
        matrix: Dict[str, Dict[str, Any]],
        fields_by_level: Dict[str, List[Dict[str, Any]]],
        entity_plan: Dict[str, Any],
        source_text: str,
    ) -> tuple[Dict[str, Dict[str, Any]], List[str]]:
        """Prevent the mapper from upgrading unsupported provisional prose.

        JSONGenerator records whether a field extraction is confirmed. The row
        mapper may reorganize those values, but it has no per-cell evidence
        contract that would justify turning a provisional paraphrase into a
        sheet-wide fact. A provisional value is therefore retained only when
        it occurs literally in the source or is owned by an independently
        audited entity-plan mapping. Entity identifiers, names, descriptions,
        and investigation contacts are deterministic presentation fields and
        are exempt from this source-literal test.
        """
        derived_presentation_fields = {
            "investigation identifier",
            "investigation title",
            "investigation description",
            "firstname",
            "lastname",
            "email address",
            "orcid",
            "organization",
            "department",
            "study identifier",
            "study title",
            "study description",
            "observation unit identifier",
            "observation unit name",
            "observation unit description",
            "sample identifier",
            "sample name",
            "sample description",
            "assay identifier",
            "assay name",
            "assay description",
        }
        confirmed: Dict[str, set[str]] = {level: set() for level in ISA_LEVELS}
        provisional: Dict[str, set[str]] = {level: set() for level in ISA_LEVELS}
        for level, fields in fields_by_level.items():
            for field in fields:
                if not isinstance(field, Mapping):
                    continue
                field_name = str(field.get("field_name") or "").strip().lower()
                status = str(field.get("status") or "").strip().lower()
                if field_name and status == "confirmed":
                    confirmed.setdefault(level, set()).add(field_name)
                elif field_name and status == "provisional":
                    provisional.setdefault(level, set()).add(field_name)

        plan_mapped: Dict[str, set[str]] = {level: set() for level in ISA_LEVELS}
        for level_plan in entity_plan.get("levels") or []:
            if not isinstance(level_plan, Mapping):
                continue
            level = str(level_plan.get("level") or "").strip().lower()
            for entity in level_plan.get("entities") or []:
                if not isinstance(entity, Mapping):
                    continue
                for attribute in entity.get("attributes") or []:
                    if not isinstance(attribute, Mapping):
                        continue
                    field_name = str(
                        attribute.get("field_name") or ""
                    ).strip().lower()
                    if field_name:
                        plan_mapped.setdefault(level, set()).add(field_name)

        normalized_source = _norm_cell(source_text)

        issues: List[str] = []
        seen: set[tuple[str, str, str]] = set()
        for level, block in matrix.items():
            if not isinstance(block, Mapping):
                continue
            for row in block.get("rows") or []:
                if not isinstance(row, dict):
                    continue
                for raw_field_name, value in list(row.items()):
                    field_name = str(raw_field_name or "").strip().lower()
                    normalized_value = _norm_cell(value)
                    if (
                        not normalized_value
                        or field_name in derived_presentation_fields
                        or field_name in confirmed.get(level, set())
                        or field_name not in provisional.get(level, set())
                        or field_name in plan_mapped.get(level, set())
                        or normalized_value in normalized_source
                    ):
                        continue
                    row[raw_field_name] = ""
                    marker = (level, field_name, normalized_value)
                    if marker in seen:
                        continue
                    seen.add(marker)
                    issues.append(
                        "Unverified provisional value cleared for "
                        f"{level}.{field_name}: {str(value)!r}."
                    )
        return matrix, issues

    @staticmethod
    def _clear_values_outside_plan_field_scope(
        matrix: Dict[str, Dict[str, Any]],
        entity_plan: Dict[str, Any],
    ) -> tuple[Dict[str, Dict[str, Any]], Dict[str, int]]:
        """Clear generated values where a mapped design field does not apply.

        Projection writes plan-owned attributes onto their entities. If the
        mapping LLM independently broadcast a value into sibling rows, those
        cells must not survive on groups/entities for which the planner has no
        mapping. This is based solely on the plan graph, never field names or
        input-specific value patterns.
        """
        cleared: Dict[str, int] = {}
        for level_plan in entity_plan.get("levels") or []:
            if not isinstance(level_plan, Mapping):
                continue
            level = str(level_plan.get("level") or "").strip().lower()
            entities = [
                entity
                for entity in level_plan.get("entities") or []
                if isinstance(entity, Mapping)
            ]
            rows = (matrix.get(level) or {}).get("rows") or []
            shared_columns = {
                str(field_name or "").strip().lower()
                for field_name in (matrix.get(level) or {}).get(
                    "_shared_columns", []
                )
            }
            if not entities or len(rows) != len(entities):
                continue
            mapped_fields: set[str] = set()
            fields_by_entity: List[set[str]] = []
            for entity in entities:
                fields = {
                    str(attribute.get("field_name") or "").strip().lower()
                    for attribute in entity.get("attributes") or []
                    if isinstance(attribute, Mapping) and attribute.get("field_name")
                }
                mapped_fields.update(fields)
                fields_by_entity.append(fields)
            for index, row in enumerate(rows):
                if not isinstance(row, dict):
                    continue
                for field_name in mapped_fields - fields_by_entity[index]:
                    if field_name in shared_columns:
                        continue
                    if _is_missing_cell(row.get(field_name)):
                        continue
                    row[field_name] = ""
                    marker = f"{level}.{field_name}"
                    cleared[marker] = cleared.get(marker, 0) + 1
        return matrix, cleared

    @staticmethod
    def _clear_values_outside_group_evidence_scope(
        matrix: Dict[str, Dict[str, Any]],
        fields_by_level: Dict[str, List[Dict[str, Any]]],
        entity_plan: Dict[str, Any],
    ) -> tuple[Dict[str, Dict[str, Any]], List[str]]:
        """Limit level-wide values whose literal support is group-specific.

        A confirmed extractor record may still overstate ``value_scope=level``.
        When its literal value occurs in the evidence of only a proper subset
        of design groups, that evidence is stronger than the scope label. The
        projected plan supplies each row's source group, so the value can be
        removed from unsupported sibling branches without domain-specific
        field names or value patterns.

        Values absent from every group evidence remain eligible as true global
        document facts. Numeric-only values are excluded because a short number
        is too likely to match an unrelated count in evidence.
        """
        design_spec = entity_plan.get("design_spec") or {}
        groups = [
            group
            for group in design_spec.get("design_groups") or []
            if isinstance(group, Mapping)
            and str(group.get("group_id") or "").strip()
        ]
        if len(groups) < 2:
            return matrix, []

        group_evidence = {
            str(group.get("group_id") or "").strip(): _norm_cell(
                group.get("evidence")
            )
            for group in groups
        }
        issues: List[str] = []
        seen: set[tuple[str, str, str, tuple[str, ...]]] = set()

        for level, fields in fields_by_level.items():
            level_plan = next(
                (
                    item
                    for item in entity_plan.get("levels") or []
                    if isinstance(item, Mapping)
                    and str(item.get("level") or "").strip().lower() == level
                ),
                None,
            )
            rows = (matrix.get(level) or {}).get("rows") or []
            entities = (level_plan or {}).get("entities") or []
            if not rows or len(rows) != len(entities):
                continue
            level_groups = {
                str(entity.get("source_group") or "").strip()
                for entity in entities
                if isinstance(entity, Mapping)
                and str(entity.get("source_group") or "").strip()
                in group_evidence
            }
            if len(level_groups) < 2:
                continue

            scoped_candidates: List[tuple[str, str, set[str]]] = []
            for field in fields:
                if not isinstance(field, Mapping):
                    continue
                if str(field.get("status") or "").strip().lower() != "confirmed":
                    continue
                if str(field.get("value_scope") or "").strip().lower() != "level":
                    continue
                field_name = str(field.get("field_name") or "").strip().lower()
                value = _norm_cell(field.get("value"))
                if (
                    not field_name
                    or not value
                    or not any(character.isalpha() for character in value)
                ):
                    continue
                supported = {
                    group_id
                    for group_id in level_groups
                    if value in group_evidence.get(group_id, "")
                }
                if supported and supported != level_groups:
                    scoped_candidates.append((field_name, value, supported))

            for field_name, value, supported in scoped_candidates:
                cleared_groups: set[str] = set()
                for row, entity in zip(rows, entities):
                    if not isinstance(row, dict) or not isinstance(entity, Mapping):
                        continue
                    source_group = str(entity.get("source_group") or "").strip()
                    if source_group in supported:
                        continue
                    if _norm_cell(row.get(field_name)) != value:
                        continue
                    row[field_name] = ""
                    cleared_groups.add(source_group)
                if not cleared_groups:
                    continue
                marker = (
                    level,
                    field_name,
                    value,
                    tuple(sorted(cleared_groups)),
                )
                if marker in seen:
                    continue
                seen.add(marker)
                issues.append(
                    "Group-scoped source evidence cleared level-wide value for "
                    f"{level}.{field_name}={value!r} outside "
                    f"{sorted(supported)}."
                )
        return matrix, issues

    @staticmethod
    def _normalize_source_measurement_units(
        matrix: Dict[str, Dict[str, Any]], source_text: str
    ) -> Dict[str, Dict[str, Any]]:
        """Normalize standalone quantity cells with source-declared symbols."""
        for block in matrix.values():
            if not isinstance(block, Mapping):
                continue
            for row in block.get("rows") or []:
                if not isinstance(row, dict):
                    continue
                for field_name, value in list(row.items()):
                    row[field_name] = normalize_source_measurement_value(
                        value, source_text
                    )
        return matrix

    @staticmethod
    def _prune_uninformative_optional_columns(
        matrix: Dict[str, Dict[str, Any]],
        fields_by_level: Dict[str, List[Dict[str, Any]]],
        entity_plan: Dict[str, Any],
        *,
        source_text: str = "",
    ) -> tuple[Dict[str, Dict[str, Any]], Dict[str, List[str]]]:
        """Keep optional schema columns only when their evidence is usable.

        The decision is based on FAIR-DS requirement metadata, extraction
        provenance, and actual cell information, never on a paper, domain, or
        field-name pattern. Structural linkage and plan-mapped design fields are
        always retained. An optional/recommended field that is merely a
        provisional prose guess is not allowed to create a workbook column.
        """
        structural = {
            "investigation identifier",
            "investigation title",
            "investigation description",
            "study identifier",
            "study title",
            "study description",
            "observation unit identifier",
            "observation unit name",
            "observation unit description",
            "sample identifier",
            "sample name",
            "sample description",
            "assay identifier",
            "assay description",
            "firstname",
            "lastname",
            "email address",
            "orcid",
            "organization",
            "department",
        }
        structural.update(
            {
                "investigation identifier",
                "study identifier",
                "observation unit identifier",
                "sample identifier",
            }
        )
        mapped_by_level: Dict[str, set[str]] = {level: set() for level in ISA_LEVELS}
        mapped_values_by_row: Dict[str, List[Dict[str, str]]] = {
            level: [] for level in ISA_LEVELS
        }
        plan_values_by_level: Dict[str, set[str]] = {
            level: set() for level in ISA_LEVELS
        }
        group_scopes: Dict[tuple[str, str], set[str]] = {}
        for group in (entity_plan.get("design_claims") or {}).get("design_groups") or []:
            if not isinstance(group, Mapping):
                continue
            group_id = str(group.get("group_id") or "").strip()
            for dimension in group.get("dimensions") or []:
                if not isinstance(dimension, Mapping):
                    continue
                dimension_name = str(dimension.get("name") or "").strip().lower()
                group_scopes[(group_id, dimension_name)] = {
                    str(level or "").strip().lower()
                    for level in dimension.get("applies_to") or []
                }
        for level_plan in entity_plan.get("levels") or []:
            if not isinstance(level_plan, dict):
                continue
            level = str(level_plan.get("level") or "")
            if level not in mapped_by_level:
                continue
            for entity in level_plan.get("entities") or []:
                if not isinstance(entity, dict):
                    continue
                entity_mapped_values: Dict[str, str] = {}
                for attribute in entity.get("attributes") or []:
                    if not isinstance(attribute, dict):
                        continue
                    field_name = str(attribute.get("field_name") or "").strip().lower()
                    if field_name:
                        mapped_by_level[level].add(field_name)
                    value = _norm_cell(attribute.get("value"))
                    if field_name and value:
                        entity_mapped_values[field_name] = value
                    origin = str(attribute.get("origin") or "").strip().lower()
                    dimension_name = str(
                        attribute.get("dimension_name") or ""
                    ).strip().lower()
                    source_group = str(entity.get("source_group") or "").strip()
                    scope = group_scopes.get((source_group, dimension_name), set())
                    if value and origin == "explicit" and (not scope or level in scope):
                        plan_values_by_level[level].add(value)
                mapped_values_by_row[level].append(entity_mapped_values)

        normalized_source = _norm_cell(source_text)

        def is_explicit_plan_cell(
            level: str,
            row_index: int,
            column: str,
            value: Any,
        ) -> bool:
            """Distinguish an explicit plan value from a missing-value token.

            Source tables may legitimately use categorical strings such as
            ``none`` or ``unknown``. Those strings remain useful evidence when
            the entity plan explicitly assigned the exact value to the exact
            field and row. Treating them as generic placeholders here would
            erase an authoritative source-table value after projection and make
            the compiled matrix contradict its own entity plan.
            """

            planned_rows = mapped_values_by_row.get(level, [])
            planned_index = row_index
            if planned_index >= len(planned_rows) and len(planned_rows) == 1:
                # Investigation contacts repeat the one investigation entity.
                planned_index = 0
            if planned_index >= len(planned_rows):
                return False
            planned_value = planned_rows[planned_index].get(column)
            return bool(planned_value) and _norm_cell(value) == planned_value

        pruned: Dict[str, List[str]] = {}
        for level, block in matrix.items():
            if not isinstance(block, dict):
                continue
            requirement = {
                str(field.get("field_name") or "").strip().lower(): str(
                    field.get("requirement") or ""
                ).strip().upper()
                for field in fields_by_level.get(level) or []
                if str(field.get("field_name") or "").strip()
            }
            supported_optional: set[str] = set()
            confirmed_values: Dict[str, set[str]] = {}
            for field in fields_by_level.get(level) or []:
                field_name = str(field.get("field_name") or "").strip().lower()
                if not field_name:
                    continue
                if (
                    str(field.get("status") or "").strip().lower() == "confirmed"
                    and bool(str(field.get("evidence") or "").strip())
                ):
                    supported_optional.add(field_name)
                    value = _norm_cell(field.get("value"))
                    if value:
                        confirmed_values.setdefault(field_name, set()).add(value)
            rows = [row for row in block.get("rows") or [] if isinstance(row, dict)]
            keep: List[str] = []
            removed: List[str] = []
            for raw_column in block.get("columns") or []:
                column = str(raw_column).strip().lower()
                informative = any(not _is_missing_cell(row.get(column)) for row in rows)
                can_prune = requirement.get(column) in {"OPTIONAL", "RECOMMENDED"}
                normalized_nonempty = {
                    _norm_cell(row.get(column))
                    for row in rows
                    if not _is_missing_cell(row.get(column))
                }
                source_supported = bool(normalized_nonempty) and all(
                    value in normalized_source
                    or value in plan_values_by_level.get(level, set())
                    for value in normalized_nonempty
                )
                repeated_level_narrative = (
                    level in MULTI_ROW_ISA_LEVELS
                    and len(rows) > 1
                    and len(normalized_nonempty) == 1
                    and all(not _is_missing_cell(row.get(column)) for row in rows)
                )
                extracted_values = confirmed_values.get(column, set())
                field_value_supported = column in supported_optional and (
                    not extracted_values
                    or normalized_nonempty.issubset(extracted_values)
                )
                redundant_with_plan_mapping = bool(normalized_nonempty) and all(
                    any(
                        candidate_value == mapped_value
                        for mapped_field, mapped_value in (
                            mapped_values_by_row.get(level, [{}])[row_index]
                            if row_index
                            < len(mapped_values_by_row.get(level, []))
                            else {}
                        ).items()
                        if mapped_field != column
                    )
                    for row_index, row in enumerate(rows)
                    if (candidate_value := _norm_cell(row.get(column)))
                )
                if (
                    can_prune
                    and column not in structural
                    and column not in mapped_by_level.get(level, set())
                    and (
                        not informative
                        or (
                            not field_value_supported
                            and not source_supported
                        )
                        or (
                            repeated_level_narrative
                            and not source_supported
                        )
                        or redundant_with_plan_mapping
                    )
                ):
                    removed.append(column)
                else:
                    keep.append(column)
            block["columns"] = keep
            block["rows"] = [
                {
                    column: ""
                    if _is_missing_cell(row.get(column))
                    and not is_explicit_plan_cell(
                        level, row_index, column, row.get(column)
                    )
                    else row.get(column, "")
                    for column in keep
                }
                for row_index, row in enumerate(rows)
            ]
            if removed:
                pruned[level] = removed
        return matrix, pruned

    @staticmethod
    def _sanitize_typed_matrix_values(
        matrix: Dict[str, Dict[str, Any]],
        fields_by_level: Dict[str, List[Dict[str, Any]]],
    ) -> tuple[Dict[str, Dict[str, Any]], List[str]]:
        """Clear schema-incompatible numeric prose while preserving review trace.

        This uses FAIR-DS ``data_type`` declarations rather than field-name or
        document-specific patterns. Missing-value sentinels remain intact;
        valid lexical numbers remain strings so Excel presentation is stable.
        """
        numeric_types = {
            "number",
            "float",
            "double",
            "decimal",
            "integer",
            "int",
        }
        integer_types = {"integer", "int"}
        number_pattern = re.compile(
            r"^[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?$"
        )
        integer_pattern = re.compile(r"^[+-]?\d+$")
        issues: List[str] = []

        for level, block in matrix.items():
            if not isinstance(block, dict):
                continue
            type_by_field = {
                str(field.get("field_name") or "").strip().lower(): str(
                    field.get("data_type") or ""
                ).strip().lower()
                for field in (fields_by_level.get(level) or [])
                if str(field.get("field_name") or "").strip()
            }
            for row in block.get("rows") or []:
                if not isinstance(row, dict):
                    continue
                for field_name, value in list(row.items()):
                    data_type = type_by_field.get(
                        str(field_name).strip().lower(), ""
                    )
                    if data_type not in numeric_types or value is None:
                        continue
                    text = str(value).strip()
                    if text.lower() in _PLACEHOLDER_CELL_VALUES:
                        continue
                    pattern = (
                        integer_pattern
                        if data_type in integer_types
                        else number_pattern
                    )
                    if pattern.fullmatch(text):
                        continue
                    row[field_name] = ""
                    issues.append(
                        f"Cleared non-{data_type} value from typed field "
                        f"'{field_name}' on {level}; source value requires human review."
                    )

        return matrix, list(dict.fromkeys(issues))

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
            "Column keys MUST be copied verbatim from the field_name values in "
            "/workspace/metadata_fields_by_isa.json; never rename, reformat, "
            "or wrap metadata terms (no 'characteristic[...]'/'comment[...]'/'person ...' conversions). "
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
        evidence_summary: Optional[Dict[str, Any]] = None,
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

        # §4.1 — Inject EvidenceStore field candidates as a seed file so the
        # inner agent (and its tools) can cross-reference section-level evidence
        # when resolving row values.
        if evidence_summary:
            evidence_file = self._maybe_create_file_data(
                json.dumps(evidence_summary, indent=2, ensure_ascii=False)
            )
            if evidence_file is not None:
                seed_files["/workspace/field_evidence_summary.json"] = evidence_file
                self.logger.debug(
                    "Injected field_evidence_summary with %d fields into IVM seed files",
                    len(evidence_summary.get("fields", {})),
                )

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

    @staticmethod
    def _build_evidence_store_summary(
        evidence_store_meta: Dict[str, Any],
        max_candidates_per_field: int = _MAX_EVIDENCE_CANDIDATES_PER_FIELD,
    ) -> Optional[Dict[str, Any]]:
        """Load evidence_store JSONL and return a compact per-field candidate summary.

        The EvidenceStore JSONL is produced by SectionMapReduceNode and contains
        FieldCandidate records from section-level extraction.  ISAValueMapper
        previously had no access to this layer — this summary bridges that gap
        (Plan §4.1).

        Returns ``None`` if the JSONL path is missing or unreadable.
        """
        jsonl_path_str = (evidence_store_meta or {}).get("jsonl_path", "")
        if not jsonl_path_str:
            return None
        jsonl_path = Path(jsonl_path_str)
        if not jsonl_path.is_file():
            return None

        fields: Dict[str, List[Dict[str, Any]]] = {}
        try:
            with jsonl_path.open("r", encoding="utf-8") as fh:
                for line in fh:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        record = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    field_name = str(record.get("field_name") or "").strip().lower()
                    if not field_name:
                        continue
                    value = str(record.get("value") or "").strip()
                    if not value:
                        continue
                    entry = {
                        "value": value,
                        "confidence": float(record.get("confidence") or 0.0),
                        "retrieval_method": str(record.get("retrieval_method") or "section_map_reduce"),
                        "source_id": str(record.get("source_id") or ""),
                        "section": str(record.get("section") or ""),
                    }
                    fields.setdefault(field_name, []).append(entry)
        except OSError:
            return None

        # Keep top-N by confidence per field.
        summarised = {
            fname: sorted(candidates, key=lambda c: -c["confidence"])[:max_candidates_per_field]
            for fname, candidates in fields.items()
        }
        return {
            "description": (
                "Section-level FieldCandidate evidence from hybrid retrieval. "
                "Use these as authoritative row values when JSONGenerator output is missing or uncertain."
            ),
            "field_count": len(summarised),
            "fields": summarised,
        }

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
        for level in MULTI_ROW_ISA_LEVELS:
            rows = (matrix.get(level) or {}).get("rows") or []
            if len(rows) < 2:
                continue
            populated = [
                sum(1 for v in row.values() if v and str(v).strip())
                for row in rows
                if isinstance(row, dict)
            ]
            if not populated:
                continue
            avg_populated = sum(populated) / len(populated)
            column_count = len((matrix.get(level) or {}).get("columns") or [])
            sparse_threshold = max(2, int(column_count * 0.25)) if column_count else 2
            sparse_rows = sum(1 for count in populated if count <= sparse_threshold)
            if sparse_rows >= max(2, len(rows) // 2) and avg_populated <= sparse_threshold + 1:
                issues.append(
                    f"Possible entity over-fragmentation on {level}: "
                    f"{len(rows)} rows with avg {avg_populated:.1f} populated fields "
                    f"({sparse_rows} sparse rows)."
                )
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
            "2. Rows = one per distinct entity declared in the authoritative entity plan. "
            "Never use an experimental group summary as a substitute for its planned entities.\n"
            "3. Every row MUST have exactly the same column keys. "
            "   Use empty string '' for missing values — NEVER omit a column.\n"
            "4. Do NOT invent synthetic identifiers (no auto-generated IDs). "
            "   Use values from the document or leave empty.\n"
            "5. Shared fields (same value across all entities) go in every row; "
            "   entity-specific fields use the value for that entity.\n"
            "   Do not broadcast one entity's narrative, timepoint, treatment, or method to siblings.\n"
            "6. Column keys MUST be copied verbatim from the input field_name "
            "   values (exact spelling and casing). NEVER rename, translate, or "
            "   reformat a term — e.g. do not turn 'organism' into "
            "   'characteristic[organism]', 'orcid' into 'comment[orcid]', or "
            "   'email address' into 'person email'.\n"
            "7. NEVER add columns that are not in the input field list, and "
            "   never drop an input field: every field_name appears exactly "
            "   once as a column, using '' when there is no value.\n"
            "8. Treat confidence 0, missing-value prose, and unsupported/inferred values as ''. "
            "Never upgrade generic evidence into a brand, instrument, date, accession, or protocol detail.\n"
            "9. Entity detection is already complete in the authoritative plan. "
            "Do not add, merge, or reinterpret its entities.\n"
            "10. FAIR-DS field definitions may declare regex/syntax constraints. "
            "Every non-empty cell MUST full-match that contract. Convert an explicitly "
            "supported source phrase to the canonical listed value; otherwise leave it blank.\n\n"
            "**Output format (JSON):**\n"
            "Wrap in ```json ... ```. Return a dict with one key per ISA level:\n"
            '{"investigation": {"columns": [...], "rows": [{...}]}, ...}'
        )

        # ── Build user prompt ───────────────────────────────────────
        user_parts = []

        entity_plan_context = render_entity_plan_for_prompt(
            state.get("entity_plan") or {}
        )
        if entity_plan_context:
            user_parts.append(entity_plan_context)

        # Extracted fields summary
        field_summary = {}
        for lvl in ISA_LEVELS:
            fds = fields_by_level.get(lvl, [])
            field_summary[lvl] = {
                "count": len(fds),
                "fields": [
                    {
                        "field_name": f.get("field_name", ""),
                        # Preserve narrative fields instead of silently cutting
                        # descriptions mid-sentence. The cap is only a context
                        # guardrail; ordinary FAIR-DS values pass through whole.
                        "value": str(f.get("value", ""))[:1200] if f.get("value") else "",
                        "confidence": f.get("confidence", 0),
                        "required": f.get("required", False),
                        "status": f.get("status", ""),
                        "status_reason": f.get("status_reason", ""),
                        "origin": f.get("origin", ""),
                        "evidence": str(f.get("evidence", ""))[:240],
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
                    "definition": meta.get("definition", "") or (
                        ki.get("definition", "") if isinstance(ki, dict) else ""
                    ),
                    "syntax": meta.get("syntax", ""),
                    "regex": meta.get("regex", ""),
                    "example": meta.get("example", ""),
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

    # ── Field-name passthrough enforcement ──────────────────────────

    @staticmethod
    def _value_match_field(
        vals: set,
        field_order: List[str],
        values_by_name: Dict[str, set],
        exclude: set,
    ) -> Optional[str]:
        """Return the field key whose upstream values cover *vals*.

        Requires every non-placeholder cell value to appear in the field's
        upstream values. Ties (e.g. ``scientific name`` vs ``host scientific
        name`` carrying the same organism) resolve to the most general term:
        fewest name tokens, then shortest name.
        """
        candidates = [
            k for k in field_order
            if k not in exclude and values_by_name.get(k) and vals <= values_by_name[k]
        ]
        if not candidates:
            return None
        candidates.sort(key=lambda k: (len(k.split()), len(k), k))
        return candidates[0]

    def _enforce_field_name_passthrough(
        self,
        matrix: Dict[str, Dict[str, Any]],
        fields_by_level: Dict[str, List[Dict[str, Any]]],
        *,
        drop_untraceable: bool,
    ) -> Dict[str, Dict[str, Any]]:
        """Force an LLM-produced matrix back onto the upstream field names.

        Terms selected upstream (``field_name`` in ``metadata_fields``) are
        immutable: ISAValueMapper fills values into the grid but must never
        rename, reformat, or invent terms. Each output column is mapped back
        to its originating field — by exact name, by unwrapping an ISA-Tab
        style wrapper (``characteristic[...]``, ``comment[...]``, …), or by a
        unique value match. Columns that cannot be traced to an upstream
        field are dropped when *drop_untraceable* is set (plain LLM path,
        where any extra column is invented boilerplate); the deep-agent path
        keeps them because they may come from source-workspace tables.
        Upstream fields missing from the matrix are re-added so the term set
        survives intact.
        """
        for lvl in ISA_LEVELS:
            sheet = matrix.get(lvl)
            if not isinstance(sheet, dict):
                continue
            fields = [
                f for f in (fields_by_level.get(lvl) or []) if isinstance(f, dict)
            ]
            allowed: Dict[str, str] = {}
            field_order: List[str] = []
            values_by_name: Dict[str, set] = {}
            for f in fields:
                orig = str(f.get("field_name") or "").strip()
                if not orig:
                    continue
                key = orig.lower()
                if key not in allowed:
                    allowed[key] = orig
                    field_order.append(key)
                val = str(f.get("value") or "").strip()
                if val and val.lower() not in _PLACEHOLDER_CELL_VALUES:
                    values_by_name.setdefault(key, set()).add(val.lower())
            if not allowed:
                # No upstream fields for this level — nothing to enforce.
                continue

            columns: List[str] = []
            for raw in sheet.get("columns") or []:
                name = str(raw).strip()
                if name and name not in columns:
                    columns.append(name)
            rows = [r for r in (sheet.get("rows") or []) if isinstance(r, dict)]
            for row in rows:
                for raw in row.keys():
                    name = str(raw).strip()
                    if name and name not in columns:
                        columns.append(name)

            cell_values: Dict[str, List[str]] = {c: [] for c in columns}
            for row in rows:
                for c in columns:
                    if row.get(c) is not None:
                        cell_values[c].append(str(row.get(c)))

            rename_map: Dict[str, Optional[str]] = {}
            claimed: set = set()
            for c in columns:
                key = c.lower()
                if key in allowed:
                    rename_map[c] = allowed[key]
                    claimed.add(key)
                    continue
                wrapper = _ISA_TAB_WRAPPER_RE.match(c)
                inner = wrapper.group(1).strip().lower() if wrapper else ""
                if inner and inner in allowed and inner not in claimed:
                    rename_map[c] = allowed[inner]
                    claimed.add(inner)
                    self.logger.warning(
                        "ISAValueMapper renamed '%s' to '%s'; restored the upstream term",
                        allowed[inner], c,
                    )
                    continue
                rename_map[c] = None
            for c in columns:
                if rename_map[c] is not None:
                    continue
                vals = {
                    v.strip().lower()
                    for v in cell_values[c]
                    if v and v.strip().lower() not in _PLACEHOLDER_CELL_VALUES
                }
                if not vals:
                    continue
                key = self._value_match_field(vals, field_order, values_by_name, claimed)
                if key is not None:
                    rename_map[c] = allowed[key]
                    claimed.add(key)
                    self.logger.warning(
                        "ISAValueMapper renamed '%s' to '%s'; restored the upstream term",
                        allowed[key], c,
                    )

            # Untraceable columns: when the values identify an upstream field
            # (claimed or not), merge cells into that field's column instead
            # of losing them; otherwise drop or keep.
            for c in columns:
                if rename_map[c] is not None:
                    continue
                vals = {
                    v.strip().lower()
                    for v in cell_values[c]
                    if v and v.strip().lower() not in _PLACEHOLDER_CELL_VALUES
                }
                target = self._value_match_field(vals, field_order, values_by_name, set()) if vals else None
                if target is not None:
                    rename_map[c] = allowed[target]
                    self.logger.warning(
                        "ISAValueMapper column '%s' in %s duplicates upstream "
                        "term '%s'; merged values into it",
                        c, lvl, allowed[target],
                    )
                elif c.lower() in _SYNTHETIC_ID_FIELDS:
                    # Core ISA linkage identifiers are structural workbook
                    # keys maintained by the pipeline (see
                    # _ensure_core_linkage_fields); keep them and normalize
                    # the spelling so downstream linkage logic finds them.
                    canon = c.lower()
                    rename_map[c] = canon
                    if canon != c:
                        self.logger.warning(
                            "ISAValueMapper renamed linkage identifier '%s' to '%s'; normalized",
                            canon, c,
                        )
                elif drop_untraceable:
                    if vals:
                        self.logger.warning(
                            "Dropping column '%s' in %s: not an upstream "
                            "metadata field", c, lvl,
                        )
                    else:
                        self.logger.debug(
                            "Dropping invented empty column '%s' in %s", c, lvl
                        )
                else:
                    rename_map[c] = c
                    self.logger.info(
                        "Keeping non-upstream column '%s' in %s "
                        "(workspace-derived candidate)", c, lvl,
                    )

            new_rows: List[Dict[str, Any]] = []
            for row in rows:
                merged: Dict[str, Any] = {}
                for raw, value in row.items():
                    canon = rename_map.get(str(raw).strip())
                    if canon is None:
                        continue
                    if not str(merged.get(canon) or "").strip() and str(value).strip():
                        merged[canon] = value
                    else:
                        merged.setdefault(canon, value)
                new_rows.append(merged)

            for key in field_order:
                if key in claimed:
                    continue
                canon = allowed[key]
                fill_values: List[str] = []
                for f in fields:
                    if str(f.get("field_name") or "").strip().lower() != key:
                        continue
                    candidate = str(f.get("value") or "").strip()
                    if candidate and candidate not in fill_values:
                        fill_values.append(candidate)
                if len(new_rows) <= 1 or len(fill_values) == 1:
                    # Single row, or the same value for every entity.
                    fill = fill_values[0] if fill_values else ""
                else:
                    # Multiple distinct values and no reliable row alignment.
                    fill = ""
                for row in new_rows:
                    row.setdefault(canon, fill)
                claimed.add(key)
                self.logger.info(
                    "Re-added upstream term '%s' missing from the %s matrix",
                    canon, lvl,
                )

            extras = list(dict.fromkeys(
                rename_map[c]
                for c in columns
                if rename_map.get(c) is not None
                and str(rename_map[c]).lower() not in allowed
            ))
            sheet["rows"] = new_rows
            sheet["columns"] = [allowed[k] for k in field_order] + extras
        return matrix

    # ── Heuristic fallback ────────────────────────────────────────────

    def _build_matrix_heuristic(
        self,
        fields_by_level: Dict[str, List[Dict[str, Any]]],
        evidence_summary: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Dict[str, Any]]:
        """Build a matrix from flat fields WITHOUT LLM (deterministic fallback).

        Fields emitted by JSONGenerator already carry ``entity_id`` when the
        model identifies separate samples, observation units, or assays. Use
        that as the authoritative row grouping before falling back to a single
        row per sheet.

        If ``evidence_summary`` is provided (§4.1 EvidenceStore integration),
        empty cells are back-filled with the highest-confidence candidate from
        section-level extraction, improving structural row recall.
        """
        evidence_fields: Dict[str, str] = {}
        if evidence_summary:
            for fname, candidates in (evidence_summary.get("fields") or {}).items():
                if candidates:
                    # Pick the top-confidence candidate value.
                    evidence_fields[fname] = candidates[0]["value"]

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
                cell_value = str(val) if val is not None else ""
                # §4.1: back-fill empty cells from evidence store candidates.
                if not cell_value and name in evidence_fields:
                    cell_value = evidence_fields[name]
                rows_by_entity[entity_id][name] = cell_value

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
        """Ensure every row in a sheet has the same column keys without case duplicate artifacts."""
        for _lvl, sheet in matrix.items():
            rows = sheet.get("rows", [])
            if not rows:
                continue

            col_canonical_map: Dict[str, str] = {}
            for row in rows:
                if isinstance(row, dict):
                    for k in row.keys():
                        k_clean = str(k).strip()
                        k_lower = k_clean.lower()
                        if k_lower not in col_canonical_map or (k_clean != k_lower and col_canonical_map[k_lower] == k_lower):
                            col_canonical_map[k_lower] = k_clean

            for c in sheet.get("columns", []):
                c_clean = str(c).strip()
                c_lower = c_clean.lower()
                if c_lower not in col_canonical_map:
                    col_canonical_map[c_lower] = c_clean

            norm_rows: List[Dict[str, Any]] = []
            for row in rows:
                if not isinstance(row, dict):
                    norm_rows.append(row)
                    continue
                norm_row: Dict[str, Any] = {}
                for k, v in row.items():
                    k_lower = str(k).strip().lower()
                    canon_key = col_canonical_map.get(k_lower, str(k).strip())
                    existing_v = norm_row.get(canon_key)
                    if existing_v is None or (str(existing_v).strip() == "" and str(v).strip() != ""):
                        norm_row[canon_key] = v
                norm_rows.append(norm_row)

            sheet["rows"] = norm_rows
            existing_order = [
                str(column).strip()
                for column in sheet.get("columns", [])
                if str(column).strip()
            ]
            canonical_by_norm = {
                str(column).strip().lower(): column
                for column in col_canonical_map.values()
            }
            ordered_norms: List[str] = []
            for column in _FAIRDS_CORE_COLUMN_ORDER.get(_lvl, []):
                normalized = column.lower()
                if normalized in canonical_by_norm and normalized not in ordered_norms:
                    ordered_norms.append(normalized)
            for column in existing_order:
                normalized = column.lower()
                if normalized in canonical_by_norm and normalized not in ordered_norms:
                    ordered_norms.append(normalized)
            for normalized in canonical_by_norm:
                if normalized not in ordered_norms:
                    ordered_norms.append(normalized)
            sheet["columns"] = [canonical_by_norm[key] for key in ordered_norms]

            for row in norm_rows:
                if isinstance(row, dict):
                    for c_lower, canon_key in col_canonical_map.items():
                        if canon_key not in row and c_lower not in row:
                            row[canon_key] = ""

        return matrix

    def _ensure_core_linkage_fields(
        self,
        matrix: Dict[str, Dict[str, Any]],
        state: FAIRifierState,
    ) -> Dict[str, Dict[str, Any]]:
        """Fill required ISA workbook linkage identifiers after extraction.

        The LLM prompt correctly discourages inventing document facts, but ISA
        identifiers are workbook keys. Leaving them blank makes otherwise useful
        extractions fail schema validation, so derive stable IDs from document
        context only when the corresponding rows already exist.
        """
        fallback = self._derive_document_identifier(state)

        inv_id = self._normalize_core_identifier(
            self._first_value(matrix, "investigation", "investigation identifier")
        )
        study_id = self._normalize_core_identifier(
            self._first_value(matrix, "study", "study identifier")
        )

        if not inv_id and study_id:
            inv_id = self._prefixed_identifier("INV", study_id)
        elif not inv_id:
            inv_id = self._prefixed_identifier("INV", fallback)

        if not study_id:
            study_id = self._prefixed_identifier("STUDY", fallback or inv_id)

        self._fill_missing_column(matrix, "investigation", "investigation identifier", inv_id)
        self._fill_missing_column(matrix, "study", "study identifier", study_id)
        self._fill_missing_column(matrix, "study", "investigation identifier", inv_id)
        self._fill_missing_column(matrix, "observationunit", "study identifier", study_id)
        self._normalize_existing_column(matrix, "investigation", "investigation identifier")
        self._normalize_existing_column(matrix, "study", "study identifier")
        self._normalize_existing_column(matrix, "study", "investigation identifier")
        self._normalize_existing_column(matrix, "observationunit", "study identifier")
        return self._normalize_row_columns(matrix)

    def _fill_missing_column(
        self,
        matrix: Dict[str, Dict[str, Any]],
        level: str,
        column: str,
        value: str,
    ) -> None:
        if not value:
            return
        sheet = matrix.get(level) or {}
        rows = sheet.get("rows") or []
        if not rows:
            return
        columns = sheet.setdefault("columns", [])
        if column not in columns:
            columns.append(column)
        for row in rows:
            if isinstance(row, dict) and not str(row.get(column) or "").strip():
                row[column] = value

    def _normalize_existing_column(
        self,
        matrix: Dict[str, Dict[str, Any]],
        level: str,
        column: str,
    ) -> None:
        sheet = matrix.get(level) or {}
        rows = sheet.get("rows") or []
        for row in rows:
            if not isinstance(row, dict):
                continue
            current = str(row.get(column) or "").strip()
            normalized = self._normalize_core_identifier(current)
            if normalized and normalized != current:
                row[column] = normalized

    def _derive_document_identifier(self, state: FAIRifierState) -> str:
        doc_info = state.get("document_info") or {}
        if not isinstance(doc_info, dict):
            doc_info = {}
        source_workspace = state.get("source_workspace") or {}
        candidates = [
            doc_info.get("doi"),
            doc_info.get("document_id"),
            state.get("document_id"),
            state.get("project_id"),
            doc_info.get("title"),
            state.get("document_path"),
            source_workspace.get("root_dir") if isinstance(source_workspace, dict) else "",
        ]
        for candidate in candidates:
            text = str(candidate or "").strip()
            if text:
                return self._slug_identifier(text)
        return "document"

    def _prefixed_identifier(self, prefix: str, raw: str) -> str:
        slug = self._slug_identifier(raw or "document")
        prefix_norm = self._slug_identifier(prefix).upper()
        if slug.upper().startswith(f"{prefix_norm}_"):
            return slug
        return f"{prefix_norm}_{slug}"

    def _normalize_core_identifier(self, value: str) -> str:
        text = str(value or "").strip()
        if not text:
            return ""
        if _FAIRDS_IDENTIFIER_RE.fullmatch(text):
            return text
        return self._slug_identifier(text)

    def _slug_identifier(self, value: str) -> str:
        text = str(value or "").strip()
        text = re.sub(r"^(?:https?://)?(?:dx\.)?doi\.org/", "", text, flags=re.IGNORECASE)
        if "/" in text and not re.match(r"^10\.\d{4,9}/", text, flags=re.IGNORECASE):
            text = Path(text).stem or text
        slug = re.sub(r"[^A-Za-z0-9]+", "_", text).strip("_")
        return slug or "document"

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
