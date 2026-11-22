"""Deterministic workflow contract for the orchestrated pipeline.

The orchestrator order and node set are fixed. This module holds the parts of
the contract that code, not a model, decides:

* which optional node may be skipped, and under which enumerated condition;
* whether a node's output satisfies its completion contract;
* a per-run node trace (entered, skipped, attempts, gate result, inner-loop
  budget use); and
* the fill-task list: one cell per planned entity and selected field, compiled
  from the entity plan after its hard gate has passed, and marked filled or
  blank from the final ISA matrix.

Nothing here calls a model or changes the output metadata.
"""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any, Dict, Iterable, List, Mapping, Optional

from .isa_order import ISA_LEVEL_ORDER, MULTI_ROW_ISA_LEVELS

# Only these nodes may be skipped, and only under these enumerated conditions.
# Every other node (parsing, planning, retrieval, entity structure, generation,
# value mapping, matrix compilation, gates) always runs.
SKIPPABLE_AGENTS: Dict[str, frozenset] = {
    "BioMetadataAgent": frozenset({"no_bio_files"}),
}

FILL_TASKS_SCHEMA_VERSION = 1
MAX_STORED_FILL_CELLS = 5000

_EMPTY_VALUES = {"", "not specified", "none", "null", "n/a"}


def _norm(value: Any) -> str:
    return " ".join(str(value or "").strip().lower().replace("_", " ").split())


def _has_value(value: Any) -> bool:
    if value is None:
        return False
    if isinstance(value, (list, tuple, set, dict)):
        return bool(value)
    return _norm(value) not in _EMPTY_VALUES


# ---------------------------------------------------------------------------
# Skip conditions
# ---------------------------------------------------------------------------


def skip_reason_for_agent(agent_name: str, state: Mapping[str, Any]) -> Optional[str]:
    """Return the enumerated skip condition that holds for ``agent_name``.

    The condition is computed from run state, never taken from model output, so
    a Planner-written ``skip_if`` cannot skip a node on its own.
    """
    allowed = SKIPPABLE_AGENTS.get(agent_name)
    if not allowed:
        return None
    if "no_bio_files" in allowed and not (state.get("bio_file_paths") or []):
        return "no_bio_files"
    return None


# ---------------------------------------------------------------------------
# Completion contracts
# ---------------------------------------------------------------------------


def evaluate_completion_contract(
    agent_name: str, state: Mapping[str, Any]
) -> Dict[str, Any]:
    """Check one node's output against its deterministic completion contract."""
    issues: List[str] = []
    metrics: Dict[str, Any] = {}

    if agent_name in {"DocumentParser", "BioMetadataAgent"}:
        if not (state.get("document_info") or {}):
            issues.append("document_info is empty")

    elif agent_name == "KnowledgeRetriever":
        knowledge = state.get("retrieved_knowledge") or []
        selected = [
            str(item).strip()
            for item in state.get("selected_packages") or []
            if str(item).strip()
        ]
        available = (state.get("api_capabilities") or {}).get("available_packages") or []
        metrics["knowledge_terms"] = len(knowledge)
        metrics["selected_packages"] = len(selected)
        if not knowledge:
            issues.append("no FAIR-DS terms retrieved")
        if not selected:
            issues.append("no FAIR-DS package selected")
        if available:
            known = {str(item).strip().lower() for item in available}
            unknown = [item for item in selected if item.lower() not in known]
            metrics["package_check"] = "verified"
            if unknown:
                issues.append(f"selected packages not in FAIR-DS: {unknown[:5]}")
        else:
            metrics["package_check"] = "unverified"

    elif agent_name == "EntityStructurePlanner":
        validation = state.get("entity_plan_validation") or {}
        if validation.get("passed") is not True:
            issues.append("entity plan validation did not pass")

    elif agent_name == "JSONGenerator":
        fields = state.get("metadata_fields") or []
        populated = [
            item for item in fields if isinstance(item, Mapping) and _has_value(item.get("value"))
        ]
        # A confirmed value needs evidence. Values the grounding check already
        # downgraded to provisional are tolerated; they are flagged, not hidden.
        ungrounded_confirmed = [
            item
            for item in populated
            if str(item.get("status") or "").lower() == "confirmed"
            and not str(item.get("evidence") or "").strip()
        ]
        metrics["fields"] = len(fields)
        metrics["populated_fields"] = len(populated)
        metrics["confirmed_without_evidence"] = len(ungrounded_confirmed)
        if not fields:
            issues.append("no metadata fields generated")
        if ungrounded_confirmed:
            issues.append(
                f"{len(ungrounded_confirmed)} confirmed field(s) carry no evidence"
            )

    elif agent_name == "ISAValueMapper":
        if (state.get("artifacts") or {}).get("isa_values_json") is None:
            issues.append("isa_values_json not produced")
        matrix_validation = state.get("entity_matrix_validation")
        if isinstance(matrix_validation, Mapping) and matrix_validation.get("passed") is not True:
            issues.append("entity matrix validation did not pass")

    return {
        "agent": agent_name,
        "passed": not issues,
        "issues": issues,
        "metrics": metrics,
    }


