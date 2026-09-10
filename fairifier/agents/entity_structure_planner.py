"""Plan ISA entities and relations before metadata values are generated."""

from __future__ import annotations

import json
import hashlib
from copy import copy, deepcopy
from typing import Any, Dict, List, Mapping

from langchain_core.messages import HumanMessage
from langsmith import traceable

from .base import BaseAgent
from .response_models import EntityDesignClaimsResponse, EntityPlanScopeAuditResponse
from ..models import FAIRifierState
from ..services.fairds_api_parser import FAIRDSAPIParser
from ..utils.document_text import read_document_text
from ..utils.entity_plan import (
    contacts_from_names,
    contacts_from_source_text,
    materialize_entity_claims,
    normalize_claim_measurement_units,
    normalize_entity_plan,
)
from ..utils.llm_helper import get_llm_helper
from ..utils.metadata_table_plan import (
    materialize_record_table_plans,
    metadata_table_profiles,
    metadata_table_profiles_for_record_plans,
    source_extension_field_name,
)
from ..utils.structured_output import invoke_structured_output
from ..utils.fairds_value_contracts import (
    build_contract_index,
    canonicalize_value,
    contract_for,
    is_field_selector_contract,
)


class EntityStructurePlannerAgent(BaseAgent):
    """Create an evidence-grounded cardinality and linkage plan.

    This stage deliberately runs before JSONGenerator.  Later agents may fill
    fields, but they may not redefine how many entities exist or collapse
    multiple planned identities into one cell.
    """

    def __init__(self) -> None:
        super().__init__("EntityStructurePlanner")
        shared_helper = get_llm_helper()
        self.llm_helper = copy(shared_helper)
        # Sampling and thinking parameters are provider-specific and belong to
        # the run-level model profile.  In particular, binding ``temperature``
        # here leaks it into Ollama's top-level ``/api/chat`` payload instead of
        # its ``options`` object.  Keep a shallow helper copy for local state,
        # but reuse the already configured provider adapter unchanged.
        self.llm_helper.llm = shared_helper.get_llm()
        # Preserve the run-level audit log across the helper copy.
        self.llm_helper.llm_responses = shared_helper.llm_responses

    @staticmethod
    def _field_catalog(knowledge: List[Dict[str, Any]]) -> Dict[str, List[str]]:
        catalog: Dict[str, List[str]] = {
            level: []
            for level in ("investigation", "study", "observationunit", "sample", "assay")
        }
        terms_by_level: Dict[str, List[str]] = {level: [] for level in catalog}
        for item in knowledge:
            if not isinstance(item, Mapping):
                continue
            metadata = item.get("metadata") if isinstance(item.get("metadata"), Mapping) else {}
            level = FAIRDSAPIParser.normalize_isa_sheet(
                metadata.get("isa_sheet") or metadata.get("sheet")
            )
            term = str(item.get("term") or "").strip()
            if level in terms_by_level and term and term not in terms_by_level[level]:
                terms_by_level[level].append(term)
        contracts = build_contract_index(knowledge)
        for level, terms in terms_by_level.items():
            for term in terms:
                contract = contract_for(contracts, level, term)
                if contract and is_field_selector_contract(contract, terms):
                    continue
                catalog[level].append(term)
        return {level: fields[:80] for level, fields in catalog.items()}

    @staticmethod
    def _planning_knowledge(state: FAIRifierState) -> List[Dict[str, Any]]:
        """Combine selected fields with full contracts of selected packages."""
        combined: List[Dict[str, Any]] = []
        seen: set[tuple[str, str]] = set()
        sources = list(state.get("retrieved_knowledge") or []) + list(
            (state.get("api_capabilities") or {}).get(
                "selected_package_field_contracts", []
            )
            or []
        )
        for item in sources:
            if not isinstance(item, dict):
                continue
            metadata = item.get("metadata") if isinstance(item.get("metadata"), dict) else {}
            level = FAIRDSAPIParser.normalize_isa_sheet(
                metadata.get("isa_sheet") or metadata.get("sheet")
            )
            term = str(item.get("term") or "").strip()
            key = (level, term.lower())
            if not level or not term or key in seen:
                continue
            seen.add(key)
            combined.append(item)
        return combined

    @staticmethod
    def _field_contract_catalog(
        knowledge: List[Dict[str, Any]],
    ) -> Dict[str, List[Dict[str, Any]]]:
        """Expose compact live field semantics to the mapping audit.

        Field labels alone are not enough to distinguish a specific factor
        column from a generic description/protocol column.  Keep this catalog
        derived from the selected FAIR-DS contracts so no domain aliases or
        input-specific patterns are embedded in the planner.
        """
        names = EntityStructurePlannerAgent._field_catalog(knowledge)
        items_by_key: Dict[tuple[str, str], Mapping[str, Any]] = {}
        for item in knowledge:
            if not isinstance(item, Mapping):
                continue
            metadata = item.get("metadata") if isinstance(item.get("metadata"), Mapping) else {}
            level = FAIRDSAPIParser.normalize_isa_sheet(
                metadata.get("isa_sheet") or metadata.get("sheet")
            )
            term = str(item.get("term") or "").strip()
            if level and term:
                items_by_key[(level, term.lower())] = item
        contracts = build_contract_index(knowledge)
        result: Dict[str, List[Dict[str, Any]]] = {level: [] for level in names}
        for level, field_names in names.items():
            for field_name in field_names:
                item = items_by_key.get((level, field_name.lower()), {})
                metadata = item.get("metadata") if isinstance(item.get("metadata"), Mapping) else {}
                contract = contract_for(contracts, level, field_name) or {}
                result[level].append(
                    {
                        "field_name": field_name,
                        "definition": contract.get("definition")
                        or metadata.get("definition")
                        or item.get("definition"),
                        "syntax": contract.get("syntax") or metadata.get("syntax"),
                        "regex": contract.get("regex") or metadata.get("regex"),
                        "example": contract.get("example") or metadata.get("example"),
                        "requirement": metadata.get("requirement"),
                        "package": metadata.get("package") or metadata.get("package_name"),
                    }
                )
        return result

    @staticmethod
    def _promote_planned_fields(
        state: FAIRifierState,
        plan: Mapping[str, Any],
        planning_knowledge: List[Dict[str, Any]],
    ) -> List[str]:
        """Promote plan-mapped fields from the already selected packages."""
        requested: set[tuple[str, str]] = set()
        for level_plan in plan.get("levels") or []:
            if not isinstance(level_plan, Mapping):
                continue
            level = str(level_plan.get("level") or "").strip().lower()
            for entity in level_plan.get("entities") or []:
                if not isinstance(entity, Mapping):
                    continue
                for attribute in entity.get("attributes") or []:
                    if not isinstance(attribute, Mapping):
                        continue
                    field_name = str(attribute.get("field_name") or "").strip()
                    if field_name:
                        requested.add((level, field_name.lower()))

        current = state.setdefault("retrieved_knowledge", [])
        existing = {
            (
                FAIRDSAPIParser.normalize_isa_sheet(
                    (item.get("metadata") or {}).get("isa_sheet")
                    or (item.get("metadata") or {}).get("sheet")
                ),
                str(item.get("term") or "").strip().lower(),
            )
            for item in current
            if isinstance(item, Mapping)
        }
        by_key = {}
        for item in planning_knowledge:
            metadata = item.get("metadata") if isinstance(item.get("metadata"), Mapping) else {}
            key = (
                FAIRDSAPIParser.normalize_isa_sheet(
                    metadata.get("isa_sheet") or metadata.get("sheet")
                ),
                str(item.get("term") or "").strip().lower(),
            )
            by_key[key] = item

        promoted: List[str] = []
        for extension in plan.get("source_extension_fields") or []:
            if not isinstance(extension, Mapping):
                continue
            level = str(extension.get("level") or "").strip().lower()
            field_name = str(extension.get("field_name") or "").strip()
            key = (level, field_name.lower())
            if level not in {"observationunit", "sample", "assay"} or not field_name:
                continue
            if key not in existing:
                current.append(
                    {
                        "term": field_name,
                        "definition": extension.get("definition")
                        or f"Source-supplied metadata field '{field_name}'.",
                        "source": "source_metadata_table",
                        "metadata": {
                            "isa_sheet": level,
                            "requirement": "OPTIONAL",
                            "required": False,
                            "package": "Source metadata extension",
                            "data_type": extension.get("data_type") or "string",
                            "type": extension.get("data_type") or "string",
                            "source_extension": True,
                            "source_column": extension.get("source_column"),
                            "source_path": extension.get("source_path"),
                            "table_name": extension.get("table_name"),
                        },
                    }
                )
                existing.add(key)
                promoted.append(f"{level}.{field_name} [source extension]")
        for key in sorted(requested):
            if key in existing or key not in by_key:
                continue
            current.append(dict(by_key[key]))
            existing.add(key)
            promoted.append(f"{key[0]}.{by_key[key].get('term')}")
        return promoted

    @staticmethod
    def _plan_errors(plan: Mapping[str, Any]) -> List[str]:
        errors: List[str] = list(plan.get("materialization_errors") or [])
        source_coverage = plan.get("source_coverage") or {}
        coverage_tables = source_coverage.get("tables") or []
        if coverage_tables and not source_coverage.get("complete", False):
            for table in coverage_tables:
                unmapped = list((table or {}).get("unmapped_columns") or [])
                if unmapped:
                    errors.append(
                        "Authoritative metadata-table coverage is incomplete for "
                        f"{table.get('source_path')}:{table.get('table_name')}: "
                        f"{unmapped}. Map, derive, or explicitly exclude every column."
                    )
        expected = ("investigation", "study", "observationunit", "sample", "assay")
        levels = {
            str(item.get("level") or ""): item
            for item in (plan.get("levels") or [])
            if isinstance(item, Mapping)
        }
        row_ids: Dict[str, set[str]] = {}
        for level in expected:
            level_plan = levels.get(level)
            if not level_plan:
                errors.append(f"Missing {level} entity plan.")
                continue
            entities = [
                entity
                for entity in (level_plan.get("entities") or [])
                if isinstance(entity, Mapping)
            ]
            declared = int(level_plan.get("cardinality") or 0)
            if not entities:
                errors.append(f"{level} plan contains no entities.")
            if declared != len(entities):
                errors.append(
                    f"{level} cardinality {declared} does not match {len(entities)} rows."
                )
            ids = [str(entity.get("row_id") or "").strip() for entity in entities]
            if any(not row_id for row_id in ids) or len(set(ids)) != len(ids):
                errors.append(f"{level} row IDs are blank or non-unique.")
            row_ids[level] = set(ids)
            if level != "investigation":
                parent_level = expected[expected.index(level) - 1]
                for entity in entities:
                    parent = str(entity.get("parent_row_id") or "").strip()
                    if parent not in row_ids.get(parent_level, set()):
                        errors.append(
                            f"{level} row {entity.get('row_id')} has unresolved parent {parent}."
                        )
        claims_groups = {
            str(group.get("group_id") or ""): group
            for group in ((plan.get("design_claims") or {}).get("design_groups") or [])
            if isinstance(group, Mapping)
        }
        entities_by_level_group: Dict[str, Dict[str, int]] = {
            level: {} for level in ("sample", "assay")
        }
        for level in ("sample", "assay"):
            for entity in (levels.get(level) or {}).get("entities") or []:
                if not isinstance(entity, Mapping):
                    continue
                group_id = str(entity.get("source_group") or "").strip()
                entities_by_level_group[level][group_id] = (
                    entities_by_level_group[level].get(group_id, 0) + 1
                )
        for group_id, assay_count in entities_by_level_group["assay"].items():
            sample_count = entities_by_level_group["sample"].get(group_id, 0)
            if assay_count <= sample_count:
                continue
            claim = claims_groups.get(group_id, {})
            reuse_allowed = bool(
                claim.get("reuse_same_sample_for_multiple_assays", False)
            )
            reuse_evidence = " ".join(
                str(claim.get("sample_reuse_evidence") or "").split()
            )
            group_evidence = " ".join(str(claim.get("evidence") or "").split())
            evidence_is_exact = bool(
                reuse_evidence
                and reuse_evidence.lower() in group_evidence.lower()
            )
            if not reuse_allowed or not evidence_is_exact:
                errors.append(
                    f"Design group {group_id} creates {assay_count} assay rows from "
                    f"only {sample_count} sample rows without an explicit source quote "
                    "authorizing reuse of the same sample. Propagate the differing "
                    "preparation/measurement dimension through Sample, or provide "
                    "verbatim sample_reuse_evidence."
                )
        return errors

    @staticmethod
    def _enforce_dimension_field_contracts(
        plan: Dict[str, Any], knowledge: List[Dict[str, Any]]
    ) -> Dict[str, Any]:
        """Drop plan mappings whose dimension values violate FAIR-DS.

        Field-name similarity is insufficient for mapping an experimental
        dimension to a workbook column.  A mapping is valid only when every
        explicit value in that group/level/dimension can satisfy the selected
        field's machine-readable value contract.  If even one value is
        incompatible, keep the dimension in entity labels and links but leave
        the FAIR-DS field unmapped; Mapper must not be asked to violate either
        the plan or the schema.
        """
        contracts = build_contract_index(knowledge)
        incompatible: set[tuple[str, str, str, str]] = set()
        attributes: List[tuple[tuple[str, str, str, str], Dict[str, Any], Any]] = []
        for level_plan in plan.get("levels") or []:
            if not isinstance(level_plan, Mapping):
                continue
            level = str(level_plan.get("level") or "").strip().lower()
            for entity in level_plan.get("entities") or []:
                if not isinstance(entity, Mapping):
                    continue
                source_group = str(entity.get("source_group") or "").strip()
                for attribute in entity.get("attributes") or []:
                    if not isinstance(attribute, dict):
                        continue
                    field_name = str(attribute.get("field_name") or "").strip()
                    if not field_name:
                        continue
                    dimension_name = str(
                        attribute.get("dimension_name") or ""
                    ).strip()
                    key = (level, source_group, dimension_name, field_name)
                    contract = contract_for(contracts, level, field_name)
                    attributes.append((key, attribute, contract))
                    if contract and canonicalize_value(
                        attribute.get("value"), contract
                    ) is None:
                        incompatible.add(key)

        source_coverage = plan.get("source_coverage") or {}
        replacement_extensions: Dict[tuple[str, str, str, str], str] = {}
        for key in incompatible:
            level, _source_group, dimension_name, field_name = key
            for table in source_coverage.get("tables") or []:
                mappings = list(table.get("fairds_mappings") or [])
                retained = [
                    mapping
                    for mapping in mappings
                    if not (
                        str(mapping.get("level") or "") == level
                        and str(mapping.get("column") or "") == dimension_name
                        and str(mapping.get("field_name") or "") == field_name
                    )
                ]
                if len(retained) == len(mappings):
                    continue
                table["fairds_mappings"] = retained
                column_roles = {
                    str(item.get("column") or ""): {
                        str(role)
                        for role in item.get("roles") or []
                        if str(role)
                    }
                    for item in table.get("column_roles") or []
                    if isinstance(item, Mapping)
                }
                removed_role = f"fairds_mapping:{level}"
                remaining_roles = column_roles.get(dimension_name, set()) - {
                    removed_role
                }
                extension_name = ""
                if not remaining_roles and dimension_name in (table.get("columns") or []):
                    # The mapping was semantically wrong, but the authoritative
                    # source value remains valid provenance. Preserve it under a
                    # deterministic source-extension label instead of dropping
                    # the column or weakening the FAIR-DS value contract.
                    extension_name = source_extension_field_name(dimension_name)
                    values = [
                        value
                        for candidate_key, _attribute, _contract in attributes
                        if candidate_key == key
                        for value in [_attribute.get("value")]
                        if str(value or "").strip()
                    ]
                    numeric = bool(values)
                    for value in values:
                        try:
                            float(str(value))
                        except (TypeError, ValueError):
                            numeric = False
                            break
                    extension = {
                        "level": level,
                        "field_name": extension_name,
                        "source_column": dimension_name,
                        "data_type": "number" if numeric else "string",
                        "definition": (
                            f"Source-supplied metadata column '{dimension_name}', "
                            f"retained because its values do not satisfy FAIR-DS "
                            f"field '{field_name}'."
                        ),
                        "source_id": table.get("source_id"),
                        "source_path": table.get("source_path"),
                        "table_name": table.get("table_name"),
                        "demoted_from_fairds_mapping": field_name,
                    }
                    table_extensions = table.setdefault("source_extensions", [])
                    if not any(
                        str(item.get("level") or "") == level
                        and str(item.get("field_name") or "") == extension_name
                        for item in table_extensions
                        if isinstance(item, Mapping)
                    ):
                        table_extensions.append(extension)
                    plan_extensions = plan.setdefault("source_extension_fields", [])
                    if not any(
                        str(item.get("level") or "") == level
                        and str(item.get("field_name") or "") == extension_name
                        for item in plan_extensions
                        if isinstance(item, Mapping)
                    ):
                        plan_extensions.append(extension)
                    remaining_roles.add(f"source_extension:{level}")
                    replacement_extensions[key] = extension_name
                for item in table.get("column_roles") or []:
                    if (
                        isinstance(item, dict)
                        and str(item.get("column") or "") == dimension_name
                    ):
                        item["roles"] = sorted(remaining_roles)
                if not remaining_roles:
                    unmapped = table.setdefault("unmapped_columns", [])
                    if dimension_name not in unmapped:
                        unmapped.append(dimension_name)
                    table["coverage_complete"] = False

        coverage_tables = source_coverage.get("tables") or []
        source_coverage["complete"] = bool(coverage_tables) and all(
            bool(table.get("coverage_complete")) for table in coverage_tables
        )

        ambiguities = plan.setdefault("unresolved_ambiguities", [])
        for key, attribute, contract in attributes:
            if key in incompatible:
                attribute["field_name"] = replacement_extensions.get(key) or None
                level, source_group, dimension_name, field_name = key
                replacement = replacement_extensions.get(key)
                note = (
                    f"Demoted {level} mapping {dimension_name!r} -> {field_name!r} "
                    f"to source extension {replacement!r} for "
                    f"{source_group or 'design group'} because its explicit values "
                    "do not satisfy the FAIR-DS field value contract."
                    if replacement
                    else (
                        f"Omitted {level} mapping {dimension_name!r} -> {field_name!r} "
                        f"for {source_group or 'design group'} because its explicit "
                        "values do not satisfy the FAIR-DS field value contract."
                    )
                )
                if note not in ambiguities:
                    ambiguities.append(note)
            elif contract:
                canonical = canonicalize_value(attribute.get("value"), contract)
                if canonical is not None:
                    attribute["value"] = canonical
        return plan

    @staticmethod
    def _source_contacts(state: FAIRifierState) -> List[Dict[str, str]]:
        authors = (state.get("document_info") or {}).get("authors") or []
        contacts = contacts_from_source_text(
            read_document_text(state), fallback_names=authors
        )
        if contacts:
            return contacts
        return contacts_from_names(authors)

    @staticmethod
    def _candidate_rank(
        plan: Mapping[str, Any],
        errors: List[str],
        *,
        used_authoritative_records: bool,
    ) -> tuple[int, int, int, int]:
        """Rank retry candidates by deterministic validity and source fidelity.

        Counting diagnostics alone can prefer a coarse Cartesian fallback over
        a successfully materialized authoritative table.  A valid candidate is
        always best; among invalid candidates, exact source records and complete
        source-column disposition outrank the raw number of diagnostics.
        """
        source_coverage = plan.get("source_coverage") or {}
        coverage_complete = bool(source_coverage.get("tables")) and bool(
            source_coverage.get("complete")
        )
        return (
            int(bool(plan) and not errors),
            int(used_authoritative_records),
            int(coverage_complete),
            -len(errors),
        )

    def _prompt(
        self,
        state: FAIRifierState,
        *,
        prior_errors: List[str] | None = None,
    ) -> str:
        document_text = read_document_text(state, max_chars=18000)
        document_info = state.get("document_info") or {}
        field_catalog = self._field_catalog(self._planning_knowledge(state))
        table_profiles = metadata_table_profiles(state.get("source_workspace") or {})
        correction = ""
        if prior_errors:
            correction = (
                "\nThe previous plan failed deterministic validation. Correct every issue:\n- "
                + "\n- ".join(prior_errors[:12])
            )
        return f"""
You are the structure-planning stage of FAIRiAgent. Determine the ISA entity
matrix before any metadata values are filled. This is a scientific data-model
task, not a prose summarization task.

Hard rules:
1. Return COMPACT SOURCE DESIGN CLAIMS, not materialized rows. For each independent
   experimental branch, state each dimension's level_count once and which of
   observationunit, sample, assay it applies to. Code will build the cross-products.
2. Use FAIR-DS ISOSA semantics and the curated workbook convention. An
   observationunit is the experimental unit or condition being observed; a sample
   is one collected, isolated, pooled, or aliquoted material record; an assay is
   one preparation/measurement event. Biological replicates are normally separate
   sample rows under their observation unit, not automatically separate
   observationunit rows. They become separate observation units only when the
   source describes distinct independently observed organisms, plots, vessels, or
   other experimental units. A treatment/stage may define observationunit rows;
   replicate material collected within each treatment/stage defines sample rows.
   A material split or dilution begins at sample. A preparation/measurement
   method is recorded as assay metadata, but the physical input path still has
   to be represented: when crossing a material factor with a preparation method
   creates distinct aliquots or prepared libraries, propagate that method
   dimension through Sample for cardinality/linkage and through Assay for the
   event. Do not map the method to a Sample metadata term. Reuse one Sample row
   for multiple Assay rows only when the source explicitly describes reuse of
   the same identified material, repeated measurements, or distinct modalities
   on that same sample. Otherwise use one traceable sample-to-assay path per
   preparation condition.
3. Represent every stated factorial design and replicate count. If N levels are
   stated but their names are absent, set level_count=N, explicit_values=[],
   origin=derived, and record the missing labels as an ambiguity. Never invent
   or enumerate plausible scientific labels; code creates ordinal placeholders.
   A stated range or a few examples/endpoints are not a complete enumeration.
   Keep explicit_values=[] and use known_values=[{{"position": 1, "value":
   "source label"}}, ...] only when the source fixes an ordinal position (for
   example the first and last values of a stated range). Unknown positions stay
   derived ordinal placeholders. Quote the incompleteness in the ambiguity.
   A replicate or factor applies only to the design group whose source statement
   explicitly contains it; never propagate dimensions across independent groups.
   Preserve source-exact units and qualifiers inside explicit_values (for example,
   keep "5 ng" rather than reducing it to "5"). Copy the complete source span:
   do not shorten a value by dropping an adjacent parenthetical qualifier or
   other source-stated modifier.
   Dimensions are not limited to row-generating factors. Preserve an explicitly
   stated constant condition with level_count=1 when it characterizes every
   entity in that design group and maps to an available value-bearing FAIR-DS
   field (for example a single stage, genotype, material, or treatment). Such a
   constant does not multiply the row count, but omitting it would leave a
   source-supported workbook column blank. Audit every group's evidence for
   these constant conditions before returning.
4. Root row_id values are stable internal identifiers only. external_identifier
   must be null unless the source explicitly supplies that identifier.
5. applies_to is a subset of observationunit, sample, assay. Parent dimensions
   must be a subset of child dimensions so every child has exactly one parent.
   Also classify every dimension with semantic_role. Use
   observation_condition for a treatment, timepoint, developmental state, or
   environmental condition defining what is independently observed;
   sample_replicate for replicate material collected within a condition;
   material_path for collection, isolation, pooling, aliquoting, or dilution;
   assay_process for a preparation/measurement method;
   constant_characteristic for a non-row-generating descriptor; and other only
   when none applies. This role is part of the cardinality decision, not a label.
6. FAIR-DS term mappings are level-specific. The catalog below contains only
   value-bearing fields; schema selector fields whose enumerated values are
   other field names are intentionally excluded. For each dimension, use
   field_mappings entries with a level and a field_name copied exactly from
   that level's catalog. Never reuse an ObservationUnit term on Sample or Assay
   merely because the dimension propagates through those rows. Omit a mapping
   when no suitable catalog field exists; the dimension will remain visible in
   the entity name and description.
7. Do not model contributors here. FAIRiAgent extracts source-exact contacts
   deterministically and repeats them as rows in the Investigation worksheet.
   There is no Person ISOSA level or Person worksheet.
8. Evidence must quote or closely reproduce the source design statement. State
   ambiguity rather than silently guessing.
9. Keep evidence at root/design-group level. Do not repeat it per factor level.
10. Before returning, compute the implied row counts for every group and confirm
    that all source design branches are represented exactly once.
    If a group has more assay rows than sample rows, set
    reuse_same_sample_for_multiple_assays=true only when the group evidence
    explicitly states reuse/repeated measurement of the same material, and copy
    that exact phrase into sample_reuse_evidence. Otherwise propagate the
    assay-varying preparation dimension through Sample so each assay retains a
    one-to-one physical input path.
11. Give every design group a concise scientific label derived from its stated
    purpose or factors. group_id is an internal key and must not be used as the
    human-readable label.
12. Be terse: this response must fit within 4,000 tokens.
13. When an authoritative metadata table explicitly enumerates the focal study's
    sample/assay records, return a record_table_plans entry. Table rows outrank a
    prose-derived Cartesian approximation, especially for incomplete or uneven
    designs. Select focal rows only with exact equality filters supported by the
    paper identity (for example its explicitly named dataset/project), choose
    source columns rather than identifier-pattern guesses, and set
    covers_complete_focal_study=true only when the table says it covers the study
    and the selected rows account for its stated records. Code, not the model,
    will enumerate the selected rows. observation_unit_columns define grouping:
    use the smallest set of table columns that preserves distinct observed
    conditions without turning replicate/sample identifiers into observation
    units. group_column separates independent experimental branches. Map source
    columns only to exact fields in the level catalog. Identity columns must be
    nonblank, scalar, and unique in the selected rows. A source run/accession
    column containing lists is supporting assay context, not automatically one
    entity per punctuation token; choose a scalar logical assay identifier
    column (it may be the same scalar row key as the sample identifier when the
    table has one logical assay record per unique sample row) and retain the list
    column in assay_description_columns. Prefer columns marked
    globally_scalar_unique in the table profile; never claim that a column is
    scalar when its list_like_count is nonzero. Record source-supported expected
    counts for observation units, samples, and assays. The grouping columns must
    reproduce those counts; use null only when the source does not support a
    count. For every selected source-table column, choose exactly one auditable
    disposition: identity/filter/grouping, an exact FAIR-DS column_mappings entry,
    a source_extension_mappings entry, a source-backed derived_mappings input,
    descriptive context, or excluded_columns
    with a concrete reason. Source accessions and per-record QC measurements are
    metadata/provenance and should normally be retained as source extensions when
    FAIR-DS has no exact term. Bulky expression, correlation, gene-list, or other
    result matrices are result payloads, not ISOSA row fields. Description text is
    not an adequate substitute for a structured accession or quantitative column.
    Source extension field labels are generated deterministically from the source
    header; the model selects only the ISA level, type, and definition. When a
    source identifier encodes a scientifically meaningful value that the paper
    explicitly defines (for example replicate number or preparation method), a
    derived_mappings entry may map it to an exact selected FAIR-DS field. Use a
    short ordered set of declarative exact/prefix/suffix/contains/regex rules,
    state the expected number of matched rows, and quote the convention evidence.
    Add exact-equality filters when the same identifier syntax has a different
    meaning in another experimental branch. Counts and rules are evaluated only
    on rows matching those filters. Never rely on a prefix alone when the table
    profile shows that prefix in both focal branches.
    Set source_extension=true only when no selected FAIR-DS field represents the
    derived concept; then provide a stable field name, data type, and definition.
    If a table column is coarser than the source-declared observation conditions
    but an identifier convention explicitly and completely distinguishes those
    conditions, add an observationunit derived mapping and set
    use_for_observation_unit_grouping=true. Code will group on the derived value;
    do not add the raw per-sample identifier to observation_unit_columns. This is
    allowed only for a documented convention with exhaustive rules and an exact
    expected_nonblank_count, never from superficial resemblance.
    This is a hard structural requirement: before returning, verify that the
    distinct tuple of group_column + observation_unit_columns + every enabled
    grouping derivation equals expected_observation_unit_count. If the raw
    columns collapse named conditions, a grouping derivation is required; do
    not merely state the finer conditions in design_groups.
    Inspect the complete identity-column value distribution before writing rules.
    Rules must cover only demonstrated conventions; unmatched rows stay blank.
    Never derive accessions, dates, organisms, treatments, or measurements from
    superficial identifier resemblance. If these requirements are not met,
    return record_table_plans=[] and keep the factor design.

Required nested JSON shape (use these exact keys; this is a structural example,
not a design to copy):
{{
  "investigations": [{{
    "row_id": "investigation_001", "label": "...",
    "parent_row_id": null, "external_identifier": null, "evidence": "..."
  }}],
  "studies": [{{
    "row_id": "study_001", "label": "...",
    "parent_row_id": "investigation_001", "external_identifier": null,
    "evidence": "..."
  }}],
  "design_groups": [{{
    "group_id": "group_001", "label": "concise design branch label",
    "study_row_id": "study_001", "evidence": "...",
    "reuse_same_sample_for_multiple_assays": false,
    "sample_reuse_evidence": null,
    "dimensions": [{{
      "name": "factor_name", "level_count": 2,
      "explicit_values": ["control", "treated"], "origin": "explicit",
      "semantic_role": "observation_condition",
      "known_values": [],
      "field_mappings": [
        {{"level": "observationunit", "field_name": "catalog term"}}
      ],
      "field_name": null,
      "applies_to": ["observationunit", "sample", "assay"]
    }}],
    "unresolved_ambiguities": []
  }}],
  "record_table_plans": [{{
    "source_id": "source_001", "table_name": "source table name",
    "study_row_id": "study_001", "study_identifier_value": "exact focal ID",
    "covers_complete_focal_study": true,
    "filters": [{{"column": "source column", "value": "exact focal value"}}],
    "sample_identifier_column": "source sample ID column",
    "assay_identifier_column": "source assay/run ID column",
    "observation_unit_columns": ["condition column"],
    "expected_observation_unit_count": 2,
    "expected_sample_count": 6,
    "expected_assay_count": 6,
    "group_column": "experimental branch column",
    "description_columns": ["source-backed context column"],
    "assay_description_columns": ["source assay context column"],
    "column_mappings": [{{
      "column": "source column", "level": "sample",
      "field_name": "exact catalog term"
    }}],
    "source_extension_mappings": [{{
      "column": "unmapped source metadata column", "level": "assay",
      "data_type": "number", "definition": "source-backed definition"
    }}],
    "derived_mappings": [{{
      "source_column": "source row label", "level": "sample",
      "field_name": "exact catalog term",
      "source_extension": false, "data_type": "string", "definition": "",
      "use_for_observation_unit_grouping": false,
      "filters": [{{"column": "branch column", "value": "exact branch"}}],
      "rules": [{{
        "match_type": "regex", "pattern": "source-backed expression",
        "value": "source-backed normalized value"
      }}],
      "expected_nonblank_count": 2,
      "evidence": "paper/table statement defining the naming convention"
    }}, {{
      "source_column": "source row label", "level": "observationunit",
      "field_name": "source-defined condition", "source_extension": true,
      "data_type": "string", "definition": "Source-defined condition label",
      "use_for_observation_unit_grouping": true,
      "filters": [{{"column": "branch column", "value": "target branch"}}],
      "rules": [{{
        "match_type": "prefix", "pattern": "documented condition prefix",
        "value": "documented condition"
      }}],
      "expected_nonblank_count": 2,
      "evidence": "paper/table statement defining every condition prefix"
    }}],
    "excluded_columns": [{{
      "column": "non-metadata column", "classification": "result_payload",
      "reason": "why it is not an ISOSA field"
    }}],
    "evidence": "why this table/filter covers the focal study"
  }}],
  "design_summary": [], "unresolved_ambiguities": [], "confidence": 0.85
}}

Parsed document information:
{json.dumps(document_info, indent=2, ensure_ascii=False)}

Available FAIR-DS fields by level:
{json.dumps(field_catalog, indent=2, ensure_ascii=False)}

Authoritative source metadata-table profiles (schema, distributions, and
examples; code retains the complete tables for deterministic row selection):
{json.dumps(table_profiles, indent=2, ensure_ascii=False)}

Source document:
{document_text}
{correction}
""".strip()

    @staticmethod
    def _claims_payload(parsed: Any) -> Dict[str, Any]:
        if hasattr(parsed, "model_dump"):
            return parsed.model_dump()
        return dict(parsed or {})

    def _scope_audit_prompt(
        self,
        claims: Mapping[str, Any],
        field_catalog: Mapping[str, List[str]],
        field_contract_catalog: Mapping[str, List[Mapping[str, Any]]],
        table_profiles: List[Mapping[str, Any]],
    ) -> str:
        return f"""
You are the semantic scope-and-field-mapping audit for an ISA entity plan.
Perform four bounded checks:
A. Find source-explicit constant experimental conditions omitted from a design
   group. A constant has one value and does not increase row count.
B. Return exactly one mapping_decisions item for EVERY existing dimension,
   independently replacing its draft field_mappings. Each decision contains zero
   or more exact FAIR-DS mappings. Use an empty mappings list when no semantically
   correct field exists. Field definitions and value contracts are provided below.
   mapping_corrections is legacy-only and must be an empty list.
C. Independently verify every design group that sets
   reuse_same_sample_for_multiple_assays=true. Approve only if the group's own
   evidence explicitly says the same identified physical material was reused,
   repeatedly measured, or measured in distinct modalities without a new
   preparation path. A shared source pool, dilution series, or several library
   preparation methods does not by itself prove reuse: distinct aliquot or
   preparation paths must remain traceable through Sample.
D. Independently assign applies_to for EVERY existing dimension. ObservationUnit
   represents the independently observed biological/physical unit or condition.
   Collection, isolation, pooling, aliquoting, dilution, and other material-path
   factors begin at Sample. Preparation or measurement factors are assay metadata;
   when they create distinct prepared inputs they also propagate through Sample
   for traceability, but they do not create ObservationUnits. Biological replicate
   material is normally Sample unless the source explicitly describes distinct
   independently observed organisms, plots, vessels, or equivalent units.
   Independently assign semantic_role using the same constrained meanings:
   observation_condition, sample_replicate, material_path, assay_process,
   constant_characteristic, or other. Do not copy the draft role without
   checking it against the quoted design evidence.
E. Independently audit EVERY column in each record_table_plans table using
   record_column_decisions. A structured source-metadata value must not survive
   only inside a prose description. Use structural_only only for exact filter
   columns and entity identity keys. Use fairds_mapping only when the source
   column meaning and values exactly satisfy the live FAIR-DS field definition
   and contract. Otherwise preserve the source value as a source_extension at
   the correct ISA level. A repository sample accession belongs to Sample; a
   run, experiment, library, preparation, sequencing, or QC value belongs to
   Assay. Source-row biological material, developmental, timepoint, and grouping
   annotations normally belong to Sample. Use ObservationUnit only when a value
   is truly constant within every resulting observed condition. Exclude only
   non-metadata/result payload columns with an explicit rationale.

Each record_column_decisions object has exactly these keys:
{{"source_id": "<profile source_id>", "table_name": "<profile table_name>",
  "column": "<exact source header>", "disposition": "structural_only|fairds_mapping|source_extension|excluded",
  "level": "observationunit|sample|assay|null", "field_name": "<exact FAIR-DS field or null>",
  "data_type": "string|number|integer|boolean", "rationale": "<brief reason>"}}
Use the key disposition, not decision. Repeat source_id and table_name on every
item even when the audit covers only one table.

Strict rules:
1. source_value must occur verbatim in that group's own evidence string.
2. field_name must be copied exactly from the catalog for the reported level.
3. Do not report a condition already represented by any draft dimension.
4. Do not report publication metadata, outcomes, generic assay prose, pool size,
   or a value for which the catalog has no suitable field.
5. A mapping correction may reference only an existing dimension and a level in
   its applies_to list. Prefer the most semantically specific compatible field.
   Do not map derived unknown labels merely to make a column non-empty.
6. Do not use a free-text narrative field when a specific compatible value field
   exists. If no semantically appropriate field exists, leave the mapping absent.
   Preparation input amounts or concentrations may map to a preparation field
   when they describe that step, but are not sample treatments merely because
   they vary between branches. A dose field is appropriate only for a substance
   administered to the biological material as a treatment. Qualitative outcomes,
   comparisons, and unnamed or ordinal method placeholders are not protocol names;
   mapping to protocol requires a source-supplied method/protocol name, identifier,
   URL, or operational procedure. Map cultivar, accession, population, or ecotype
   labels to an ecotype/cultivar/accession field; reserve genotype for an explicit
   genetic constitution or mutation. An organism-part value is an anatomical or
   material label, never a count of pooled units.
7. missing_conditions and mapping_corrections may be empty, but
   mapping_decisions and dimension_scopes must still review every dimension.
8. Return one reuse_validations item for every proposed reuse claim. For an
   approval, evidence_quote must be the shortest verbatim phrase that proves
   reuse. If proof is absent or ambiguous, approved=false.
9. Return exactly one dimension_scopes item for every draft dimension. applies_to
   must be one of these ordered suffixes: [observationunit, sample, assay],
   [sample, assay], or [assay]. Do not add, remove, or rename dimensions.
   Each item must also contain semantic_role.
10. A nested mapping item contains only level and field_name. Its group and
    dimension are inherited from the containing mapping_decisions item. It may
    use only a level present in the audited applies_to scope.
11. Return exactly one record_column_decisions item for every column in each
    record-table profile used by a complete focal-study plan. For
    fairds_mapping, field_name must be copied exactly from the selected level's
    catalog. For source_extension, field_name must be null because code derives
    a stable label from the source header. Developmental-stage labels belong in
    a developmental-stage field rather than a generic organism-part field;
    adapter trimming is not library preparation; paired-end/single-end layout is
    not library source. When no exact standard term exists, source_extension is
    the correct high-coverage answer, not a loose free-text mapping.

Draft source claims:
{json.dumps(claims, indent=2, ensure_ascii=False)}

Value-bearing FAIR-DS fields by level:
{json.dumps(field_catalog, indent=2, ensure_ascii=False)}

Live FAIR-DS field definitions and value contracts:
{json.dumps(field_contract_catalog, indent=2, ensure_ascii=False)}

Authoritative metadata-table profiles, including source value examples:
        {json.dumps(table_profiles, indent=2, ensure_ascii=False)}
        """.strip()

    def _record_column_adjudication_prompt(
        self,
        claims: Mapping[str, Any],
        first_pass_audit: Mapping[str, Any],
        field_contract_catalog: Mapping[str, List[Mapping[str, Any]]],
        table_profiles: List[Mapping[str, Any]],
    ) -> str:
        """Build a focused second opinion for source-table field semantics.

        Cardinality and scope are intentionally absent from this prompt.  The
        first audit must not get to decide row structure and every column's
        scientific meaning in one very large response: those are different
        tasks, and a regex such as ``.*`` cannot validate semantic fit.
        """

        record_plans = [
            plan
            for plan in claims.get("record_table_plans") or []
            if isinstance(plan, Mapping) and plan.get("covers_complete_focal_study")
        ]
        first_decisions = first_pass_audit.get("record_column_decisions") or []
        return f"""
You are an independent FAIR-DS record-column semantic adjudicator. Review each
column of every authoritative focal-study metadata table. Return ONLY a JSON
object with record_column_decisions; the other EntityPlanScopeAuditResponse
arrays may be empty.

For every source column, return exactly one decision with source_id, table_name,
column, disposition, level, field_name, data_type, and rationale. Do not defer to
the first-pass decision: compare the source header, representative values, and
the live target-field definition.

Rules:
1. structural_only is limited to the declared filter, identity, group, and
   observation-unit grouping columns.
2. fairds_mapping requires exact semantic compatibility, not merely a permissive
   regex, similar wording, or a value that happens to validate. Prefer the most
   specific compatible field.
3. Keep material/anatomical identity, developmental or lifecycle state, sampling
   time, preparation method, read layout, adapter processing, accessions, and QC
   measurements conceptually distinct. A process setting is not a material
   characteristic; a category is not a protocol; a time point is not a lifecycle
   stage unless the source explicitly equates them.
4. If no exact selected-package field exists, use source_extension at the
   scientifically correct ISA level. This is the safe high-coverage result.
5. An informative nonblank column in an authoritative metadata table must not be
   discarded merely because it is redundant for one analysis. Use excluded only
   for a genuine result payload or computed scientific outcome, with a concrete
   rationale.
6. For source_extension, field_name must be null; code derives the stable label
   from the exact source header. For fairds_mapping, copy field_name exactly from
   the live catalog below.

Authoritative record plans:
{json.dumps(record_plans, indent=2, ensure_ascii=False)}

First-pass decisions to challenge, not copy:
{json.dumps(first_decisions, indent=2, ensure_ascii=False)}

Live FAIR-DS field definitions and value contracts:
{json.dumps(field_contract_catalog, indent=2, ensure_ascii=False)}

Authoritative table profiles with value distributions and example rows:
{json.dumps(table_profiles, indent=2, ensure_ascii=False)}
""".strip()

    @staticmethod
    def _apply_record_column_audit(
        claims: Dict[str, Any],
        audit: Mapping[str, Any],
        field_catalog: Mapping[str, List[str]],
        table_profiles: List[Mapping[str, Any]],
    ) -> tuple[List[str], List[str]]:
        """Apply independently audited, lossless source-column dispositions."""
        normalized_catalog = {
            level: {
                str(field).strip().lower(): str(field).strip()
                for field in fields
            }
            for level, fields in field_catalog.items()
        }
        profiles = {
            (
                str(profile.get("source_id") or "").strip(),
                str(profile.get("table_name") or "").strip(),
            ): profile
            for profile in table_profiles
            if isinstance(profile, Mapping)
        }
        decisions: Dict[tuple[str, str, str], List[Mapping[str, Any]]] = {}
        for item in audit.get("record_column_decisions") or []:
            if not isinstance(item, Mapping):
                continue
            source_id = str(item.get("source_id") or "").strip()
            table_name = str(item.get("table_name") or "").strip()
            column = str(item.get("column") or "").strip()
            if column and (not source_id or not table_name):
                matching_profiles = [
                    key
                    for key, profile in profiles.items()
                    if column
                    in {
                        str(candidate).strip()
                        for candidate in profile.get("columns") or []
                    }
                    and (not source_id or key[0] == source_id)
                    and (not table_name or key[1] == table_name)
                ]
                if len(matching_profiles) == 1:
                    source_id, table_name = matching_profiles[0]
            key = (
                source_id,
                table_name,
                column,
            )
            decisions.setdefault(key, []).append(item)

        applied: List[str] = []
        errors: List[str] = []
        for plan in claims.get("record_table_plans") or []:
            if not isinstance(plan, dict) or not plan.get("covers_complete_focal_study"):
                continue
            source_id = str(plan.get("source_id") or "").strip()
            table_name = str(plan.get("table_name") or "").strip()
            profile = profiles.get((source_id, table_name)) or {}
            columns = [str(column).strip() for column in profile.get("columns") or []]
            if not columns:
                errors.append(
                    f"Record-column audit cannot resolve table {source_id}:{table_name}."
                )
                continue
            filter_columns = {
                str(item.get("column") or "").strip()
                for item in plan.get("filters") or []
                if isinstance(item, Mapping)
            }
            identity_columns = {
                str(plan.get("sample_identifier_column") or "").strip(),
                str(plan.get("assay_identifier_column") or "").strip(),
            }
            group_column = str(plan.get("group_column") or "").strip()
            structural_only = filter_columns | identity_columns
            if group_column:
                structural_only.add(group_column)

            for column in columns:
                matches = decisions.get((source_id, table_name, column), [])
                if len(matches) != 1:
                    errors.append(
                        "Independent record-column audit omitted or duplicated "
                        f"{source_id}:{table_name}:{column}."
                    )
                    continue
                decision = matches[0]
                disposition = str(decision.get("disposition") or "").strip().lower()
                level = str(decision.get("level") or "").strip().lower()
                requested = str(decision.get("field_name") or "").strip().lower()
                rationale = " ".join(str(decision.get("rationale") or "").split())

                if disposition == "structural_only":
                    if column not in structural_only:
                        errors.append(
                            f"Record-column audit cannot hide metadata column {column!r} "
                            "as structural_only."
                        )
                    continue

                plan["column_mappings"] = [
                    item
                    for item in plan.get("column_mappings") or []
                    if not isinstance(item, Mapping)
                    or str(item.get("column") or "").strip() != column
                ]
                plan["source_extension_mappings"] = [
                    item
                    for item in plan.get("source_extension_mappings") or []
                    if not isinstance(item, Mapping)
                    or str(item.get("column") or "").strip() != column
                ]
                plan["excluded_columns"] = [
                    item
                    for item in plan.get("excluded_columns") or []
                    if not isinstance(item, Mapping)
                    or str(item.get("column") or "").strip() != column
                ]

                if disposition == "fairds_mapping":
                    canonical = normalized_catalog.get(level, {}).get(requested)
                    if level not in {"observationunit", "sample", "assay"} or not canonical:
                        errors.append(
                            f"Record-column audit returned unknown FAIR-DS target "
                            f"{level or '?'}.{requested or '?'} for {column!r}."
                        )
                        continue
                    plan["column_mappings"].append(
                        {"column": column, "level": level, "field_name": canonical}
                    )
                    applied.append(f"{source_id}:{column}->{level}.{canonical}")
                elif disposition == "source_extension":
                    if level not in {"observationunit", "sample", "assay"}:
                        errors.append(
                            f"Record-column audit returned invalid extension level "
                            f"{level or '?'} for {column!r}."
                        )
                        continue
                    plan["source_extension_mappings"].append(
                        {
                            "column": column,
                            "level": level,
                            "data_type": str(decision.get("data_type") or "string"),
                            "definition": rationale
                            or f"Source-supplied metadata column '{column}'.",
                        }
                    )
                    applied.append(f"{source_id}:{column}->{level}.source_extension")
                elif disposition == "excluded":
                    if not rationale:
                        errors.append(
                            f"Record-column audit exclusion for {column!r} lacks rationale."
                        )
                        continue
                    distribution = next(
                        (
                            item
                            for item in profile.get("column_distributions") or []
                            if isinstance(item, Mapping)
                            and str(item.get("column") or "").strip() == column
                        ),
                        {},
                    )
                    if int(distribution.get("nonblank") or 0) > 0:
                        # A table selected to enumerate the focal entities is a
                        # metadata boundary. Its populated non-structural columns
                        # remain record provenance even when they lack a standard
                        # term; exclusion here silently destroys source data.
                        # Use audited level context when present, otherwise the
                        # plan's structural column roles provide a generic level.
                        if level not in {"observationunit", "sample", "assay"}:
                            if column in {
                                str(item).strip()
                                for item in plan.get("assay_description_columns") or []
                            }:
                                level = "assay"
                            elif column in {
                                str(item).strip()
                                for item in plan.get("observation_unit_columns") or []
                            }:
                                level = "observationunit"
                            else:
                                level = "sample"
                        plan["source_extension_mappings"].append(
                            {
                                "column": column,
                                "level": level,
                                "data_type": str(decision.get("data_type") or "string"),
                                "definition": (
                                    "Populated source-record metadata retained instead "
                                    "of the proposed exclusion: " + rationale
                                ),
                            }
                        )
                        applied.append(
                            f"{source_id}:{column}->{level}.source_extension"
                        )
                        continue
                    plan["excluded_columns"].append(
                        {
                            "column": column,
                            "classification": "out_of_scope",
                            "reason": rationale,
                        }
                    )
                    applied.append(f"{source_id}:{column}->excluded")
                else:
                    errors.append(
                        f"Record-column audit returned invalid disposition "
                        f"{disposition or '?'} for {column!r}."
                    )
        return applied, errors

    @staticmethod
    def _apply_scope_audit_findings(
        claims: Dict[str, Any],
        audit: Mapping[str, Any],
        field_catalog: Mapping[str, List[str]],
    ) -> List[str]:
        """Add only exact, catalog-valid constant dimensions from the audit."""
        groups = {
            str(group.get("group_id") or ""): group
            for group in claims.get("design_groups") or []
            if isinstance(group, dict)
        }
        normalized_catalog = {
            level: {str(field).strip().lower(): str(field).strip() for field in fields}
            for level, fields in field_catalog.items()
        }
        propagation = {
            "observationunit": ["observationunit", "sample", "assay"],
            "sample": ["sample", "assay"],
            "assay": ["assay"],
        }
        added: List[str] = []
        for finding in audit.get("missing_conditions") or []:
            if not isinstance(finding, Mapping):
                continue
            group_id = str(finding.get("group_id") or "").strip()
            group = groups.get(group_id)
            level = str(finding.get("level") or "").strip().lower()
            source_value = str(finding.get("source_value") or "").strip()
            requested_field = str(finding.get("field_name") or "").strip().lower()
            dimension_name = str(finding.get("dimension_name") or "").strip()
            field_name = normalized_catalog.get(level, {}).get(requested_field)
            evidence = " ".join(str((group or {}).get("evidence") or "").split())
            if (
                not group
                or level not in propagation
                or not source_value
                or not dimension_name
                or not field_name
                or " ".join(source_value.split()).lower() not in evidence.lower()
            ):
                continue
            represented_values = {
                " ".join(str(value or "").split()).lower()
                for dimension in group.get("dimensions") or []
                if isinstance(dimension, dict)
                for value in (
                    list(dimension.get("explicit_values") or [])
                    + [
                        item.get("value")
                        for item in dimension.get("known_values") or []
                        if isinstance(item, dict)
                    ]
                )
                if str(value or "").strip()
            }
            normalized_value = " ".join(source_value.split()).lower()
            if normalized_value in represented_values:
                continue
            group.setdefault("dimensions", []).append(
                {
                    "name": dimension_name,
                    "level_count": 1,
                    "explicit_values": [source_value],
                    "known_values": [],
                    "origin": "explicit",
                    "field_mappings": [
                        {"level": level, "field_name": field_name}
                    ],
                    "field_name": None,
                    "applies_to": propagation[level],
                }
            )
            added.append(f"{group_id}:{level}.{field_name}={source_value}")
        return added

    @staticmethod
    def _enforce_independent_reuse_audit(
        claims: Dict[str, Any], audit: Mapping[str, Any]
    ) -> List[str]:
        """Fail closed on many-assays-per-sample claims without audit proof.

        When reuse is rejected, every varying assay-only dimension represents
        a distinct physical preparation path and is propagated through Sample.
        This preserves one traceable sample-to-assay path without inventing
        values or relying on domain-specific factor names.
        """
        validations = {
            str(item.get("group_id") or "").strip(): item
            for item in audit.get("reuse_validations") or []
            if isinstance(item, Mapping)
        }
        rejected: List[str] = []
        for group in claims.get("design_groups") or []:
            if not isinstance(group, dict) or not group.get(
                "reuse_same_sample_for_multiple_assays"
            ):
                continue
            group_id = str(group.get("group_id") or "").strip()
            validation = validations.get(group_id, {})
            quote = " ".join(str(validation.get("evidence_quote") or "").split())
            evidence = " ".join(str(group.get("evidence") or "").split())
            approved = bool(validation.get("approved")) and bool(
                quote and quote.lower() in evidence.lower()
            )
            if approved:
                group["sample_reuse_evidence"] = quote
                continue
            group["reuse_same_sample_for_multiple_assays"] = False
            group["sample_reuse_evidence"] = None
            for dimension in group.get("dimensions") or []:
                if not isinstance(dimension, dict):
                    continue
                scope = [
                    str(level or "").strip().lower()
                    for level in dimension.get("applies_to") or []
                ]
                if (
                    int(dimension.get("level_count") or 0) > 1
                    and "assay" in scope
                    and "sample" not in scope
                    and "observationunit" not in scope
                ):
                    dimension["applies_to"] = ["sample", "assay"]
            rejected.append(group_id or "unnamed design group")
        return rejected

    @staticmethod
    def _apply_dimension_scope_audit(
        claims: Dict[str, Any], audit: Mapping[str, Any]
    ) -> tuple[List[str], List[str]]:
        """Require independent agreement on every ISA dimension scope.

        Scope changes for varying dimensions alter row cardinality and parent
        linkage. Without an authoritative record table, a single audit response
        therefore cannot silently rewrite those claims. When a complete source
        record plan exists, the independent audit may repair the draft because
        deterministic table materialization subsequently verifies the resulting
        cardinality, identity, coverage, and parent relations.
        """
        allowed = {
            ("observationunit", "sample", "assay"),
            ("sample", "assay"),
            ("assay",),
        }
        semantic_roles = {
            "observation_condition",
            "sample_replicate",
            "material_path",
            "assay_process",
            "constant_characteristic",
            "other",
        }
        role_scopes = {
            "observation_condition": ("observationunit", "sample", "assay"),
            "sample_replicate": ("sample", "assay"),
            "material_path": ("sample", "assay"),
        }
        findings: Dict[tuple[str, str], Mapping[str, Any]] = {}
        duplicates: set[tuple[str, str]] = set()
        for item in audit.get("dimension_scopes") or []:
            if not isinstance(item, Mapping):
                continue
            key = (
                str(item.get("group_id") or "").strip(),
                str(item.get("dimension_name") or "").strip().lower(),
            )
            if key in findings:
                duplicates.add(key)
            findings[key] = item

        authoritative_record_plan = any(
            isinstance(plan, Mapping) and plan.get("covers_complete_focal_study")
            for plan in claims.get("record_table_plans") or []
        )

        applied: List[str] = []
        errors: List[str] = []
        for group in claims.get("design_groups") or []:
            if not isinstance(group, dict):
                continue
            group_id = str(group.get("group_id") or "").strip()
            for dimension in group.get("dimensions") or []:
                if not isinstance(dimension, dict):
                    continue
                dimension_name = str(dimension.get("name") or "").strip()
                key = (group_id, dimension_name.lower())
                finding = findings.get(key)
                if not finding or key in duplicates:
                    errors.append(
                        f"Independent scope audit omitted or duplicated {group_id}:"
                        f"{dimension_name}."
                    )
                    continue
                previous = tuple(dimension.get("applies_to") or [])
                draft_role = str(
                    dimension.get("semantic_role") or "other"
                ).strip().lower()
                audit_role = str(
                    finding.get("semantic_role") or "other"
                ).strip().lower()
                if draft_role not in semantic_roles or audit_role not in semantic_roles:
                    errors.append(
                        "Invalid semantic role for "
                        f"{group_id}:{dimension_name}: "
                        f"draft={draft_role!r}, audit={audit_role!r}."
                    )
                    continue
                if draft_role != audit_role and (
                    draft_role != "other" or audit_role != "other"
                ):
                    if not authoritative_record_plan:
                        errors.append(
                            "Independent semantic-role audit disagreed with the draft "
                            f"for {group_id}:{dimension_name}: "
                            f"draft={draft_role!r}, audit={audit_role!r}."
                        )
                        continue
                    dimension["semantic_role"] = audit_role
                    applied.append(
                        f"{group_id}:{dimension_name}.role={audit_role}"
                    )
                    draft_role = audit_role
                semantic_scope = role_scopes.get(draft_role)
                if draft_role == "assay_process":
                    semantic_scope = (
                        ("assay",)
                        if group.get("reuse_same_sample_for_multiple_assays")
                        else ("sample", "assay")
                    )
                if semantic_scope is not None:
                    if previous != semantic_scope:
                        dimension["applies_to"] = list(semantic_scope)
                        applied.append(
                            f"{group_id}:{dimension_name}="
                            f"{'/'.join(semantic_scope)}"
                        )
                    continue
                scope = tuple(
                    str(level or "").strip().lower()
                    for level in finding.get("applies_to") or []
                )
                # Without explicitly approved material reuse, a varying
                # assay-only factor necessarily creates distinct preparation
                # inputs. Normalize the audit to the traceable Sample→Assay
                # path before comparing it with the draft.
                if (
                    not group.get("reuse_same_sample_for_multiple_assays")
                    and int(dimension.get("level_count") or 0) > 1
                    and scope == ("assay",)
                ):
                    scope = ("sample", "assay")
                if scope not in allowed:
                    errors.append(
                        f"Independent scope audit returned invalid scope {list(scope)} "
                        f"for {group_id}:{dimension_name}."
                    )
                    continue
                if previous != scope:
                    explicit_count = len(
                        {
                            str(value).strip()
                            for value in dimension.get("explicit_values") or []
                            if str(value).strip()
                        }
                    )
                    dimension_count = int(dimension.get("level_count") or 0) or explicit_count
                    if dimension_count == 1 or authoritative_record_plan:
                        dimension["applies_to"] = list(scope)
                        applied.append(
                            f"{group_id}:{dimension_name}="
                            f"{'/'.join(scope)}"
                        )
                        continue
                    errors.append(
                        "Independent scope audit disagreed with the draft scope "
                        f"for {group_id}:{dimension_name}: "
                        f"draft={list(previous)}, audit={list(scope)}."
                    )
        return applied, errors

    @staticmethod
    def _apply_mapping_audit_findings(
        claims: Dict[str, Any],
        audit: Mapping[str, Any],
        field_catalog: Mapping[str, List[str]],
        knowledge: List[Dict[str, Any]],
    ) -> List[str]:
        """Apply only exact-catalog, contract-compatible mapping repairs."""
        groups = {
            str(group.get("group_id") or ""): group
            for group in claims.get("design_groups") or []
            if isinstance(group, dict)
        }
        normalized_catalog = {
            level: {str(field).strip().lower(): str(field).strip() for field in fields}
            for level, fields in field_catalog.items()
        }
        contracts = build_contract_index(knowledge)
        applied: List[str] = []
        for finding in audit.get("mapping_corrections") or []:
            if not isinstance(finding, Mapping):
                continue
            group_id = str(finding.get("group_id") or "").strip()
            dimension_name = str(finding.get("dimension_name") or "").strip()
            level = str(finding.get("level") or "").strip().lower()
            requested = str(finding.get("field_name") or "").strip().lower()
            group = groups.get(group_id)
            field_name = normalized_catalog.get(level, {}).get(requested)
            if not group or not dimension_name or not field_name:
                continue
            dimension = next(
                (
                    item
                    for item in group.get("dimensions") or []
                    if isinstance(item, dict)
                    and str(item.get("name") or "").strip().lower()
                    == dimension_name.lower()
                ),
                None,
            )
            if not dimension or level not in (dimension.get("applies_to") or []):
                continue
            values = list(dimension.get("explicit_values") or []) + [
                item.get("value")
                for item in dimension.get("known_values") or []
                if isinstance(item, Mapping)
            ]
            values = [value for value in values if str(value or "").strip()]
            # Unknown ordinal placeholders must never be written into a domain
            # field merely because the field accepts arbitrary text.
            if not values:
                continue
            contract = contract_for(contracts, level, field_name)
            if contract and any(canonicalize_value(value, contract) is None for value in values):
                continue
            mappings = [
                mapping
                for mapping in dimension.get("field_mappings") or []
                if isinstance(mapping, Mapping)
                and str(mapping.get("level") or "").strip().lower() != level
            ]
            mappings.append({"level": level, "field_name": field_name})
            dimension["field_mappings"] = mappings
            applied.append(f"{group_id}:{dimension_name}->{level}.{field_name}")
        return applied

    @staticmethod
    def _apply_complete_mapping_audit(
        claims: Dict[str, Any],
        audit: Mapping[str, Any],
        field_catalog: Mapping[str, List[str]],
        knowledge: List[Dict[str, Any]],
    ) -> tuple[List[str], List[str]]:
        """Replace every draft dimension mapping with an independent decision.

        A correction-only audit can silently accept both missing and semantically
        weak mappings.  This boundary instead requires one decision for every
        design dimension, validates it against live selected-package contracts,
        and reports unusable mapping suggestions without invalidating otherwise
        sound entity cardinality and linkage. Field mapping is a semantic
        enrichment boundary, not evidence that the planned entities exist.
        """
        dimensions: Dict[tuple[str, str], Dict[str, Any]] = {}
        for group in claims.get("design_groups") or []:
            if not isinstance(group, dict):
                continue
            group_id = str(group.get("group_id") or "").strip()
            for dimension in group.get("dimensions") or []:
                if not isinstance(dimension, dict):
                    continue
                dimension_name = str(dimension.get("name") or "").strip()
                if group_id and dimension_name:
                    dimensions[(group_id, dimension_name.lower())] = dimension

        decisions: Dict[tuple[str, str], List[Mapping[str, Any]]] = {}
        for decision in audit.get("mapping_decisions") or []:
            if not isinstance(decision, Mapping):
                continue
            key = (
                str(decision.get("group_id") or "").strip(),
                str(decision.get("dimension_name") or "").strip().lower(),
            )
            decisions.setdefault(key, []).append(decision)

        normalized_catalog = {
            level: {
                str(field).strip().lower(): str(field).strip()
                for field in fields
            }
            for level, fields in field_catalog.items()
        }
        contracts = build_contract_index(knowledge)
        applied: List[str] = []
        errors: List[str] = []

        for key, dimension in dimensions.items():
            matches = decisions.get(key, [])
            if len(matches) != 1:
                # An unaudited draft mapping must not leak into materialized
                # rows. Keep the factor/cardinality but fail closed on its
                # optional semantic projection.
                dimension["field_mappings"] = []
                errors.append(
                    "Independent mapping audit omitted or duplicated "
                    f"{key[0]}:{dimension.get('name')}."
                )
                continue

            applies_to = {
                str(level or "").strip().lower()
                for level in dimension.get("applies_to") or []
            }
            values = list(dimension.get("explicit_values") or []) + [
                item.get("value")
                for item in dimension.get("known_values") or []
                if isinstance(item, Mapping)
            ]
            values = [value for value in values if str(value or "").strip()]
            new_mappings: List[Dict[str, str]] = []
            seen_levels: set[str] = set()
            rejected_reasons: List[str] = []
            for mapping in matches[0].get("mappings") or []:
                if not isinstance(mapping, Mapping):
                    rejected_reasons.append("non-object target")
                    continue
                level = str(mapping.get("level") or "").strip().lower()
                requested = str(mapping.get("field_name") or "").strip().lower()
                field_name = normalized_catalog.get(level, {}).get(requested)
                if (
                    level not in applies_to
                    or level in seen_levels
                    or not field_name
                    or not values
                ):
                    rejected_reasons.append(
                        f"unusable target {level or '?'}:{requested or '?'}"
                    )
                    continue
                contract = contract_for(contracts, level, field_name)
                if contract and any(
                    canonicalize_value(value, contract) is None for value in values
                ):
                    rejected_reasons.append(
                        f"value-contract mismatch {level}.{field_name}"
                    )
                    continue
                seen_levels.add(level)
                new_mappings.append({"level": level, "field_name": field_name})

            previous = [
                mapping
                for mapping in dimension.get("field_mappings") or []
                if isinstance(mapping, Mapping)
            ]
            dimension["field_mappings"] = new_mappings
            if rejected_reasons:
                errors.append(
                    "Independent mapping audit rejected mapping target(s) for "
                    f"{key[0]}:{dimension.get('name')}: "
                    + ", ".join(rejected_reasons)
                    + "."
                )
            if previous != new_mappings:
                rendered = ",".join(
                    f"{item['level']}.{item['field_name']}" for item in new_mappings
                ) or "unmapped"
                applied.append(f"{key[0]}:{dimension.get('name')}->{rendered}")

        unexpected = sorted(set(decisions) - set(dimensions))
        for group_id, dimension_name in unexpected:
            errors.append(
                "Independent mapping audit referenced unknown dimension "
                f"{group_id}:{dimension_name}."
            )
        return applied, errors

    @traceable(name="EntityStructurePlanner", tags=["agent", "structure"])
    async def execute(self, state: FAIRifierState) -> FAIRifierState:
        self.log_execution(state, "🧱 Planning ISA entity cardinality and relations")
        source_text = read_document_text(state)
        source_fingerprint = hashlib.sha256(source_text.encode("utf-8")).hexdigest()
        existing_plan = state.get("entity_plan") or {}
        existing_validation = state.get("entity_plan_validation") or {}
        if (
            existing_plan.get("source_fingerprint") == source_fingerprint
            and existing_validation.get("passed") is True
        ):
            self.logger.info(
                "Entity structure plan locked for unchanged source; reusing rows=%s contacts=%s",
                existing_validation.get("row_counts", {}),
                existing_validation.get("investigation_contact_count", 0),
            )
            return state
        contacts = self._source_contacts(state)
        planning_knowledge = self._planning_knowledge(state)
        table_profiles = metadata_table_profiles(state.get("source_workspace") or {})
        plan: Dict[str, Any] = {}
        errors: List[str] = []
        best_plan: Dict[str, Any] = {}
        best_errors: List[str] = []
        best_rank: tuple[int, int, int, int] | None = None
        for attempt in range(1, 3):
            parsed = await invoke_structured_output(
                self.llm_helper,
                [HumanMessage(content=self._prompt(state, prior_errors=errors or None))],
                EntityDesignClaimsResponse,
                operation_name=f"EntityStructurePlanner.attempt_{attempt}",
                max_tokens=32768,
            )
            if not parsed:
                transport_error = "The model returned no parseable structure plan."
                if best_plan:
                    plan = best_plan
                    errors = [*best_errors, transport_error]
                else:
                    errors = [transport_error]
                continue
            claims = self._claims_payload(parsed)
            claims = normalize_claim_measurement_units(claims, source_text)
            audit_table_profiles = metadata_table_profiles_for_record_plans(
                state.get("source_workspace") or {},
                claims.get("record_table_plans") or [],
            )
            if not audit_table_profiles:
                audit_table_profiles = table_profiles
            field_catalog = self._field_catalog(planning_knowledge)
            field_contract_catalog = self._field_contract_catalog(planning_knowledge)
            scope_audit = await invoke_structured_output(
                self.llm_helper,
                [
                    HumanMessage(
                        content=self._scope_audit_prompt(
                            claims,
                            field_catalog,
                            field_contract_catalog,
                            audit_table_profiles,
                        )
                    )
                ],
                EntityPlanScopeAuditResponse,
                operation_name=f"EntityStructurePlanner.scope_audit_{attempt}",
                max_tokens=8192,
            )
            audit_payload = self._claims_payload(scope_audit) if scope_audit else {}
            rejected_reuse = self._enforce_independent_reuse_audit(
                claims, audit_payload
            )
            if rejected_reuse:
                self.log_execution(
                    state,
                    "🧪 Rejected unproven many-assays-per-sample reuse: "
                    + ", ".join(rejected_reuse),
                )
            scope_repairs, scope_audit_errors = self._apply_dimension_scope_audit(
                claims, audit_payload
            )
            if scope_repairs:
                self.log_execution(
                    state,
                    "🧬 Repaired ISA dimension scopes: " + ", ".join(scope_repairs),
                )
            mapping_repairs, mapping_audit_errors = self._apply_complete_mapping_audit(
                claims, audit_payload, field_catalog, planning_knowledge
            )
            if mapping_repairs:
                self.log_execution(
                    state,
                    "🧭 Independently audited dimension-to-FAIR-DS mappings: "
                    + ", ".join(mapping_repairs),
                )
            scope_additions = self._apply_scope_audit_findings(
                claims, audit_payload, field_catalog
            )
            if scope_additions:
                self.log_execution(
                    state,
                    "🔎 Restored source-explicit constant entity attributes: "
                    + ", ".join(scope_additions),
                )
            record_audit_payload = audit_payload
            if any(
                isinstance(record_plan, Mapping)
                and record_plan.get("covers_complete_focal_study")
                for record_plan in claims.get("record_table_plans") or []
            ):
                focused_record_audit = await invoke_structured_output(
                    self.llm_helper,
                    [
                        HumanMessage(
                            content=self._record_column_adjudication_prompt(
                                claims,
                                audit_payload,
                                field_contract_catalog,
                                audit_table_profiles,
                            )
                        )
                    ],
                    EntityPlanScopeAuditResponse,
                    operation_name=(
                        f"EntityStructurePlanner.record_column_audit_{attempt}"
                    ),
                    max_tokens=8192,
                )
                focused_payload = (
                    self._claims_payload(focused_record_audit)
                    if focused_record_audit
                    else {}
                )
                trial_claims = deepcopy(claims)
                trial_repairs, trial_errors = self._apply_record_column_audit(
                    trial_claims,
                    focused_payload,
                    field_catalog,
                    audit_table_profiles,
                )
                if not trial_errors:
                    claims = trial_claims
                    record_audit_payload = focused_payload
                    record_repairs = trial_repairs
                    record_audit_errors = []
                else:
                    self.log_execution(
                        state,
                        "⚠️ Focused record-column adjudication was incomplete; "
                        "falling back to the complete first-pass audit: "
                        + "; ".join(trial_errors[:4]),
                        "warning",
                    )
                    record_repairs, record_audit_errors = (
                        self._apply_record_column_audit(
                            claims,
                            record_audit_payload,
                            field_catalog,
                            audit_table_profiles,
                        )
                    )
            else:
                record_repairs, record_audit_errors = (
                    self._apply_record_column_audit(
                        claims,
                        record_audit_payload,
                        field_catalog,
                        audit_table_profiles,
                    )
                )
            if record_repairs:
                self.log_execution(
                    state,
                    "🧾 Independently audited source-table column dispositions: "
                    + ", ".join(record_repairs),
                )
            materialized = materialize_entity_claims(
                claims,
                field_catalog=field_catalog,
            )
            record_materialized, record_errors = materialize_record_table_plans(
                claims.get("record_table_plans") or [],
                workspace=state.get("source_workspace") or {},
                root_levels={
                    str(item.get("level") or ""): item
                    for item in materialized.get("levels") or []
                    if isinstance(item, Mapping)
                },
                field_catalog=field_catalog,
                design_groups=claims.get("design_groups") or [],
            )
            record_plan_succeeded = (
                record_materialized is not None and not record_errors
            )
            if record_plan_succeeded:
                record_materialized["design_claims"] = claims
                record_materialized["design_spec"] = materialized.get("design_spec") or {}
                materialized = record_materialized
                self.log_execution(
                    state,
                    "📋 Materialized exact focal-study records from an authoritative metadata table",
                )
            elif claims.get("record_table_plans"):
                materialized.setdefault("materialization_errors", []).extend(
                    record_errors
                )
            materialized = self._enforce_dimension_field_contracts(
                materialized,
                planning_knowledge,
            )
            plan = normalize_entity_plan(
                materialized,
                investigation_contacts=contacts,
            )
            plan["source_fingerprint"] = source_fingerprint
            errors = self._plan_errors(plan)
            if not record_plan_succeeded:
                errors.extend(scope_audit_errors)
            elif scope_audit_errors:
                plan.setdefault("unresolved_ambiguities", []).extend(
                    item
                    for item in scope_audit_errors
                    if item not in (plan.get("unresolved_ambiguities") or [])
                )
            if record_audit_errors:
                errors.extend(record_audit_errors)
            # Mapping suggestions cannot determine whether the entity graph is
            # structurally valid. Preserve their diagnostics as reviewable
            # ambiguities while allowing sound cardinality/linkage to proceed.
            if mapping_audit_errors:
                plan.setdefault("unresolved_ambiguities", []).extend(
                    item
                    for item in mapping_audit_errors
                    if item not in (plan.get("unresolved_ambiguities") or [])
                )
            candidate_rank = self._candidate_rank(
                plan,
                errors,
                used_authoritative_records=record_plan_succeeded,
            )
            if plan and (best_rank is None or candidate_rank > best_rank):
                best_plan = plan
                best_errors = list(errors)
                best_rank = candidate_rank
            if not errors:
                break

        if errors and best_plan:
            plan = best_plan
            errors = best_errors

        promoted_fields = self._promote_planned_fields(
            state, plan, planning_knowledge
        ) if plan and not errors else []
        if promoted_fields:
            plan["promoted_fields"] = promoted_fields
            self.log_execution(
                state,
                "🧩 Promoted plan-mapped FAIR-DS fields from selected packages: "
                + ", ".join(promoted_fields),
            )

        validation = {
            "passed": bool(plan) and not errors,
            "errors": errors,
            "row_counts": {
                str(level.get("level") or ""): len(level.get("entities") or [])
                for level in (plan.get("levels") or [])
                if isinstance(level, Mapping)
            },
            "investigation_contact_count": len(
                plan.get("investigation_contacts") or []
            ),
        }
        state["entity_plan"] = plan
        state["entity_plan_validation"] = validation
        state.setdefault("artifacts", {})["entity_plan"] = json.dumps(
            {"plan": plan, "validation": validation}, indent=2, ensure_ascii=False
        )
        self.update_confidence(state, "entity_structure", float(plan.get("confidence") or 0.0))
        if errors:
            state["needs_human_review"] = True
            state.setdefault("errors", []).extend(
                f"EntityStructurePlanner: {error}" for error in errors
            )
            self.logger.error("Entity structure plan failed validation: %s", errors)
        else:
            self.logger.info(
                "Entity structure plan ready: rows=%s contacts=%d",
                validation["row_counts"],
                validation["investigation_contact_count"],
            )
        return state


__all__ = ["EntityStructurePlannerAgent"]
