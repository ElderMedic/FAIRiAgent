"""Plan ISA entities and relations before metadata values are generated."""

from __future__ import annotations

import json
import hashlib
import re
from copy import copy, deepcopy
from typing import Any, Dict, List, Mapping

from langchain_core.messages import HumanMessage
from langsmith import traceable

from .base import BaseAgent
from ..config import FAIRifierConfig, config
from .response_models import (
    EntityDesignClaimsResponse,
    EntityPlanRecordColumnAuditResponse,
    EntityPlanScopeAuditResponse,
    MaterialInventoryResponse,
    ReportedAssayReviewResponse,
)
from ..models import FAIRifierState
from ..services.fairds_api_parser import FAIRDSAPIParser
from ..utils.document_text import normalize_source_evidence_text, read_document_text
from ..utils.entity_plan import (
    contacts_from_names,
    contacts_from_source_text,
    expand_table_row_templates,
    materialize_entity_claims,
    rebind_results_to_named_samples,
    materialize_reported_assays,
    materialize_reported_materials,
    normalize_claim_measurement_units,
    normalize_entity_plan,
    repair_reported_material_quotes,
    text_names,
    reported_parent_binding_digest,
)
from ..utils.llm_helper import get_llm_helper
from ..utils.metadata_table_plan import (
    materialize_record_table_plans,
    metadata_table_profiles,
    metadata_table_profiles_for_document_datasets,
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

# The largest curated FAIRiBench workbook has 40 rows at one level. A design
# group that crosses dimensions beyond this needs a source statement that every
# combination was run; otherwise the cross-product invents untested rows.
MAX_UNCONFIRMED_CROSSED_ROWS = 48
PHYSICAL_RELATION_AUDIT_VERSION = 1

_SCHEMA_SOURCE_RULES = """
Schema defines record roles and allowed values; source defines actual identities,
counts, and relationships. Read the selected field definitions and value contracts
before assigning roles or links. A material category does not establish a distinct
physical preparation. Repeated measurements do not by themselves establish new
material. Reference endpoints require source evidence: a schema reference field
specifies the permitted relationship, but does not prove which source entities are
linked or how many entities exist. If the source does not establish reuse or
distinct physical inputs, keep the physical relation unknown and record the
ambiguity for review. Do not infer a physical entity or link from a field name,
an allowed category, or a schema example.
""".strip()


def _quote_in_source(quote: Any, source_text: str | None) -> bool:
    """Authenticate an audit quote against supplied source text, not draft prose."""
    normalized = normalize_source_evidence_text(quote)
    return bool(normalized and normalized in normalize_source_evidence_text(source_text))


def _review_quote_in_source(quote: Any, source_text: str | None, threshold: float = 0.92) -> bool:
    """Verbatim, or near-verbatim, presence of a reviewer quote in the source.

    Models often re-type a quote with small differences (spacing, dashes,
    rendered markup). Accept a quote of at least six words when at least
    ``threshold`` of its characters match, in order, one contiguous source
    window. An invented quote does not reach this similarity.
    """
    if _quote_in_source(quote, source_text):
        return True
    from difflib import SequenceMatcher

    needle = normalize_source_evidence_text(quote)
    haystack = normalize_source_evidence_text(source_text)
    words = needle.split()
    if len(words) < 6 or not haystack:
        return False
    anchors = {" ".join(words[i:i + 3]) for i in range(0, len(words) - 2, max(1, len(words) // 6))}
    for anchor in anchors:
        start = haystack.find(anchor)
        while start != -1:
            window = haystack[max(0, start - len(needle)): start + 2 * len(needle)]
            blocks = SequenceMatcher(None, window, needle, autojunk=False).get_matching_blocks()
            if sum(block.size for block in blocks) >= threshold * len(needle):
                return True
            start = haystack.find(anchor, start + 1)
    return False


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
    def _preferred_dataset_profiles(
        profiles: List[Mapping[str, Any]],
        source_text: str = "",
    ) -> List[Mapping[str, Any]]:
        """Keep dataset-table candidates explicitly described as focal.

        A manuscript can mention many public datasets used for comparison.  A
        longer candidate list both dilutes the focal evidence and makes the
        structure prompt needlessly large.  Positive scores are assigned only
        from source phrases such as "this study" or "generated in this work";
        when no such phrase exists, retain the candidates for model judgement.
        """
        focal_cues = (
            "this study",
            "this work",
            "current study",
            "present study",
            "our study",
            "our work",
            "generated in",
            "generated by",
            "generated during",
            "produced in",
            "produced by",
            "data from this",
            "all sequencing data",
            "data are deposited",
            "data were deposited",
            "have been submitted",
        )
        contextual_cues = (
            "reused",
            "previously published",
            "external dataset",
            "reference dataset",
            "contextual dataset",
        )
        source_segments = [
            segment.strip().lower()
            for segment in re.split(r"(?:\r?\n)+|(?<=[.!?])\s+", source_text)
            if segment.strip()
        ]
        rescored: List[Mapping[str, Any]] = []
        for raw_profile in profiles:
            profile = dict(raw_profile)
            score = int(profile.get("focal_evidence_score") or 0)
            filter_values = [
                str(item.get("value") or "").strip()
                for item in profile.get("applied_filters") or []
                if isinstance(item, Mapping) and str(item.get("value") or "").strip()
            ]
            for value in filter_values:
                for context in source_segments:
                    if value.lower() not in context:
                        continue
                    context_score = sum(
                        2 for cue in focal_cues if cue in context
                    ) - sum(2 for cue in contextual_cues if cue in context)
                    score = max(score, context_score)
            profile["focal_evidence_score"] = score
            rescored.append(profile)
        rescored.sort(
            key=lambda item: (
                -int(item.get("focal_evidence_score") or 0),
                str(item.get("source_id") or ""),
                str(item.get("table_name") or ""),
            )
        )
        positive = [
            profile
            for profile in rescored
            if int(profile.get("focal_evidence_score") or 0) > 0
        ]
        return positive or rescored[:8]

    @staticmethod
    def _candidate_record_plan_errors(
        claims: Mapping[str, Any],
        profiles: List[Mapping[str, Any]],
    ) -> List[str]:
        """Require the planner to address strong source-enumerated evidence."""
        strong_profiles = [
            profile
            for profile in profiles
            if int(profile.get("focal_evidence_score") or 0) > 0
        ]
        if not strong_profiles:
            return []
        plans = [
            plan
            for plan in claims.get("record_table_plans") or []
            if isinstance(plan, Mapping)
        ]
        errors: List[str] = []
        for profile in strong_profiles:
            expected_filters = {
                (
                    str(item.get("column") or "").strip(),
                    str(item.get("value") or "").strip(),
                )
                for item in profile.get("applied_filters") or []
                if isinstance(item, Mapping)
            }
            addressed = False
            complete_exact = False
            for plan in plans:
                if (
                    str(plan.get("source_id") or "").strip()
                    != str(profile.get("source_id") or "").strip()
                    or str(plan.get("table_name") or "").strip()
                    != str(profile.get("table_name") or "").strip()
                ):
                    continue
                plan_filters = {
                    (
                        str(item.get("column") or "").strip(),
                        str(item.get("value") or "").strip(),
                    )
                    for item in plan.get("filters") or []
                    if isinstance(item, Mapping)
                }
                if expected_filters <= plan_filters:
                    addressed = True
                    complete_exact = bool(
                        plan.get("covers_complete_focal_study")
                        and plan_filters == expected_filters
                    )
                    break
            if not addressed:
                rendered_filter = ", ".join(
                    f"{column}={value}" for column, value in sorted(expected_filters)
                )
                errors.append(
                    "The source explicitly identifies a focal dataset and an exact "
                    "metadata-table subset enumerates its records, but the plan did "
                    "not address that table/filter: "
                    f"{profile.get('source_id')}:{profile.get('table_name')} "
                    f"({rendered_filter}; {profile.get('record_count')} records). "
                    "Return a record_table_plans entry for this exact subset before "
                    "using a prose-derived Cartesian design."
                )
            elif (
                int(profile.get("focal_evidence_score") or 0) >= 4
                and not complete_exact
            ):
                rendered_filter = ", ".join(
                    f"{column}={value}" for column, value in sorted(expected_filters)
                )
                errors.append(
                    "The source states that the dataset contains the focal study "
                    "data, but its record-table plan was marked incomplete or was "
                    "narrowed beyond the dataset boundary. Use exactly "
                    f"{rendered_filter} ({profile.get('record_count')} records), "
                    "set covers_complete_focal_study=true, and preserve all "
                    "experimental branches within that subset."
                )
        return errors

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
        """Expose compact live field semantics to planning and mapping audits.

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
    def _requires_physical_relation_reaudit(plan: Mapping[str, Any]) -> bool:
        """Identify legacy plans affected by the unproven-reuse fallback."""
        if plan.get("physical_relation_audit_version") == PHYSICAL_RELATION_AUDIT_VERSION:
            return False
        coverage = plan.get("source_coverage") or {}
        if coverage.get("complete") and coverage.get("tables"):
            return False
        for group in (plan.get("design_claims") or {}).get("design_groups") or []:
            if not isinstance(group, Mapping):
                continue
            if group.get("reuse_same_sample_for_multiple_assays"):
                return True
            if group.get("sample_reuse_audit_status") == "unresolved":
                return True
            for dimension in group.get("dimensions") or []:
                if not isinstance(dimension, Mapping):
                    continue
                count = int(dimension.get("level_count") or 0) or len(
                    dimension.get("explicit_values") or []
                )
                role = str(dimension.get("semantic_role") or "other").strip().lower()
                scope = tuple(dimension.get("applies_to") or [])
                if count > 1 and "assay" in scope and (
                    role == "assay_process"
                    or (role == "other" and scope in {("assay",), ("sample", "assay")})
                ):
                    return True
        return False

    @staticmethod
    def _plan_errors(
        plan: Mapping[str, Any], *, source_text: str | None = None,
    ) -> List[str]:
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
        samples = {row["row_id"]: row for row in (levels.get("sample") or {}).get("entities") or []}
        reviewed_results: set[str] = set()
        receipts = plan.get("reported_assay_reviews") or {}
        fingerprint = (hashlib.sha256(source_text.encode()).hexdigest()
                       if source_text is not None else plan.get("source_fingerprint"))
        material_receipts = plan.get("reported_material_reviews") or {}
        reviewed_materials: set[str] = set()
        for level_name, parent_name in (("observationunit", "study"), ("sample", "observationunit")):
            parents = {row["row_id"]: row for row in (levels.get(parent_name) or {}).get("entities") or []}
            for row in (levels.get(level_name) or {}).get("entities") or []:
                if row.get("record_kind") not in {"material_preparation", "material_identity"}:
                    continue
                key = row["row_id"]
                parent = parents.get(row.get("parent_row_id"))
                receipt = material_receipts.get(key) or {}
                if (parent and receipt.get("source_sha256") == fingerprint
                        and receipt.get("record_sha256") == EntityStructurePlannerAgent._reported_record_digest(row, parent)):
                    reviewed_materials.add(key)
                else:
                    errors.append(f"Reported material {key} lacks a current independent review.")
        for proposal in (plan.get("design_claims") or {}).get("reported_materials") or []:
            if proposal.get("record_id") not in reviewed_materials:
                errors.append(f"Reported material {proposal.get('record_id')} was not materialized and reviewed.")
        for row in (levels.get("assay") or {}).get("entities") or []:
            if row.get("record_kind") not in {"fitted_result", "aggregate_result", "qualitative_result"}:
                continue
            key = row["row_id"]
            parent = samples.get(row.get("parent_row_id"))
            receipt = receipts.get(key) or {}
            if (parent and receipt.get("source_sha256") == fingerprint
                    and receipt.get("record_sha256") == EntityStructurePlannerAgent._reported_record_digest(row, parent)):
                reviewed_results.add(key)
            else:
                errors.append(f"Reported assay {key} lacks a current independent review.")
        for proposal in (plan.get("design_claims") or {}).get("reported_assays") or []:
            if proposal.get("record_id") not in reviewed_results:
                errors.append(f"Reported assay {proposal.get('record_id')} was not materialized and reviewed.")
        claims_groups = {
            str(group.get("group_id") or ""): group
            for group in ((plan.get("design_claims") or {}).get("design_groups") or [])
            if isinstance(group, Mapping)
        }
        # Equal row counts do not resolve an uncertain physical-input relation.
        # Fully materialized source records can establish identities and links
        # directly; a draft's claimed table coverage alone cannot do so.
        verified_records = bool(coverage_tables) and bool(source_coverage.get("complete"))
        if not verified_records:
            for group_id, claim in claims_groups.items():
                if claim.get("sample_reuse_audit_status") == "unresolved":
                    errors.append(
                        f"Unresolved physical sample relation for design group {group_id}; "
                        "source evidence must establish shared or distinct inputs."
                    )
                for dimension in claim.get("dimensions") or []:
                    if isinstance(dimension, Mapping) and dimension.get("physical_relation_review_required"):
                        errors.append(
                            f"Unresolved physical sample relation for {group_id}:"
                            f"{dimension.get('name')}; cardinality requires source review."
                        )
        entities_by_level_group: Dict[str, Dict[str, int]] = {
            level: {} for level in ("observationunit", "sample", "assay")
        }
        for level in ("observationunit", "sample", "assay"):
            for entity in (levels.get(level) or {}).get("entities") or []:
                if not isinstance(entity, Mapping):
                    continue
                if level == "assay" and entity.get("row_id") in reviewed_results:
                    # An analysis result does not assert another physical run.
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
            evidence_is_exact = (
                _quote_in_source(reuse_evidence, source_text)
                if source_text is not None
                else bool(reuse_evidence and reuse_evidence in group_evidence)
            )
            assay_only_dimensions = [
                dimension for dimension in claim.get("dimensions") or []
                if isinstance(dimension, Mapping)
                and tuple(dimension.get("applies_to") or []) == ("assay",)
                and int(dimension.get("level_count") or 0) > 1
            ]
            dimension_reuse = bool(assay_only_dimensions) and all(
                dimension.get("sample_relation") == "same_sample"
                and dimension.get("sample_relation_source_verified") is True
                and (
                    source_text is None
                    or _quote_in_source(dimension.get("sample_relation_evidence"), source_text)
                )
                for dimension in assay_only_dimensions
            )
            if dimension_reuse and not any(
                isinstance(dimension, Mapping) and dimension.get("physical_relation_review_required")
                for dimension in claim.get("dimensions") or []
            ):
                reuse_allowed = evidence_is_exact = True
            if not reuse_allowed or not evidence_is_exact:
                errors.append(
                    f"Design group {group_id} creates {assay_count} assay rows from "
                    f"only {sample_count} sample rows without an explicit source quote "
                    "authorizing reuse of the same sample. Resolve the physical input "
                    "relationship from source evidence; do not infer distinct Samples "
                    "from missing reuse evidence."
                )
        if not coverage_tables:
            for group_id, claim in claims_groups.items():
                group_evidence = " ".join(str(claim.get("evidence") or "").split())
                factorial_quote = " ".join(
                    str(claim.get("full_factorial_evidence") or "").split()
                )
                if factorial_quote and factorial_quote.lower() in group_evidence.lower():
                    continue
                for level in ("observationunit", "sample", "assay"):
                    crossed = []
                    for dimension in claim.get("dimensions") or []:
                        if not isinstance(dimension, Mapping):
                            continue
                        scope = {
                            str(item).strip().lower()
                            for item in dimension.get("applies_to") or []
                        }
                        try:
                            level_count = int(dimension.get("level_count") or 0)
                        except (TypeError, ValueError):
                            level_count = 0
                        if level in scope and level_count > 1:
                            crossed.append(
                                f"{dimension.get('name')} ({level_count})"
                            )
                    rows = entities_by_level_group[level].get(group_id, 0)
                    if len(crossed) >= 2 and rows > MAX_UNCONFIRMED_CROSSED_ROWS:
                        errors.append(
                            f"Design group {group_id} crosses {' x '.join(crossed)} "
                            f"into {rows} {level} rows. Code builds every combination "
                            "of a group's dimensions. Keep them in one group only if "
                            "the source states that every combination was run, and "
                            "copy that sentence into full_factorial_evidence. "
                            "Otherwise split the group into one design group per "
                            "tested branch, each with only the levels it received."
                        )
                        break
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
    ) -> tuple[int, int, int, int, int]:
        """Rank retry candidates by deterministic validity and source fidelity.

        Counting diagnostics alone can prefer a coarse Cartesian fallback over
        a successfully materialized authoritative table.  A valid candidate is
        always best; among invalid candidates, exact source records and complete
        source-column disposition and currently verified reported results
        outrank the raw number of diagnostics.
        """
        source_coverage = plan.get("source_coverage") or {}
        coverage_complete = bool(source_coverage.get("tables")) and bool(
            source_coverage.get("complete")
        )
        rows = {
            row["row_id"]: row for level in plan.get("levels") or []
            for row in level.get("entities") or [] if row.get("row_id")
        }
        fingerprint = plan.get("source_fingerprint")
        reviewed_results = 0
        for row_id, receipt in (plan.get("reported_assay_reviews") or {}).items():
            row = rows.get(row_id) or {}
            parent = rows.get(row.get("parent_row_id"))
            if (
                fingerprint and parent
                and row.get("record_kind") in {"fitted_result", "aggregate_result", "qualitative_result"}
                and receipt.get("source_sha256") == fingerprint
                and receipt.get("record_sha256") == EntityStructurePlannerAgent._reported_record_digest(row, parent)
            ):
                reviewed_results += 1
        return (
            int(bool(plan) and not errors),
            int(used_authoritative_records),
            int(coverage_complete),
            reviewed_results,
            -len(errors),
        )

    def _prompt(
        self,
        state: FAIRifierState,
        *,
        prior_errors: List[str] | None = None,
    ) -> str:
        # The scope audit reads the full working text but cannot add omitted
        # design groups. Give initial planning the same source, including late
        # methods/results, before cardinality and parent links are locked.
        document_text = read_document_text(state)
        document_info = state.get("document_info") or {}
        planning_knowledge = self._planning_knowledge(state)
        field_catalog = self._field_catalog(planning_knowledge)
        field_contract_catalog = self._field_contract_catalog(planning_knowledge)
        table_profiles = metadata_table_profiles(state.get("source_workspace") or {})
        dataset_profiles = metadata_table_profiles_for_document_datasets(
            state.get("source_workspace") or {},
            document_info.get("datasets_mentioned") or [],
        )
        dataset_profiles = list(
            self._preferred_dataset_profiles(
                dataset_profiles, read_document_text(state)
            )
        )
        if dataset_profiles:
            focused_tables = {
                (str(item.get("source_id") or ""), str(item.get("table_name") or ""))
                for item in dataset_profiles
            }
            table_profiles = dataset_profiles + [
                item
                for item in table_profiles
                if (
                    str(item.get("source_id") or ""),
                    str(item.get("table_name") or ""),
                )
                not in focused_tables
            ]
        correction = ""
        if prior_errors:
            shown = prior_errors[:20]
            omitted = len(prior_errors) - len(shown)
            correction = (
                "\nThe previous plan failed deterministic validation. Correct every issue below. "
                "If one issue cannot be removed without dropping the study, keep the closest "
                "complete plan and record that residual in unresolved_ambiguities. Always return "
                "a plan:\n- "
                + "\n- ".join(shown)
                + (f"\n- {omitted} further issues were omitted; fix the same patterns." if omitted else "")
            )
        return f"""
You are the structure-planning stage of FAIRiAgent. Determine the ISA entity
matrix before any metadata values are filled. This is a scientific data-model
task, not a prose summarization task.

{_SCHEMA_SOURCE_RULES}

Hard rules:
1. Return COMPACT SOURCE DESIGN CLAIMS for individually enumerated experiments.
   Use reported_materials and reported_assays for source-reported material
   identities and aggregate/fitted results as specified in rule 14. For each independent
   experimental branch, state each dimension's level_count once and which of
   observationunit, sample, assay it applies to. Code will build the cross-products.
2. Use FAIR-DS ISOSA semantics and the curated workbook convention. An
   observationunit is the experimental unit or condition being observed; a sample
   is a source-described material record; an assay is a preparation, measurement
   or analysis record. A material identity is not a claim that only one physical
   vial existed. Label the source-supported grain explicitly. For individual
   experimental records, biological replicates are normally separate
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
   on that same sample. Add distinct Samples only when the source establishes
   distinct physical inputs. Otherwise preserve the uncertainty for review;
   absence of reuse evidence does not establish distinct material.
3. For individual experimental inventories, represent every stated factorial
   design and replicate count. Do not expand aggregate results into replicas.
   If N levels are
   stated but their names are absent, set level_count=N, explicit_values=[],
   origin=derived, and record the missing labels as an ambiguity. Never invent
   or enumerate plausible scientific labels; code creates ordinal placeholders.
   level_count must be a positive integer when the source establishes the total.
   If the total is unknown, set level_count=null and record the missing count in
   unresolved_ambiguities. Do not replace an unknown count with 0 or 1 to satisfy
   the schema. An unknown count remains unresolved and requires review; it does
   not authorize materializing a complete design.
   A stated range or a few examples/endpoints are not a complete enumeration.
   Keep explicit_values=[] and use known_values=[{{"position": 1, "value":
   "source label"}}, ...] only when the source fixes an ordinal position (for
   example the first and last values of a stated range). Unknown positions stay
   derived ordinal placeholders. Quote the incompleteness in the ambiguity.
   When the total is unknown but the source states the span (for example
   "incubated at temperatures ranging from 30–80 °C"), also copy that span
   verbatim into reported_range and give the dimension its field_mappings.
   The span is recorded as one value on the group's rows; it never creates rows.
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
    that exact phrase into sample_reuse_evidence. A false reuse flag means only
    that reuse is unproven. Do not use it to create distinct Sample rows.
11. Code builds EVERY combination of the dimensions in a design group. Put two
    multi-level dimensions in the same group only when the source states that
    every combination was run, and copy that sentence into
    full_factorial_evidence. When the source tested a subset (for example
    different enzyme variants under different conditions, or one assay type on
    only some samples), use one design group per tested branch, each with only
    the levels that branch received. A group that crosses dimensions into more
    than {MAX_UNCONFIRMED_CROSSED_ROWS} rows at one level is rejected unless
    full_factorial_evidence quotes the group evidence.
11. Give every design group a concise scientific label derived from its stated
    purpose or factors. group_id is an internal key and must not be used as the
    human-readable label.
12. Be terse and reference shared material IDs instead of repeating their records.
    Preserve all independently reported branches and results.
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

14. Preserve reported means, fitted parameters and qualitative results even
    when the underlying experiment count is unknown. Use reported_materials to
    declare source-described preparation ObservationUnits (material_preparation)
    and material Samples (material_identity), with exact source_subject labels,
    source_quote, record_id, parent_row_id, label and source_group. These are
    material identities, not invented individual vessels or aliquots. Their
    roles and parent links must fit the selected package and source evidence.
    Use reported_assays for aggregate_result, fitted_result or qualitative_result
    records. Reference a declared material Sample record_id in sample_row_id;
    never guess an ID that code may generate from a factorial design. Include
    source_subject, a verbatim source_quote and attributes containing exact
    selected Assay field_name/value pairs. Preserve source values and units;
    normalisation happens after planning. A value read from a table cell
    takes its unit from the column or row header (e.g. header "Km (mM)" and
    cell "1.15 ± 0.01" give "1.15 ± 0.01 mM"); never drop a header unit. When a
    table reports the same measurements for many materials, one per row, propose
    ONE record for one of those rows: quote that complete HTML row, name its
    material, map each measured cell, and set repeat_for_table_rows=true. Code
    repeats it for every other row of the table, reading each value from the same
    column, so do not list the other rows yourself. When the columns are levels of
    one condition (e.g. 55 °C, 62 °C, 70 °C), propose one such record per column,
    each with that column's condition. Put missing underlying counts in
    unreported_design, not in a fabricated one-level factor. Never assign a
    group mean to a single replicate. Keep distinct materials and measurement
    conditions separate. Do not duplicate these records in design_groups or
    complete source-table plans. If material identity or parentage is unknown,
    retain the uncertainty rather than inventing a link. All reported records
    receive independent source/schema review before they are accepted.

Required nested JSON shape (use these exact keys; this is a structural example,
not a design to copy):
design_summary and unresolved_ambiguities are lists of strings, not objects.
Use one short source-supported statement per string, or an empty list.
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
    "full_factorial_evidence": null,
    "dimensions": [{{
      "name": "factor_name", "level_count": 2,
      "explicit_values": ["control", "treated"], "origin": "explicit",
      "semantic_role": "observation_condition",
      "known_values": [], "reported_range": null,
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
  "reported_materials": [], "reported_assays": [],
  "design_summary": [], "unresolved_ambiguities": [], "confidence": 0.85
}}

Parsed document information:
{json.dumps(document_info, indent=2, ensure_ascii=False)}

Available FAIR-DS fields by level:
{json.dumps(field_catalog, indent=2, ensure_ascii=False)}

Live FAIR-DS field definitions and value contracts:
{json.dumps(field_contract_catalog, indent=2, ensure_ascii=False)}

Authoritative source metadata-table profiles (schema, distributions, and
examples; code retains the complete tables for deterministic row selection):
{json.dumps(table_profiles, indent=2, ensure_ascii=False)}

Profiles carrying candidate_filter_requires_planner_confirmation were selected
deterministically because an exact table value occurs in the parsed document's
datasets_mentioned evidence. Treat the applied filter as a strong focal-record
candidate, but independently confirm completeness. Do not add a narrower branch
filter when the cited dataset contains multiple experimental branches.

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
        *,
        source_text: str = "",
    ) -> str:
        return f"""
You are the semantic scope-and-field-mapping audit for an ISA entity plan.

{_SCHEMA_SOURCE_RULES}

Perform four bounded checks:
A. Find source-explicit constant experimental conditions omitted from a design
   group. A constant has one value and does not increase row count.
B. Return exactly one mapping_decisions item for EVERY existing dimension,
   independently replacing its draft field_mappings. Each decision contains zero
   or more exact FAIR-DS mappings. Use an empty mappings list when no semantically
   correct field exists. Field definitions and value contracts are provided below.
   mapping_corrections is legacy-only and must be an empty list.
C. Independently verify every design group that sets
   reuse_same_sample_for_multiple_assays=true. Approve only if the actual source
   explicitly says the same identified physical material was reused,
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
   reuse in the actual source, not merely in the draft claims. If proof is absent
   or ambiguous, approved=false. That does not establish distinct physical inputs.
9. Return exactly one dimension_scopes item for every draft dimension. applies_to
   must be one of these ordered suffixes: [observationunit, sample, assay],
   [sample, assay], or [assay]. Do not add, remove, or rename dimensions.
   Each item must also contain semantic_role, sample_relation, and evidence_quote.
   For each varying preparation/measurement axis, sample_relation is same_sample,
   distinct_samples, or unknown. Support either positive relation with a verbatim
   actual-source quote specific to that axis. Use unknown when the source does not
   distinguish repeated readouts from separate material inputs. Do not infer one
   axis's physical relation from another axis or from a group-wide reuse flag.
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

Draft claims (proposals, not an authoritative quote corpus):
{json.dumps(claims, indent=2, ensure_ascii=False)}

Actual document source (may extend beyond the draft's opening excerpt):
{source_text or "(No document source supplied; retain unresolved physical relations.)"}

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
object with the single top-level key record_column_decisions. This focused
response has no mapping_corrections, mapping_decisions, dimension_scopes,
reuse_validations, or missing_conditions keys.

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
        claims: Dict[str, Any], audit: Mapping[str, Any], *, source_text: str | None = None,
    ) -> List[str]:
        """Fail closed on many-assays-per-sample claims without audit proof.

        Rejected or missing proof leaves the physical relation unresolved. It
        must not create distinct Sample rows or authorize reuse by default.
        """
        validations: Dict[str, List[Mapping[str, Any]]] = {}
        for item in audit.get("reuse_validations") or []:
            if isinstance(item, Mapping):
                validations.setdefault(str(item.get("group_id") or "").strip(), []).append(item)
        rejected: List[str] = []
        for group in claims.get("design_groups") or []:
            if not isinstance(group, dict) or not group.get(
                "reuse_same_sample_for_multiple_assays"
            ):
                continue
            group_id = str(group.get("group_id") or "").strip()
            matches = validations.get(group_id, [])
            validation = matches[0] if len(matches) == 1 else {}
            quote = " ".join(str(validation.get("evidence_quote") or "").split())
            approved = validation.get("approved") is True and _quote_in_source(quote, source_text)
            if approved:
                group["sample_reuse_evidence"] = quote
                group["sample_reuse_audit_status"] = "approved"
                continue
            group["reuse_same_sample_for_multiple_assays"] = False
            group["sample_reuse_evidence"] = None
            group["sample_reuse_audit_status"] = "unresolved"
            for dimension in group.get("dimensions") or []:
                if not isinstance(dimension, dict):
                    continue
                scope = [
                    str(level or "").strip().lower()
                    for level in dimension.get("applies_to") or []
                ]
                if (
                    int(dimension.get("level_count") or 0) > 1
                    and (
                        scope == ["assay"]
                        or dimension.get("semantic_role") == "assay_process"
                    )
                ):
                    dimension["physical_relation_review_required"] = True
            rejected.append(group_id or "unnamed design group")
        return rejected

    @staticmethod
    def _apply_dimension_scope_audit(
        claims: Dict[str, Any], audit: Mapping[str, Any], *, source_text: str | None = None,
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
                if int(dimension.get("level_count") or 0) > 1 and (
                    dimension.get("semantic_role") == "assay_process"
                    or (
                        dimension.get("semantic_role", "other") == "other"
                        and tuple(dimension.get("applies_to") or [])
                        in {("assay",), ("sample", "assay")}
                    )
                ):
                    dimension["physical_relation_review_required"] = True
                finding = findings.get(key)
                if not finding or key in duplicates:
                    errors.append(
                        f"Independent scope audit omitted or duplicated {group_id}:"
                        f"{dimension_name}."
                    )
                    if (
                        int(dimension.get("level_count") or 0) > 1
                        and (
                            dimension.get("semantic_role") == "assay_process"
                            or tuple(dimension.get("applies_to") or []) == ("assay",)
                        )
                    ):
                        dimension["physical_relation_review_required"] = True
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
                scope = tuple(
                    str(level or "").strip().lower()
                    for level in finding.get("applies_to") or []
                )
                if scope not in allowed:
                    errors.append(
                        f"Independent scope audit returned invalid scope {list(scope)} "
                        f"for {group_id}:{dimension_name}."
                    )
                    continue
                explicit_count = len({
                    str(value).strip() for value in dimension.get("explicit_values") or []
                    if str(value).strip()
                })
                dimension_count = int(dimension.get("level_count") or 0) or explicit_count
                relation = str(finding.get("sample_relation") or "unknown").strip()
                quote = " ".join(str(finding.get("evidence_quote") or "").split())
                relation_scope = {
                    "same_sample": ("assay",),
                    "distinct_samples": ("sample", "assay"),
                }.get(relation)
                if (
                    relation == "distinct_samples"
                    and draft_role == "observation_condition"
                    and scope == ("observationunit", "sample", "assay")
                ):
                    # Distinct observed units can each supply a distinct sample.
                    # Keep their independently audited ObservationUnit grouping;
                    # a material distinction need not start at Sample.
                    relation_scope = scope
                verified_relation = bool(
                    relation_scope is not None
                    and scope == relation_scope
                    and _quote_in_source(quote, source_text)
                )
                relation_required = dimension_count > 1 and (
                    draft_role == "assay_process"
                    or bool(dimension.get("physical_relation_review_required"))
                    or (draft_role == "other" and (scope == ("assay",) or previous == ("assay",)))
                    or relation != "unknown"
                )
                if relation_required and not verified_relation:
                    dimension["sample_relation"] = "unknown"
                    dimension["sample_relation_source_verified"] = False
                    dimension["physical_relation_review_required"] = True
                    errors.append(
                        f"Unresolved physical sample relation for {group_id}:{dimension_name}; "
                        "the source must establish shared or distinct inputs."
                    )
                    if previous != scope:
                        errors.append(
                            "Independent scope audit disagreed with the draft scope "
                            f"for {group_id}:{dimension_name}: "
                            f"draft={list(previous)}, audit={list(scope)}."
                        )
                    continue
                if verified_relation:
                    dimension["sample_relation"] = relation
                    dimension["sample_relation_evidence"] = quote
                    dimension["sample_relation_source_verified"] = True
                    dimension["physical_relation_review_required"] = False
                semantic_scope = role_scopes.get(draft_role)
                if verified_relation:
                    semantic_scope = relation_scope
                if semantic_scope is not None:
                    if previous != semantic_scope:
                        dimension["applies_to"] = list(semantic_scope)
                        applied.append(
                            f"{group_id}:{dimension_name}={'/'.join(semantic_scope)}"
                        )
                    continue
                if previous != scope:
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
            relation_dimensions = [
                dimension for dimension in group.get("dimensions") or []
                if isinstance(dimension, Mapping)
                and (
                    dimension.get("physical_relation_review_required")
                    or dimension.get("sample_relation_source_verified")
                )
            ]
            if (
                group.get("sample_reuse_audit_status") == "unresolved"
                and relation_dimensions
                and all(
                    dimension.get("sample_relation_source_verified")
                    and not dimension.get("physical_relation_review_required")
                    for dimension in relation_dimensions
                )
            ):
                group["sample_reuse_audit_status"] = "resolved_by_dimension_evidence"
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

    _RECORD_REVIEW_ERROR_PREFIXES = (
        "Reported results lack complete source-backed independent approval",
        "Reported record ",
        "Reported assay ",
        "Reported material ",
        "Independent review rejected reported record",
        "Independent review referenced unknown reported record",
        # Whether one physical sample is shared across assays is a semantic
        # question for review; the row graph is complete either way.
        "Unresolved physical sample relation",
    )
    # The same question, asked of a whole design group (more assays than
    # samples without a quote authorising reuse).
    _RECORD_REVIEW_ERROR_MARKERS = ("authorizing reuse of the same sample",)

    @classmethod
    def _blocking_plan_errors(cls, errors: List[str]) -> List[str]:
        """Plan errors that make the entity graph itself unusable.

        Review failures of individual reported materials/results are not
        blocking: rejected records are dropped and approved ones kept.
        """
        return [
            error for error in errors or []
            if not str(error).startswith(cls._RECORD_REVIEW_ERROR_PREFIXES)
            and not any(marker in str(error) for marker in cls._RECORD_REVIEW_ERROR_MARKERS)
        ]

    async def _material_inventory(self, source_text: str) -> List[Dict[str, str]]:
        """List the distinct materials the study characterises, by exact name.

        A focused call: the full planner prompt carries many structural rules
        and tends to omit materials that are listed only in tables (e.g. a
        screened variant panel). Each name must occur verbatim in the source.
        """
        if not source_text.strip():
            return []
        prompt = (
            "List every distinct material that this study characterises or uses as a "
            "measured subject: enzyme or protein variants, organisms or strains, "
            "substrates and material samples. Include materials that appear only in "
            "tables or supplementary information. Give each name exactly as written in "
            "the source (copy it verbatim, including mutation codes). Do not list "
            "reagents, buffers, instruments, or materials only cited from other work. "
            "Merge spelling variants of the same material; keep different variants "
            "separate.\n\nSource:\n" + source_text
        )
        try:
            parsed = await invoke_structured_output(
                self.llm_helper, [HumanMessage(content=prompt)], MaterialInventoryResponse,
                operation_name="EntityStructurePlanner.material_inventory",
                max_tokens=16384 if config.llm_enable_thinking else 4096,
            )
        except Exception as exc:  # optional enrichment; planning continues
            self.logger.warning("Material inventory skipped: %s", exc)
            return []
        items = self._claims_payload(parsed).get("materials") or [] if parsed else []
        source = normalize_source_evidence_text(source_text)
        kept: Dict[str, Dict[str, str]] = {}
        for item in items:
            name = normalize_source_evidence_text(item.get("name"))
            if len(name) < 2 or not re.search(r"(?<!\w)" + re.escape(name) + r"(?!\w)", source):
                continue
            kept.setdefault(name.lower(), {"name": name, "role": str(item.get("role") or "other")})
        # Keep the most discussed materials when a screen lists very many.
        def mentions(entry: Dict[str, str]) -> int:
            return len(re.findall(r"(?<!\w)" + re.escape(entry["name"]) + r"(?!\w)", source))

        inventory = sorted(kept.values(), key=mentions, reverse=True)[:24]
        self.logger.info("🧪 Material inventory: %d source-verified materials", len(inventory))
        return inventory

    @staticmethod
    def _with_material_inventory(
        claims: Dict[str, Any], inventory: List[Dict[str, str]], *, source_text: str = "",
    ) -> Dict[str, Any]:
        """Add inventory materials the claims do not already represent.

        Each missing material becomes a source-described material identity
        (a material_preparation ObservationUnit and a material_identity Sample
        named by the material). They pass the same quote and independent
        review gates as planner-proposed materials.

        A proposed material Sample placed directly under the Study gets the
        same shape: its own material_preparation ObservationUnit. A proposal
        whose subject the source never names ("purified A, B, C") cannot be
        grounded and is dropped; its Samples keep their own grounding through
        their own ObservationUnit instead of failing with their parent.
        """
        studies = [s for s in claims.get("studies") or [] if isinstance(s, Mapping)]
        study_id = str((studies[0] if studies else {}).get("row_id") or "").strip()
        if not study_id:
            return claims
        proposed = [dict(record) for record in claims.get("reported_materials") or []]
        if source_text:
            source = normalize_source_evidence_text(source_text)
            ungrounded = {
                str(record.get("record_id") or "") for record in proposed
                if not text_names(source, normalize_source_evidence_text(record.get("source_subject")))
            }
            proposed = [r for r in proposed if str(r.get("record_id") or "") not in ungrounded]
            if ungrounded:
                claims = {**claims, "ungrounded_reported_materials": sorted(ungrounded)}
        # A Sample hung on anything but a proposed ObservationUnit (the
        # Investigation id, an id defined nowhere) gets its own, as under Study.
        proposed_ous = {str(r.get("record_id") or "") for r in proposed if r.get("level") == "observationunit"}
        for record in proposed:
            if record.get("level") == "sample" and record.get("parent_row_id") not in proposed_ous:
                record["parent_row_id"] = study_id
        materials: List[Dict[str, Any]] = []
        used = {str(record.get("record_id") or "") for record in proposed}
        for record in proposed:
            if record.get("level") == "sample" and record.get("parent_row_id") == study_id:
                ou_id = f"ou_{record.get('record_id') or 'material'}"
                while ou_id in used:
                    ou_id += "_ou"
                used.add(ou_id)
                materials.append({
                    **record, "record_id": ou_id, "level": "observationunit",
                    "record_kind": "material_preparation",
                    "label": f"{record.get('label') or record.get('source_subject')} (material preparation)",
                })
                record["parent_row_id"] = ou_id
            materials.append(record)
        claims = {**claims, "reported_materials": materials}
        if not inventory:
            return claims
        represented: set[str] = set()
        for record in materials:
            represented.add(normalize_source_evidence_text(record.get("source_subject")).lower())
            represented.add(normalize_source_evidence_text(record.get("label")).lower())
        for group in claims.get("design_groups") or []:
            for dimension in (group or {}).get("dimensions") or []:
                for value in (dimension or {}).get("explicit_values") or []:
                    represented.add(normalize_source_evidence_text(value).lower())
        represented.discard("")

        def is_represented(name: str) -> bool:
            # "BHET (bis(2-hydroxyethyl) terephthalate)" is BHET; a multi-word
            # name inside a fuller description ("Amorphous polyethylene
            # terephthalate pellets (PET, Cat#138)") is the same material. A
            # single word is not: "LCC" inside "LCC ICCG" is another enzyme.
            name = normalize_source_evidence_text(name).lower()
            head, paren, rest = name.partition(" (")
            aliases = {name, head.strip()} | ({rest[:-1].strip()} if paren and rest.endswith(")") else set())
            if aliases & represented:
                return True
            return len(name.split()) > 1 and any(
                re.search(r"(?<!\w)" + re.escape(name) + r"(?!\w)", text) for text in represented
            )

        for item in inventory:
            name = item["name"]
            if is_represented(name):
                continue
            slug = re.sub(r"[^a-z0-9]+", "_", name.lower()).strip("_")[:40] or "material"
            ou_id, sample_id = f"inv_ou_{slug}", f"inv_{slug}"
            if ou_id in used or sample_id in used:
                continue
            used.update({ou_id, sample_id})
            common = {"source_subject": name, "source_quote": "", "source_group": "material_inventory"}
            materials.append({**common, "record_id": ou_id, "level": "observationunit",
                              "parent_row_id": study_id, "record_kind": "material_preparation",
                              "label": f"{name} (material preparation)"})
            materials.append({**common, "record_id": sample_id, "level": "sample",
                              "parent_row_id": ou_id, "record_kind": "material_identity",
                              "label": name})
        return {**claims, "reported_materials": materials}

    @staticmethod
    def _reported_record_digest(record: Mapping[str, Any], parent: Mapping[str, Any]) -> str:
        payload = json.dumps([record, parent], sort_keys=True, ensure_ascii=False)
        return hashlib.sha256(payload.encode()).hexdigest()

    async def _materialize_reviewed_results(
        self, plan: Mapping[str, Any], records: List[Dict[str, Any]],
        knowledge: List[Dict[str, Any]], source_text: str,
        *, materials: List[Dict[str, Any]] | None = None,
    ) -> Dict[str, Any]:
        materials = materials or []
        if not records and not materials:
            return dict(plan)
        # A result proposed for one table row repeats over the table's other
        # rows. Repeats are reviewed through their template, not one by one;
        # each still passes the verbatim row and cell checks below.
        records = rebind_results_to_named_samples(records, materials)
        records, materials, derived = expand_table_row_templates(records, materials, source_text)
        result = deepcopy(dict(plan))
        # Check each material on its own: one misquoted variant drops only that
        # material (and its children), not the whole inventory. Rejecting all of
        # them left papers whose rows come only from this inventory with no
        # Sample or Assay rows at all.
        accepted, dropped, structural_errors = result, set(), []
        for material in sorted(materials, key=lambda item: item.get("level") == "sample"):
            step = materialize_reported_materials(accepted, [material], source_text=source_text)
            new_errors = (step.get("materialization_errors") or [])[
                len(accepted.get("materialization_errors") or []):
            ]
            if new_errors:
                structural_errors.extend(new_errors)
                dropped.add(material.get("record_id"))
            else:
                accepted = step
        if structural_errors:
            result.setdefault("materialization_errors", []).extend(structural_errors)
            materials = [item for item in materials if item.get("record_id") not in dropped]
            records = [item for item in records if item.get("sample_row_id") not in dropped]
            if not records and not materials:
                return result
        candidate = materialize_reported_materials(result, materials, source_text=source_text)
        if len(candidate.get("materialization_errors") or []) > len(result.get("materialization_errors") or []):
            return candidate
        contracts = build_contract_index(knowledge)
        for record in records:
            for attribute in record.get("attributes") or []:
                contract = contract_for(contracts, "assay", attribute.get("field_name") or "")
                if contract and canonicalize_value(attribute.get("value"), contract) is None:
                    result.setdefault("materialization_errors", []).append(
                        f"Reported assay {record.get('record_id')} violates field contract "
                        f"{attribute.get('field_name')}."
                    )
                    return result
        prompt = (
            "Independently review EVERY proposed material/preparation and Assay result. Return decisions with "
            "record_id, approved, evidence_quote and rationale. Approve only when the actual "
            "source establishes the named material, its exact planned Sample parent, the "
            "result grain, and the meaning of EVERY mapped field. A mean or fitted coefficient "
            "is an analysis result, not an individual replicate observation. Never attach a "
            "group result to an arbitrary replicate or a material from another experiment. "
            "Check that units, uncertainty, conditions and scope mean what the selected field "
            "definitions mean. Field syntax is already checked by code and normalised after "
            "review: a value written as the source prints it (with its ± error or unit) is not a "
            "reason to reject, and parameters the source reports for the same material in one "
            "table row or sentence may share one result record. Reject for wrong facts only. "
            "For each proposed material, verify both its identity and its ObservationUnit/Sample "
            "role and parent link. A named material may represent the source-described material "
            "identity; it must not claim an unreported individual vessel, aliquot or replicate. "
            "When result and material labels differ, verify that the source establishes their "
            "alias relationship in this experiment; similar names alone do not establish identity. "
            "Reject missing or conflicting evidence. Copy a contiguous verbatim passage "
            "from the Actual source below, preserving its Markdown and mathematical markup. "
            "Do not render equations or units into a different spelling inside evidence_quote. "
            "The proposals and existing plan are unverified claims, not source evidence.\n\n"
            "Selected contracts:\n" + json.dumps(self._field_contract_catalog(knowledge), ensure_ascii=False)
            + "\n\nProposed graph:\n" + json.dumps(candidate.get("levels") or [], ensure_ascii=False)
            + "\n\nProposed materials:\n" + json.dumps(
                [m for m in materials if m["record_id"] not in derived], ensure_ascii=False)
            + "\n\nProposed results:\n" + json.dumps(
                [r for r in records if r["record_id"] not in derived], ensure_ascii=False)
            + "\n\nActual source:\n" + source_text
        )
        review = await invoke_structured_output(
            self.llm_helper, [HumanMessage(content=prompt)], ReportedAssayReviewResponse,
            operation_name="EntityStructurePlanner.reported_result_review",
            max_tokens=32768 if config.llm_enable_thinking else 8192,
        )
        decisions = self._claims_payload(review).get("decisions") or []
        expected = [record["record_id"] for record in [*materials, *records]
                    if record["record_id"] not in derived]
        actual = [item.get("record_id") for item in decisions]
        valid = len(set(expected)) == len(expected) and sorted(actual) == sorted(expected)
        valid = valid and all(item.get("approved") is True and
                              _review_quote_in_source(item.get("evidence_quote"), source_text)
                              for item in decisions)
        review_record = {
            "expected_record_ids": expected,
            "decisions": decisions,
            "passed": valid,
        }
        result["reported_record_review"] = review_record
        candidate["reported_record_review"] = review_record
        if not valid:
            errors = result.setdefault("materialization_errors", [])
            errors.append(
                "Reported results lack complete source-backed independent approval."
            )
            if len(set(expected)) != len(expected):
                errors.append("Reported record proposals contain duplicate record_id values.")
            for record_id in expected:
                if actual.count(record_id) != 1:
                    errors.append(
                        f"Reported record {record_id} needs exactly one independent review decision."
                    )
            for item in decisions:
                record_id = item.get("record_id")
                if record_id not in expected:
                    errors.append(f"Independent review referenced unknown reported record {record_id}.")
                    continue
                if item.get("approved") is not True:
                    rationale = " ".join(str(item.get("rationale") or "No reason supplied.").split())[:600]
                    errors.append(
                        f"Independent review rejected reported record {record_id}: {rationale} "
                        "Recheck this review claim against the actual source before revising."
                    )
                elif not _review_quote_in_source(item.get("evidence_quote"), source_text):
                    errors.append(
                        f"Reported record {record_id} review evidence_quote is not present in the "
                        "source; copy a verbatim source passage including its markup."
                    )
            # Only ambiguous proposals end the review. A decision for an id nobody
            # proposed is recorded above and ignored: the records that were approved
            # one by one keep their rows (the reviewer once invented six ids and
            # five approved assays were lost with them).
            if len(set(expected)) != len(expected):
                return result
        approved_ids = {
            item["record_id"] for item in decisions
            if actual.count(item.get("record_id")) == 1
            and item.get("approved") is True
            and _review_quote_in_source(item.get("evidence_quote"), source_text)
        }
        approved_ids |= {item for item, template in derived.items() if template in approved_ids}
        # Keep independently verified records without treating a partial review
        # as a complete plan. Descendants of rejected materials cannot survive.
        available_parents = {
            row["row_id"] for level in result.get("levels") or []
            for row in level.get("entities") or []
        }
        accepted_materials = []
        for material in sorted(materials, key=lambda item: item.get("level") == "sample"):
            if material["record_id"] in approved_ids and material.get("parent_row_id") in available_parents:
                accepted_materials.append(material)
                available_parents.add(material["record_id"])
        candidate = materialize_reported_materials(result, accepted_materials, source_text=source_text)
        reviewed_samples = {
            row["row_id"]: row for level in candidate.get("levels") or []
            if level.get("level") == "sample" for row in level.get("entities") or []
        }
        # Only fully source-backed review decisions reach this handoff. Bind
        # aliases to the exact reviewed proposal and parent, never to a global
        # string synonym that could merge materials from different experiments.
        parent_bindings = {
            record["record_id"]: reported_parent_binding_digest(
                record, reviewed_samples[record["sample_row_id"]], source_text
            )
            for record in records if record["record_id"] in approved_ids
            and record.get("sample_row_id") in reviewed_samples
        }
        result = candidate
        for record in records:
            if record["record_id"] not in parent_bindings:
                continue
            result = materialize_reported_assays(
                result, [record], source_text=source_text, field_catalog=self._field_catalog(knowledge),
                reviewed_parent_bindings=parent_bindings,
            )
        parents = {row["row_id"]: row for level in result.get("levels") or []
                   for row in level.get("entities") or []}
        result["source_fingerprint"] = hashlib.sha256(source_text.encode()).hexdigest()
        for level in result.get("levels") or []:
            if level["level"] not in {"observationunit", "sample", "assay"}:
                continue
            receipt_key = "reported_assay_reviews" if level["level"] == "assay" else "reported_material_reviews"
            receipts = result.setdefault(receipt_key, {})
            for row in level.get("entities") or []:
                if row["row_id"] in approved_ids:
                    receipts[row["row_id"]] = {
                        "source_sha256": result["source_fingerprint"],
                        "record_sha256": self._reported_record_digest(row, parents[row["parent_row_id"]]),
                    }
        return result

    @traceable(name="EntityStructurePlanner", tags=["agent", "structure"])
    async def execute(self, state: FAIRifierState) -> FAIRifierState:
        self.log_execution(state, "🧱 Planning ISA entity cardinality and relations")
        source_text = read_document_text(state)
        source_fingerprint = hashlib.sha256(source_text.encode("utf-8")).hexdigest()
        existing_plan = state.get("entity_plan") or {}
        existing_validation = state.get("entity_plan_validation") or {}
        requires_physical_reaudit = self._requires_physical_relation_reaudit(existing_plan)
        if (
            existing_plan.get("source_fingerprint") == source_fingerprint
            and existing_validation.get("passed") is True
            and not requires_physical_reaudit
        ):
            self.logger.info(
                "Entity structure plan locked for unchanged source; reusing rows=%s contacts=%s",
                existing_validation.get("row_counts", {}),
                existing_validation.get("investigation_contact_count", 0),
            )
            return state
        if requires_physical_reaudit and existing_validation.get("passed") is True:
            self.logger.info(
                "Re-auditing a legacy entity plan with unverified physical input relations."
            )
        contacts = self._source_contacts(state)
        planning_knowledge = self._planning_knowledge(state)
        table_profiles = metadata_table_profiles(state.get("source_workspace") or {})
        dataset_profiles = metadata_table_profiles_for_document_datasets(
            state.get("source_workspace") or {},
            (state.get("document_info") or {}).get("datasets_mentioned") or [],
        )
        dataset_profiles = list(
            self._preferred_dataset_profiles(dataset_profiles, source_text)
        )
        plan: Dict[str, Any] = {}
        errors: List[str] = []
        retry_errors: List[str] = []
        best_plan: Dict[str, Any] = {}
        best_errors: List[str] = []
        best_rank: tuple[int, int, int, int, int] | None = None

        def _set_retry_errors(items: List[str]) -> None:
            # Each validation describes the current candidate. Accumulating old
            # failures lets resolved errors consume the bounded prompt and hide
            # newer source/parentage review findings from subsequent attempts.
            retry_errors[:] = list(dict.fromkeys(item for item in items if item))

        max_attempts = max(
            1,
            int(
                getattr(
                    config,
                    "entity_plan_max_attempts",
                    FAIRifierConfig.entity_plan_max_attempts,
                )
            ),
        )
        # The inventory only merges into parsed claims, so it runs alongside
        # the first planning attempt instead of before it.
        import asyncio

        inventory_task = asyncio.ensure_future(self._material_inventory(source_text))
        material_inventory: List[Dict[str, str]] | None = None
        truncated_before = False
        for attempt in range(1, max_attempts + 1):
            schema_errors: List[str] = []
            from ..utils.llm_helper import thinking_override
            from ..utils.structured_output import TRUNCATED_ANSWER_MARKER

            # Thinking stays on for planning: a no-thinking retry produced
            # complete but much coarser plans (entities merged) on Qwen.
            with thinking_override(None):
                parsed = await invoke_structured_output(
                    self.llm_helper,
                    [HumanMessage(content=self._prompt(state, prior_errors=retry_errors or None))],
                    EntityDesignClaimsResponse,
                    operation_name=f"EntityStructurePlanner.attempt_{attempt}",
                    allow_truncated=True,
                    # Reasoning consumes the same output allowance as the JSON answer.
                    max_tokens=65536 if config.llm_enable_thinking else 32768,
                    validation_errors=schema_errors,
                )
            if TRUNCATED_ANSWER_MARKER in schema_errors:
                truncated_before = True
            if not parsed:
                parse_errors = schema_errors or [
                    "The model returned no parseable structure plan."
                ]
                if best_plan:
                    plan = best_plan
                    errors = [*best_errors, *parse_errors]
                else:
                    errors = parse_errors
                _set_retry_errors(errors)
                continue
            claims = self._claims_payload(parsed)
            claims = normalize_claim_measurement_units(claims, source_text)
            if material_inventory is None:
                material_inventory = await inventory_task
            claims = self._with_material_inventory(claims, material_inventory, source_text=source_text)
            claims["reported_materials"] = repair_reported_material_quotes(
                claims.get("reported_materials") or [], source_text=source_text
            )
            candidate_errors = self._candidate_record_plan_errors(
                claims, dataset_profiles
            )
            if candidate_errors:
                errors = candidate_errors
                _set_retry_errors(errors)
                continue
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
                            source_text=source_text,
                        )
                    )
                ],
                EntityPlanScopeAuditResponse,
                operation_name=f"EntityStructurePlanner.scope_audit_{attempt}",
                max_tokens=32768 if config.llm_enable_thinking else 8192,
            )
            audit_payload = self._claims_payload(scope_audit) if scope_audit else {}
            rejected_reuse = self._enforce_independent_reuse_audit(
                claims, audit_payload, source_text=source_text
            )
            if rejected_reuse:
                self.log_execution(
                    state,
                    "🧪 Rejected unproven many-assays-per-sample reuse: "
                    + ", ".join(rejected_reuse),
                )
            scope_repairs, scope_audit_errors = self._apply_dimension_scope_audit(
                claims, audit_payload, source_text=source_text
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
                    EntityPlanRecordColumnAuditResponse,
                    operation_name=(
                        f"EntityStructurePlanner.record_column_audit_{attempt}"
                    ),
                    max_tokens=32768 if config.llm_enable_thinking else 8192,
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
            plan["physical_relation_audit_version"] = PHYSICAL_RELATION_AUDIT_VERSION
            plan = await self._materialize_reviewed_results(
                plan, claims.get("reported_assays") or [], planning_knowledge, source_text,
                materials=claims.get("reported_materials") or [],
            )
            errors = self._plan_errors(plan, source_text=source_text)
            # The scope audit may repair a draft, but a disagreement or an
            # out-of-contract scope is not evidence that the materialized
            # entity graph is unusable. Those notes used to veto the whole
            # run. Keep them reviewable, as mapping-audit diagnostics already are.
            if scope_audit_errors:
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
            truncated = TRUNCATED_ANSWER_MARKER in schema_errors
            if truncated:
                truncated_before = True
                # A recovered prefix lacks its tail (often the last design
                # groups and reported results): rank it below complete plans
                # and re-plan while attempts remain.
                errors = [*errors, "The structure plan answer was truncated; re-planning."]
            candidate_rank = self._candidate_rank(
                plan,
                errors,
                used_authoritative_records=record_plan_succeeded,
            )
            if plan and (best_rank is None or candidate_rank > best_rank):
                best_plan = plan
                best_errors = list(errors)
                best_rank = candidate_rank
            _set_retry_errors(errors)
            if not errors:
                break
            if plan and not self._blocking_plan_errors(errors):
                # Only individual reported records failed review; those are
                # already dropped and the approved ones kept. Re-planning the
                # whole study for them would redo all the work for nothing.
                self.log_execution(
                    state,
                    f"🧾 Keeping plan: {len(errors)} per-record review issue(s), no structural error",
                )
                break

        if material_inventory is None and not inventory_task.done():
            inventory_task.cancel()

        if errors and best_plan:
            plan = best_plan
            errors = best_errors

        promoted_fields = self._promote_planned_fields(
            state, plan, planning_knowledge
        ) if plan and not self._blocking_plan_errors(errors) else []
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
