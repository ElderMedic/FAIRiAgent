"""PlannerTask helpers (P1 §4 of architecture refactor).

The Planner now emits a list of ``PlannerTask`` objects (machine-readable)
instead of relying on free-text ``special_instructions`` that downstream
agents regex-parse for package names and search terms.

This module provides:
- ``parse_plan_tasks_from_llm_output`` — defensive parser for the LLM's
  structured plan, normalizing string-vs-list shapes and dropping empties.
- ``extract_plan_task`` — find the task assigned to a given agent. Accepts
  both ``PlannerTask`` instances and plain dicts (state may be serialized).
"""

from __future__ import annotations

from dataclasses import asdict, fields
from typing import Any, Dict, Iterable, List, Optional, Union

from ..models import PlannerTask


PlanTaskLike = Union[PlannerTask, Dict[str, Any]]


def extract_plan_task(
    plan_tasks: Optional[Iterable[PlanTaskLike]],
    agent_name: str,
) -> Optional[PlannerTask]:
    """Return the ``PlannerTask`` assigned to ``agent_name``, if any.

    Accepts an iterable of ``PlannerTask`` instances or plain dicts (since
    ``state["plan_tasks"]`` may be JSON-serialized in checkpoints).
    """
    if not plan_tasks:
        return None
    for entry in plan_tasks:
        if isinstance(entry, PlannerTask):
            if entry.agent_name == agent_name:
                return entry
        elif isinstance(entry, dict):
            if entry.get("agent_name") == agent_name:
                return _coerce_to_planner_task(entry)
    return None


def parse_plan_tasks_from_llm_output(
    llm_output: Optional[Dict[str, Any]],
) -> List[PlannerTask]:
    """Parse the ``plan_tasks`` array from a Planner LLM response.

    Defensive: drops invalid entries, normalizes shapes (string → list,
    comma-separated string → list), filters empty items.
    """
    if not isinstance(llm_output, dict):
        return []
    raw = llm_output.get("plan_tasks")
    if not isinstance(raw, list):
        return []

    tasks: List[PlannerTask] = []
    for entry in raw:
        if not isinstance(entry, dict):
            continue
        agent_name = entry.get("agent_name")
        if not isinstance(agent_name, str) or not agent_name.strip():
            continue
        tasks.append(_coerce_to_planner_task(entry))
    return tasks


def _coerce_to_planner_task(entry: Dict[str, Any]) -> PlannerTask:
    """Build a ``PlannerTask`` from a possibly-loose dict."""
    agent_name = str(entry.get("agent_name") or "").strip()
    return PlannerTask(
        agent_name=agent_name,
        priority_packages=_to_str_list(entry.get("priority_packages")),
        search_terms=_to_str_list(entry.get("search_terms")),
        focus_sheets=_to_str_list(entry.get("focus_sheets")),
        skip_if=_clean_optional_str(entry.get("skip_if")),
        notes=str(entry.get("notes") or "").strip(),
    )


def _to_str_list(value: Any) -> List[str]:
    """Coerce a value to a list of non-empty strings."""
    if value is None:
        return []
    if isinstance(value, str):
        # Accept comma-separated form as a convenience for sloppy LLMs.
        if "," in value:
            parts = [p.strip() for p in value.split(",")]
        else:
            parts = [value.strip()]
        return [p for p in parts if p]
    if isinstance(value, list):
        out: List[str] = []
        for item in value:
            if item is None:
                continue
            s = str(item).strip()
            if s:
                out.append(s)
        return out
    # Other types: stringify
    s = str(value).strip()
    return [s] if s else []


def _clean_optional_str(value: Any) -> Optional[str]:
    if value is None:
        return None
    s = str(value).strip()
    return s or None


def planner_task_to_dict(task: PlannerTask) -> Dict[str, Any]:
    """Convert a PlannerTask to a plain dict for state storage."""
    return asdict(task)


def planner_task_fields() -> List[str]:
    """Return the field names of PlannerTask (used by Planner prompt)."""
    return [f.name for f in fields(PlannerTask)]
