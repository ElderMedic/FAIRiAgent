"""Curation helpers for public FAIRiAgent ground-truth value datasets.

The contract is deliberately permissive: only identifiers and resolvable ISA
relationships are structural requirements. Domain metadata is scored only when
it is present in the source-backed GT; omission never means an empty value.
"""

from __future__ import annotations

import hashlib
import html
import json
import re
from collections import Counter, defaultdict
from copy import deepcopy
from datetime import date
from pathlib import Path
from typing import Any, Iterable


PROJECT_ROOT = Path(__file__).resolve().parents[2]
VALUES_DIR = PROJECT_ROOT / "evaluation/datasets/annotated/values"
ANNOTATED_DIR = VALUES_DIR.parent
EXCLUDED_DATASETS = frozenset({"biorem", "pomato", "compbiobench"})
PLACEHOLDERS = frozenset(
    {"", "na", "n/a", "not reported", "not specified", "not specified in paper", "unknown"}
)

IDENTIFIER_FIELDS = {
    "investigation": "investigation identifier",
    "study": "study identifier",
    "observationunit": "observation unit identifier",
    "sample": "sample identifier",
    "assay": "assay identifier",
}

PUBLICATION_OVERRIDES: dict[str, dict[str, Any]] = {
    "biosensor": {
        "title": "Bacillus-based whole-cell biosensor array for early monitoring of Aspergillus flavus contamination and aflatoxin B1 prediction in maize",
        "type": "manuscript",
        "doi_status": "not_present_in_source",
    },
    "earthworm": {
        "title": "Gene expression profile dynamics of earthworms exposed to ZnO and ZnO:Mn nanomaterials",
        "doi": "10.1101/2025.06.16.660036",
        "url": "https://doi.org/10.1101/2025.06.16.660036",
        "type": "preprint",
        "publisher": "bioRxiv",
        "published": "2025-06-20",
        "license": "CC BY 4.0",
        "verification_source": "Crossref DOI record",
    },
}

DOMAIN_EXTENSIONS = {
    "biosensor": ["biosensor_engineering", "transcriptomics", "food_safety"],
    "earthworm": ["ecotoxicology", "exposure_study", "transcriptomics"],
    "aetherobacter_fasciculatus_genome": ["genome_sequencing", "genome_annotation"],
    "arabidopsis_vacuolar_srna": ["plant_biology", "small_rna_sequencing"],
    "human_gut_microbiome_temporal": ["human_microbiome", "metagenomics"],
    "pea_cold_stress": ["plant_stress", "rna_sequencing", "small_rna_sequencing"],
    "pseudomonas_recombinase_screen": ["microbial_engineering", "recombineering", "sequencing"],
    "sea_cucumber_gut_metagenome": ["marine_microbiome", "metagenomics"],
}

EXTERNAL_REFERENCE_OVERRIDES = {
    "biosensor": [
        {"authority": "NCBI Taxonomy", "identifier": "4577", "label": "Zea mays", "url": "https://www.ncbi.nlm.nih.gov/Taxonomy/Browser/wwwtax.cgi?id=4577"},
        {"authority": "NCBI Taxonomy", "identifier": "1423", "label": "Bacillus subtilis", "url": "https://www.ncbi.nlm.nih.gov/Taxonomy/Browser/wwwtax.cgi?id=1423"},
        {"authority": "NCBI Taxonomy", "identifier": "5059", "label": "Aspergillus flavus", "url": "https://www.ncbi.nlm.nih.gov/Taxonomy/Browser/wwwtax.cgi?id=5059"},
    ],
    "earthworm": [
        {"authority": "NCBI Taxonomy", "identifier": "6396", "label": "Eisenia fetida", "url": "https://www.ncbi.nlm.nih.gov/Taxonomy/Browser/wwwtax.cgi?id=6396"},
        {"authority": "Crossref", "identifier": "10.1101/2025.06.16.660036", "label": "bioRxiv preprint DOI", "url": "https://api.crossref.org/works/10.1101%2F2025.06.16.660036"},
    ],
}


def _slug(value: Any) -> str:
    text = re.sub(r"[^a-z0-9]+", "_", str(value).lower()).strip("_")
    return text[:48] or "row"


