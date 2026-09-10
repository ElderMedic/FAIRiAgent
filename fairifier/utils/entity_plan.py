"""Plan and project the five FAIR-DS ISOSA levels.

The plan fixes entity cardinality and parentage before values are mapped. It
does not introduce a sixth ``Person`` level: FAIR-DS contact fields repeat as
rows in the Investigation worksheet, as in the curated reference workbooks.
"""

from __future__ import annotations

import json
import re
from copy import deepcopy
from itertools import product
from typing import Any, Dict, Iterable, List, Mapping, Optional

from .isa_order import ISA_LEVEL_ORDER


_ID_FIELDS = {
    "investigation": "investigation identifier",
    "study": "study identifier",
    "observationunit": "observation unit identifier",
    "sample": "sample identifier",
    "assay": "assay identifier",
}
_NAME_FIELDS = {
    "investigation": "investigation title",
    "study": "study title",
    "observationunit": "observation unit name",
    "sample": "sample name",
    "assay": "assay name",
}
_DESCRIPTION_FIELDS = {
    "investigation": "investigation description",
    "study": "study description",
    "observationunit": "observation unit description",
    "sample": "sample description",
    "assay": "assay description",
}
_PARENT_FIELDS = {
    "study": "investigation identifier",
    "observationunit": "study identifier",
    "sample": "observation unit identifier",
    "assay": "sample identifier",
}


def source_measurement_unit_aliases(source_text: str) -> Dict[str, str]:
    """Return source-declared long-unit to symbol mappings.

    Only a single alphabetic unit word immediately followed by a shorter
    parenthetical symbol is accepted. Replacement is later restricted to cells
    consisting solely of a numeric quantity plus that unit, so ordinary prose
    abbreviations cannot rewrite metadata values.
    """
    aliases: Dict[str, str] = {}
    pattern = re.compile(
        r"\b([A-Za-z\u00b5\u03bc]{3,})\s*\(([A-Za-z\u00b5\u03bc]{1,8})\)"
    )
    for match in pattern.finditer(str(source_text or "")):
        long_unit, symbol = match.groups()
        if len(symbol) >= len(long_unit):
            continue
        aliases[long_unit.lower()] = symbol
        if long_unit.lower().endswith("s") and not long_unit.lower().endswith("ss"):
            aliases[long_unit[:-1].lower()] = symbol
    return aliases


def normalize_source_measurement_value(value: Any, source_text: str) -> Any:
    """Use a source-declared unit symbol for one standalone measurement."""
    if not isinstance(value, str):
        return value
    match = re.fullmatch(
        r"\s*([+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?)\s+"
        r"([A-Za-z\u00b5\u03bc]+)\s*",
        value,
    )
    if not match:
        return value
    magnitude, unit = match.groups()
    symbol = source_measurement_unit_aliases(source_text).get(unit.lower())
    return f"{magnitude} {symbol}" if symbol else value


def normalize_claim_measurement_units(
    claims: Dict[str, Any], source_text: str
) -> Dict[str, Any]:
    """Normalize explicit/known design quantities using source unit aliases."""
    for group in claims.get("design_groups") or []:
        if not isinstance(group, dict):
            continue
        for dimension in group.get("dimensions") or []:
            if not isinstance(dimension, dict):
                continue
            dimension["explicit_values"] = [
                normalize_source_measurement_value(value, source_text)
                for value in dimension.get("explicit_values") or []
            ]
            for known in dimension.get("known_values") or []:
                if isinstance(known, dict):
                    known["value"] = normalize_source_measurement_value(
                        known.get("value"), source_text
                    )
    return claims
_CONTACT_FIELDS = (
    "firstname",
    "lastname",
    "email address",
    "orcid",
    "organization",
    "department",
)
_RESERVED_DIMENSION_FIELDS = {
    *_ID_FIELDS.values(),
    *_NAME_FIELDS.values(),
    *_DESCRIPTION_FIELDS.values(),
    *_PARENT_FIELDS.values(),
    *_CONTACT_FIELDS,
}


def _norm(value: Any) -> str:
    return " ".join(str(value or "").strip().lower().split())


def _tokens(value: Any) -> set[str]:
    tokens: set[str] = set()
    for token in re.findall(r"[a-z0-9]+", _norm(value)):
        if token.isdigit():
            tokens.add(str(int(token)))
        elif len(token) > 1:
            tokens.add(token)
    return tokens


def _dedupe_similar_texts(values: Iterable[Any]) -> List[str]:
    """Deduplicate semantically equivalent review notes without fixed phrases."""
    kept: List[str] = []
    token_sets: List[set[str]] = []
    for value in values:
        text = str(value or "").strip()
        if not text:
            continue
        tokens = _tokens(text)
        duplicate = False
        for prior in token_sets:
            union = tokens | prior
            overlap = len(tokens & prior) / len(union) if union else 1.0
            if overlap >= 0.72:
                duplicate = True
                break
        if not duplicate:
            kept.append(text)
            token_sets.append(tokens)
    return kept


def _split_source_name(name: str) -> Dict[str, str]:
    """Split a source name conservatively without expanding initials."""
    exact = " ".join(str(name or "").strip().split())
    parts = exact.replace(",", " ").split()
    if not parts:
        return {"source_name": exact, "firstname": "", "lastname": ""}
    trailing = re.sub(r"[^A-Za-z]", "", parts[-1])
    family_first = len(parts) > 1 and 0 < len(trailing) <= 4 and trailing.isupper()
    if family_first:
        lastname, firstname = parts[0], " ".join(parts[1:])
    else:
        firstname, lastname = " ".join(parts[:-1]), parts[-1]
    return {
        "source_name": exact,
        "firstname": firstname,
        "lastname": lastname,
        "email address": "",
        "orcid": "",
        "organization": "",
        "department": "",
    }


def _clean_declared_author_text(value: str) -> str:
    """Remove citation/affiliation markup without altering author name tokens."""
    cleaned = re.sub(r"\$?\^\{[^}]*\}\$?", " ", str(value or ""))
    cleaned = re.sub(r"\$?\{\}\$?", " ", cleaned)
    cleaned = re.sub(r"[¹²³⁴⁵⁶⁷⁸⁹⁰*†‡]+", " ", cleaned)
    return " ".join(cleaned.split()).strip(" ,;")


