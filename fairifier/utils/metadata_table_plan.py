"""Ground ISA entity rows in source-supplied metadata tables.

The helpers in this module are deliberately domain-neutral.  They expose table
shape and categorical distributions to the structure agent, validate the
agent's column/row-selection decision against the original JSONL table, and
materialize exact row identities without guessing from identifier syntax.
"""

from __future__ import annotations

import json
import re
from copy import deepcopy
from collections import Counter
from itertools import combinations
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Optional, Tuple

from .isa_order import ISA_LEVEL_ORDER


def _text(value: Any) -> str:
    return " ".join(str(value or "").strip().split())


def _scalar_identifier(value: Any) -> bool:
    text = _text(value)
    return bool(text) and not any(separator in text for separator in (",", ";", "\n"))


def _identity_candidate(column: str, values: List[str], *, scalar_unique: bool) -> bool:
    """Distinguish row keys from unique quantitative measurements."""
    if not scalar_unique:
        return False
    header_hint = re.search(
        r"(?:^|[._\s-])(id|identifier|accession|name|label|key|run)(?:$|[._\s-])",
        column,
        flags=re.IGNORECASE,
    )
    numeric = 0
    for value in values:
        try:
            float(value)
        except ValueError:
            continue
        numeric += 1
    return bool(header_hint) or numeric < 0.8 * len(values)


def _design_value_tokens(value: Any) -> set[str]:
    """Return stable lexical tokens for aligning table branches to design groups."""
    return {
        token
        for token in re.findall(r"[a-z0-9]+", _text(value).lower())
        if len(token) > 1
    }


def _canonical_design_value(value: Any) -> str:
    """Normalize harmless spacing/case differences in audited factor values."""
    return re.sub(r"\s+", "", _text(value).lower())


def _observation_dimension_count(group: Mapping[str, Any]) -> Optional[int]:
    """Calculate a group's independently audited observation-condition count."""
    count = 1
    for dimension in group.get("dimensions") or []:
        if not isinstance(dimension, Mapping):
            continue
        applies_to = {
            _text(level).lower() for level in dimension.get("applies_to") or []
        }
        if (
            "observationunit" not in applies_to
            or _text(dimension.get("semantic_role")).lower()
            != "observation_condition"
        ):
            continue
        explicit = {
            _text(value)
            for value in dimension.get("explicit_values") or []
            if _text(value)
        }
        level_count = int(dimension.get("level_count") or 0)
        dimension_count = level_count or len(explicit)
        if not dimension_count:
            return None
        count *= dimension_count
    return count


def _align_table_groups_to_design(
    records: List[Mapping[str, Any]],
    group_column: str,
    design_groups: Iterable[Mapping[str, Any]],
) -> Optional[Dict[str, Mapping[str, Any]]]:
    """Align source branch labels to independently audited design groups.

    Alignment is accepted only when every selected table branch has one unique
    lexical match and no design group is reused. This keeps the repair generic
    and fails closed for opaque or ambiguous branch labels.
    """
    values = sorted({_text(row.get(group_column)) for row in records})
    if not group_column or not values or any(not value for value in values):
        return None
    groups = [group for group in design_groups if isinstance(group, Mapping)]
    aligned: Dict[str, Mapping[str, Any]] = {}
    used: set[str] = set()
    for value in values:
        value_tokens = _design_value_tokens(value)
        if not value_tokens:
            return None
        matches = []
        for group in groups:
            group_id = _text(group.get("group_id"))
            haystack = " ".join(
                [group_id, _text(group.get("label")), _text(group.get("evidence"))]
            )
            if value_tokens <= _design_value_tokens(haystack):
                matches.append(group)
        if len(matches) != 1 or _text(matches[0].get("group_id")) in used:
            return None
        aligned[value] = matches[0]
        used.add(_text(matches[0].get("group_id")))
    return aligned


