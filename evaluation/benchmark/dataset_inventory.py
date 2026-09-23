"""Dataset inventory and split-leakage checks for benchmark manifests."""

from __future__ import annotations

import json
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Dict, List, Mapping

from .assets import collect_asset_checksums
from .contracts import load_manifest


def _ground_truth_summary(path: Path, instance_id: str | None = None) -> Dict[str, Any]:
    if not path.is_file():
        return {"available": False, "field_count": None, "required_field_count": None}
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"available": False, "field_count": None, "required_field_count": None}
    document = value
    if isinstance(value, Mapping) and isinstance(value.get("documents"), list):
        document = next(
            (
                candidate
                for candidate in value["documents"]
                if isinstance(candidate, Mapping) and candidate.get("document_id") == instance_id
            ),
            None,
        )
        if document is None:
            return {"available": True, "field_count": None, "required_field_count": None}
    fields = document.get("ground_truth_fields") if isinstance(document, Mapping) else None
    if not isinstance(fields, list):
        return {"available": True, "field_count": None, "required_field_count": None}
    required = sum(1 for field in fields if isinstance(field, Mapping) and field.get("is_required") is True)
    return {
        "available": True,
        "field_count": len(fields),
        "required_field_count": required,
    }


def _source_summary(path: Path) -> Dict[str, Any]:
    """Describe source size/format without parsing or calling a service."""

    summary: Dict[str, Any] = {
        "path": str(path),
        "format": path.suffix.lower().lstrip(".") or "unknown",
        "bytes": path.stat().st_size if path.is_file() else None,
        "characters": None,
        "pages": None,
        "read_method": None,
        "layout_signals": {
            "measurement_status": "not_measured",
            "text_block_count": None,
            "image_count": None,
            "pages_with_images": None,
            "pages_with_sparse_text": None,
            "pages_with_no_text": None,
            "tables_detected": None,
            "pages_with_tables": None,
            "table_detection_status": "not_measured",
        },
    }
    if not path.is_file():
        return summary
    if path.suffix.lower() == ".pdf":
        try:
            import fitz  # type: ignore

            with fitz.open(str(path)) as document:
                summary["pages"] = len(document)
                page_texts = [page.get_text() for page in document]
                summary["characters"] = sum(len(text) for text in page_texts)
                text_block_count = 0
                image_count = 0
                pages_with_images = 0
                pages_with_sparse_text = 0
                pages_with_no_text = 0
                tables_detected = 0
                pages_with_tables = 0
                table_detection_status = "passed"
                for page_index, page_text in enumerate(page_texts):
                    page = document[page_index]
                    text_block_count += len(page.get_text("blocks"))
                    page_images = page.get_images(full=True)
                    image_count += len(page_images)
                    if page_images:
                        pages_with_images += 1
                    if len(page_text.strip()) == 0:
                        pages_with_no_text += 1
                    elif len(page_text.strip()) < 100:
                        pages_with_sparse_text += 1
                    try:
                        tables = page.find_tables().tables
                        tables_detected += len(tables)
                        if tables:
                            pages_with_tables += 1
                    except Exception:  # pragma: no cover - version-dependent PyMuPDF
                        table_detection_status = "failed"
                summary["layout_signals"] = {
                    "measurement_status": "passed",
                    "text_block_count": text_block_count,
                    "image_count": image_count,
                    "pages_with_images": pages_with_images,
                    "pages_with_sparse_text": pages_with_sparse_text,
                    "pages_with_no_text": pages_with_no_text,
                    "tables_detected": tables_detected,
                    "pages_with_tables": pages_with_tables,
                    "table_detection_status": table_detection_status,
                }
            summary["read_method"] = "pdf_text"
        except (ImportError, OSError, RuntimeError):
            summary["read_method"] = "pdf_bytes_fallback"
    else:
        try:
            summary["characters"] = len(path.read_text(encoding="utf-8", errors="replace"))
            summary["read_method"] = "text"
        except OSError:
            summary["read_method"] = "bytes_only"
    return summary


def _length_bin(characters: Any) -> str:
    if not isinstance(characters, (int, float)):
        return "unknown"
    if characters < 10_000:
        return "short_lt_10k_characters"
    if characters < 50_000:
        return "medium_10k_to_50k_characters"
    if characters < 200_000:
        return "long_50k_to_200k_characters"
    return "very_long_ge_200k_characters"


def _text_extractability(source: Mapping[str, Any]) -> str:
    characters = source.get("characters")
    pages = source.get("pages")
    if not isinstance(characters, (int, float)):
        return "unavailable"
    if isinstance(pages, (int, float)) and pages > 0:
        density = float(characters) / float(pages)
        if density < 100:
            return "sparse_text_or_ocr_risk"
    if characters == 0:
        return "no_extractable_text"
    return "text_available"