def enrich_contacts_from_source_text(
    contacts: Iterable[Mapping[str, Any]], text: str
) -> List[Dict[str, str]]:
    """Attach only source-explicit contact details to identified people.

    E-mail addresses are assigned when a corresponding-author line names the
    person or when the address local part uniquely matches their first and last
    name. A single explicit institutional affiliation may be shared by all
    declared authors; competing affiliations are left unresolved.
    """
    enriched = [
        {
            field: str(contact.get(field) or "").strip()
            for field in ("source_name", *_CONTACT_FIELDS)
        }
        for contact in contacts
        if isinstance(contact, Mapping)
        and (contact.get("firstname") or contact.get("lastname"))
    ]
    source = str(text or "")
    emails = list(
        dict.fromkeys(
            re.findall(
                r"(?<![A-Za-z0-9._%+-])([A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,})(?![A-Za-z0-9._%+-])",
                source,
            )
        )
    )
    for email in emails:
        location = source.lower().find(email.lower())
        context = source[max(0, location - 180) : location + len(email) + 80]
        context_norm = _norm(_clean_declared_author_text(context))
        local_tokens = set(re.findall(r"[a-z]+", email.split("@", 1)[0].lower()))
        scores: List[tuple[int, int]] = []
        for index, contact in enumerate(enriched):
            first = _norm(contact.get("firstname"))
            last = _norm(contact.get("lastname"))
            full = _norm(f"{first} {last}")
            name_tokens = set(re.findall(r"[a-z]+", full))
            score = 0
            if full and full in context_norm:
                score += 10
            if last and last in context_norm:
                score += 3
            if last and last in local_tokens:
                score += 4
            if first and set(first.split()) & local_tokens:
                score += 2
            score += len(name_tokens & local_tokens)
            scores.append((score, index))
        ranked = sorted(scores, reverse=True)
        if ranked and ranked[0][0] > 0 and (
            len(ranked) == 1 or ranked[0][0] > ranked[1][0]
        ):
            enriched[ranked[0][1]]["email address"] = email

    affiliation_match = re.search(
        r"Affiliations?\s*:\s*(.+?)(?=\n\s*(?:Corresponding\s+author|Authors?|#)|\Z)",
        source,
        flags=re.IGNORECASE | re.DOTALL,
    )
    if affiliation_match:
        affiliation_text = _clean_declared_author_text(affiliation_match.group(1))
        candidates = [
            item.strip(" .;")
            for item in re.split(r"\s*;\s*", affiliation_text)
            if re.search(
                r"\b(?:academy|centre|center|college|department|hospital|institute|laborator(?:y|ies)|school|university)\b",
                item,
                flags=re.IGNORECASE,
            )
        ]
        unique_candidates = list(dict.fromkeys(candidates))
        if len(unique_candidates) == 1:
            for contact in enriched:
                if not contact.get("organization"):
                    contact["organization"] = unique_candidates[0]
    return enriched


def contacts_from_source_text(
    text: str, *, fallback_names: Optional[Iterable[Any]] = None
) -> List[Dict[str, str]]:
    """Return source-exact investigation contacts in declared order.

    GEO-style contributor lines commonly use ``Family INITIALS``. When a
    citation in the same supplied source contains longer initials for the same
    family name, those exact initials are preferred. Full names are never
    inferred or looked up externally.
    """
    match = re.search(
        r"^(?:Contributor\(s\)|Contributors?|Authors?)\s*(?:\t|:)\s*(.+)$",
        str(text or ""),
        flags=re.IGNORECASE | re.MULTILINE,
    )
    contacts = contacts_from_names(fallback_names or [])
    identities_from_fallback = bool(contacts)
    if not contacts and match:
        declared = _clean_declared_author_text(match.group(1))
        names = re.split(r"\s*[,;]\s*|\s+and\s+", declared, flags=re.IGNORECASE)
        contacts = [_split_source_name(name) for name in names if name.strip()]
    if not contacts:
        return []

    for contact in contacts:
        if identities_from_fallback:
            continue
        family = contact.get("lastname", "")
        if not family:
            continue
        candidates = re.findall(
            rf"(?<![A-Za-z]){re.escape(family)}\s+([A-Z]{{1,4}})(?![A-Za-z])",
            str(text or ""),
        )
        if candidates:
            contact["firstname"] = max(candidates, key=len)
    return enrich_contacts_from_source_text(contacts, text)


def contacts_from_names(names: Iterable[Any]) -> List[Dict[str, str]]:
    """Conservatively normalize already-extracted source author strings."""
    contacts: List[Dict[str, str]] = []
    seen: set[tuple[str, str]] = set()
    for name in names:
        contact = _split_source_name(str(name or ""))
        key = (_norm(contact.get("firstname")), _norm(contact.get("lastname")))
        if not any(key) or key in seen:
            continue
        contacts.append(contact)
        seen.add(key)
    return contacts