def _plain_text(value: Any) -> Any:
    if not isinstance(value, str):
        return value
    without_tags = re.sub(r"<[^>]+>", "", html.unescape(value))
    return re.sub(r"\s+", " ", without_tags).strip()


def _stable_id(prefix: str, document_id: str, label: Any, index: int) -> str:
    seed = f"{document_id}|{prefix}|{label}|{index}"
    suffix = hashlib.sha256(seed.encode("utf-8")).hexdigest()[:8]
    return f"{prefix}_{_slug(label)}_{suffix}"


def _clean(value: Any) -> Any:
    if isinstance(value, dict):
        cleaned = {}
        for key, item in value.items():
            if key == "_evidence":
                continue
            result = _clean(item)
            if result is not None and result != {} and result != []:
                cleaned[key] = result
        return cleaned
    if isinstance(value, list):
        return [item for item in (_clean(item) for item in value) if item is not None]
    if value is None:
        return None
    if isinstance(value, str) and value.strip().lower() in PLACEHOLDERS:
        return None
    return value


def _source_assets(document_id: str) -> list[dict[str, Any]]:
    candidates: list[Path] = []
    if document_id.startswith("petase_"):
        doi_slug = document_id.removeprefix("petase_")
        candidates.extend((PROJECT_ROOT / "evaluation/datasets/PETase_papers_json").glob("*"))
        candidates = [p for p in candidates if _slug(p.stem).replace("_", "") in doi_slug.replace("_", "") or doi_slug.replace("_", "") in _slug(p.stem).replace("_", "")]
        paper_dir = PROJECT_ROOT / "evaluation/datasets/raw/petase_enzyme_engineering/papers" / doi_slug
        if paper_dir.exists():
            candidates.extend(paper_dir.iterdir())
    else:
        raw_dir = PROJECT_ROOT / "evaluation/datasets/raw" / document_id
        if raw_dir.exists():
            # Register the original paper/metadata inputs, not parser derivatives
            # (page images, layout JSON, and copied PDFs under mineru_* folders).
            candidates.extend(path for path in raw_dir.iterdir() if path.is_file())

    assets = []
    seen_digests: set[str] = set()
    unique_paths = {p.resolve() for p in candidates if p.is_file()}
    ordered_paths = sorted(
        unique_paths,
        key=lambda path: ("evaluation/datasets/raw" not in str(path), str(path)),
    )
    for path in ordered_paths:
        if any(part in EXCLUDED_DATASETS for part in path.parts):
            continue
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        if digest in seen_digests:
            continue
        seen_digests.add(digest)
        suffix = path.suffix.lower()
        role = "primary_source" if suffix in {".pdf", ".md", ".docx"} else "source_metadata"
        if "si" in path.stem.lower() or "supp" in path.stem.lower():
            role = "supplementary_source"
        assets.append(
            {
                "path": str(path.relative_to(PROJECT_ROOT)),
                "role": role,
                "sha256": digest,
            }
        )
    return assets


def _publication(document: dict[str, Any], publication_cache: dict[str, Any]) -> dict[str, Any]:
    document_id = document["document_id"]
    doi = str(document.get("paper_doi") or "").strip()
    cached = publication_cache.get(doi.lower(), {}) if doi else {}
    result = {
        key: value
        for key, value in {
            "title": document.get("paper_title"),
            "doi": doi or None,
            "journal": document.get("paper_journal"),
            "published": document.get("paper_date"),
            "authors": document.get("paper_authors"),
        }.items()
        if value
    }
    result.update({key: value for key, value in cached.items() if key not in {"retrieved_at", "source_url"}})
    result.update(PUBLICATION_OVERRIDES.get(document_id, {}))
    result = {key: _plain_text(value) for key, value in result.items()}
    if result.get("doi"):
        result.setdefault("url", f"https://doi.org/{result['doi']}")
    return result


def _tokens(value: Any) -> set[str]:
    stop = {"the", "and", "for", "with", "sample", "assay", "analysis", "exposed", "rna", "seq"}
    return {token for token in re.findall(r"[a-z0-9]+", str(value).lower()) if len(token) > 2 and token not in stop}