# ---------------------------------------------------------------------------
# Node trace
# ---------------------------------------------------------------------------


def record_node_trace(
    state: Dict[str, Any], node: str, *, status: str, **details: Any
) -> Dict[str, Any]:
    """Append one node record to ``state['workflow_trace']`` and sync the artifact."""
    entry: Dict[str, Any] = {
        "node": node,
        "status": status,
        "timestamp": datetime.now().isoformat(),
    }
    entry.update({key: value for key, value in details.items() if value is not None})
    trace = state.setdefault("workflow_trace", [])
    trace.append(entry)
    state.setdefault("artifacts", {})["workflow_trace"] = json.dumps(
        trace, indent=2, ensure_ascii=False, default=str
    )
    return entry


def react_budget_snapshot(
    state: Mapping[str, Any], agent_name: str
) -> Optional[Dict[str, Any]]:
    """Return inner-loop usage for ``agent_name`` when it ran a ReAct loop."""
    scratch = (state.get("react_scratchpad") or {}).get(agent_name)
    if not isinstance(scratch, Mapping):
        return None
    budget = scratch.get("budget") if isinstance(scratch.get("budget"), Mapping) else {}
    iterations = int(scratch.get("iterations") or 0)
    max_iterations = int(budget.get("max_iterations") or 0)
    return {
        "iterations": iterations,
        "max_iterations": max_iterations,
        "distinct_tools_called": len(scratch.get("tools_called") or []),
        "max_tool_calls": int(budget.get("max_tool_calls") or 0),
        "iteration_budget_reached": bool(max_iterations and iterations >= max_iterations),
    }


# ---------------------------------------------------------------------------
# Fill tasks
# ---------------------------------------------------------------------------


def _field_level(item: Mapping[str, Any]) -> str:
    from ..services.fairds_api_parser import FAIRDSAPIParser

    metadata = item.get("metadata") if isinstance(item.get("metadata"), Mapping) else {}
    return FAIRDSAPIParser.normalize_isa_sheet(
        metadata.get("isa_sheet") or metadata.get("sheet")
    )


def _entity_aliases(entity: Mapping[str, Any]) -> List[str]:
    aliases: List[str] = []
    for key in ("row_id", "label", "external_identifier"):
        alias = _norm(entity.get(key))
        if alias and alias not in aliases:
            aliases.append(alias)
    return aliases