def normalize_entity_plan(
    plan: Mapping[str, Any],
    *,
    investigation_contacts: Optional[Iterable[Mapping[str, Any]]] = None,
) -> Dict[str, Any]:
    """Normalize a materialized plan without altering entity cardinality."""
    result = deepcopy(dict(plan or {}))
    levels_out: List[Dict[str, Any]] = []
    seen_levels: set[str] = set()
    for raw_level in result.get("levels") or []:
        if not isinstance(raw_level, Mapping):
            continue
        level = _norm(raw_level.get("level")).replace(" ", "")
        if level not in ISA_LEVEL_ORDER or level in seen_levels:
            continue
        entities: List[Dict[str, Any]] = []
        for index, raw_entity in enumerate(raw_level.get("entities") or [], start=1):
            if not isinstance(raw_entity, Mapping):
                continue
            entity = dict(raw_entity)
            entity["row_id"] = str(
                entity.get("row_id") or f"{level}_{index:03d}"
            ).strip()
            entity["label"] = str(entity.get("label") or entity["row_id"]).strip()
            entity["parent_row_id"] = (
                str(entity.get("parent_row_id") or "").strip() or None
            )
            entity["external_identifier"] = (
                str(entity.get("external_identifier") or "").strip() or None
            )
            entity["source_group"] = str(
                entity.get("source_group") or "unspecified"
            ).strip()
            entity["attributes"] = [
                dict(attribute)
                for attribute in (entity.get("attributes") or [])
                if isinstance(attribute, Mapping)
            ]
            entities.append(entity)
        try:
            cardinality = int(raw_level.get("cardinality"))
        except (TypeError, ValueError):
            cardinality = len(entities)
        levels_out.append(
            {
                "level": level,
                "cardinality": cardinality,
                "entities": entities,
                "evidence": [str(item) for item in raw_level.get("evidence") or []],
                "unresolved_ambiguities": [
                    str(item)
                    for item in raw_level.get("unresolved_ambiguities") or []
                ],
            }
        )
        seen_levels.add(level)
    result["levels"] = levels_out
    contacts = investigation_contacts
    if contacts is None:
        contacts = result.get("investigation_contacts") or []
    result["investigation_contacts"] = [
        {
            field: str(contact.get(field) or "").strip()
            for field in ("source_name", *_CONTACT_FIELDS)
        }
        for contact in contacts
        if isinstance(contact, Mapping)
        and (contact.get("firstname") or contact.get("lastname"))
    ]
    result.pop("persons", None)
    result.setdefault("design_summary", [])
    result.setdefault("unresolved_ambiguities", [])
    result.setdefault("confidence", 0.0)
    return result


def materialize_entity_spec(spec: Mapping[str, Any]) -> Dict[str, Any]:
    """Expand compact factorial design claims into the five ISOSA levels."""
    errors: List[str] = []
    levels: Dict[str, Dict[str, Any]] = {
        level: {
            "level": level,
            "cardinality": 0,
            "entities": [],
            "evidence": [],
            "unresolved_ambiguities": [],
        }
        for level in ISA_LEVEL_ORDER
    }

    investigation_ids = [
        str(root.get("row_id") or "").strip()
        for root in spec.get("investigations") or []
        if isinstance(root, Mapping) and str(root.get("row_id") or "").strip()
    ]
    for level, key in (("investigation", "investigations"), ("study", "studies")):
        for root in spec.get(key) or []:
            if not isinstance(root, Mapping):
                continue
            parent = str(root.get("parent_row_id") or "").strip() or None
            if level == "study" and parent is None and len(investigation_ids) == 1:
                parent = investigation_ids[0]
            levels[level]["entities"].append(
                {
                    "row_id": str(root.get("row_id") or "").strip(),
                    "label": str(root.get("label") or root.get("row_id") or "").strip(),
                    "parent_row_id": parent,
                    "external_identifier": (
                        str(root.get("external_identifier") or "").strip() or None
                    ),
                    "source_group": "root",
                    "attributes": [],
                }
            )
            evidence = str(root.get("evidence") or "").strip()
            if evidence and evidence not in levels[level]["evidence"]:
                levels[level]["evidence"].append(evidence)

    for group in spec.get("design_groups") or []:
        if not isinstance(group, Mapping):
            continue
        group_id = str(group.get("group_id") or "design_group").strip()
        study_row_id = str(group.get("study_row_id") or "").strip()
        evidence = str(group.get("evidence") or "").strip()
        dimensions = {
            str(dimension.get("name") or "").strip(): dimension
            for dimension in group.get("dimensions") or []
            if isinstance(dimension, Mapping)
            and str(dimension.get("name") or "").strip()
        }
        expansions = {
            str(expansion.get("level") or "").strip().lower(): expansion
            for expansion in group.get("expansions") or []
            if isinstance(expansion, Mapping)
        }
        materialized: Dict[str, List[Dict[str, Any]]] = {}

        for level in ("observationunit", "sample", "assay"):
            expansion = expansions.get(level)
            if not expansion:
                errors.append(f"Design group {group_id} is missing {level} expansion.")
                continue
            names = [str(name).strip() for name in expansion.get("dimension_names") or []]
            unknown = [name for name in names if name not in dimensions]
            if unknown:
                errors.append(
                    f"Design group {group_id} {level} uses unknown dimensions: {unknown}"
                )
                continue
            factor_levels: List[List[Mapping[str, Any]]] = []
            for name in names:
                values = [
                    value
                    for value in dimensions[name].get("levels") or []
                    if isinstance(value, Mapping)
                    and str(value.get("value") or "").strip()
                ]
                if not values:
                    errors.append(f"Design dimension {group_id}.{name} has no levels.")
                factor_levels.append(values)
            combinations = list(product(*factor_levels)) if factor_levels else [tuple()]
            level_entities: List[Dict[str, Any]] = []
            for index, combination in enumerate(combinations, start=1):
                combo = {name: dict(value) for name, value in zip(names, combination)}
                if level == "observationunit":
                    parent_row_id: Optional[str] = study_row_id
                else:
                    parent_level = "observationunit" if level == "sample" else "sample"
                    parents = []
                    for parent in materialized.get(parent_level, []):
                        parent_combo = parent["_combination"]
                        # A parent may carry attributes that legitimately stop
                        # at its ISA level. Join on dimensions shared by the
                        # two levels; the cardinality check below still fails
                        # closed when those keys do not identify one parent.
                        shared_names = set(combo).intersection(parent_combo)
                        if all(
                            str(combo[name].get("value"))
                            == str(parent_value.get("value"))
                            for name, parent_value in parent_combo.items()
                            if name in shared_names
                        ):
                            parents.append(parent)
                    if len(parents) != 1:
                        errors.append(
                            f"Design group {group_id} {level} row {index} matches "
                            f"{len(parents)} {parent_level} parents."
                        )
                    parent_row_id = parents[0]["row_id"] if parents else None

                attributes = []
                for name, factor_level in combo.items():
                    factor_origin = str(
                        factor_level.get("origin") or "explicit"
                    ).strip().lower()
                    by_level = dimensions[name].get("field_names_by_level")
                    if isinstance(by_level, Mapping):
                        field_name = str(by_level.get(level) or "").strip()
                    else:
                        # Legacy materialized specs predate level-specific term
                        # mappings. Preserve their behavior when no catalog was
                        # available to validate the mapping.
                        field_name = str(
                            dimensions[name].get("field_name") or ""
                        ).strip()
                    if factor_origin != "explicit":
                        field_name = ""
                    attributes.append(
                        {
                            "dimension_name": name,
                            "field_name": field_name or None,
                            "value": str(factor_level.get("value") or ""),
                            "origin": factor_origin,
                        }
                    )
                suffix = " | ".join(
                    str(value.get("value") or "") for value in combination
                )
                prefix = str(expansion.get("label_prefix") or group_id).strip()
                entity = {
                    "row_id": f"{group_id}_{level}_{index:03d}",
                    "label": f"{prefix}: {suffix}" if suffix else prefix,
                    "parent_row_id": parent_row_id,
                    "external_identifier": None,
                    "source_group": group_id,
                    "attributes": attributes,
                    "_combination": combo,
                }
                level_entities.append(entity)
                levels[level]["entities"].append(
                    {key: value for key, value in entity.items() if key != "_combination"}
                )
            materialized[level] = level_entities
            if evidence and evidence not in levels[level]["evidence"]:
                levels[level]["evidence"].append(evidence)
            levels[level]["unresolved_ambiguities"].extend(
                str(item) for item in group.get("unresolved_ambiguities") or []
            )

    for level in ISA_LEVEL_ORDER:
        levels[level]["cardinality"] = len(levels[level]["entities"])
        levels[level]["unresolved_ambiguities"] = list(
            dict.fromkeys(levels[level]["unresolved_ambiguities"])
        )
    group_counts: List[Dict[str, Any]] = []
    for group in spec.get("design_groups") or []:
        if not isinstance(group, Mapping):
            continue
        group_id = str(group.get("group_id") or "design_group").strip()
        group_counts.append(
            {
                "group_id": group_id,
                "row_counts": {
                    level: sum(
                        1
                        for entity in levels[level]["entities"]
                        if entity.get("source_group") == group_id
                    )
                    for level in ("observationunit", "sample", "assay")
                },
            }
        )
    return {
        "levels": [levels[level] for level in ISA_LEVEL_ORDER],
        # Counts are derived from the materialized graph. Model-written prose is
        # retained only as an audit note and is never treated as authoritative.
        "design_summary": group_counts,
        "claimed_design_summary": list(spec.get("design_summary") or []),
        "unresolved_ambiguities": list(spec.get("unresolved_ambiguities") or []),
        "confidence": float(spec.get("confidence") or 0.0),
        "design_spec": deepcopy(dict(spec)),
        "materialization_errors": errors,
    }


