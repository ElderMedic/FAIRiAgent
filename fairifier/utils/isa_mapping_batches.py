"""Pure bounded ISA mapping schedules and identity-safe sparse assembly.

Investigation/contact and Study mapping stay with the caller. Scientific cells
are never initialized from unbound proposals or broadcast across batch rows.
"""

from collections import defaultdict
from copy import deepcopy
import json
from typing import Any, Mapping

from .isa_order import ISA_LEVEL_ORDER

_LEVELS = ("observationunit", "sample", "assay")
_IDS = {
    "investigation": "investigation identifier", "study": "study identifier",
    "observationunit": "observation unit identifier", "sample": "sample identifier",
    "assay": "assay identifier",
}
_PARENT = {level: ISA_LEVEL_ORDER[index - 1] for index, level in enumerate(ISA_LEVEL_ORDER) if index}


def _text(value: Any) -> str:
    return "" if value is None else str(value).strip()


def _key(value: Any) -> str:
    return " ".join(_text(value).lower().split())


def _rows(plan):
    levels = {level: [] for level in ISA_LEVEL_ORDER}
    for block in plan.get("levels") or []:
        if isinstance(block, Mapping) and block.get("level") in levels:
            levels[block["level"]].extend(block.get("entities") or [])
    for level, rows in levels.items():
        ids = [_text(row.get("row_id")) for row in rows]
        if any(not value for value in ids) or len(set(ids)) != len(ids):
            raise ValueError(f"{level} requires unique nonempty canonical row IDs")
    return levels


def _columns(fields, level):
    structural = [_IDS[level], _IDS[_PARENT[level]]]
    return list(dict.fromkeys(structural + [
        _key(field.get("field_name")) for field in fields.get(level, [])
        if _key(field.get("field_name"))
    ]))


def _sliced_plan(plan, rows, level, selected):
    wanted = {name: set() for name in ISA_LEVEL_ORDER}
    wanted[level] = {_text(row["row_id"]) for row in selected}
    for name in reversed(ISA_LEVEL_ORDER):
        if name not in _PARENT:
            continue
        parent_level = _PARENT[name]
        parent_ids = {_text(row["row_id"]) for row in rows[parent_level]}
        for row in rows[name]:
            if _text(row["row_id"]) not in wanted[name]:
                continue
            parent = _text(row.get("parent_row_id"))
            if parent not in parent_ids:
                raise ValueError(f"{name}.{row['row_id']} has no unique canonical parent")
            wanted[parent_level].add(parent)
    return {
        "levels": [{
            "level": name, "cardinality": len(wanted[name]),
            "entities": deepcopy([row for row in rows[name] if _text(row["row_id"]) in wanted[name]]),
        } for name in ISA_LEVEL_ORDER if wanted[name]],
        "investigation_contacts": deepcopy(plan.get("investigation_contacts") or []),
    }


# Every mapping call re-reads the whole source, so batches are as large as one
# answer comfortably allows (the estimate counts >= 80 characters per cell,
# about twice the observed answer size).
MAX_BATCH_ENTITIES = 32
MAX_BATCH_OUTPUT_CHARS = 32000