def compile_fill_tasks(
    entity_plan: Mapping[str, Any],
    knowledge_items: Iterable[Mapping[str, Any]],
) -> Dict[str, Any]:
    """Compile the cell list: every planned entity x every selected field of its level.

    Call only after the entity plan passed its hard gate. The model never
    chooses which cells exist; it fills them.
    """
    fields_by_level: Dict[str, List[Dict[str, Any]]] = {level: [] for level in ISA_LEVEL_ORDER}
    seen: set = set()
    for item in knowledge_items or []:
        if not isinstance(item, Mapping):
            continue
        name = str(item.get("term") or "").strip()
        if not name:
            continue
        level = _field_level(item)
        key = (level, _norm(name))
        if level not in fields_by_level or key in seen:
            continue
        seen.add(key)
        metadata = item.get("metadata") if isinstance(item.get("metadata"), Mapping) else {}
        requirement = str(metadata.get("requirement") or "").strip().upper()
        fields_by_level[level].append(
            {
                "field_name": name,
                "required": requirement == "MANDATORY" or bool(metadata.get("required")),
                "package": str(metadata.get("package") or ""),
            }
        )

    entities: Dict[str, Dict[str, Any]] = {}
    cells: List[Dict[str, Any]] = []
    per_level: Dict[str, Dict[str, int]] = {}
    total_cells = 0
    for level_plan in entity_plan.get("levels") or []:
        if not isinstance(level_plan, Mapping):
            continue
        level = _norm(level_plan.get("level")).replace(" ", "")
        if level not in fields_by_level:
            continue
        level_fields = fields_by_level[level]
        level_entities = [
            entity
            for entity in level_plan.get("entities") or []
            if isinstance(entity, Mapping) and str(entity.get("row_id") or "").strip()
        ]
        per_level[level] = {
            "entities": len(level_entities),
            "fields": len(level_fields),
            "cells": len(level_entities) * len(level_fields),
        }
        for entity in level_entities:
            row_id = str(entity.get("row_id")).strip()
            entities[f"{level}:{row_id}"] = {
                "level": level,
                "row_id": row_id,
                "label": str(entity.get("label") or row_id),
                "parent_row_id": entity.get("parent_row_id"),
                "aliases": _entity_aliases(entity),
            }
            for field in level_fields:
                total_cells += 1
                if len(cells) < MAX_STORED_FILL_CELLS:
                    cells.append(
                        {
                            "task_id": f"{level}:{row_id}:{_norm(field['field_name'])}",
                            "level": level,
                            "entity_row_id": row_id,
                            "field_name": field["field_name"],
                            "required": field["required"],
                            "package": field["package"],
                            "status": "pending",
                        }
                    )

    return {
        "schema_version": FILL_TASKS_SCHEMA_VERSION,
        "summary": {
            "total_cells": total_cells,
            "stored_cells": len(cells),
            "truncated": total_cells > len(cells),
            "per_level": per_level,
        },
        "entities": entities,
        "cells": cells,
    }


def first_pass_entity_alignment(
    fill_tasks: Dict[str, Any],
    metadata_fields: Iterable[Mapping[str, Any]],
) -> Dict[str, Any]:
    """Measure how many first-pass multi-row fields name a planned entity.

    The generator emits fields under its own group labels; rows are expanded onto
    planned entities later (value mapper and matrix projection). This is
    therefore a diagnostic of the generation granularity, not a fill status:
    ``multirow_entity_alignment`` is the share of populated multi-row fields whose
    ``entity_id`` equals a planned entity's row id, label or external identifier.
    """
    from ..services.fairds_api_parser import FAIRDSAPIParser

    alias_to_entity: Dict[str, set] = {}
    for entity in (fill_tasks.get("entities") or {}).values():
        level = str(entity.get("level") or "")
        alias_to_entity.setdefault(level, set()).update(entity.get("aliases") or [])

    populated = 0
    aligned = 0
    groups: set = set()
    for item in metadata_fields or []:
        if not isinstance(item, Mapping) or not _has_value(item.get("value")):
            continue
        level = FAIRDSAPIParser.normalize_isa_sheet(
            item.get("isa_sheet") or item.get("isa_level")
        )
        if level not in MULTI_ROW_ISA_LEVELS:
            continue
        populated += 1
        alias = _norm(item.get("entity_id"))
        groups.add((level, alias))
        if alias and alias in alias_to_entity.get(level, ()):
            aligned += 1

    first_pass = {
        "populated_multirow_fields": populated,
        "distinct_entity_labels": len(groups),
        "multirow_entity_alignment": round(aligned / populated, 4) if populated else None,
    }
    fill_tasks.setdefault("summary", {})["first_pass"] = first_pass
    return first_pass