def materialize_entity_claims(
    claims: Mapping[str, Any],
    *,
    field_catalog: Optional[Mapping[str, Iterable[Any]]] = None,
) -> Dict[str, Any]:
    """Convert LLM design claims to a factorial spec, then materialize rows."""
    spec: Dict[str, Any] = {
        "investigations": deepcopy(list(claims.get("investigations") or [])),
        "studies": deepcopy(list(claims.get("studies") or [])),
        "design_groups": [],
        "design_summary": deepcopy(list(claims.get("design_summary") or [])),
        "unresolved_ambiguities": deepcopy(
            list(claims.get("unresolved_ambiguities") or [])
        ),
        "confidence": float(claims.get("confidence") or 0.0),
    }
    claim_errors: List[str] = []
    allowed_levels = ("observationunit", "sample", "assay")
    for raw_group in claims.get("design_groups") or []:
        if not isinstance(raw_group, Mapping):
            continue
        group_id = str(raw_group.get("group_id") or "design_group").strip()
        group_label = str(raw_group.get("label") or "").strip()
        group_ambiguities = list(raw_group.get("unresolved_ambiguities") or [])
        dimensions = []
        applies_by_level = {level: [] for level in allowed_levels}
        for raw_dimension in raw_group.get("dimensions") or []:
            if not isinstance(raw_dimension, Mapping):
                continue
            name = str(raw_dimension.get("name") or "factor").strip()
            try:
                level_count = int(raw_dimension.get("level_count") or 0)
            except (TypeError, ValueError):
                level_count = 0
            values = [
                str(value).strip()
                for value in raw_dimension.get("explicit_values") or []
                if str(value).strip()
            ]
            known_values: Dict[int, str] = {}
            for item in raw_dimension.get("known_values") or []:
                if not isinstance(item, Mapping):
                    continue
                try:
                    position = int(item.get("position") or 0)
                except (TypeError, ValueError):
                    position = 0
                value = str(item.get("value") or "").strip()
                if not value:
                    continue
                if position < 1 or position > level_count:
                    claim_errors.append(
                        f"Design claim {group_id}.{name} has known value position "
                        f"{position} outside 1..{level_count}."
                    )
                    continue
                if position in known_values and _norm(known_values[position]) != _norm(value):
                    claim_errors.append(
                        f"Design claim {group_id}.{name} has conflicting known values "
                        f"at position {position}."
                    )
                    continue
                known_values[position] = value
            if level_count < 1:
                claim_errors.append(
                    f"Design claim {group_id}.{name} has invalid level_count {level_count}."
                )
                continue
            origin = str(raw_dimension.get("origin") or "derived").strip().lower()
            if values and len(values) > level_count:
                claim_errors.append(
                    f"Design claim {group_id}.{name} declares {level_count} levels "
                    f"but supplies {len(values)} values."
                )
                continue
            if values and len(values) < level_count:
                group_ambiguities.append(
                    f"{name} has {level_count} stated levels but only {len(values)} "
                    "partial labels; ordinal placeholders preserve the declared cardinality."
                )
                values = []
                origin = "derived"
            elif not values:
                # An unnamed level cannot be source-explicit even if the model
                # marked the dimension that way. Keep its count and make the
                # placeholder provenance honest.
                origin = "derived"
            has_explicit_values = bool(values) and origin == "explicit"
            has_any_explicit_values = has_explicit_values or bool(known_values)
            if level_count == 1 and not has_any_explicit_values:
                # A single unnamed, derived level neither changes cardinality
                # nor contributes a source value. Keep the uncertainty in the
                # plan, but do not repeat a synthetic "factor 01" token in
                # every entity name and description.
                group_ambiguities.append(
                    f"{name} has one unnamed derived level; it is retained as "
                    "an ambiguity but omitted from entity labels and attributes."
                )
                continue
            display_name = " ".join(
                part
                for part in re.split(r"[_\-\s]+", name)
                if part
            ) or "factor"
            if values:
                factor_levels = [
                    {"value": value, "origin": origin} for value in values
                ]
            else:
                factor_levels = [
                    {
                        "value": known_values.get(
                            index, f"{display_name} {index:02d}"
                        ),
                        "origin": "explicit" if index in known_values else "derived",
                    }
                    for index in range(1, level_count + 1)
                ]
            valid_fields_by_level = {
                level: {
                    _norm(field)
                    for field in (field_catalog or {}).get(level, [])
                    if _norm(field)
                }
                for level in allowed_levels
            }
            requested_mappings: Dict[str, str] = {}
            for mapping in raw_dimension.get("field_mappings") or []:
                if not isinstance(mapping, Mapping):
                    continue
                mapping_level = str(mapping.get("level") or "").strip().lower()
                mapping_field = str(mapping.get("field_name") or "").strip()
                if mapping_level in allowed_levels and mapping_field:
                    requested_mappings[mapping_level] = mapping_field

            legacy_field = str(raw_dimension.get("field_name") or "").strip()
            field_names_by_level: Dict[str, Optional[str]] = {}
            for level in allowed_levels:
                requested = requested_mappings.get(level)
                if not requested and legacy_field:
                    requested = legacy_field
                if not requested:
                    field_names_by_level[level] = None
                    continue
                catalog_fields = valid_fields_by_level[level]
                if (
                    has_any_explicit_values
                    and _norm(requested) not in _RESERVED_DIMENSION_FIELDS
                    and (
                        field_catalog is None
                        or _norm(requested) in catalog_fields
                    )
                ):
                    field_names_by_level[level] = requested
                else:
                    field_names_by_level[level] = None

            dimensions.append(
                {
                    "name": name,
                    "field_name": legacy_field or None,
                    "field_names_by_level": field_names_by_level,
                    "levels": factor_levels,
                }
            )
            for level in raw_dimension.get("applies_to") or []:
                normalized = str(level).strip().lower()
                if normalized in applies_by_level:
                    applies_by_level[normalized].append(name)
                else:
                    claim_errors.append(
                        f"Design claim {group_id}.{name} uses unknown ISA level {level}."
                    )
        if not group_label:
            group_label = " / ".join(
                dimension["name"] for dimension in dimensions
            ) or "design branch"
        spec["design_groups"].append(
            {
                "group_id": group_id,
                "label": group_label,
                "study_row_id": str(raw_group.get("study_row_id") or "").strip(),
                "evidence": str(raw_group.get("evidence") or "").strip(),
                "dimensions": dimensions,
                "expansions": [
                    {
                        "level": level,
                        "dimension_names": applies_by_level[level],
                        "label_prefix": (
                            f"{group_label} "
                            f"{'observation unit' if level == 'observationunit' else level}"
                        ),
                    }
                    for level in allowed_levels
                ],
                "unresolved_ambiguities": _dedupe_similar_texts(group_ambiguities),
            }
        )
    plan = materialize_entity_spec(spec)
    plan["design_claims"] = deepcopy(dict(claims))
    plan["materialization_errors"] = list(
        dict.fromkeys(claim_errors + list(plan.get("materialization_errors") or []))
    )
    return plan