def plan_mapping_batches(fields_by_level, entity_plan, *, max_fields=12,
                         max_entities=MAX_BATCH_ENTITIES,
                         max_output_chars=MAX_BATCH_OUTPUT_CHARS):
    """Partition every requested non-root entity/field pair exactly once.

    Structural keys repeat in each field chunk. Output estimates include a
    conservative 80-character floor per scientific cell and full upstream
    value lengths; a single cell larger than the budget fails explicitly.
    Proposals retain their original entity IDs and scope without rebinding.
    """
    if max_fields < 3 or max_entities < 1 or max_output_chars < 1:
        raise ValueError("Mapping batch limits must permit IDs and one scientific field")
    rows = _rows(entity_plan)
    batches = []
    for level in _LEVELS:
        proposals = fields_by_level.get(level) or []
        if not proposals or not rows[level]:
            continue
        columns = _columns(fields_by_level, level)
        structural, scientific = columns[:2], columns[2:]
        costs = {
            name: len(json.dumps(name)) + 4 + max(80, max((
                len(json.dumps(field.get("value"), ensure_ascii=False))
                for field in proposals if _key(field.get("field_name")) == name
            ), default=0)) for name in scientific
        }

        def row_cost(row, names):
            identity = {_IDS[level]: row["row_id"], _IDS[_PARENT[level]]: row.get("parent_row_id")}
            return len(json.dumps(identity, ensure_ascii=False)) + 4 + sum(costs[name] for name in names)

        largest_identity = max(row_cost(row, []) for row in rows[level])
        chunks, chunk = [], []
        for name in scientific:
            if 100 + largest_identity + costs[name] > max_output_chars:
                raise ValueError(f"Single {level}.{name} cell exceeds mapping output budget")
            if chunk and (len(chunk) + 2 >= max_fields or
                          100 + largest_identity + sum(costs[item] for item in chunk + [name]) > max_output_chars):
                chunks.append(chunk)
                chunk = []
            chunk.append(name)
        chunks.append(chunk)
        for names in chunks:
            selected, estimate = [], 100
            for row in rows[level]:
                cost = row_cost(row, names)
                if 100 + cost > max_output_chars:
                    raise ValueError(f"{level} identity exceeds mapping output budget")
                if selected and (len(selected) >= max_entities or estimate + cost > max_output_chars):
                    batches.append(_batch(level, structural + names, selected, estimate,
                                          proposals, entity_plan, rows))
                    selected, estimate = [], 100
                selected.append(row)
                estimate += cost
            if selected:
                batches.append(_batch(level, structural + names, selected, estimate,
                                      proposals, entity_plan, rows))
    return batches


def _batch(level, names, selected, estimate, proposals, plan, rows):
    targets = {_text(row["row_id"]) for row in selected}
    identities = _identity_index(rows[level])

    def relevant(field):
        canonical = identities.get(_text(field.get("entity_id")))
        scope = _key(field.get("value_scope") or "entity")
        return canonical is None or canonical in targets or scope != "entity"

    return {
        "target_level": level, "field_names": names,
        "row_ids": [_text(row["row_id"]) for row in selected],
        "entity_plan": _sliced_plan(plan, rows, level, selected),
        "fields_by_level": {level: deepcopy([
            field for field in proposals
            if _key(field.get("field_name")) in names and relevant(field)
        ])},
        "estimated_output_chars": estimate,
    }


def seed_mapping_matrix(fields_by_level, entity_plan):
    """Seed all non-root planned rows with canonical links and blank cells."""
    rows = _rows(entity_plan)
    matrix = {}
    for level in _LEVELS:
        columns = _columns(fields_by_level, level)
        parent_ids = {_text(row["row_id"]) for row in rows[_PARENT[level]]}
        output = []
        for entity in rows[level]:
            parent = _text(entity.get("parent_row_id"))
            if parent not in parent_ids:
                raise ValueError(f"{level}.{entity['row_id']} has no unique canonical parent")
            row = dict.fromkeys(columns, "")
            row[_IDS[level]] = _text(entity["row_id"])
            row[_IDS[_PARENT[level]]] = parent
            output.append(row)
        matrix[level] = {"columns": columns, "rows": output}
    return matrix


def _identity_index(rows):
    owners = defaultdict(set)
    for row in rows:
        canonical = _text(row["row_id"])
        for token in (canonical, _text(row.get("external_identifier"))):
            if token:
                owners[token].add(canonical)
    return {token: next(iter(ids)) for token, ids in owners.items() if len(ids) == 1}