def _reconcile_authoritative_observation_grouping(
    plan: Dict[str, Any],
    records: List[Dict[str, Any]],
    columns: List[str],
    design_groups: Iterable[Mapping[str, Any]],
) -> Optional[str]:
    """Reconcile table grouping with independent design-scope decisions.

    The source table owns row identity, while audited design dimensions own
    what constitutes an independently observed condition. When both sides can
    be aligned without ambiguity, choose the smallest unique set of source
    columns whose per-branch cardinalities exactly reproduce those conditions.
    """
    group_column = _text(plan.get("group_column"))
    aligned = _align_table_groups_to_design(records, group_column, design_groups)
    if not aligned:
        return None
    expected_by_group: Dict[str, int] = {}
    for value, group in aligned.items():
        expected = _observation_dimension_count(group)
        if expected is None:
            return None
        expected_by_group[value] = expected

    # A derivation that was drafted as an ObservationUnit grouping may have
    # been contradicted by the independent dimension-scope audit. Re-scope it
    # only when its rule values identify exactly one audited dimension.
    reconciled_derivations: List[Dict[str, Any]] = []
    for raw_mapping in plan.get("derived_mappings") or []:
        if not isinstance(raw_mapping, Mapping):
            continue
        mapping = dict(raw_mapping)
        if not mapping.get("use_for_observation_unit_grouping"):
            reconciled_derivations.append(mapping)
            continue
        filter_values = {
            _text(item.get("value"))
            for item in mapping.get("filters") or []
            if isinstance(item, Mapping)
            and _text(item.get("column")) == group_column
        }
        matched_groups = [aligned[value] for value in filter_values if value in aligned]
        rule_values = {
            _canonical_design_value(rule.get("value"))
            for rule in mapping.get("rules") or []
            if isinstance(rule, Mapping) and _text(rule.get("value"))
        }
        derived_values = {
            _canonical_design_value(
                _derived_value(row.get(mapping.get("source_column")), mapping.get("rules") or [])
            )
            for row in records
            if _matches_exact_filters(row, mapping.get("filters") or [])
        }
        derived_values.discard("")
        matching_dimensions: List[Mapping[str, Any]] = []
        for group in matched_groups:
            for dimension in group.get("dimensions") or []:
                if not isinstance(dimension, Mapping):
                    continue
                explicit = {
                    _canonical_design_value(value)
                    for value in dimension.get("explicit_values") or []
                    if _text(value)
                }
                if explicit and (explicit == rule_values or explicit == derived_values):
                    matching_dimensions.append(dimension)
        if len(matched_groups) != 1 or len(matching_dimensions) != 1:
            reconciled_derivations.append(mapping)
            continue
        dimension = matching_dimensions[0]
        if "observationunit" in {
            _text(level).lower() for level in dimension.get("applies_to") or []
        }:
            reconciled_derivations.append(mapping)
            continue
        targets = [
            target
            for target in dimension.get("field_mappings") or []
            if isinstance(target, Mapping)
            and _text(target.get("level")).lower() in {"sample", "assay"}
            and _text(target.get("field_name"))
        ]
        if not targets:
            targets = [
                {
                    "level": "sample",
                    "field_name": _text(dimension.get("name")),
                    "source_extension": True,
                }
            ]
        for target in targets:
            clone = dict(mapping)
            clone["level"] = _text(target.get("level")).lower()
            clone["field_name"] = _text(target.get("field_name"))
            clone["source_extension"] = bool(target.get("source_extension"))
            clone["use_for_observation_unit_grouping"] = False
            reconciled_derivations.append(clone)
    plan["derived_mappings"] = reconciled_derivations

    sample_column = _text(plan.get("sample_identifier_column"))
    assay_column = _text(plan.get("assay_identifier_column"))
    filter_columns = {
        _text(item.get("column"))
        for item in plan.get("filters") or []
        if isinstance(item, Mapping)
    }
    excluded = {sample_column, assay_column, group_column, *filter_columns}
    candidate_columns: List[str] = []
    for column in columns:
        if column in excluded:
            continue
        usable = True
        for value, expected in expected_by_group.items():
            branch_values = {
                _text(row.get(column))
                for row in records
                if _text(row.get(group_column)) == value
            }
            if not branch_values or "" in branch_values or len(branch_values) > expected:
                usable = False
                break
        if usable:
            candidate_columns.append(column)

    def matches_expected(candidate: Tuple[str, ...]) -> bool:
        for value, expected in expected_by_group.items():
            observed = {
                tuple(_text(row.get(column)) for column in candidate)
                for row in records
                if _text(row.get(group_column)) == value
            }
            if len(observed) != expected:
                return False
        return True

    solutions: List[Tuple[str, ...]] = []
    for width in range(0, min(3, len(candidate_columns)) + 1):
        solutions = [
            candidate
            for candidate in combinations(candidate_columns, width)
            if matches_expected(candidate)
        ]
        if solutions:
            break
    if len(solutions) != 1:
        return None
    selected_columns = list(solutions[0])
    old_columns = [_text(value) for value in plan.get("observation_unit_columns") or []]
    old_expected = int(plan.get("expected_observation_unit_count") or 0)
    new_expected = sum(expected_by_group.values())
    plan["observation_unit_columns"] = selected_columns
    plan["expected_observation_unit_count"] = new_expected
    if old_columns == selected_columns and old_expected == new_expected:
        return None
    return (
        "reconciled observation-unit grouping from independently audited "
        f"design scopes: {old_columns or ['<group only>']} / {old_expected or '?'} "
        f"-> {selected_columns or ['<group only>']} / {new_expected}"
    )


def source_extension_field_name(column: Any) -> str:
    """Create a stable, readable field label from a source-table header."""
    label = re.sub(r"[._-]+", " ", _text(column)).lower()
    return " ".join(label.split())


def _derived_value(value: Any, rules: Iterable[Mapping[str, Any]]) -> str:
    """Apply the first declarative, agent-selected derivation rule."""
    text = _text(value)
    for rule in rules:
        match_type = _text(rule.get("match_type")).lower()
        pattern = _text(rule.get("pattern"))
        if match_type == "exact":
            matched = text == pattern
        elif match_type == "prefix":
            matched = text.startswith(pattern)
        elif match_type == "suffix":
            matched = text.endswith(pattern)
        elif match_type == "contains":
            matched = pattern in text
        elif match_type == "regex":
            regex_match = re.search(pattern, text)
            matched = regex_match is not None
        else:
            matched = False
        if matched:
            result = _text(rule.get("value"))
            if match_type == "regex" and regex_match is not None:
                capture = re.fullmatch(
                    r"(?:group\(?([1-9][0-9]*)\)?|\$([1-9][0-9]*)|\\([1-9][0-9]*))",
                    result,
                )
                if capture:
                    group_index = int(next(part for part in capture.groups() if part))
                    try:
                        return _text(regex_match.group(group_index))
                    except IndexError:
                        return ""
            return result
    return ""


def _matches_exact_filters(
    row: Mapping[str, Any], filters: Iterable[Mapping[str, Any]]
) -> bool:
    return all(
        _text(row.get(_text(item.get("column")))) == _text(item.get("value"))
        for item in filters
    )


def _load_jsonl(path: Path) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            try:
                value = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(value, dict):
                rows.append(value)
    return rows