def render_entity_plan_for_prompt(plan: Mapping[str, Any], max_chars: int = 14000) -> str:
    """Render the locked five-level plan for ISAValueMapper."""
    if not plan:
        return ""
    compact = {
        "levels": plan.get("levels") or [],
        "investigation_contacts": plan.get("investigation_contacts") or [],
        "unresolved_ambiguities": plan.get("unresolved_ambiguities") or [],
    }
    text = json.dumps(compact, indent=2, ensure_ascii=False)
    if len(text) > max_chars:
        text = text[:max_chars] + "\n... [entity plan truncated]"
    return (
        "AUTHORITATIVE FIVE-LEVEL ISOSA PLAN. Fill these rows and links. "
        "Investigation contacts repeat as Investigation rows; never create a Person level.\n"
        + text
    )


def _entity_tokens(entity: Mapping[str, Any]) -> set[str]:
    return _tokens(
        " ".join(
            str(attribute.get("value") or "")
            for attribute in entity.get("attributes") or []
            if isinstance(attribute, Mapping)
        )
    )


def _source_row_match(
    rows: List[Dict[str, Any]], entity: Mapping[str, Any]
) -> tuple[Dict[str, Any], int, bool]:
    """Return a row only when its entity match is positive and unambiguous."""
    if not rows:
        return {}, 0, False
    wanted = _entity_tokens(entity)
    scored: List[tuple[int, int, Dict[str, Any]]] = []
    for index, row in enumerate(rows):
        row_tokens = _tokens(" ".join(str(value) for value in row.values()))
        scored.append((len(wanted & row_tokens), index, row))
    scored.sort(key=lambda item: (-item[0], item[1]))
    best_score = scored[0][0]
    unique = best_score > 0 and sum(score == best_score for score, _, _ in scored) == 1
    return deepcopy(scored[0][2]), best_score, unique