def merge_mapping_batch(matrix, response, batch, entity_plan):
    """Merge one full-matrix response into its scheduled cells only.

    All target IDs must be acknowledged, even for all-empty rows. Duplicates,
    foreign identities and explicit parent/group conflicts cannot write cells.
    Conflicting later values never overwrite an earlier scientific value.
    """
    level = batch["target_level"]
    plan_rows = _rows(entity_plan)
    identities = _identity_index(plan_rows[level])
    parent_ids = _identity_index(plan_rows[_PARENT[level]])
    entities = {_text(row["row_id"]): row for row in plan_rows[level]}
    targets = set(batch["row_ids"])
    allowed = set(batch["field_names"])
    id_field, parent_field = _IDS[level], _IDS[_PARENT[level]]
    issues, candidates = [], defaultdict(list)
    block = response.get(level) if isinstance(response, Mapping) else None
    response_rows = block.get("rows") if isinstance(block, Mapping) else None
    if not isinstance(response_rows, list):
        return [f"Missing or invalid {level} batch rows: {sorted(targets)}"]
    for other, other_block in response.items():
        if other != level and isinstance(other_block, Mapping) and other_block.get("rows"):
            issues.append(f"Unrequested {other} rows ignored in {level} batch")
    for raw in response_rows:
        if not isinstance(raw, Mapping):
            issues.append(f"Invalid {level} batch row ignored")
            continue
        row, key_conflict = {}, False
        for key, value in raw.items():
            normalized = _key(key)
            if normalized in row and _text(row[normalized]) != _text(value):
                key_conflict = True
            row[normalized] = value
        if key_conflict:
            issues.append(f"Conflicting normalized keys in {level} batch row")
            identified = {
                identities.get(_text(value)) for key, value in raw.items()
                if _key(key) == id_field
            }
            for canonical in identified & targets:
                candidates[canonical].append(({}, False))
            continue
        # The prompt asks for the canonical row_id; a model may echo it under
        # "row_id" and fill the ISA identifier with a label of its own. A
        # string that names no planned record claims nothing; only a known,
        # different record is a conflict.
        by_id = identities.get(_text(row.get(id_field)))
        by_row = _text(row.get("row_id"))
        if by_row in identities and by_id not in (None, by_row):
            issues.append(f"Conflicting row_id and identifier in {level} batch row")
            continue
        canonical = by_row if by_row in targets else by_id
        if canonical not in targets:
            issues.append(f"Unknown, ambiguous or out-of-batch {level} identifier")
            continue
        entity = entities[canonical]
        parent = parent_ids.get(_text(row.get(parent_field)))
        group = _text(row.get("source_group"))
        valid = (not parent or parent == _text(entity.get("parent_row_id")))
        valid = valid and (not group or group == _text(entity.get("source_group")))
        if not valid:
            issues.append(f"Conflicting parent/group for {level}.{canonical}")
        candidates[canonical].append((row, valid))
    destinations = {_text(row.get(id_field)): row for row in matrix[level]["rows"]}
    for canonical in batch["row_ids"]:
        matches = candidates.get(canonical, [])
        if not matches:
            issues.append(f"Missing {level} target row {canonical}")
            continue
        if len(matches) != 1:
            issues.append(f"Duplicate {level} target row {canonical}; cells not merged")
            continue
        source, valid = matches[0]
        if not valid:
            continue
        for name, value in source.items():
            if name in {id_field, parent_field, "source_group", "row_id"}:
                continue
            if name not in allowed:
                issues.append(f"Unrequested field {level}.{name} ignored")
                continue
            if isinstance(value, (dict, list, tuple)):
                issues.append(f"Non-scalar cell {level}.{canonical}.{name} ignored")
                continue
            text = _text(value)
            previous = _text(destinations[canonical].get(name))
            if text and previous and text != previous:
                issues.append(f"Conflicting cell {level}.{canonical}.{name}; previous value retained")
            elif text:
                destinations[canonical][name] = text
    return list(dict.fromkeys(issues))