def _embedded_header_index(rows: List[Mapping[str, Any]]) -> Optional[int]:
    """Find a header row embedded beneath title/comment rows.

    Spreadsheet ingestion preserves the first physical row as dictionary keys.
    Many curated workbooks put provenance comments above the real header.  The
    real header is the early row with the broadest set of short, unique textual
    cells.  No study-specific column names are required.
    """
    if rows:
        physical_headers = [_text(key) for key in rows[0].keys()]
        placeholders = sum(
            not header
            or header.lower().startswith("unnamed:")
            or header.lower().startswith("column_")
            for header in physical_headers
        )
        if len(physical_headers) >= 2 and placeholders / len(physical_headers) < 0.5:
            return None

    candidates: List[Tuple[float, int]] = []
    for index, row in enumerate(rows[:25]):
        values = [_text(value) for value in row.values() if _text(value)]
        if len(values) < 2:
            continue
        unique_ratio = len({value.lower() for value in values}) / len(values)
        textual = sum(any(char.isalpha() for char in value) for value in values)
        short = sum(len(value) <= 80 for value in values)
        score = len(values) + unique_ratio + textual / len(values) + short / len(values)
        candidates.append((score, index))
    return (
        max(candidates, key=lambda item: (item[0], -item[1]))[1]
        if candidates
        else None
    )


def normalized_table_rows(path: Path) -> Tuple[List[str], List[Dict[str, Any]], int]:
    """Return promoted columns, data records, and physical header index."""
    raw_rows = _load_jsonl(path)
    if not raw_rows:
        return [], [], -1
    header_index = _embedded_header_index(raw_rows)
    if header_index is None:
        return [str(key) for key in raw_rows[0]], raw_rows, -1
    physical_keys = list(raw_rows[header_index].keys())
    headers: List[str] = []
    used: Counter[str] = Counter()
    for position, key in enumerate(physical_keys, start=1):
        header = _text(raw_rows[header_index].get(key)) or f"column_{position}"
        used[header] += 1
        if used[header] > 1:
            header = f"{header}_{used[header]}"
        headers.append(header)
    records = []
    for raw in raw_rows[header_index + 1 :]:
        record = {
            header: raw.get(key, "")
            for header, key in zip(headers, physical_keys)
        }
        if any(_text(value) for value in record.values()):
            records.append(record)
    return headers, records, header_index


def _workspace_manifest(workspace: Mapping[str, Any]) -> Mapping[str, Any]:
    manifest = workspace.get("manifest")
    if isinstance(manifest, Mapping):
        return manifest
    path = workspace.get("manifest_path")
    if path and Path(str(path)).is_file():
        return json.loads(Path(str(path)).read_text(encoding="utf-8"))
    return {}


def _metadata_table_profile(
    *,
    source_id: Any,
    table_name: Any,
    source_path: Any,
    header_index: int,
    columns: List[str],
    records: List[Dict[str, Any]],
    max_examples: int,
    unfiltered_record_count: Optional[int] = None,
    applied_filters: Optional[List[Dict[str, str]]] = None,
) -> Dict[str, Any]:
    """Summarize the exact record population an agent must reason about."""
    distributions = []
    for column in columns:
        values = [_text(row.get(column)) for row in records if _text(row.get(column))]
        counts = Counter(values)
        list_like_values = [
            value
            for value in values
            if any(separator in value for separator in (",", ";", "\n"))
        ]
        scalar_unique = (
            len(values) == len(records)
            and len(counts) == len(records)
            and not list_like_values
        )
        identity_candidate = _identity_candidate(
            column, values, scalar_unique=scalar_unique
        )
        example_limit = 60 if identity_candidate else 12
        examples = [
            {"value": value, "count": count}
            for value, count in counts.most_common(example_limit)
        ]
        distributions.append(
            {
                "column": column,
                "nonblank": len(values),
                "blank": len(records) - len(values),
                "unique": len(counts),
                "list_like_count": len(list_like_values),
                "list_like_examples": list_like_values[:3],
                "globally_scalar_unique": scalar_unique,
                "identity_candidate": identity_candidate,
                "top_values": examples,
            }
        )
    identity_candidates = [
        item["column"] for item in distributions if item["identity_candidate"]
    ]
    profile = {
        "source_id": source_id,
        "table_name": table_name,
        "source_path": source_path,
        "header_row_index_zero_based": header_index,
        "record_count": len(records),
        "columns": columns,
        "globally_scalar_unique_columns": identity_candidates,
        "column_distributions": distributions,
        "example_rows": records[:max_examples],
    }
    if unfiltered_record_count is not None:
        profile["unfiltered_record_count"] = unfiltered_record_count
        profile["applied_filters"] = applied_filters or []
    return profile


def metadata_table_profiles(
    workspace: Mapping[str, Any], *, max_examples: int = 8
) -> List[Dict[str, Any]]:
    """Build compact, prompt-safe profiles for metadata-table sources."""
    root = Path(str(workspace.get("root_dir") or "."))
    profiles: List[Dict[str, Any]] = []
    for source in _workspace_manifest(workspace).get("sources") or []:
        if not isinstance(source, Mapping) or source.get("source_role") != "metadata_table":
            continue
        for table in source.get("tables") or []:
            if not isinstance(table, Mapping) or not table.get("path"):
                continue
            table_path = root / str(table["path"])
            if not table_path.is_file():
                continue
            columns, records, header_index = normalized_table_rows(table_path)
            profiles.append(
                _metadata_table_profile(
                    source_id=source.get("source_id"),
                    table_name=table.get("name"),
                    source_path=source.get("path"),
                    header_index=header_index,
                    columns=columns,
                    records=records,
                    max_examples=max_examples,
                )
            )
    return profiles