def _safe_source_row(
    rows: List[Dict[str, Any]],
    entity: Mapping[str, Any],
    entities: List[Mapping[str, Any]],
    *,
    level: str,
    shared_columns: Optional[Iterable[str]] = None,
) -> Dict[str, Any]:
    """Copy only scope-safe source values into a materialized entity row.

    For a multi-entity level, prose-derived candidate rows have no reliable row
    scope. A value is therefore reusable only when it is present and identical
    in every candidate row, or when the plan carries a source-supplied external
    identifier that exactly selects one candidate row. Factor values are set
    separately from the locked plan. This prevents a group note or preparation
    statement from landing on one arbitrary entity after fuzzy token matching.
    """
    if not rows:
        return {}
    if len(entities) == 1:
        return deepcopy(rows[0])

    forbidden = {
        *_ID_FIELDS.values(),
        *_NAME_FIELDS.values(),
        *_DESCRIPTION_FIELDS.values(),
        *_PARENT_FIELDS.values(),
        *_CONTACT_FIELDS,
    }

    external_identifier = str(entity.get("external_identifier") or "").strip()
    exact_row: Optional[Dict[str, Any]] = None
    if external_identifier:
        id_field = _ID_FIELDS[level]
        exact_matches = [
            row
            for row in rows
            if _norm(row.get(id_field)) == _norm(external_identifier)
        ]
        if len(exact_matches) == 1:
            exact_row = exact_matches[0]
    if exact_row is None and len(rows) < 2:
        # A single collapsed source row cannot define sibling identity or
        # narrative, but confirmed non-identity properties may be common to all
        # rows (for example a single scientific name). Identity fields remain
        # forbidden and are compiled from the plan below.
        explicitly_shared = {
            str(column).strip().lower() for column in shared_columns or []
        }
        return {
            str(column).strip().lower(): value
            for column, value in rows[0].items()
            if str(column).strip().lower() not in forbidden
            and str(column).strip().lower() in explicitly_shared
            and str(value or "").strip()
        }

    safe: Dict[str, Any] = {}
    all_columns = list(
        dict.fromkeys(
            str(column).strip().lower()
            for row in rows
            for column in row
            if str(column).strip()
        )
    )
    for normalized_column in all_columns:
        if normalized_column in forbidden:
            continue
        if exact_row is not None:
            value = exact_row.get(normalized_column)
            if str(value or "").strip():
                safe[normalized_column] = value
            continue
        values = [row.get(normalized_column) for row in rows]
        if any(not str(value or "").strip() for value in values):
            continue
        normalized_values = {_norm(value) for value in values}
        if len(normalized_values) == 1:
            safe[normalized_column] = values[0]
    return safe


def _entity_description(
    entity: Mapping[str, Any],
    level: str,
    *,
    parent: Optional[Mapping[str, Any]] = None,
    parent_identifier: str = "",
) -> str:
    """Describe one ISA entity at its own level of the material graph.

    In particular, an assay description must not repeat all sample material
    characteristics.  It names its input sample and adds only dimensions that
    are new at the assay level (for example, a measurement or preparation
    branch introduced after sample collection).
    """
    parent_attributes = {
        (
            _norm(item.get("dimension_name")),
            _norm(item.get("value")),
        )
        for item in (parent or {}).get("attributes") or []
        if isinstance(item, Mapping) and str(item.get("value") or "").strip()
    }
    attribute_items = [
        item
        for item in entity.get("attributes") or []
        if isinstance(item, Mapping)
        and str(item.get("value") or "").strip()
        and (
            level != "assay"
            or (
                _norm(item.get("dimension_name")),
                _norm(item.get("value")),
            )
            not in parent_attributes
        )
    ]
    attributes = [
        f"{str(item.get('dimension_name') or 'factor').strip()}="
        f"{str(item.get('value') or '').strip()}"
        for item in attribute_items
    ]
    if level == "assay" and parent_identifier:
        description = f"Assay for sample {parent_identifier}"
        if attributes:
            description += "; assay-specific conditions: " + "; ".join(attributes)
        return description
    if attributes:
        display = "observation unit" if level == "observationunit" else level
        return f"{display.capitalize()} defined by " + "; ".join(attributes)
    return str(entity.get("label") or entity.get("row_id") or "").strip()


def _list_like_identifier(value: Any) -> bool:
    text = str(value or "")
    return any(separator in text for separator in (",", ";", "\n"))


def _contact_source_row(
    rows: List[Dict[str, Any]], contact: Mapping[str, Any]
) -> Dict[str, Any]:
    """Find a source row for this contact without mixing different people."""
    first = _norm(contact.get("firstname"))
    last = _norm(contact.get("lastname"))
    for row in rows:
        if _norm(row.get("firstname")) == first and _norm(row.get("lastname")) == last:
            return row
    return {}