def validate_split_leakage(instances: List[Mapping[str, Any]], asset_checksums: Mapping[str, Any]) -> List[str]:
    """Detect duplicate assets and shared project/study groups across splits."""

    errors: List[str] = []
    source_owner: Dict[str, str] = {}
    groups: Dict[str, Dict[str, set[str]]] = defaultdict(lambda: defaultdict(set))
    for instance in instances:
        instance_id = str(instance["instance_id"])
        source = (asset_checksums.get(instance_id) or {}).get("source") or {}
        digest = source.get("sha256")
        if digest:
            prior = source_owner.get(digest)
            if prior and prior != instance_id:
                errors.append("duplicate source checksum shared by %s and %s" % (prior, instance_id))
            source_owner[digest] = instance_id
        split = str(instance.get("split") or "unspecified")
        metadata = instance.get("metadata") if isinstance(instance.get("metadata"), Mapping) else {}
        for group_key in ("project_id", "study_family_id"):
            group_value = instance.get(group_key) or metadata.get(group_key)
            if group_value:
                groups[group_key][str(group_value)].add(split)
    for group_key, group_map in groups.items():
        for group_value, splits in group_map.items():
            if len(splits) > 1:
                errors.append("%s=%s appears in multiple splits: %s" % (group_key, group_value, sorted(splits)))
    return errors


def build_inventory(manifest_path: Path, *, project_root: Path) -> Dict[str, Any]:
    """Build a distribution inventory without requiring evidence annotations."""

    manifest = load_manifest(manifest_path)
    asset_checksums = collect_asset_checksums(
        manifest,
        manifest_path,
        project_root=project_root,
        require_ground_truth=True,
    )
    instances = manifest["instances"]
    split_counts = Counter(str(instance.get("split") or "unspecified") for instance in instances)
    domain_counts = Counter(
        str((instance.get("strata") or {}).get("domain") or "unspecified")
        for instance in instances
    )
    details: List[Dict[str, Any]] = []
    for instance in instances:
        instance_id = str(instance["instance_id"])
        gt_path = (asset_checksums[instance_id]["ground_truth"]["path"])
        source_path = Path(asset_checksums[instance_id]["source"]["path"])
        declared_context_assets = [
            asset_name
            for asset_name in (
                "package",
                "ground_truth_values",
                "standards_context",
                "retrieved_context",
                "supplementary",
            )
            if asset_name in asset_checksums[instance_id]
        ]
        values_asset = asset_checksums[instance_id].get("ground_truth_values")
        values_summary = None
        if isinstance(values_asset, Mapping):
            values_summary = {
                "path": values_asset.get("path"),
                "sha256": values_asset.get("sha256"),
            }
        source_summary = _source_summary(source_path)
        ground_truth_summary = _ground_truth_summary(Path(gt_path), instance_id)
        supplementary_assets = asset_checksums[instance_id].get("supplementary")
        supplementary_count: int | str = (
            len(supplementary_assets)
            if isinstance(supplementary_assets, list)
            else "not_declared"
        )
        details.append(
            {
                "instance_id": instance_id,
                "split": instance.get("split"),
                "strata": instance.get("strata") or {},
                "source_sha256": asset_checksums[instance_id]["source"]["sha256"],
                "ground_truth_sha256": asset_checksums[instance_id]["ground_truth"]["sha256"],
                "ground_truth": ground_truth_summary,
                "ground_truth_values": values_summary,
                "source": source_summary,
                "layout_signals": source_summary.get("layout_signals") or {},
                "distribution": {
                    "length_bin": _length_bin(source_summary.get("characters")),
                    "text_extractability": _text_extractability(source_summary),
                    "table_density": (instance.get("strata") or {}).get("table_density", "unknown"),
                    "ocr_quality": (instance.get("strata") or {}).get("ocr_quality", "unknown"),
                    "supplementary_asset_count": supplementary_count,
                    "annotation_field_count": ground_truth_summary.get("field_count"),
                },
                "declared_context_assets": declared_context_assets,
            }
        )
    leakage_errors = validate_split_leakage(instances, asset_checksums)
    def count_distribution(key: str) -> Dict[str, int]:
        counts: Counter[str] = Counter()
        for detail in details:
            value = (detail.get("distribution") or {}).get(key)
            counts[str(value if value is not None else "unknown")] += 1
        return dict(counts)

    def count_layout_signal(key: str) -> Dict[str, int]:
        counts: Counter[str] = Counter()
        for detail in details:
            signals = detail.get("layout_signals") or {}
            value = signals.get(key)
            counts[str(value if value is not None else "unknown")] += 1
        return dict(counts)

    return {
        "schema_version": "fairiagent.dataset_inventory.v2",
        "benchmark_release": manifest["benchmark_release"],
        "instance_count": len(instances),
        "split_counts": dict(split_counts),
        "domain_counts": dict(domain_counts),
        "distribution_counts": {
            key: count_distribution(key)
            for key in (
                "length_bin",
                "text_extractability",
                "table_density",
                "ocr_quality",
                "supplementary_asset_count",
            )
        },
        "layout_signal_counts": {
            key: count_layout_signal(key)
            for key in (
                "table_detection_status",
                "tables_detected",
                "pages_with_sparse_text",
                "pages_with_no_text",
                "pages_with_images",
            )
        },
        "evidence_annotation_required": False,
        "model_or_api_calls_performed": False,
        "split_leakage_errors": leakage_errors,
        "instances": details,
    }


def main() -> int:
    import argparse

    parser = argparse.ArgumentParser(description="Build a FAIRiAgent benchmark dataset inventory")
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--project-root", type=Path, default=Path.cwd())
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    inventory = build_inventory(args.manifest, project_root=args.project_root)
    rendered = json.dumps(inventory, indent=2, ensure_ascii=False)
    if args.output:
        args.output.write_text(rendered, encoding="utf-8")
    print(rendered)
    return 0 if not inventory["split_leakage_errors"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