def _best_reference(row: dict[str, Any], targets: list[dict[str, Any]], id_field: str, name_fields: Iterable[str]) -> str | None:
    query = _tokens(" ".join(str(row.get(key, "")) for key in ("sample name", "assay description", "assay name", "observation unit name")))
    scored = []
    for target in targets:
        target_tokens = _tokens(" ".join(str(target.get(key, "")) for key in name_fields))
        scored.append((len(query & target_tokens), target.get(id_field)))
    scored.sort(reverse=True)
    if scored and scored[0][0] > 0 and (len(scored) == 1 or scored[0][0] > scored[1][0]):
        return scored[0][1]
    return None


def _apply_source_specific_corrections(document: dict[str, Any]) -> None:
    """Remove known inferred labels and correct externally verified identifiers."""
    document_id = document["document_id"]
    samples = document.get("isa_sheets", {}).get("sample", {}).get("expected_rows", [])
    if document_id == "biosensor":
        unsupported = {
            "biosafety level",
            "geographic location (country and/or sea)",
            "broad-scale environmental context",
            "local environmental context",
            "environmental medium",
        }
        for row in samples:
            for field in unsupported:
                row.pop(field, None)
    elif document_id == "earthworm":
        for row in samples:
            row["ncbi taxonomy id"] = "6396"
            row.pop("geographic location (country and/or sea)", None)
        # Each sequencing row summarizes multiple experimental groups. Linking
        # it to one arbitrary group would be false precision.
        for row in document.get("isa_sheets", {}).get("assay", {}).get("expected_rows", []):
            row.pop("observation unit identifier", None)
            row.pop("sample identifier", None)


def curate_document(document: dict[str, Any], publication_cache: dict[str, Any] | None = None) -> dict[str, Any]:
    """Return a source-grounded, structurally linked GT document."""
    publication_cache = publication_cache or {}
    result = _clean(deepcopy(document))
    document_id = result["document_id"]
    if document_id in EXCLUDED_DATASETS or document_id.startswith("compbiobench"):
        raise ValueError(f"Excluded dataset must not be curated: {document_id}")

    _apply_source_specific_corrections(result)

    sheets = result.setdefault("isa_sheets", {})
    identifier_remaps: dict[str, dict[str, list[str]]] = {}
    for sheet_name, id_field in IDENTIFIER_FIELDS.items():
        rows = sheets.get(sheet_name, {}).get("expected_rows", [])
        counts = Counter(str(row.get(id_field)) for row in rows if row.get(id_field))
        remap: dict[str, list[str]] = defaultdict(list)
        for index, row in enumerate(rows):
            label = next((row.get(key) for key in (f"{sheet_name} name", f"{sheet_name} title", "assay description", "sample name", "observation unit name") if row.get(key)), index)
            old_id = str(row.get(id_field) or "")
            if not old_id or counts[old_id] > 1:
                row[id_field] = _stable_id(sheet_name.upper(), document_id, label, index)
            remap[old_id].append(row[id_field])
        identifier_remaps[sheet_name] = dict(remap)

    reference_targets = {
        "investigation identifier": "investigation",
        "study identifier": "study",
        "observation unit identifier": "observationunit",
        "sample identifier": "sample",
    }
    for sheet_name, sheet in sheets.items():
        own_id = IDENTIFIER_FIELDS.get(sheet_name)
        for row in sheet.get("expected_rows", []):
            for field, target_sheet in reference_targets.items():
                if field == own_id or field not in row:
                    continue
                old_reference = str(row[field])
                candidates = identifier_remaps[target_sheet].get(old_reference, [])
                if len(candidates) == 1:
                    row[field] = candidates[0]
                elif len(candidates) > 1:
                    row.pop(field, None)

    investigations = sheets.get("investigation", {}).get("expected_rows", [])
    studies = sheets.get("study", {}).get("expected_rows", [])
    observation_units = sheets.get("observationunit", {}).get("expected_rows", [])
    samples = sheets.get("sample", {}).get("expected_rows", [])
    assays = sheets.get("assay", {}).get("expected_rows", [])
    inv_id = investigations[0].get("investigation identifier") if investigations else None
    study_id = studies[0].get("study identifier") if studies else None
    for row in studies:
        if inv_id:
            row["investigation identifier"] = inv_id
    for row in observation_units:
        if study_id:
            row["study identifier"] = study_id

    for index, row in enumerate(samples):
        if row.get("observation unit identifier"):
            continue
        reference = _best_reference(row, observation_units, "observation unit identifier", ("observation unit name", "observation unit description"))
        if not reference and len(samples) == len(observation_units) and index < len(observation_units):
            reference = observation_units[index]["observation unit identifier"]
        if reference:
            row["observation unit identifier"] = reference

    for row in assays:
        if document_id == "earthworm":
            continue
        if not row.get("sample identifier"):
            reference = _best_reference(row, samples, "sample identifier", ("sample name", "sample description"))
            if reference:
                row["sample identifier"] = reference
        if not row.get("observation unit identifier"):
            reference = _best_reference(row, observation_units, "observation unit identifier", ("observation unit name", "observation unit description"))
            if reference:
                row["observation unit identifier"] = reference

    publication = _publication(result, publication_cache)
    title = publication.get("title")
    if title and investigations:
        investigations[0]["investigation title"] = title
    if title and studies:
        studies[0]["study title"] = title

    extensions = ["petase_enzyme_engineering"] if document_id.startswith("petase_") else DOMAIN_EXTENSIONS.get(document_id, [])
    result.update(
        {
            "schema_version": "fairiagent.ground_truth_values.v3",
            "publication": publication,
            "source_assets": _source_assets(document_id),
            "external_references": EXTERNAL_REFERENCE_OVERRIDES.get(document_id, []),
            "schema_profile": {
                "core": "fairds_isa_linked_core_v1",
                "extensions": extensions,
                "field_policy": "source_reported_fields_only",
                "omitted_field_semantics": "unreported_or_not_applicable; not scored",
            },
            "annotation": {
                "reference_authority": "human_curated_ground_truth",
                "annotation_method": "source_document_and_metadata_asset_curation",
                "review_status": "curated_structural_pass",
                "evidence_policy": "values must be traceable to listed source assets; inferred bibliographic facts require a named verification source",
                "curation_date": date.today().isoformat(),
            },
        }
    )
    result.pop("generated_at", None)
    return result