def project_matrix_onto_entity_plan(
    matrix: Mapping[str, Any], plan: Mapping[str, Any]
) -> Dict[str, Dict[str, Any]]:
    """Project extracted FAIR-DS values onto fixed rows and parent links."""
    projected: Dict[str, Dict[str, Any]] = {
        key: deepcopy(value)
        for key, value in dict(matrix or {}).items()
        if key in ISA_LEVEL_ORDER and isinstance(value, Mapping)
    }
    level_plans = {
        str(item.get("level") or ""): item
        for item in plan.get("levels") or []
        if isinstance(item, Mapping)
    }
    entities_by_row_id = {
        str(entity.get("row_id") or "").strip(): entity
        for level_plan in level_plans.values()
        for entity in level_plan.get("entities") or []
        if isinstance(entity, Mapping) and str(entity.get("row_id") or "").strip()
    }
    resolved_ids: Dict[str, Dict[str, str]] = {}

    for level in ISA_LEVEL_ORDER:
        level_plan = level_plans.get(level)
        if not level_plan:
            continue
        source_block = projected.get(level) or {}
        source_rows = [
            dict(row)
            for row in source_block.get("rows") or []
            if isinstance(row, Mapping)
        ]
        shared_columns = source_block.get("_shared_columns") or []
        columns = list(
            dict.fromkeys(
                str(column).strip().lower()
                for column in source_block.get("columns") or []
                if str(column).strip()
            )
        )
        required_columns = [_ID_FIELDS[level], _DESCRIPTION_FIELDS[level]]
        name_field = _NAME_FIELDS.get(level)
        # Assay name is package-defined rather than part of the default core
        # sheet.  Treat it as the entity label when selected, but do not add a
        # column that the chosen FAIR-DS packages did not declare.
        if name_field and (level != "assay" or name_field in columns):
            required_columns.insert(1, name_field)
        if level in _PARENT_FIELDS:
            required_columns.append(_PARENT_FIELDS[level])
        for column in required_columns:
            if column not in columns:
                columns.append(column)

        plan_entities = [
            entity
            for entity in level_plan.get("entities") or []
            if isinstance(entity, Mapping)
        ]
        for entity in plan_entities:
            for attribute in entity.get("attributes") or []:
                if not isinstance(attribute, Mapping):
                    continue
                field_name = str(attribute.get("field_name") or "").strip().lower()
                if field_name and field_name not in columns:
                    columns.append(field_name)

        rows_out: List[Dict[str, Any]] = []
        id_map: Dict[str, str] = {}
        for entity in plan_entities:
            row = _safe_source_row(
                source_rows,
                entity,
                plan_entities,
                level=level,
                shared_columns=shared_columns,
            )
            row_id = str(entity.get("row_id") or "").strip()
            identifier = str(entity.get("external_identifier") or "").strip() or row_id
            row[_ID_FIELDS[level]] = identifier
            id_map[row_id] = identifier
            # Entity identity and row-specific narrative come from the locked
            # plan. Never broadcast a source example across sibling rows.
            if name_field and name_field in columns:
                row[name_field] = str(entity.get("label") or row_id)
            if len(plan_entities) > 1 or not str(
                row.get(_DESCRIPTION_FIELDS[level]) or ""
            ).strip():
                parent_row_id = str(entity.get("parent_row_id") or "").strip()
                parent_level = (
                    ISA_LEVEL_ORDER[ISA_LEVEL_ORDER.index(level) - 1]
                    if level in _PARENT_FIELDS
                    else ""
                )
                parent_identifier = resolved_ids.get(parent_level, {}).get(
                    parent_row_id, parent_row_id
                )
                row[_DESCRIPTION_FIELDS[level]] = _entity_description(
                    entity,
                    level,
                    parent=entities_by_row_id.get(parent_row_id),
                    parent_identifier=parent_identifier,
                )
            parent_field = _PARENT_FIELDS.get(level)
            if parent_field:
                parent_level = ISA_LEVEL_ORDER[ISA_LEVEL_ORDER.index(level) - 1]
                parent_row_id = str(entity.get("parent_row_id") or "").strip()
                row[parent_field] = resolved_ids.get(parent_level, {}).get(
                    parent_row_id, parent_row_id
                )
            for attribute in entity.get("attributes") or []:
                if not isinstance(attribute, Mapping):
                    continue
                field_name = str(attribute.get("field_name") or "").strip().lower()
                if field_name:
                    row[field_name] = str(attribute.get("value") or "")
            rows_out.append({column: row.get(column, "") for column in columns})
        resolved_ids[level] = id_map

        if level == "investigation":
            contacts = [
                contact
                for contact in plan.get("investigation_contacts") or []
                if isinstance(contact, Mapping)
            ]
            if contacts:
                for column in _CONTACT_FIELDS:
                    if column not in columns:
                        columns.append(column)
                repeated: List[Dict[str, Any]] = []
                for base_row in rows_out:
                    for contact in contacts:
                        row = dict(base_row)
                        matched = _contact_source_row(source_rows, contact)
                        row["firstname"] = str(contact.get("firstname") or "")
                        row["lastname"] = str(contact.get("lastname") or "")
                        for column in _CONTACT_FIELDS[2:]:
                            row[column] = str(
                                contact.get(column) or matched.get(column) or ""
                            )
                        repeated.append({column: row.get(column, "") for column in columns})
                rows_out = repeated
        projected[level] = {"columns": columns, "rows": rows_out}

    projected.pop("person", None)
    return projected


