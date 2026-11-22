"""Plan and project the five FAIR-DS ISOSA levels.

The plan fixes entity cardinality and parentage before values are mapped. It
does not introduce a sixth ``Person`` level: FAIR-DS contact fields repeat as
rows in the Investigation worksheet, as in the curated reference workbooks.
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
from copy import deepcopy
from itertools import product
from typing import Any, Dict, Iterable, List, Mapping, Optional

from .isa_order import ISA_LEVEL_ORDER
from .document_text import normalize_source_evidence_text


logger = logging.getLogger(__name__)


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
        unresolved_count_dimensions: List[str] = []
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
            origin = str(raw_dimension.get("origin") or "derived").strip().lower()
            if (
                raw_dimension.get("level_count") is None
                and values
                and origin == "explicit"
            ):
                # explicit_values is the complete source enumeration; partial
                # observations belong in known_values and cannot establish N.
                level_count = len(values)
            reported_range = str(raw_dimension.get("reported_range") or "").strip()
            if level_count < 1 and reported_range:
                # The individual levels are unknown but the source states the
                # span. Record the span as one explicit value: it maps to the
                # factor's field without inventing levels or rows.
                group_ambiguities.append(
                    f"{name}: levels not enumerated in the source; recorded as the "
                    f"stated span '{reported_range}' and not expanded into rows."
                )
                level_count = 1
                values = [reported_range]
                origin = "explicit"
                raw_dimension = {**raw_dimension, "known_values": []}
            if level_count < 1:
                # The source does not state how many levels this factor has.
                # Do not expand it (that would invent rows), and do not drop
                # the group (that would drop its reported results). Keep the
                # group with its resolved factors and record the factor as a
                # group-level note, as for a single unnamed level below.
                unresolved_count_dimensions.append(name)
                group_ambiguities.append(
                    f"{name}: number of levels not stated in the source; kept as a "
                    "group note and not expanded into rows."
                )
                continue
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
            if values and len(values) > level_count:
                if origin == "explicit" and len(set(values)) == len(values):
                    # The enumerated source values are the evidence; the
                    # declared count is the model's own tally. Keep the
                    # values (dropping the whole factor for an off-by-one
                    # count would lose every listed material) and note it.
                    group_ambiguities.append(
                        f"{name}: declared {level_count} levels but listed "
                        f"{len(values)} distinct source values; the listed values were used."
                    )
                    level_count = len(values)
                else:
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
        # A field holds one value per row. When two factors of a group claim
        # the same field at one level, the first keeps it and the others stay
        # descriptive attributes; otherwise each write erases the other and no
        # repair can satisfy both mappings.
        claimed_fields: Dict[str, set] = {}
        for dimension in dimensions:
            for level, field in dimension["field_names_by_level"].items():
                if not field:
                    continue
                if _norm(field) in claimed_fields.setdefault(level, set()):
                    dimension["field_names_by_level"][level] = None
                else:
                    claimed_fields[level].add(_norm(field))
        # ISA is a tree: every child row has exactly one parent, so a factor
        # that distinguishes parents also distinguishes their descendants.
        # Without this, 21 enzyme x substrate observation units shared one
        # sample and one assay, leaving no row for each kinetic result.
        for depth, level in enumerate(allowed_levels):
            for name in list(applies_by_level[level]):
                for deeper in allowed_levels[depth + 1:]:
                    if name not in applies_by_level[deeper]:
                        applies_by_level[deeper].append(name)
        if unresolved_count_dimensions:
            spec["unresolved_ambiguities"].append(
                f"Design group {group_id}: level count not stated for "
                f"{', '.join(unresolved_count_dimensions)}; these factors are not "
                "expanded into rows."
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


def _reported_quote_in_source(quote: str, source: str) -> bool:
    """Accept a source passage or complete HTML table row, never a bare token."""
    table_row = bool(
        re.fullmatch(r"<tr(?:\s[^>]*)?>.*</tr>", quote, re.I | re.S)
        and len(re.findall(r"<(?:td|th)\b", quote, re.I)) >= 2
    )
    return bool(quote and quote in source and (len(quote.split()) >= 3 or table_row))


def text_names(text: str, name: str) -> bool:
    """``name`` occurs word-bounded in ``text``, ignoring letter case.

    Case is typography for a material name: "Amorphous PET powder" opening a
    label is the "amorphous PET powder" of the source sentence.
    """
    return bool(name and re.search(r"(?<!\w)" + re.escape(name) + r"(?!\w)", text, re.I))


def _source_window_naming(source: str, names: List[str], max_chars: int = 600) -> str:
    """Shortest sentence-bounded source passage that names every ``names``."""
    names = [name for name in dict.fromkeys(names) if name]
    if not names or not source:
        return ""
    first = names[0]
    for match in re.finditer(r"(?<!\w)" + re.escape(first) + r"(?!\w)", source, re.I):
        begin = max(0, match.start() - max_chars // 2)
        end = min(len(source), match.end() + max_chars // 2)
        # Snap to sentence/row boundaries inside the window when possible.
        left = max(source.rfind(". ", begin, match.start()), source.rfind("|", begin, match.start()))
        right_candidates = [i for i in (source.find(". ", match.end(), end), source.find("|", match.end(), end)) if i != -1]
        start = left + 1 if left != -1 else begin
        stop = (min(right_candidates) + 1) if right_candidates else end
        window = source[start:stop].strip()
        if len(window.split()) >= 3 and all(text_names(window, name) for name in names):
            return window
        wide = source[begin:end].strip()
        if all(text_names(wide, name) for name in names):
            return wide
    return ""


def repair_reported_material_quotes(
    records: Iterable[Mapping[str, Any]], *, source_text: str,
) -> List[Dict[str, Any]]:
    """Replace a paraphrased material quote with a real source passage.

    A material identity is grounded by its name occurring verbatim in the
    source. Models often paraphrase the supporting quote (e.g. summarising a
    supplementary table), which used to drop the material entirely. When the
    proposed quote is not in the source, or does not name the subject, but the
    subject is in the source, substitute the
    nearest sentence-bounded passage that names the subject (and, for a
    Sample, its parent ObservationUnit subject). Never invents text; records
    whose subject is absent from the source are returned unchanged and fail
    validation as before.
    """
    source = normalize_source_evidence_text(source_text)
    repaired: List[Dict[str, Any]] = []
    subjects = {
        str(record.get("record_id") or ""): normalize_source_evidence_text(record.get("source_subject"))
        for record in records
    }
    for record in records:
        item = dict(record)
        quote = normalize_source_evidence_text(item.get("source_quote"))
        subject = normalize_source_evidence_text(item.get("source_subject"))
        if subject and not (_reported_quote_in_source(quote, source) and text_names(quote, subject)):
            names = [subject]
            parent_subject = subjects.get(str(item.get("parent_row_id") or ""), "")
            if item.get("level") == "sample" and parent_subject:
                names.append(parent_subject)
            window = _source_window_naming(source, names)
            if window:
                item["source_quote"] = window
                item["source_quote_repaired"] = True
        repaired.append(item)
    return repaired


def materialize_reported_materials(
    plan: Mapping[str, Any], records: Iterable[Mapping[str, Any]], *, source_text: str,
) -> Dict[str, Any]:
    """Build cited material identities without asserting a physical-run census.

    This performs structural/source checks only. Independent semantic review
    must establish whether the proposed ObservationUnit and Sample roles fit
    the selected schema and the actual material/preparation evidence.
    """
    result = deepcopy(dict(plan))
    levels = {item["level"]: item for item in result.get("levels") or []}
    entities = {level: {row["row_id"]: row for row in block.get("entities") or []}
                for level, block in levels.items()}
    occupied = {key for rows in entities.values() for key in rows}
    source = normalize_source_evidence_text(source_text)
    errors = []
    order = {"observationunit": 0, "sample": 1}
    for record in sorted(records, key=lambda item: order.get(item.get("level"), 2)):
        level = record.get("level")
        key = str(record.get("record_id") or "").strip()
        parent_id = str(record.get("parent_row_id") or "").strip()
        parent_level = {"observationunit": "study", "sample": "observationunit"}.get(level)
        parent = entities.get(parent_level, {}).get(parent_id)
        subject = str(record.get("source_subject") or "").strip()
        quote = normalize_source_evidence_text(record.get("source_quote"))
        kind = {"observationunit": "material_preparation", "sample": "material_identity"}.get(level)
        def names_subject(value: str) -> bool:
            return text_names(quote, normalize_source_evidence_text(value))
        reasons = []
        if not key or key in occupied:
            reasons.append("record_id must be nonblank and unique")
        if level not in order:
            reasons.append("level must be observationunit or sample")
        if record.get("record_kind") != kind:
            reasons.append(f"record_kind for {level} must be {kind}")
        if parent is None:
            reasons.append(f"parent_row_id must identify an existing {parent_level} record")
        if not _reported_quote_in_source(quote, source):
            reasons.append("source_quote must be a contiguous passage or complete HTML row from the source")
        if not names_subject(subject):
            reasons.append("source_subject must occur verbatim in source_quote; put descriptive wording in label")
        if level == "sample" and parent is not None and not names_subject(str(parent.get("source_subject") or "")):
            reasons.append("source_quote must also name the parent ObservationUnit source_subject")
        if reasons:
            errors.append(f"Reported material {key or '(blank)'}: " + "; ".join(reasons) + ".")
            continue
        occupied.add(key)
        entity = {
            "row_id": key, "parent_row_id": parent_id,
            "label": str(record.get("label") or subject), "external_identifier": None,
            "source_group": str(record.get("source_group") or "reported_materials"),
            "record_kind": kind, "source_subject": subject, "source_quote": quote,
            "attributes": [{"dimension_name": "source material", "field_name": None,
                            "value": subject, "origin": "explicit"}],
        }
        if level not in levels:
            levels[level] = {"level": level, "entities": [], "evidence": [], "unresolved_ambiguities": []}
            result.setdefault("levels", []).append(levels[level])
        entities.setdefault(level, {})[key] = entity
        levels[level]["entities"].append(entity)
        levels[level]["cardinality"] = len(levels[level]["entities"])
    if errors:
        result = deepcopy(dict(plan))
        result.setdefault("materialization_errors", []).extend(errors)
    return result


def reported_parent_binding_digest(
    record: Mapping[str, Any], parent: Mapping[str, Any], source_text: str,
) -> str:
    """Bind a semantic parent-review handoff to the exact proposal and source."""
    payload = json.dumps([record, parent, source_text], sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(payload.encode()).hexdigest()


_HTML_ROW_RE = re.compile(r"<tr(?:\s[^>]*)?>.*?</tr>", re.I | re.S)
_HTML_TABLE_RE = re.compile(r"<table\b.*?</table>", re.I | re.S)
_HTML_CELL_RE = re.compile(r"<t[dh]\b[^>]*>(.*?)</t[dh]>", re.I | re.S)


def _plain_cell(text: str) -> str:
    """Cell text without HTML or math markup: ``\\(IsPETaseTM^{K95N/F201I}\\)``
    reads as ``IsPETaseTMK95N/F201I``, the way a model retypes it."""
    text = re.sub(r"<[^>]+>|\\[()\[\]]|\$", " ", text)
    text = re.sub(r"\\(?:mathrm|text|textit|mathit|textbf|mathbf)\s*", "", text)
    # Drop super/subscript markers, keeping a name's own underscore (Thc_Cut1).
    text = re.sub(r"\s*(?:\^|_(?=\s*\{))\s*", "", text).replace("{", "").replace("}", "")
    return " ".join(text.split())


_MEAN_ERROR_RE = re.compile(
    r"(?<![\d.])\d+(?:\.\d+)?(?:[eE][+-]?\d+)?\s*±\s*\d+(?:\.\d+)?(?:[eE][+-]?\d+)?"
)


def _cited_table_row(quote: str, source: str) -> tuple[str, List[str]]:
    """A source table row inside ``quote`` and its header-labelled rendering.

    In a pivoted table (e.g. Km and kcat columns split by enzyme) the HTML row
    names neither the enzyme nor the unit; both sit in the header rows. The
    derived rendering of the same row (``render_table_rows``) carries them,
    deterministically, so it is evidence of the same grid cells.
    """
    from ..services.publication_tables import _unwrap_number, rendered_table_rows

    rows = _HTML_ROW_RE.findall(quote)
    if not rows:
        # Cells re-joined without their row ("IsPETaseWT<br>45.1 ± 0.1"):
        # cite the one source row holding every fragment as a whole cell.
        parts = {_plain_cell(part) for part in re.split(r"<[^>]+>|\s\|\s", quote) if part.strip()}
        if len(parts) >= 2:
            found = {
                row for row in _HTML_ROW_RE.findall(source)
                if parts <= {_plain_cell(cell) for cell in _HTML_CELL_RE.findall(row)}
            }
            rows = list(found) if len(found) == 1 else []
    if not rows:
        # A row retyped as prose ("Thc_Cut1 50: KM 2.3 ± 0.68 g·L-1; kcat
        # 0.072 ± 0.0056 s-1"): cite the one source row whose cells hold
        # every "mean ± error" pair of the quote.
        pairs = {re.sub(r"\s+", "", pair) for pair in _MEAN_ERROR_RE.findall(quote)}
        if len(pairs) >= 2:
            found = {
                row for row in _HTML_ROW_RE.findall(source)
                if pairs <= {re.sub(r"\s+", "", _unwrap_number(_cell_text(cell)))
                             for cell in _HTML_CELL_RE.findall(row)}
            }
            rows = list(found) if len(found) == 1 else []
    for row in rows:
        if not _reported_quote_in_source(row, source):
            continue
        for table in _HTML_TABLE_RE.findall(source):
            if row in table:
                index = _HTML_ROW_RE.findall(table).index(row)
                lines = [_plain_cell(line) for at, line in rendered_table_rows(table) if at == index]
                if lines:
                    return row, lines
    return "", []


def _row_cell_value(value: str, subject: str, row_lines: List[str]) -> str:
    """``value`` as the cell of ``subject``'s own column in a rendered row, or ''.

    A value with a unit must find that unit in the column header; a mean
    copied from a ``mean ± error`` cell comes back with its error.
    """
    from .record_value_resolution import _norm, _table_cell_binding

    entries = [("source material", _norm(subject))]
    for line in row_lines:
        binding = _table_cell_binding(value, line, entries, {})
        if binding and binding[0] and binding[1]:
            return binding[1]
        # The error of a "mean ± error" cell, split into its own field, is
        # verified by the mean binding to this material.
        for cell in (part.partition("=")[2] for part in line.split(";")):
            mean, sep, error = cell.partition("±")
            if sep and error.strip() == value.strip():
                binding = _table_cell_binding(mean.strip(), line, entries, {})
                if binding and binding[0] and binding[1]:
                    return value.strip()
    return ""


def _cell_text(cell: str) -> str:
    return " ".join(re.sub(r"<[^>]+>", " ", cell).split())


def _cell_role(value: str, cells: List[str], skip: int) -> Optional[tuple[int, str, str]]:
    """The one numeric cell ``value`` was read from: (index, part, unit suffix).

    ``part`` is ``whole``, ``mean`` or ``error`` of a ``mean ± error`` cell.
    None when no cell, or more than one, holds the value.
    """
    value = normalize_source_evidence_text(value).strip()
    found = []
    for index, cell in enumerate(cells):
        if index == skip or not re.search(r"\d", cell):
            continue
        mean, sep, error = (part.strip() for part in cell.partition("±"))
        for part, text in (("whole", cell), ("mean", mean if sep else ""), ("error", error)):
            if text and (value == text or (part != "error" and value.startswith(text + " "))):
                found.append((index, part, value[len(text):]))
                break
    return found[0] if len(found) == 1 else None


def _cell_part(cell: str, part: str) -> str:
    mean, sep, error = (item.strip() for item in cell.partition("±"))
    if part == "whole":
        return cell
    return (mean if part == "mean" else error) if sep else ""


def rebind_results_to_named_samples(
    records: List[Dict[str, Any]], materials: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    """Hang a result on the one declared Sample its source_subject names.

    A result about "Thc_Cut1" filed under the PET substrate Sample cannot pass
    the identity check. When exactly one declared material Sample has the
    result's source_subject as its own, and the current Sample's subject is
    not that name, the result moves there. Anything less exact is left alone.
    """
    def key(value: Any) -> str:
        return _plain_cell(normalize_source_evidence_text(value)).lower()

    by_id = {str(m.get("record_id") or ""): m for m in materials}
    named: Dict[str, List[str]] = {}
    for item in materials:
        if item.get("level") == "sample":
            named.setdefault(key(item.get("source_subject")), []).append(item["record_id"])
    out = []
    for record in records:
        subject = key(record.get("source_subject"))
        current = by_id.get(str(record.get("sample_row_id") or ""))
        owners = named.get(subject) or []
        if (subject and len(owners) == 1 and owners[0] != record.get("sample_row_id")
                and (current is None or key(current.get("source_subject")) != subject)):
            record = {**record, "sample_row_id": owners[0]}
        out.append(record)
    return out


def expand_table_row_templates(
    records: List[Dict[str, Any]], materials: List[Dict[str, Any]], source_text: str,
) -> tuple[List[Dict[str, Any]], List[Dict[str, Any]], Dict[str, str]]:
    """Repeat a result proposed for one table row over the table's other rows.

    A template record (``repeat_for_table_rows``) cites one body row of a
    source table. Each attribute read from a cell of that row is read from
    the same column of every sibling row; other attributes are shared. A
    sibling row gets the material named in the template's material column,
    reusing a declared material Sample of that name or declaring one (with
    its own preparation ObservationUnit) quoted by the row. The material is
    the row's cell in the template's material column, or, in a table grouped
    by label rows ("Thc_Cut1" over its 50 and 60 °C rows), the row's label.
    Rows a proposed record already cites, rows with a different cell count,
    and cells without a number are skipped. Returns the new
    records and materials and, for each new id, its template's record_id;
    every new record still passes the verbatim row and cell checks.
    """
    from ..services.publication_tables import _NUMERIC_CELL_RE, _TableGrid

    source = normalize_source_evidence_text(source_text)
    by_id = {str(item.get("record_id") or ""): item for item in materials}
    samples = {
        normalize_source_evidence_text(item.get("source_subject")).lower(): item["record_id"]
        for item in materials if item.get("level") == "sample"
    }
    # Rows a proposed record already cites are not repeated.
    cited = {_cited_table_row(normalize_source_evidence_text(r.get("source_quote")), source)[0]
             for r in records} - {""}
    new_records: List[Dict[str, Any]] = []
    new_materials: List[Dict[str, Any]] = []
    derived: Dict[str, str] = {}
    for template in records:
        if not template.get("repeat_for_table_rows"):
            continue
        rid = str(template.get("record_id") or "")
        row, _ = _cited_table_row(normalize_source_evidence_text(template.get("source_quote")), source)
        table = next((t for t in _HTML_TABLE_RE.findall(source) if row and row in t), "")
        if not table:
            continue
        cells = [_cell_text(cell) for cell in _HTML_CELL_RE.findall(row)]
        rows = _HTML_ROW_RE.findall(table)
        # A row holding one label ("Thc_Cut1") heads the rows below it.
        sections, label_rows, current = [], {}, ""
        for raw in rows:
            filled = [_cell_text(cell) for cell in _HTML_CELL_RE.findall(raw) if _cell_text(cell)]
            if len(filled) == 1 and not _NUMERIC_CELL_RE.match(filled[0]):
                current = filled[0]
                label_rows[current] = raw
            sections.append(current)
        subject = normalize_source_evidence_text(template.get("source_subject"))
        named = [i for i, cell in enumerate(cells) if _plain_cell(cell) == _plain_cell(subject)]
        if len(named) == 1:
            subject_index = named[0]
        elif row in rows and _plain_cell(sections[rows.index(row)]) == _plain_cell(subject):
            subject_index = -1  # the material is the row's section label
        else:
            continue
        roles = {}
        for position, attribute in enumerate(template.get("attributes") or []):
            role = _cell_role(str(attribute.get("value") or ""), cells, subject_index)
            if role:
                roles[position] = role
        sample = by_id.get(str(template.get("sample_row_id") or ""), {})
        study = by_id.get(str(sample.get("parent_row_id") or ""), {}).get("parent_row_id")
        if not roles:
            continue
        grid = _TableGrid(table)
        grid.feed(table)
        grid.close()
        header_rows = set(grid.project()["header_rows"])
        for number, sibling in enumerate(rows, start=1):
            row_cells = [_cell_text(cell) for cell in _HTML_CELL_RE.findall(sibling)]
            if (number - 1 in header_rows or sibling in cited or sibling == row
                    or len(row_cells) != len(cells) or sibling in label_rows.values()):
                continue
            name = row_cells[subject_index] if subject_index >= 0 else sections[number - 1]
            if not name or re.fullmatch(r"[\d\s.,±%+-]*", name) or "\\" in name:
                continue
            attributes = []
            for position, attribute in enumerate(template.get("attributes") or []):
                if position not in roles:
                    attributes.append(dict(attribute))
                    continue
                index, part, suffix = roles[position]
                cell = _cell_part(row_cells[index], part)
                if re.search(r"\d", cell):
                    attributes.append({**attribute, "value": cell + suffix})
            if len(attributes) == len(template.get("attributes") or []) - len(roles):
                continue
            # Keep only cells the row checks will accept for this material.
            _, lines = _cited_table_row(sibling, source)
            read_values = [a for position, a in enumerate(template.get("attributes") or []) if position in roles]
            if not lines or not all(
                _row_cell_value(str(a.get("value") or ""), name, lines)
                for a in attributes if a.get("field_name") in {r.get("field_name") for r in read_values}
            ):
                continue
            sample_id = samples.get(name.lower())
            if sample_id is None:
                if not study:
                    continue
                slug = re.sub(r"[^a-z0-9]+", "_", name.lower()).strip("_")[:40] or "material"
                ou_id, sample_id = f"tbl_ou_{slug}", f"tbl_{slug}"
                if ou_id in by_id or sample_id in by_id:
                    continue
                common = {"source_subject": name,
                          "source_quote": sibling if subject_index >= 0 else label_rows[name],
                          "source_group": str(template.get("source_group") or "table")}
                for item in ({**common, "record_id": ou_id, "level": "observationunit",
                              "parent_row_id": study, "record_kind": "material_preparation",
                              "label": f"{name} (material preparation)"},
                             {**common, "record_id": sample_id, "level": "sample",
                              "parent_row_id": ou_id, "record_kind": "material_identity",
                              "label": name}):
                    new_materials.append(item)
                    by_id[item["record_id"]] = item
                    derived[item["record_id"]] = rid
                samples[name.lower()] = sample_id
            clone_id = f"{rid}_row{number}"
            label = str(template.get("label") or "")
            new_records.append({
                **template, "record_id": clone_id, "sample_row_id": sample_id,
                "source_subject": name, "source_quote": sibling, "attributes": attributes,
                "label": label.replace(subject, name) if subject in label else f"{name}: {label}",
                "repeat_for_table_rows": False,
            })
            derived[clone_id] = rid
    return [*records, *new_records], [*materials, *new_materials], derived


def materialize_reported_assays(
    plan: Mapping[str, Any], records: Iterable[Mapping[str, Any]], *,
    source_text: str, field_catalog: Mapping[str, Iterable[str]],
    reviewed_parent_bindings: Mapping[str, str] | None = None,
) -> Dict[str, Any]:
    """Attach reported results to existing materials without inventing raw runs.

    Identity and literal-source checks do not establish semantic validity.
    Callers must still audit record grain, field meaning and parentage. A
    source alias absent from the material inventory requires an explicit,
    source-bound parent-review handoff; a known conflicting identity fails.
    Rejection leaves the existing graph intact and records the batch errors.
    """
    result = deepcopy(dict(plan))
    levels = {item["level"]: item for item in result.get("levels") or []}
    samples = {item["row_id"]: item for item in levels.get("sample", {}).get("entities") or []}
    identity_owners: Dict[str, set[str]] = {}
    material_identity_owners: Dict[str, set[str]] = {}
    for sample_id, sample in samples.items():
        identities = {
            normalize_source_evidence_text(attribute.get("value"))
            for attribute in sample.get("attributes") or []
        }
        identities.add(normalize_source_evidence_text(sample.get("external_identifier")))
        for identity in identities - {""}:
            identity_owners.setdefault(identity, set()).add(sample_id)
            if sample.get("record_kind") == "material_identity":
                material_identity_owners.setdefault(identity, set()).add(sample_id)
    occupied = {item["row_id"] for block in levels.values() for item in block.get("entities") or []}
    allowed = {str(name).strip().lower(): str(name).strip() for name in field_catalog.get("assay", [])}
    dropped: List[str] = []
    source = normalize_source_evidence_text(source_text)
    additions, errors = [], []

    def occurs(fragment: str, text: str) -> bool:
        fragment = normalize_source_evidence_text(fragment)
        if not fragment:
            return False
        return bool(re.search(r"(?<![\w.+\-])" + re.escape(fragment) + r"(?!\w|[.,]\d)", text))

    for record in records:
        key = str(record.get("record_id") or "").strip()
        parent = samples.get(str(record.get("sample_row_id") or ""))
        subject = str(record.get("source_subject") or "").strip()
        quote = normalize_source_evidence_text(record.get("source_quote"))
        kind = record.get("record_kind")
        # A material identity and its physical replicates can share a name.
        # Resolve an explicitly typed material reference among material records;
        # selecting an arbitrary physical replicate remains ambiguous.
        owners = (
            material_identity_owners
            if parent and parent.get("record_kind") == "material_identity"
            else identity_owners
        )
        subject_owners = owners.get(normalize_source_evidence_text(subject))
        identity_verified = bool(parent and subject_owners == {parent["row_id"]})
        row_lines: List[str] = []
        if not (_reported_quote_in_source(quote, source) and occurs(subject, quote)):
            row, row_lines = _cited_table_row(quote, source)
            if row and any(occurs(subject, line) for line in row_lines):
                # Keep only the verbatim row; a caption or annotation the
                # planner stitched to it is not source evidence.
                quote = row
            else:
                row_lines = []
        # A quoted row that names its material may still carry each value's
        # unit only in the column header: read such a value as its cell.
        header_lines = row_lines or (_cited_table_row(quote, source)[1] if "<tr" in quote.lower() else [])
        if (
            parent and parent.get("record_kind") == "material_identity"
            and not subject_owners
            and (reviewed_parent_bindings or {}).get(key)
            == reported_parent_binding_digest(record, parent, source_text)
        ):
            identity_verified = True
        if (
            not key or key in occupied or parent is None
            or kind not in {"fitted_result", "aggregate_result", "qualitative_result"}
            or not subject or not identity_verified
            or not _reported_quote_in_source(quote, source)
            or not (occurs(subject, quote) or row_lines)
        ):
            errors.append(f"Reported assay {key or '(blank)'} has unverified identity, parent or evidence.")
            continue
        occupied.add(key)
        attributes = []
        for attribute in record.get("attributes") or []:
            field = str(attribute.get("field_name") or "").strip().lower()
            raw_value = attribute.get("value")
            value = str(raw_value if raw_value is not None else "").strip()
            if row_lines:
                # A value read through the rendered row must be the cell in this
                # material's own column (and unit), not any equal number.
                value = _row_cell_value(value, subject, row_lines) or ""
                verified = bool(value)
            else:
                verified = occurs(value, quote)
                if not verified and header_lines:
                    value = _row_cell_value(value, subject, header_lines) or ""
                    verified = bool(value)
            if field not in allowed or field in _RESERVED_DIMENSION_FIELDS or not verified:
                # Drop only this attribute: one unquoted metadata field (e.g. a
                # DOI or a vocabulary label) must not discard the record's
                # source-quoted result values.
                dropped.append(f"Reported assay {key} dropped an unverified value or field: {field}.")
                continue
            attributes.append({"dimension_name": allowed[field], "field_name": allowed[field],
                               "value": value, "origin": "explicit"})
        if not attributes:
            errors.append(f"Reported assay {key} has no source-backed result attributes.")
            continue
        additions.append({
            "row_id": key, "label": str(record.get("label") or key),
            "parent_row_id": parent["row_id"], "external_identifier": None,
            "source_group": str(record.get("source_group") or "reported_results"),
            "record_kind": kind, "source_subject": subject, "source_quote": quote,
            "attributes": attributes,
            "unreported_design": list(record.get("unreported_design") or []),
        })
    if dropped:
        result.setdefault("materialization_errors", []).extend(dropped)
    if errors:
        result.setdefault("materialization_errors", []).extend(errors)
        return result
    if additions:
        assay = levels.get("assay")
        if assay is None:
            assay = {"level": "assay", "entities": [], "evidence": [], "unresolved_ambiguities": []}
            result.setdefault("levels", []).append(assay)
        assay["entities"].extend(additions)
        assay["cardinality"] = len(assay["entities"])
    return result


def render_entity_plan_for_prompt(plan: Mapping[str, Any], max_chars: int = 14000) -> str:
    """Render a complete identity graph, using a soft budget for narrative.

    Row IDs, parent links, groups and design attributes are required for value
    mapping. If these alone exceed the budget, retain them in full rather than
    producing incomplete JSON or omitting the later ISA levels.
    """
    if not plan:
        return ""
    compact = {
        "levels": plan.get("levels") or [],
        "investigation_contacts": plan.get("investigation_contacts") or [],
        "unresolved_ambiguities": plan.get("unresolved_ambiguities") or [],
    }
    text = json.dumps(compact, indent=2, ensure_ascii=False)
    if len(text) > max_chars:
        compact["levels"] = [
            {
                "level": level.get("level"),
                "cardinality": level.get("cardinality"),
                "entities": [
                    {
                        key: entity.get(key)
                        for key in (
                            "row_id",
                            "parent_row_id",
                            "external_identifier",
                            "source_group",
                            "label",
                            "attributes",
                        )
                    }
                    for entity in level.get("entities") or []
                    if isinstance(entity, Mapping)
                ],
            }
            for level in compact["levels"]
            if isinstance(level, Mapping)
        ]
        text = json.dumps(compact, separators=(",", ":"), ensure_ascii=False)
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


def _planned_identity_counts(
    entities: Iterable[Mapping[str, Any]],
) -> Dict[str, int]:
    counts: Dict[str, int] = {}
    for entity in entities:
        for identifier in {
            _norm(entity.get("row_id")),
            _norm(entity.get("external_identifier")),
        } - {""}:
            counts[identifier] = counts.get(identifier, 0) + 1
    return counts


def _output_entity_identifier(
    entity: Mapping[str, Any], identity_counts: Mapping[str, int],
) -> str:
    """Use an external identifier only when it uniquely identifies this row."""
    external_identifier = str(entity.get("external_identifier") or "").strip()
    if external_identifier and identity_counts.get(_norm(external_identifier), 0) == 1:
        return external_identifier
    return str(entity.get("row_id") or "").strip()


def _safe_source_row(
    rows: List[Dict[str, Any]],
    entity: Mapping[str, Any],
    entities: List[Mapping[str, Any]],
    *,
    level: str,
    shared_columns: Optional[Iterable[str]] = None,
    identity_counts: Optional[Mapping[str, int]] = None,
    parent_identifiers: Optional[Iterable[str]] = None,
) -> Dict[str, Any]:
    """Copy only scope-safe source values into a materialized entity row.

    For a multi-entity level, prose-derived candidate rows have no reliable row
    scope. Structured rows can retain their values when a unique planned ID
    and compatible parent/group select one row. ID-free prose rows can supply
    shared values, but unmatched or conflicting IDs cannot be treated as
    evidence of a level-wide value. Factor values are set separately from the
    locked plan; no fuzzy or positional row matching is used here.
    """
    if not rows:
        return {}
    forbidden = {
        *_ID_FIELDS.values(),
        *_NAME_FIELDS.values(),
        *_DESCRIPTION_FIELDS.values(),
        *_PARENT_FIELDS.values(),
        *_CONTACT_FIELDS,
    }

    id_field = _ID_FIELDS[level]
    row_id = str(entity.get("row_id") or "").strip()
    external_identifier = str(entity.get("external_identifier") or "").strip()
    if identity_counts is None:
        identity_counts = _planned_identity_counts(entities)
    canonical_id = _norm(row_id)
    external_alias = _norm(external_identifier)
    ambiguous_alias = bool(
        external_alias and identity_counts.get(external_alias, 0) != 1
    )
    if canonical_id and identity_counts.get(canonical_id, 0) != 1:
        return {}
    if ambiguous_alias and any(
        _norm(planned.get("row_id")) == external_alias for planned in entities
    ):
        # A collision with another canonical ID leaves the row's namespace
        # ambiguous. A repeated external-only label does not invalidate a
        # separate unique canonical ID.
        return {}

    parent_field = _PARENT_FIELDS.get(level)
    allowed_parents = {
        str(value).strip() for value in parent_identifiers or [] if str(value).strip()
    }
    parent_row_id = str(entity.get("parent_row_id") or "").strip()
    if parent_row_id:
        allowed_parents.add(parent_row_id)

    def scope_matches(row: Mapping[str, Any], *, require_parent: bool) -> bool:
        actual_parent = (
            str(row.get(parent_field) or "").strip() if parent_field else ""
        )
        if parent_field and (
            (require_parent and not actual_parent)
            or (actual_parent and actual_parent not in allowed_parents)
        ):
            return False
        source_group = str(row.get("source_group") or "").strip()
        return not source_group or source_group == str(
            entity.get("source_group") or ""
        ).strip()

    def value_text(value: Any) -> str:
        return "" if value is None else str(value).strip()

    exact_row: Optional[Dict[str, Any]] = None
    exact_matches = [
        row
        for row in rows
        if (row_id and str(row.get(id_field) or "").strip() == row_id)
        or (
            external_identifier
            and not ambiguous_alias
            and _norm(row.get(id_field)) == _norm(external_identifier)
        )
    ]
    if ambiguous_alias and not exact_matches:
        return {}
    if len(exact_matches) > 1:
        if level != "investigation" or any(
            not scope_matches(row, require_parent=False) for row in exact_matches
        ):
            return {}
        # Investigation repeats its identifier for contact rows. Preserve
        # only their common non-contact values; contacts are joined separately
        # below. Other ISA levels still require exactly one matching row.
        common: Dict[str, Any] = {}
        for column in dict.fromkeys(key for row in exact_matches for key in row):
            if column in _CONTACT_FIELDS:
                continue
            values = [row.get(column) for row in exact_matches]
            if all(value_text(value) for value in values) and len(
                {" ".join(value_text(value).lower().split()) for value in values}
            ) == 1:
                common[column] = deepcopy(values[0])
        return common
    if exact_matches:
        exact_row = exact_matches[0]
        # A unique planned identity binds the row even when the mapper omits
        # its parent. Projection fills that link from the authoritative graph;
        # an explicitly supplied parent or group must still agree with it.
        if not scope_matches(exact_row, require_parent=False):
            return {}
        if len(entities) == 1:
            return deepcopy(exact_row)

    explicitly_shared = {
        str(column).strip().lower() for column in shared_columns or []
    }
    identified_rows = any(str(row.get(id_field) or "").strip() for row in rows)
    if (
        exact_row is None
        and len(entities) == 1
        and len(rows) == 1
        and not identified_rows
    ):
        return (
            deepcopy(rows[0]) if scope_matches(rows[0], require_parent=False) else {}
        )
    if exact_row is None and len(rows) < 2:
        # A single collapsed source row cannot define sibling identity or
        # narrative, but confirmed non-identity properties may be common to all
        # rows (for example a single scientific name). Identity fields remain
        # forbidden and are compiled from the plan below.
        return {
            str(column).strip().lower(): value
            for column, value in rows[0].items()
            if str(column).strip().lower() not in forbidden
            and str(column).strip().lower() in explicitly_shared
            and value_text(value)
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
            if value_text(value):
                safe[normalized_column] = value
            continue
        if identified_rows and normalized_column not in explicitly_shared:
            continue
        values = [row.get(normalized_column) for row in rows]
        if any(not value_text(value) for value in values):
            continue
        normalized_values = {
            " ".join(value_text(value).lower().split()) for value in values
        }
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
        kind = {"fitted_result": "Fitted result", "aggregate_result": "Aggregate result",
                "qualitative_result": "Qualitative result"}.get(entity.get("record_kind"))
        description = f"{kind or 'Assay'} for sample {parent_identifier}"
        if attributes:
            description += ("; reported values: " if kind else "; assay-specific conditions: ") + "; ".join(attributes)
        if kind and entity.get("unreported_design"):
            description += "; " + "; ".join(str(note) for note in entity["unreported_design"])
        return description
    if entity.get("record_kind") in {"material_preparation", "material_identity"}:
        return f"{entity['record_kind'].replace('_', ' ').capitalize()}: {entity.get('source_subject')}"
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


def normalize_matrix_row_keys(row: Mapping[str, Any]) -> Optional[Dict[str, Any]]:
    """Normalize field keys without silently selecting conflicting cell values.

    Case variants of a field share one lowercase key. Blank duplicates can be
    filled and identical nonblank values can be merged; scientific value case
    remains significant. Conflicting scientific cells become blank. Conflicts
    in structural IDs or source group reject the row, rather than turning an
    ambiguous association into an anonymous row eligible for shared values.
    """
    normalized: Dict[str, Any] = {}
    conflicts: set[str] = set()
    for key, value in row.items():
        name = str(key).strip().lower()
        if not name or name in conflicts:
            continue
        if name not in normalized:
            normalized[name] = deepcopy(value)
            continue
        previous = normalized[name]
        previous_text = "" if previous is None else str(previous).strip()
        value_text = "" if value is None else str(value).strip()
        if not previous_text:
            normalized[name] = deepcopy(value)
        elif value_text and value_text != previous_text:
            normalized[name] = ""
            conflicts.add(name)
    if conflicts:
        identity_conflicts = conflicts & {*_ID_FIELDS.values(), "source_group"}
        logger.warning(
            "Conflicting case-variant matrix columns %s; %s",
            sorted(conflicts),
            "rejected source row" if identity_conflicts else "left conflicting cells blank",
        )
        if identity_conflicts:
            return None
    return normalized


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
            normalized
            for row in source_block.get("rows") or []
            if isinstance(row, Mapping)
            for normalized in [normalize_matrix_row_keys(row)]
            if normalized is not None
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
        identity_counts = _planned_identity_counts(plan_entities)
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
            parent_row_id = str(entity.get("parent_row_id") or "").strip()
            parent_level = (
                ISA_LEVEL_ORDER[ISA_LEVEL_ORDER.index(level) - 1]
                if level in _PARENT_FIELDS
                else ""
            )
            parent_identifiers = {
                parent_row_id,
                resolved_ids.get(parent_level, {}).get(parent_row_id, parent_row_id),
            } - {""}
            row = _safe_source_row(
                source_rows,
                entity,
                plan_entities,
                level=level,
                shared_columns=shared_columns,
                identity_counts=identity_counts,
                parent_identifiers=parent_identifiers,
            )
            row_id = str(entity.get("row_id") or "").strip()
            identifier = _output_entity_identifier(entity, identity_counts)
            row[_ID_FIELDS[level]] = identifier
            id_map[row_id] = identifier
            # Entity identity and row-specific narrative come from the locked
            # plan. Never broadcast a source example across sibling rows.
            if name_field and name_field in columns:
                row[name_field] = str(entity.get("label") or row_id)
            if entity.get("record_kind") or len(plan_entities) > 1 or not str(
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
    errors: List[str] = list(plan.get("materialization_errors") or [])
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
        identity_counts = _planned_identity_counts(entities)
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
            expected_id = _output_entity_identifier(entity, identity_counts)
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
    "materialize_reported_assays",
    "materialize_reported_materials",
    "text_names",
    "reported_parent_binding_digest",
    "normalize_entity_plan",
    "project_matrix_onto_entity_plan",
    "render_entity_plan_for_prompt",
    "validate_entity_matrix_against_plan",
]