def load_publication_cache(path: Path | None = None) -> dict[str, Any]:
    path = path or PROJECT_ROOT / "evaluation/config/publication_metadata_cache.json"
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}


def public_value_paths() -> list[Path]:
    paths = []
    for path in sorted(VALUES_DIR.glob("ground_truth_*_values.json")):
        document_id = path.name.removeprefix("ground_truth_").removesuffix("_values.json")
        if document_id in EXCLUDED_DATASETS or document_id.startswith("compbiobench"):
            continue
        paths.append(path)
    return paths


def validate_document(document: dict[str, Any]) -> list[str]:
    issues: list[str] = []
    doc_id = document.get("document_id", "<missing>")
    if doc_id in EXCLUDED_DATASETS or str(doc_id).startswith("compbiobench"):
        issues.append(f"{doc_id}: excluded dataset present")
    if not document.get("source_assets"):
        issues.append(f"{doc_id}: no source assets")
    identifiers: dict[str, set[str]] = {}
    for sheet_name, id_field in IDENTIFIER_FIELDS.items():
        rows = document.get("isa_sheets", {}).get(sheet_name, {}).get("expected_rows", [])
        ids = [row.get(id_field) for row in rows]
        if any(not item for item in ids):
            issues.append(f"{doc_id}/{sheet_name}: blank identifier")
        if len(ids) != len(set(ids)):
            issues.append(f"{doc_id}/{sheet_name}: duplicate identifier")
        identifiers[sheet_name] = {str(item) for item in ids if item}
    for sheet_name, sheet in document.get("isa_sheets", {}).items():
        for index, row in enumerate(sheet.get("expected_rows", [])):
            for key, value in row.items():
                if isinstance(value, str) and value.strip().lower() in PLACEHOLDERS:
                    issues.append(f"{doc_id}/{sheet_name}[{index}]/{key}: placeholder value")
            references = {
                "investigation identifier": "investigation",
                "study identifier": "study",
                "observation unit identifier": "observationunit",
                "sample identifier": "sample",
            }
            own_id = IDENTIFIER_FIELDS.get(sheet_name)
            for field, target_sheet in references.items():
                if field == own_id or field not in row:
                    continue
                if str(row[field]) not in identifiers[target_sheet]:
                    issues.append(f"{doc_id}/{sheet_name}[{index}]/{field}: unresolved reference {row[field]}")
    return issues