def validate_entity_matrix_against_plan(
    matrix: Mapping[str, Any],
    plan: Mapping[str, Any],
    *,
    expected_authors: Optional[Iterable[Any]] = None,
) -> Dict[str, Any]:
    """Validate cardinality, scalar identifiers, links, and contact rows."""
    del expected_authors
    errors: List[str] = []
    warnings: List[str] = []
    row_counts: Dict[str, int] = {}
    identifiers: Dict[str, set[str]] = {}
    semantic_metrics: Dict[str, Dict[str, Any]] = {}
    mapped_attribute_errors: List[str] = []
    if "person" in matrix:
        errors.append("Person is not a FAIR-DS ISOSA worksheet; contacts belong in Investigation.")

    level_plans = {
        str(item.get("level") or ""): item
        for item in plan.get("levels") or []
        if isinstance(item, Mapping)
    }
    plan_entities_by_row_id = {
        str(entity.get("row_id") or "").strip(): entity
        for level_plan in level_plans.values()
        for entity in level_plan.get("entities") or []
        if isinstance(entity, Mapping) and str(entity.get("row_id") or "").strip()
    }
    contacts = [
        contact
        for contact in plan.get("investigation_contacts") or []
        if isinstance(contact, Mapping)
    ]
    for level in ISA_LEVEL_ORDER:
        block = matrix.get(level) if isinstance(matrix.get(level), Mapping) else {}
        rows = [row for row in block.get("rows") or [] if isinstance(row, Mapping)]
        row_counts[level] = len(rows)
        plan_level = level_plans.get(level)
        declared = int(plan_level.get("cardinality") or 0) if plan_level else 0
        materialized = len(plan_level.get("entities") or []) if plan_level else 0
        if plan_level and declared != materialized:
            errors.append(
                f"Entity plan {level} cardinality {declared} != {materialized} rows."
            )
        expected_rows = declared
        if level == "investigation" and contacts:
            expected_rows = declared * len(contacts)
        if plan_level and len(rows) != expected_rows:
            errors.append(
                f"Matrix {level} row count {len(rows)} != expected {expected_rows}."
            )

        id_field = _ID_FIELDS[level]
        ids = [str(row.get(id_field) or "").strip() for row in rows]
        if any(not value for value in ids):
            errors.append(f"One or more {level} rows have no scalar {id_field}.")
        if any(_list_like_identifier(value) for value in ids):
            errors.append(f"{level} contains a list-like identifier cell.")
        unique_ids = {value for value in ids if value}
        if level == "investigation":
            if plan_level and len(unique_ids) != declared:
                errors.append("Investigation identifiers do not match planned investigations.")
        elif len(unique_ids) != len(ids):
            errors.append(f"{level} identifiers are not unique.")
        identifiers[level] = unique_ids

        entities = [
            entity
            for entity in (plan_level.get("entities") or [] if plan_level else [])
            if isinstance(entity, Mapping)
        ]
        rows_by_id: Dict[str, List[Mapping[str, Any]]] = {}
        for row in rows:
            rows_by_id.setdefault(str(row.get(id_field) or "").strip(), []).append(row)
        signatures: List[tuple[tuple[str, str], ...]] = []
        identity_fields = {
            id_field,
            _NAME_FIELDS.get(level, ""),
            _DESCRIPTION_FIELDS[level],
            _PARENT_FIELDS.get(level, ""),
            *_CONTACT_FIELDS,
        }
        for entity in entities:
            row_id = str(entity.get("row_id") or "").strip()
            expected_id = str(entity.get("external_identifier") or "").strip() or row_id
            candidates = rows_by_id.get(expected_id) or []
            if level == "investigation" and contacts:
                candidate = candidates[0] if candidates else None
            else:
                candidate = candidates[0] if len(candidates) == 1 else None
            if not candidate:
                continue
            expected_label = str(entity.get("label") or row_id).strip()
            candidate_columns = {
                str(column).strip().lower() for column in block.get("columns") or []
            }
            configured_name = _NAME_FIELDS.get(level)
            label_field = (
                configured_name
                if configured_name and configured_name in candidate_columns
                else _DESCRIPTION_FIELDS[level]
            )
            mapped_name_values = {
                _norm(attribute.get("value"))
                for attribute in entity.get("attributes") or []
                if isinstance(attribute, Mapping)
                and configured_name
                and _norm(attribute.get("field_name")) == _norm(configured_name)
                and _norm(attribute.get("value"))
            }
            actual_label = str(candidate.get(label_field) or "").strip()
            if (
                configured_name is not None
                and configured_name in candidate_columns
                and actual_label != expected_label
                and _norm(actual_label) not in mapped_name_values
            ):
                errors.append(
                    f"{level} row {expected_id} name does not match planned entity label."
                )
            elif not actual_label:
                errors.append(f"{level} row {expected_id} has no entity description.")
            parent = plan_entities_by_row_id.get(
                str(entity.get("parent_row_id") or "").strip()
            )
            inherited_attributes = {
                (
                    _norm(item.get("dimension_name")),
                    _norm(item.get("value")),
                )
                for item in (parent or {}).get("attributes") or []
                if isinstance(item, Mapping)
            }
            for attribute in entity.get("attributes") or []:
                if not isinstance(attribute, Mapping):
                    continue
                field_name = str(attribute.get("field_name") or "").strip().lower()
                expected_value = str(attribute.get("value") or "").strip()
                if field_name and str(candidate.get(field_name) or "").strip() != expected_value:
                    mapped_attribute_errors.append(
                        f"{level} row {expected_id} does not preserve mapped dimension "
                        f"{field_name}={expected_value!r}."
                    )
                inherited = (
                    _norm(attribute.get("dimension_name")),
                    _norm(expected_value),
                ) in inherited_attributes
                presentation_text = " ".join(
                    str(candidate.get(field) or "")
                    for field in {
                        label_field,
                        _DESCRIPTION_FIELDS[level],
                    }
                )
                if (
                    not field_name
                    and expected_value
                    and not inherited
                    and _norm(expected_value) not in _norm(presentation_text)
                ):
                    errors.append(
                        f"{level} row {expected_id} name/description omits unmapped design dimension "
                        f"{expected_value!r}."
                    )
            signatures.append(
                tuple(
                    sorted(
                        (str(key).strip().lower(), _norm(value))
                        for key, value in candidate.items()
                        if str(key).strip().lower() not in identity_fields
                        and _norm(value) not in {"", "not specified", "unknown", "n/a"}
                    )
                )
            )
        if mapped_attribute_errors:
            errors.extend(mapped_attribute_errors)
        duplicate_count = len(signatures) - len(set(signatures))
        semantic_metrics[level] = {
            "entity_count": len(entities),
            "unique_identity_stripped_signatures": len(set(signatures)),
            "duplicate_identity_stripped_rows": max(duplicate_count, 0),
        }

        parent_field = _PARENT_FIELDS.get(level)
        if parent_field:
            parent_level = ISA_LEVEL_ORDER[ISA_LEVEL_ORDER.index(level) - 1]
            for row in rows:
                parent_id = str(row.get(parent_field) or "").strip()
                if not parent_id:
                    errors.append(f"{level} row is missing {parent_field}.")
                elif parent_id not in identifiers.get(parent_level, set()):
                    errors.append(
                        f"{level} row references unknown {parent_field}: {parent_id}"
                    )

    if contacts:
        rows = [
            row
            for row in ((matrix.get("investigation") or {}).get("rows") or [])
            if isinstance(row, Mapping)
        ]
        actual = {
            (_norm(row.get("firstname")), _norm(row.get("lastname"))) for row in rows
        }
        expected = {
            (_norm(contact.get("firstname")), _norm(contact.get("lastname")))
            for contact in contacts
        }
        if actual != expected:
            errors.append("Investigation contact rows do not match source contributors.")

    ambiguities = list(plan.get("unresolved_ambiguities") or [])
    for level_plan in level_plans.values():
        ambiguities.extend(level_plan.get("unresolved_ambiguities") or [])
    warnings.extend(_dedupe_similar_texts(ambiguities))
    return {
        "passed": not errors,
        "submission_ready": not errors and not warnings,
        "errors": list(dict.fromkeys(errors)),
        "warnings": _dedupe_similar_texts(warnings),
        "row_counts": row_counts,
        "investigation_contact_count": len(contacts),
        "mapped_attribute_errors": list(dict.fromkeys(mapped_attribute_errors)),
        "semantic_metrics": semantic_metrics,
    }


__all__ = [
    "contacts_from_source_text",
    "enrich_contacts_from_source_text",
    "materialize_entity_claims",
    "materialize_entity_spec",
    "normalize_entity_plan",
    "project_matrix_onto_entity_plan",
    "render_entity_plan_for_prompt",
    "validate_entity_matrix_against_plan",
]