def _matrix_blocks(matrix: Mapping[str, Any]) -> Mapping[str, Any]:
    inner = matrix.get("isa_values") if isinstance(matrix.get("isa_values"), Mapping) else matrix
    return inner if isinstance(inner, Mapping) else {}


def reconcile_fill_tasks_from_matrix(
    fill_tasks: Dict[str, Any],
    matrix: Mapping[str, Any],
) -> Dict[str, Any]:
    """Mark each stored cell from the final ISA matrix, in place.

    * ``filled``: the entity's matrix row has a populated value in that column.
    * ``blank``: the row exists and the column is empty or absent.
    * ``row_missing``: no matrix row carries the entity's identifier.

    Rows are attributed to entities by their identifier column matching the
    entity's row id, label or external identifier. Several rows may share one
    entity (investigation contacts); a cell is filled when any of them is.
    """
    from .entity_plan import _ID_FIELDS

    entities = fill_tasks.get("entities") or {}
    alias_to_entity: Dict[str, Dict[str, str]] = {}
    for key, entity in entities.items():
        level = str(entity.get("level") or "")
        for alias in entity.get("aliases") or []:
            alias_to_entity.setdefault(level, {}).setdefault(alias, key)

    blocks = _matrix_blocks(matrix)
    rows_by_entity: Dict[str, List[Mapping[str, Any]]] = {}
    for level, id_field in _ID_FIELDS.items():
        block = blocks.get(level)
        if not isinstance(block, Mapping):
            continue
        for row in block.get("rows") or []:
            if not isinstance(row, Mapping):
                continue
            normalized_row = {_norm(column): value for column, value in row.items()}
            entity_key = alias_to_entity.get(level, {}).get(
                _norm(normalized_row.get(_norm(id_field)))
            )
            if entity_key:
                rows_by_entity.setdefault(entity_key, []).append(normalized_row)

    counts = {"filled": 0, "blank": 0, "row_missing": 0}
    per_level: Dict[str, Dict[str, int]] = {}
    for cell in fill_tasks.get("cells") or []:
        level = cell["level"]
        rows = rows_by_entity.get(f"{level}:{cell['entity_row_id']}") or []
        field_key = _norm(cell["field_name"])
        if not rows:
            status = "row_missing"
        elif any(_has_value(row.get(field_key)) for row in rows):
            status = "filled"
        else:
            status = "blank"
        cell["status"] = status
        counts[status] += 1
        per_level.setdefault(level, {"filled": 0, "blank": 0, "row_missing": 0})[status] += 1

    stored = sum(counts.values())
    summary = fill_tasks.setdefault("summary", {})
    summary["status_source"] = "final_matrix"
    summary["status_counts"] = counts
    summary["status_per_level"] = per_level
    summary["fill_rate"] = round(counts["filled"] / stored, 4) if stored else None
    summary["entities_with_rows"] = len(rows_by_entity)
    summary["entities_planned"] = len(entities)
    return fill_tasks


def fill_tasks_artifact(fill_tasks: Mapping[str, Any]) -> str:
    return json.dumps(fill_tasks, indent=2, ensure_ascii=False, default=str)


def mapper_fixable_structure_issues(state: Dict[str, Any]) -> List[str]:
    """Structure-gate errors that re-running ISAValueMapper could change.

    Errors that the entity plan itself carries (its materialization or
    validation errors) are fixed only by re-planning; re-running the value
    mapper would redo the whole matrix for nothing.
    """
    gate = state.get("entity_matrix_validation") or {}
    plan = state.get("entity_plan") or {}
    plan_errors = set(plan.get("materialization_errors") or []) | set(
        (state.get("entity_plan_validation") or {}).get("errors") or []
    )
    return [issue for issue in gate.get("errors") or [] if issue not in plan_errors]