def metadata_table_profiles_for_record_plans(
    workspace: Mapping[str, Any],
    record_plans: Iterable[Mapping[str, Any]],
    *,
    max_examples: int = 8,
) -> List[Dict[str, Any]]:
    """Profile only rows selected by each authoritative record-table plan.

    The unfiltered table is appropriate while the agent is discovering which
    study population to select. Once it has declared exact filters, however,
    field semantics must be judged from that focal population. Otherwise a
    heterogeneous reference table can make an identically named column mean
    something different in unrelated projects and bias the mapping audit.
    """
    profiles: List[Dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for plan in record_plans:
        if not isinstance(plan, Mapping) or not plan.get("covers_complete_focal_study"):
            continue
        source_id = _text(plan.get("source_id"))
        table_name = _text(plan.get("table_name"))
        key = (source_id, table_name)
        if not source_id or not table_name or key in seen:
            continue
        seen.add(key)
        located = _find_table(workspace, source_id, table_name)
        if not located:
            continue
        table_path, source = located
        columns, records, header_index = normalized_table_rows(table_path)
        filters = [
            {
                "column": _text(item.get("column")),
                "value": _text(item.get("value")),
            }
            for item in plan.get("filters") or []
            if isinstance(item, Mapping)
        ]
        selected = [row for row in records if _matches_exact_filters(row, filters)]
        profiles.append(
            _metadata_table_profile(
                source_id=source_id,
                table_name=table_name,
                source_path=source.get("path"),
                header_index=header_index,
                columns=columns,
                records=selected,
                max_examples=max_examples,
                unfiltered_record_count=len(records),
                applied_filters=filters,
            )
        )
    return profiles


def _find_table(
    workspace: Mapping[str, Any], source_id: str, table_name: str
) -> Optional[Tuple[Path, Mapping[str, Any]]]:
    root = Path(str(workspace.get("root_dir") or "."))
    for source in _workspace_manifest(workspace).get("sources") or []:
        if not isinstance(source, Mapping) or str(source.get("source_id")) != source_id:
            continue
        if source.get("source_role") != "metadata_table":
            return None
        for table in source.get("tables") or []:
            if (
                isinstance(table, Mapping)
                and str(table.get("name")) == table_name
                and table.get("path")
            ):
                return root / str(table["path"]), source
    return None


def materialize_record_table_plans(
    record_plans: Iterable[Mapping[str, Any]],
    *,
    workspace: Mapping[str, Any],
    root_levels: Mapping[str, Mapping[str, Any]],
    field_catalog: Mapping[str, Iterable[str]],
    design_groups: Iterable[Mapping[str, Any]] = (),
) -> Tuple[Optional[Dict[str, Any]], List[str]]:
    """Materialize exact table rows selected by an audited agent plan.

    The model chooses semantic columns and an exact equality filter.  Code owns
    row enumeration, uniqueness, scalar-ID checks, and parent construction.
    """
    errors: List[str] = []
    pre_materialization_notes: List[str] = []
    accepted: List[
        Tuple[Mapping[str, Any], List[Dict[str, Any]], Mapping[str, Any], bool]
    ] = []
    catalogs = {
        level: {str(field).strip().lower(): str(field).strip() for field in fields}
        for level, fields in field_catalog.items()
    }
    for raw_plan in record_plans:
        plan = deepcopy(raw_plan)
        if not isinstance(plan, Mapping) or not plan.get("covers_complete_focal_study"):
            continue
        source_id = _text(plan.get("source_id"))
        table_name = _text(plan.get("table_name"))
        found = _find_table(workspace, source_id, table_name)
        if not found:
            errors.append(f"Record-table plan references unknown table {source_id}:{table_name}.")
            continue
        table_path, source = found
        columns, records, _ = normalized_table_rows(table_path)
        column_set = set(columns)
        selectors = plan.get("filters") or []
        invalid_selectors = [
            item for item in selectors
            if not isinstance(item, Mapping) or _text(item.get("column")) not in column_set
        ]
        if invalid_selectors:
            errors.append(f"Record-table plan {source_id}:{table_name} has unknown filter columns.")
            continue
        selected = records
        for selector in selectors:
            column = _text(selector.get("column"))
            value = _text(selector.get("value"))
            selected = [row for row in selected if _text(row.get(column)) == value]
        grouping_note = _reconcile_authoritative_observation_grouping(
            plan, selected, columns, design_groups
        )
        if grouping_note:
            pre_materialization_notes.append(
                f"{source.get('path')}:{table_name}: {grouping_note}."
            )
        sample_column = _text(plan.get("sample_identifier_column"))
        assay_column = _text(plan.get("assay_identifier_column"))
        observation_columns = [_text(item) for item in plan.get("observation_unit_columns") or []]
        has_derived_observation_grouping = any(
            isinstance(mapping, Mapping)
            and bool(mapping.get("use_for_observation_unit_grouping"))
            and _text(mapping.get("level")).lower() == "observationunit"
            for mapping in plan.get("derived_mappings") or []
        )
        required = [sample_column, assay_column, *observation_columns]
        unknown_identity_columns = [
            column for column in required if column and column not in column_set
        ]
        if (
            not sample_column
            or not assay_column
            or (not observation_columns and not has_derived_observation_grouping)
            or unknown_identity_columns
        ):
            missing_roles = []
            if not sample_column:
                missing_roles.append("sample_identifier_column")
            if not assay_column:
                missing_roles.append("assay_identifier_column")
            if not observation_columns and not has_derived_observation_grouping:
                missing_roles.append("observation_unit grouping")
            errors.append(
                f"Record-table plan {source_id}:{table_name} has invalid identity "
                f"or grouping columns: missing roles={missing_roles or []}, "
                f"unknown columns={unknown_identity_columns or []}; available "
                f"columns={columns}."
            )
            continue
        sample_ids = [_text(row.get(sample_column)) for row in selected]
        assay_ids = [_text(row.get(assay_column)) for row in selected]
        if not selected:
            errors.append(f"Record-table plan {source_id}:{table_name} selected zero rows.")
            continue
        count_errors: List[str] = []
        for count_key, actual in (
            ("expected_sample_count", len(selected)),
            ("expected_assay_count", len(selected)),
        ):
            expected = int(plan.get(count_key) or 0)
            if expected and expected != actual:
                count_errors.append(
                    f"Record-table plan {source_id}:{table_name} expected "
                    f"{expected} for {count_key}, but selected {actual} rows."
                )
        if count_errors:
            errors.extend(count_errors)
            continue
        if any(not _scalar_identifier(value) for value in sample_ids):
            errors.append(
                f"Record-table plan {source_id}:{table_name} contains blank or "
                "list-like sample IDs."
            )
            continue
        if len(set(sample_ids)) != len(sample_ids):
            errors.append(
                f"Record-table plan {source_id}:{table_name} contains duplicate sample IDs."
            )
            continue
        assay_ids_are_scalar_unique = (
            all(_scalar_identifier(value) for value in assay_ids)
            and len(set(assay_ids)) == len(assay_ids)
        )
        accepted.append((plan, selected, source, assay_ids_are_scalar_unique))

    if not accepted:
        return None, errors

    levels: Dict[str, Dict[str, Any]] = {
        level: {
            "level": level,
            "cardinality": 0,
            "entities": (
                list((root_levels.get(level) or {}).get("entities") or [])
                if level in {"investigation", "study"}
                else []
            ),
            "evidence": (
                list((root_levels.get(level) or {}).get("evidence") or [])
                if level in {"investigation", "study"}
                else []
            ),
            "unresolved_ambiguities": list(
                (root_levels.get(level) or {}).get("unresolved_ambiguities") or []
            )
            if level in {"investigation", "study"}
            else [],
        }
        for level in ISA_LEVEL_ORDER
    }
    seen_samples: set[str] = set()
    seen_assays: set[str] = set()
    materialization_notes: List[str] = list(pre_materialization_notes)
    source_extension_fields: Dict[Tuple[str, str], Dict[str, Any]] = {}
    source_coverage_tables: List[Dict[str, Any]] = []
    observation_ids: Dict[Tuple[str, Tuple[str, ...]], str] = {}
    for plan_index, (
        plan,
        records,
        source,
        assay_ids_are_scalar_unique,
    ) in enumerate(accepted, start=1):
        study_row_id = _text(plan.get("study_row_id"))
        study_ids = {
            _text(entity.get("row_id"))
            for entity in levels["study"]["entities"]
            if isinstance(entity, Mapping)
        }
        if study_row_id not in study_ids:
            errors.append(f"Record-table plan has unresolved study {study_row_id}.")
            continue
        study_identifier = _text(plan.get("study_identifier_value"))
        selector_values = {
            _text(item.get("value"))
            for item in plan.get("filters") or []
            if isinstance(item, Mapping)
        }
        if study_identifier:
            if study_identifier not in selector_values:
                errors.append(
                    "Record-table study_identifier_value must be one of its exact filter values."
                )
                continue
            for study_entity in levels["study"]["entities"]:
                if (
                    isinstance(study_entity, dict)
                    and _text(study_entity.get("row_id")) == study_row_id
                ):
                    study_entity["external_identifier"] = study_identifier
        sample_column = _text(plan.get("sample_identifier_column"))
        assay_column = _text(plan.get("assay_identifier_column"))
        observation_columns = [_text(item) for item in plan.get("observation_unit_columns") or []]
        description_columns = [
            _text(item) for item in plan.get("description_columns") or [] if _text(item)
        ]
        assay_description_columns = [
            _text(item)
            for item in plan.get("assay_description_columns") or []
            if _text(item)
        ]
        if not assay_ids_are_scalar_unique and assay_column != sample_column:
            # A table row can represent one logical assay while retaining a
            # list of contributing run/accession identifiers. The list is
            # assay context, not a safe row-expansion instruction. If every
            # row already has a unique scalar sample key, use that row key for
            # the one-to-one logical assay and preserve the requested column.
            assay_description_columns = list(
                dict.fromkeys([assay_column, *assay_description_columns])
            )
            materialization_notes.append(
                f"{source.get('path')}:{plan.get('table_name')}: "
                f"used scalar row key '{sample_column}' for logical assays; "
                f"retained non-scalar or repeated '{assay_column}' as assay context."
            )
        valid_mappings: Dict[Tuple[str, str], str] = {}
        for mapping in plan.get("column_mappings") or []:
            if not isinstance(mapping, Mapping):
                continue
            column = _text(mapping.get("column"))
            level = _text(mapping.get("level")).lower()
            requested = _text(mapping.get("field_name")).lower()
            canonical = catalogs.get(level, {}).get(requested)
            if column and canonical:
                valid_mappings[(level, column)] = canonical
        extension_mappings: Dict[Tuple[str, str], Dict[str, Any]] = {}
        for mapping in plan.get("source_extension_mappings") or []:
            if not isinstance(mapping, Mapping):
                continue
            column = _text(mapping.get("column"))
            level = _text(mapping.get("level")).lower()
            field_name = source_extension_field_name(column)
            if (
                column not in records[0]
                or level not in {"observationunit", "sample", "assay"}
                or not field_name
            ):
                errors.append(
                    f"Record-table plan {source.get('source_id')}:"
                    f"{plan.get('table_name')} has an invalid source extension "
                    f"mapping for {column or '?'} at {level or '?'} level."
                )
                continue
            if (level, column) in valid_mappings:
                materialization_notes.append(
                    f"{source.get('path')}:{plan.get('table_name')}: ignored "
                    f"source extension for '{column}' because it has a FAIR-DS "
                    "field mapping at the same level."
                )
                continue
            extension = {
                "level": level,
                "field_name": field_name,
                "source_column": column,
                "data_type": _text(mapping.get("data_type")) or "string",
                "definition": _text(mapping.get("definition"))
                or f"Source-supplied metadata column '{column}'.",
                "source_id": source.get("source_id"),
                "source_path": source.get("path"),
                "table_name": plan.get("table_name"),
            }
            extension_mappings[(level, column)] = extension
            source_extension_fields[(level, field_name)] = extension
        derived_mappings: Dict[Tuple[str, str], Dict[str, Any]] = {}
        fatal_derivation_errors: List[str] = []
        for mapping in plan.get("derived_mappings") or []:
            if not isinstance(mapping, Mapping):
                continue
            source_column = _text(mapping.get("source_column"))
            level = _text(mapping.get("level")).lower()
            requested = _text(mapping.get("field_name")).lower()
            canonical = catalogs.get(level, {}).get(requested)
            is_extension = bool(mapping.get("source_extension")) and not canonical
            if is_extension and not canonical:
                canonical = source_extension_field_name(requested)
            rules = [
                rule
                for rule in mapping.get("rules") or []
                if isinstance(rule, Mapping)
            ]
            derivation_filters = [
                item
                for item in mapping.get("filters") or []
                if isinstance(item, Mapping)
            ]
            invalid_filter_columns = [
                _text(item.get("column"))
                for item in derivation_filters
                if _text(item.get("column")) not in records[0]
                or not _text(item.get("value"))
            ]
            use_for_observation_grouping = bool(
                mapping.get("use_for_observation_unit_grouping")
            )
            mapping_errors: List[str] = []
            if (
                source_column not in records[0]
                or level not in {"observationunit", "sample", "assay"}
                or not canonical
                or not rules
                or invalid_filter_columns
            ):
                mapping_errors.append(
                    f"invalid derived mapping for {source_column or '?'} to "
                    f"{level or '?'}.{requested or '?'}"
                )
            for rule in rules:
                match_type = _text(rule.get("match_type")).lower()
                pattern = _text(rule.get("pattern"))
                value = _text(rule.get("value"))
                if (
                    match_type not in {"exact", "prefix", "suffix", "contains", "regex"}
                    or not pattern
                    or not value
                    or len(pattern) > 200
                ):
                    mapping_errors.append(
                        f"invalid {match_type or '?'} derivation rule for "
                        f"{level}.{canonical}"
                    )
                    continue
                if match_type == "regex":
                    try:
                        re.compile(pattern)
                    except re.error:
                        mapping_errors.append(
                            f"invalid regex derivation rule for {level}.{canonical}"
                        )
            expected_nonblank = int(mapping.get("expected_nonblank_count") or 0)
            if use_for_observation_grouping and (
                level != "observationunit"
                or not expected_nonblank
                or not _text(mapping.get("evidence"))
            ):
                mapping_errors.append(
                    "observation-unit grouping derivation requires the "
                    "observationunit level, an exact expected_nonblank_count, "
                    "and source evidence"
                )
            if not mapping_errors:
                derived_values = [
                    _derived_value(row.get(source_column), rules)
                    if _matches_exact_filters(row, derivation_filters)
                    else ""
                    for row in records
                ]
                actual_nonblank = sum(bool(value) for value in derived_values)
                if expected_nonblank and expected_nonblank != actual_nonblank:
                    mapping_errors.append(
                        f"derived mapping {level}.{canonical} expected "
                        f"{expected_nonblank} values but produced {actual_nonblank}"
                    )
            if mapping_errors:
                rendered_errors = "; ".join(dict.fromkeys(mapping_errors))
                if use_for_observation_grouping:
                    fatal_derivation_errors.append(rendered_errors)
                else:
                    materialization_notes.append(
                        f"{source.get('path')}:{plan.get('table_name')}: omitted "
                        f"unsafe optional derivation {level or '?'}.{canonical or requested or '?'}: "
                        f"{rendered_errors}."
                    )
                continue
            derived_mappings[(level, canonical)] = {
                "source_column": source_column,
                "field_name": canonical,
                "rules": rules,
                "filters": derivation_filters,
                "evidence": _text(mapping.get("evidence")),
                "expected_nonblank_count": expected_nonblank or None,
                "source_extension": is_extension,
                "use_for_observation_unit_grouping": use_for_observation_grouping,
            }
            if is_extension:
                source_extension_fields[(level, canonical)] = {
                    "level": level,
                    "field_name": canonical,
                    "source_column": source_column,
                    "data_type": _text(mapping.get("data_type")) or "string",
                    "definition": _text(mapping.get("definition"))
                    or f"Source-backed value derived from '{source_column}'.",
                    "source_id": source.get("source_id"),
                    "source_path": source.get("path"),
                    "table_name": plan.get("table_name"),
                    "derived": True,
                }
        if fatal_derivation_errors:
            errors.extend(
                f"Record-table plan {source.get('source_id')}:"
                f"{plan.get('table_name')} has {message}."
                for message in fatal_derivation_errors
            )
            continue
        invalid_observation_mappings = [
            column
            for level, column in [*valid_mappings, *extension_mappings]
            if level == "observationunit" and column not in observation_columns
        ]
        invalid_observation_mappings.extend(
            mapping["source_column"]
            for (level, _), mapping in derived_mappings.items()
            if level == "observationunit"
            and not mapping.get("use_for_observation_unit_grouping")
            and mapping["source_column"] not in observation_columns
        )
        if invalid_observation_mappings:
            errors.append(
                f"Record-table plan {source.get('source_id')}:"
                f"{plan.get('table_name')} maps observation-unit columns "
                f"{sorted(set(invalid_observation_mappings))} without using "
                "them as observation-unit grouping dimensions."
            )
            continue
        group = _text(plan.get("group_column"))
        expected_observation_count = int(
            plan.get("expected_observation_unit_count") or 0
        )
        if expected_observation_count:
            grouping_derivations = [
                mapping
                for (level, _), mapping in derived_mappings.items()
                if level == "observationunit"
                and mapping.get("use_for_observation_unit_grouping")
            ]

            def grouping_count(candidate_columns: List[str]) -> int:
                return len(
                    {
                        (
                            _text(row.get(group)) if group else f"table_{plan_index:03d}",
                            *(_text(row.get(column)) for column in candidate_columns),
                            *(
                                _derived_value(
                                    row.get(mapping["source_column"]),
                                    mapping["rules"],
                                )
                                if _matches_exact_filters(row, mapping.get("filters") or [])
                                else ""
                                for mapping in grouping_derivations
                            ),
                        )
                        for row in records
                    }
                )

            current_count = grouping_count(observation_columns)
            refinements = [
                column
                for column in description_columns
                if column not in observation_columns
                and 1 < len({_text(row.get(column)) for row in records}) < len(records)
            ]
            if current_count < expected_observation_count:
                for width in range(1, len(refinements) + 1):
                    matching = next(
                        (
                            list(extra)
                            for extra in combinations(refinements, width)
                            if grouping_count([*observation_columns, *extra])
                            == expected_observation_count
                        ),
                        None,
                    )
                    if matching is not None:
                        observation_columns.extend(matching)
                        materialization_notes.append(
                            f"{source.get('path')}:{plan.get('table_name')}: "
                            "refined observation-unit grouping with "
                            f"{matching} to preserve {expected_observation_count} "
                            "source-declared conditions."
                        )
                        break
            if grouping_count(observation_columns) != expected_observation_count:
                errors.append(
                    f"Record-table plan {source.get('source_id')}:"
                    f"{plan.get('table_name')} could not preserve its "
                    f"source-declared {expected_observation_count} observation units."
                )
                continue
        evidence = _text(plan.get("evidence")) or (
            "Exact records selected from metadata table "
            f"{source.get('path')}:{plan.get('table_name')}"
        )
        excluded = {
            _text(item.get("column")): {
                "classification": _text(item.get("classification")),
                "reason": _text(item.get("reason")),
            }
            for item in plan.get("excluded_columns") or []
            if isinstance(item, Mapping) and _text(item.get("column"))
        }
        column_roles: Dict[str, set[str]] = {}

        def add_column_role(column: str, role: str) -> None:
            if column:
                column_roles.setdefault(column, set()).add(role)

        add_column_role(sample_column, "sample_identity")
        add_column_role(assay_column, "assay_identity")
        add_column_role(group, "branch_grouping")
        for column in observation_columns:
            add_column_role(column, "observation_unit_grouping")
        for column in description_columns:
            add_column_role(column, "sample_context")
        for column in assay_description_columns:
            add_column_role(column, "assay_context")
        for item in plan.get("filters") or []:
            if isinstance(item, Mapping):
                add_column_role(_text(item.get("column")), "exact_filter")
        for level, column in valid_mappings:
            add_column_role(column, f"fairds_mapping:{level}")
        for level, column in extension_mappings:
            add_column_role(column, f"source_extension:{level}")
        for mapping in derived_mappings.values():
            add_column_role(mapping["source_column"], "derivation_input")
            for item in mapping.get("filters") or []:
                if isinstance(item, Mapping):
                    add_column_role(_text(item.get("column")), "derivation_filter")
        for column in excluded:
            add_column_role(column, "explicit_exclusion")

        role_columns = set(column_roles)
        table_columns = list(records[0]) if records else []
        unmapped_columns = [column for column in table_columns if column not in role_columns]
        source_coverage_tables.append(
            {
                "source_id": source.get("source_id"),
                "source_path": source.get("path"),
                "table_name": plan.get("table_name"),
                "selected_record_count": len(records),
                "columns": table_columns,
                "column_roles": [
                    {"column": column, "roles": sorted(column_roles.get(column, set()))}
                    for column in table_columns
                    if column in column_roles
                ],
                "fairds_mappings": [
                    {"level": level, "column": column, "field_name": field_name}
                    for (level, column), field_name in sorted(valid_mappings.items())
                ],
                "source_extensions": list(extension_mappings.values()),
                "derived_mappings": list(derived_mappings.values()),
                "excluded_columns": [
                    {"column": column, **details}
                    for column, details in sorted(excluded.items())
                ],
                "unmapped_columns": unmapped_columns,
                "coverage_complete": not unmapped_columns,
            }
        )
        if unmapped_columns:
            materialization_notes.append(
                f"{source.get('path')}:{plan.get('table_name')}: source coverage "
                f"remains incomplete for {unmapped_columns}."
            )

        sample_attribute_columns = list(
            dict.fromkeys(
                [
                    *description_columns,
                    *(column for (level, column) in valid_mappings if level == "sample"),
                    *(column for (level, column) in extension_mappings if level == "sample"),
                ]
            )
        )
        assay_attribute_columns = list(
            dict.fromkeys(
                [
                    *assay_description_columns,
                    *(column for (level, column) in valid_mappings if level == "assay"),
                    *(column for (level, column) in extension_mappings if level == "assay"),
                ]
            )
        )

        for record_index, row in enumerate(records, start=1):
            sample_id = _text(row.get(sample_column))
            assay_id = (
                _text(row.get(assay_column))
                if assay_ids_are_scalar_unique
                else sample_id
            )
            if sample_id in seen_samples or assay_id in seen_assays:
                errors.append("Record-table plans overlap on sample or assay identifiers.")
                continue
            seen_samples.add(sample_id)
            seen_assays.add(assay_id)
            group_value = _text(row.get(group)) if group else f"table_{plan_index:03d}"
            observation_values = tuple(_text(row.get(column)) for column in observation_columns)
            derived_observation_values = tuple(
                _derived_value(row.get(mapping["source_column"]), mapping["rules"])
                if _matches_exact_filters(row, mapping.get("filters") or [])
                else ""
                for (level, _), mapping in derived_mappings.items()
                if level == "observationunit"
                and mapping.get("use_for_observation_unit_grouping")
            )
            observation_key = (
                group_value,
                observation_values,
                derived_observation_values,
            )
            ou_row_id = observation_ids.get(observation_key)
            if ou_row_id is None:
                ou_row_id = (
                    f"record_{plan_index:03d}_observationunit_"
                    f"{len(observation_ids) + 1:03d}"
                )
                observation_ids[observation_key] = ou_row_id
                ou_attributes = [
                    {
                        "dimension_name": column,
                        "field_name": (
                            valid_mappings.get(("observationunit", column))
                            or (
                                extension_mappings.get(("observationunit", column))
                                or {}
                            ).get("field_name")
                        ),
                        "value": value,
                        "origin": "explicit",
                    }
                    for column, value in zip(observation_columns, observation_values)
                    if value
                ]
                ou_attributes.extend(
                    {
                        "dimension_name": mapping["source_column"],
                        "field_name": mapping["field_name"],
                        "value": value,
                        "origin": "derived",
                        "evidence": mapping["evidence"],
                    }
                    for (level, _), mapping in derived_mappings.items()
                    for value in [
                        _derived_value(
                            row.get(mapping["source_column"]), mapping["rules"]
                        )
                        if _matches_exact_filters(
                            row, mapping.get("filters") or []
                        )
                        else ""
                    ]
                    if level == "observationunit" and value
                )
                levels["observationunit"]["entities"].append(
                    {
                        "row_id": ou_row_id,
                        "label": " / ".join(
                            value
                            for value in (*observation_values, *derived_observation_values)
                            if value
                        )
                        or group_value,
                        "parent_row_id": study_row_id,
                        "external_identifier": None,
                        "source_group": group_value,
                        "attributes": ou_attributes,
                    }
                )
            context_attributes = [
                {
                    "dimension_name": column,
                    "field_name": valid_mappings.get(("sample", column)),
                    "value": _text(row.get(column)),
                    "origin": "explicit",
                }
                for column in sample_attribute_columns
                if column in row and _text(row.get(column))
            ]
            for attribute in context_attributes:
                extension = extension_mappings.get(("sample", attribute["dimension_name"]))
                if extension:
                    attribute["field_name"] = extension["field_name"]
            context_attributes.extend(
                {
                    "dimension_name": mapping["source_column"],
                    "field_name": mapping["field_name"],
                    "value": value,
                    "origin": "derived",
                    "evidence": mapping["evidence"],
                }
                for (level, _), mapping in derived_mappings.items()
                for value in [
                    _derived_value(
                        row.get(mapping["source_column"]), mapping["rules"]
                    )
                    if _matches_exact_filters(row, mapping.get("filters") or [])
                    else ""
                ]
                if level == "sample" and value
            )
            sample_row_id = f"record_{plan_index:03d}_sample_{record_index:04d}"
            levels["sample"]["entities"].append(
                {
                    "row_id": sample_row_id,
                    "label": sample_id,
                    "parent_row_id": ou_row_id,
                    "external_identifier": sample_id,
                    "source_group": group_value,
                    "attributes": context_attributes,
                }
            )
            assay_attributes = [
                {
                    "dimension_name": column,
                    "field_name": valid_mappings.get(("assay", column)),
                    "value": _text(row.get(column)),
                    "origin": "explicit",
                }
                for column in assay_attribute_columns
                if column in row
                and _text(row.get(column))
            ]
            for attribute in assay_attributes:
                extension = extension_mappings.get(("assay", attribute["dimension_name"]))
                if extension:
                    attribute["field_name"] = extension["field_name"]
            assay_attributes.extend(
                {
                    "dimension_name": mapping["source_column"],
                    "field_name": mapping["field_name"],
                    "value": value,
                    "origin": "derived",
                    "evidence": mapping["evidence"],
                }
                for (level, _), mapping in derived_mappings.items()
                for value in [
                    _derived_value(
                        row.get(mapping["source_column"]), mapping["rules"]
                    )
                ]
                if level == "assay" and value
            )
            levels["assay"]["entities"].append(
                {
                    "row_id": f"record_{plan_index:03d}_assay_{record_index:04d}",
                    "label": assay_id,
                    "parent_row_id": sample_row_id,
                    "external_identifier": assay_id,
                    "source_group": group_value,
                    "attributes": assay_attributes,
                }
            )
        for level in ("observationunit", "sample", "assay"):
            if evidence not in levels[level]["evidence"]:
                levels[level]["evidence"].append(evidence)

    for level in ISA_LEVEL_ORDER:
        levels[level]["cardinality"] = len(levels[level]["entities"])
    if errors:
        # A complete focal-study record plan is atomic. Returning a partially
        # materialized graph would make later stages treat missing or
        # overlapping source rows as authoritative evidence.
        return None, errors
    return {
        "levels": [levels[level] for level in ISA_LEVEL_ORDER],
        "design_summary": [
            {
                "group_id": "metadata_table_records",
                "row_counts": {
                    level: len(levels[level]["entities"])
                    for level in ("observationunit", "sample", "assay")
                },
            }
        ],
        "claimed_design_summary": [],
        "unresolved_ambiguities": [],
        "confidence": 1.0,
        "materialization_errors": errors,
        "materialization_notes": materialization_notes,
        "source_extension_fields": list(source_extension_fields.values()),
        "source_coverage": {
            "tables": source_coverage_tables,
            "complete": bool(source_coverage_tables)
            and all(item["coverage_complete"] for item in source_coverage_tables),
        },
    }, errors
